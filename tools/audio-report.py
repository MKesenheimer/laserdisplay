#!/usr/bin/env python3
# Analyse an audio file and translate its features into a human readable,
# text based report: tempo, beat grid, per-onset hits (kick/hat/tone),
# dynamics, song structure (silence/quiet/medium/loud sections), timbre,
# and events such as build-ups, drops, climax, intro and ending.
#
# The same data can be exported as JSON (--json FILE) so that downstream
# tools (e.g. a laser show generator) can consume the exact numbers.
#
# usage: python audio-report.py FILE.wav|mp3|ogg|flac
#               [--details 0..1] [--resolution SECONDS] [--json FILE.json]
#
#   --details D     amount of detail to capture, 0.0 (only the strongest
#                   beats and coarse sections) .. 1.0 (maximum detail);
#                   scales the onset/event thresholds and the report size
#   --resolution R  maximum timing resolution in seconds; features closer
#                   than R are merged and all times snap to an R grid
#                   (also speeds up analysis, default ~23 ms)

import sys
import os
import json
import math
import argparse

import numpy as np

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# ---------- decoding -------------------------------------------------------

def progress_bar(fraction, caption='', width=40):
    fraction = max(0.0, min(fraction, 1.0))
    filled = int(width * fraction)
    label = ' %s' % caption if caption else ''
    sys.stdout.write('\r[%-*s] %3d%%%s' % (width, '=' * filled, int(100 * fraction), label))
    sys.stdout.flush()


def progress_status(msg):
    sys.stdout.write('\r%-79s' % msg[:79])
    sys.stdout.flush()


def progress_done():
    sys.stdout.write('\r%-79s\r' % '')
    sys.stdout.flush()


def decode_audio(path, rate=22050):
    """Decode an arbitrary audio file to mono float samples using GStreamer."""
    Gst.init(None)
    location = path.replace('\\', '\\\\').replace('"', '\\"')
    pipeline = Gst.parse_launch(
        'filesrc location="%s" ! decodebin ! audioconvert ! audioresample ! '
        'audio/x-raw,format=F32LE,layout=interleaved,channels=1,rate=%d ! '
        'appsink name=sink emit-signals=true' % (location, rate))
    pipeline.set_state(Gst.State.PLAYING)
    sink = pipeline.get_by_name('sink')

    chunks = []
    collected = 0
    total_samples = None
    shown_percent = -1
    try:
        while True:
            sample = sink.emit('pull-sample')
            if sample is None:
                break  # end of stream
            ok, info = sample.get_buffer().map(Gst.MapFlags.READ)
            if ok:
                chunk = np.frombuffer(info.data, dtype=np.float32)
                chunks.append(chunk)
                collected += len(chunk)

            # the duration is known once the demuxer has parsed the header
            if total_samples is None:
                qok, dur_ns = pipeline.query_duration(Gst.Format.TIME)
                if qok and dur_ns > 0:
                    total_samples = int(dur_ns / float(Gst.SECOND) * rate)

            if total_samples:
                percent = int(100 * collected / float(total_samples))
                if percent > shown_percent:
                    shown_percent = percent
                    progress_bar(percent / 100.0,
                                 caption='decoding %s' % os.path.basename(path))
            else:
                progress_status('decoding %s ... %d kB' % (
                    os.path.basename(path), collected * 4 // 1024))
    finally:
        pipeline.set_state(Gst.State.NULL)

    progress_done()
    if not chunks:
        raise IOError('Could not decode %s' % path)
    return np.concatenate(chunks), rate


# ---------- small helpers --------------------------------------------------

BAR_CHARS = ' .:-=+*#%@'
EPS = 1e-12
SILENCE_DB = -45.0        # frames below this dBFS count as silence
F_MIN, F_MAX = 80.0, 5000.0   # melody search range

LEVEL_NAMES = {0: 'silence', 1: 'quiet', 2: 'medium', 3: 'loud'}


def normalize(x):
    span = x.max() - x.min()
    return (x - x.min()) / span if span > 0 else x * 0.0


def smooth(x, k=5):
    if k < 2:
        return x
    return np.convolve(x, np.ones(k) / k, mode='same')


def fmt_time(t):
    t = max(0.0, t)
    return '%d:%04.1f' % (int(t // 60), t - 60 * int(t // 60))


def bar_char(v):
    return BAR_CHARS[max(0, min(len(BAR_CHARS) - 1, int(v * len(BAR_CHARS))))]


def note_name(freq):
    if freq <= 0:
        return '-'
    n = int(round(69 + 12 * math.log2(freq / 440.0)))
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    return '%s%d' % (names[n % 12], n // 12 - 1)


# ---------- analysis -------------------------------------------------------

def analyze(samples, rate, details=0.5, resolution=None):
    """Extract the audio features; `details` (0..1) scales all detection
    thresholds and the report size, `resolution` (seconds) is the maximum
    timing resolution of every captured feature."""
    N = 2048                      # fft window
    hop = 512 if resolution is None else int(round(rate * resolution))
    hop = max(1, min(hop, N // 2))     # keep some fft overlap
    resolution = hop / float(rate)     # effective timing resolution
    f_a = rate / float(hop)            # analysis frame rate (~43 fps)
    nyq = rate / 2.0

    # threshold knobs derived from the detail level: low details = only
    # strong, long, obvious features; high details = sensitive detection
    onset_k = 3.0 - 2.0 * details          # onset threshold in flux sigmas
    min_seg = 1.5 + 3.0 * (1.0 - details)  # shortest structure segment (s)
    rise_min = 0.30 + 0.20 * (1.0 - details)   # build-up: total energy rise
    rise_dur = 1.5 + 1.5 * (1.0 - details)     # build-up: minimum duration (s)
    drop_min = 0.35 + 0.20 * (1.0 - details)   # drop: depth within 1 s

    n_frames = max(0, (len(samples) - N) // hop)
    duration = len(samples) / float(rate)

    progress_status('analysing: computing spectrogram ...')
    window = np.hanning(N)
    frames = np.lib.stride_tricks.sliding_window_view(samples, N)[::hop][:n_frames] * window
    spec = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(N, 1.0 / rate)

    # ---- frequency bands ---------------------------------------------------
    progress_status('analysing: frequency bands ...')
    band_defs = [('sub', 20, 60), ('bass', 60, 140), ('lowmid', 140, 450),
                 ('mid', 450, 2000), ('himid', 2000, 6000), ('high', 6000, 12000)]
    bands = {}
    for name, lo, hi in band_defs:
        mask = (freqs >= lo) & (freqs < min(hi, nyq * 0.999))
        bands[name] = normalize(smooth(spec[:, mask].mean(axis=1))) if mask.any() \
            else np.zeros(n_frames)

    rms = np.sqrt((frames ** 2).mean(axis=1))
    loud = normalize(smooth(rms))                    # 0..1 loudness
    db = 20.0 * np.log10(rms + EPS)                  # dBFS
    db_s = smooth(db, 5)

    # ---- onset envelope (spectral flux) ------------------------------------
    progress_status('analysing: onsets & tempo ...')
    flux = np.maximum(0.0, np.diff(spec, axis=0)).sum(axis=1)
    flux = smooth(normalize(flux))
    flux = np.concatenate(([0.0], flux))[:n_frames]  # re-align length

    # per-band flux, used to classify what kind of hit each onset is
    dspec = np.maximum(0.0, np.diff(spec, axis=0))
    bflux = {}
    for name, lo, hi in band_defs:
        mask = (freqs >= lo) & (freqs < min(hi, nyq * 0.999))
        bflux[name] = dspec[:, mask].sum(axis=1) if mask.any() else np.zeros(max(0, n_frames - 1))

    # global tempo: autocorrelation of the onset envelope
    centered = flux - flux.mean()
    ac = np.correlate(centered, centered, mode='full')[len(centered) - 1:]
    lags = np.arange(len(ac)) / f_a
    tmask = (lags >= 60.0 / 190) & (lags <= 60.0 / 60)
    beat_period = float(lags[tmask][np.argmax(ac[tmask])]) if tmask.any() else 0.5
    bpm = 60.0 / beat_period

    # tempo curve: windowed autocorrelation every 2 s over an 8 s window
    bpm_curve = np.full(n_frames, np.nan)
    win = int(round(8 * f_a))
    hw = win // 2
    centers = range(hw, max(hw + 1, n_frames - hw), max(1, int(round(2 * f_a))))
    for c in centers:
        seg = flux[c - hw:c + hw]
        if len(seg) < win // 2:
            continue
        seg = seg - seg.mean()
        acw = np.correlate(seg, seg, mode='full')[len(seg) - 1:]
        lw = np.arange(len(acw)) / f_a
        m = (lw >= 60.0 / 190) & (lw <= 60.0 / 60)
        if not m.any():
            continue
        conf = acw[m][np.argmax(acw[m])] / (acw[0] + EPS)
        if conf > 0.12:
            bpm_curve[c] = 60.0 / lw[m][np.argmax(acw[m])]
    valid = np.flatnonzero(~np.isnan(bpm_curve))
    if len(valid) > 1:
        bpm_curve = np.interp(np.arange(n_frames), valid, bpm_curve[valid])
    else:
        bpm_curve = np.full(n_frames, bpm)

    # ---- onset peak picking -------------------------------------------------
    min_gap = max(1, int(f_a * max(beat_period / 2, resolution)))

    def pick_onsets(k):
        thresh = flux.mean() + k * flux.std()
        picked = []
        for i in range(1, n_frames - 1):
            if flux[i] > thresh and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]:
                if not picked or i - picked[-1] >= min_gap:
                    picked.append(i)
        return picked

    onsets = pick_onsets(onset_k)
    while len(onsets) < 16 and onset_k > 0.5:
        # relax the threshold rather than reporting (almost) no beats at all
        onset_k = max(0.5, onset_k * 0.7)
        onsets = pick_onsets(onset_k)
    sorted_flux = np.sort(flux)

    # classify each hit: which band gained the most energy at the onset
    onset_infos = []
    for i in onsets:
        j = min(i, len(dspec) - 1)
        v = np.array([bflux[n][j] for n, _, _ in band_defs]) + EPS
        share = dict(zip([n for n, _, _ in band_defs], v / v.sum()))
        low = share['sub'] + share['bass']
        high = share['himid'] + share['high']
        mid = share['lowmid'] + share['mid']
        if low >= 0.55:
            kind = 'kick'
        elif high >= 0.55:
            kind = 'hat/snare'
        elif mid >= 0.60:
            kind = 'tone'
        else:
            kind = 'mixed'
        strength = float(np.searchsorted(sorted_flux, flux[i]) / max(1, len(sorted_flux)))
        t = round(i / f_a / resolution) * resolution   # snap to time grid
        onset_infos.append({'t': t, 'strength': strength, 'type': kind})

    # ---- beat grid (quantise onsets to a musical bar grid, 4/4 assumed) -----
    step = max(1, int(round(beat_period * f_a)))
    best_ph, best_sc = 0, -1.0
    for ph in range(step):
        idx = np.arange(ph, n_frames, beat_period * f_a).astype(int)
        sc = flux[idx].sum()
        if sc > best_sc:
            best_sc, best_ph = sc, ph
    grid = []
    k = 0
    while True:
        t = best_ph / f_a + k * beat_period
        if t > duration - 0.05:
            break
        grid.append(t)
        k += 1
    gidx = np.clip((np.array(grid) * f_a).astype(int), 0, n_frames - 1) if grid else []
    w = flux[gidx] if len(gidx) else np.zeros(0)
    sums = [w[j::4].sum() for j in range(4)] if len(w) else [0.0] * 4
    downbeat = sums.index(max(sums))
    n_bars = max(0, (len(grid) - downbeat)) // 4

    # ---- timbre -------------------------------------------------------------
    progress_status('analysing: timbre & melody ...')
    cent = (spec * freqs).sum(axis=1) / (spec.sum(axis=1) + EPS) / nyq   # 0..1
    mel_mask = (freqs >= F_MIN) & (freqs <= F_MAX)
    mel_freqs = freqs[mel_mask]
    dominant = mel_freqs[spec[:, mel_mask].argmax(axis=1)] if mel_mask.any() \
        else np.zeros(n_frames)

    # ---- structure segmentation ----------------------------------------------
    progress_status('analysing: structure ...')
    non_silent = db_s > SILENCE_DB
    vals = db_s[non_silent]
    if len(vals) < 10:
        vals = db_s
    q25, q60, q90 = np.percentile(vals, [25, 60, 90])
    level = non_silent.astype(int)               # 1 = audible but quiet
    level[(db_s > q60) & non_silent] = 2
    level[(db_s > q90) & non_silent] = 3

    # collapse into runs, absorb runs shorter than MIN_SEG, merge neighbours
    edges = np.concatenate(([0], np.flatnonzero(np.diff(level)) + 1, [n_frames]))
    runs = [[int(edges[i]), int(edges[i + 1]), int(level[edges[i]])]
            for i in range(len(edges) - 1)]
    min_len = max(1, int(min_seg * f_a))

    def merge_equal(rs):
        out = []
        for r in rs:
            if out and out[-1][2] == r[2]:
                out[-1][1] = r[1]
            else:
                out.append(r)
        return out

    runs = merge_equal(runs)
    # absorb too-short runs into the neighbouring run with the closest level,
    # so that the segmentation does not drift towards one arbitrary level
    while len(runs) > 1:
        shortest = min(range(len(runs)), key=lambda r: runs[r][1] - runs[r][0])
        s, e, l = runs[shortest]
        if e - s >= min_len:
            break
        if shortest == 0:
            target = 1
        elif shortest == len(runs) - 1:
            target = shortest - 1
        else:
            dl = abs(runs[shortest - 1][2] - l)
            dr = abs(runs[shortest + 1][2] - l)
            target = shortest - 1 if dl <= dr else shortest + 1
        runs[target] = [min(s, runs[target][0]), max(e, runs[target][1]),
                        runs[target][2]]
        del runs[shortest]
        runs = merge_equal(runs)

    segments = []
    for s, e, l in runs:
        y = loud[s:e]
        x = np.arange(len(y)) / f_a
        try:
            slope = float(np.polyfit(x, y, 1)[0]) if len(x) > 4 else 0.0
        except Exception:
            slope = 0.0
        trend = 'rising' if slope > 0.06 else 'falling' if slope < -0.06 else 'steady'
        seg_bpm = float(np.nanmedian(bpm_curve[s:e]))
        seg_cent = float(cent[s:e].mean())
        seg_dom = float(np.median(dominant[s:e]))
        if l == 0:
            char = 'silent'
        else:
            words = [{1: 'sparse', 2: 'steady', 3: 'full-on'}[l]]
            if seg_cent < 0.09:
                words.append('dark')
            elif seg_cent < 0.16:
                words.append('warm')
            else:
                words.append('bright')
            if trend != 'steady':
                words.append(trend)
            char = ', '.join(words)
        segments.append({
            'start': s / f_a, 'end': e / f_a, 'level': l, 'character': char,
            'bpm': seg_bpm, 'bass': float(bands['bass'][s:e].mean()),
            'mid': float(bands['mid'][s:e].mean()),
            'high': float(bands['high'][s:e].mean()),
            'centroid': seg_cent, 'dominant_hz': seg_dom,
            'trend': trend, 'slope': slope,
        })

    # ---- events: build-ups, drops, climax, intro, ending ----------------------
    progress_status('analysing: events ...')
    loud_s = smooth(loud, max(3, int(0.3 * f_a)))
    events = []

    first = int(np.flatnonzero(non_silent)[0]) if non_silent.any() else 0
    if first / f_a > 0.2:
        events.append({'type': 'intro', 't0': 0.0, 't1': first / f_a,
                       'desc': 'music starts after %.1fs of silence' % (first / f_a)})

    per_sec = np.gradient(loud_s) * f_a
    rising = per_sec > 0.10
    idx = np.flatnonzero(rising)
    if len(idx):
        splits = np.flatnonzero(np.diff(idx) > 1)
        for group in np.split(idx, splits + 1):
            s, e = int(group[0]), int(group[-1]) + 1
            if (e - s) / f_a < rise_dur:
                continue  # too short to be a musical build-up
            if loud_s[e - 1] - loud_s[s] >= rise_min and loud_s[e - 1] >= 0.5:
                if events and events[-1]['type'] == 'build-up' and s - events[-1]['_ef'] < f_a:
                    events[-1]['t1'] = e / f_a
                    events[-1]['_ef'] = e
                    continue
                events.append({'type': 'build-up', 't0': s / f_a, 't1': e / f_a,
                               'desc': 'energy rises %.2f in %.1fs -> drop likely at end'
                                       % (loud_s[e - 1] - loud_s[s], (e - s) / f_a),
                               '_ef': e})
    for ev in events:
        ev.pop('_ef', None)

    fut = np.concatenate((loud_s[int(f_a):], np.full(int(f_a), loud_s[-1])))
    delta = fut - loud_s
    cand = np.flatnonzero((delta < -drop_min) & (loud_s > 0.55))
    last_t = -10.0
    for i in cand:
        is_min = (i == 0 or delta[i] <= delta[i - 1]) and \
                 (i + 1 >= len(delta) or delta[i] < delta[i + 1])
        if not is_min:
            continue
        t = i / f_a
        if t - last_t < 2.0:
            continue
        events.append({'type': 'drop', 't0': t, 't1': t + 1.0,
                       'desc': 'loudness drops %.2f -> %.2f within 1s'
                               % (loud_s[i], fut[i])})
        last_t = t

    thr = np.percentile(loud_s, 92)
    mask = loud_s >= thr
    if mask.any():
        best_s = best_e = best_len = 0
        s = None
        for i in range(n_frames):
            if mask[i] and s is None:
                s = i
            elif not mask[i] and s is not None:
                if i - s > best_len:
                    best_s, best_e, best_len = s, i, i - s
                s = None
        if s is not None and n_frames - s > best_len:
            best_s, best_e, best_len = s, n_frames, n_frames - s
        if best_len > 2 * f_a:
            events.append({'type': 'climax', 't0': best_s / f_a, 't1': best_e / f_a,
                           'desc': 'loudest part of the song (%.1fs long)'
                                   % (best_len / f_a)})

    tail = min(n_frames - 1, int(8 * f_a))
    if tail > 10 and per_sec[-tail:].mean() < -0.03 and \
            loud_s[-1] < loud_s[-tail] - 0.2:
        events.append({'type': 'ending', 't0': (n_frames - tail) / f_a, 't1': duration,
                       'desc': 'fade-out ending'})
    elif n_frames > int(2.5 * f_a) and \
            loud_s[-1] < 0.15 and loud_s[-int(2.5 * f_a)] > 0.5:
        events.append({'type': 'ending', 't0': (n_frames - int(2.5 * f_a)) / f_a,
                       't1': duration, 'desc': 'hard stop'})

    for ev in events:
        for key in ('t0', 't1'):
            ev[key] = round(ev[key] / resolution) * resolution  # snap to grid
    events.sort(key=lambda e: e['t0'])

    progress_done()
    return {
        'f_a': f_a, 'n_frames': n_frames, 'duration': duration, 'rate': rate,
        'details': details, 'resolution': resolution,
        'db': db_s, 'loud': loud, 'bands': bands, 'flux': flux,
        'bpm': bpm, 'beat_period': beat_period, 'bpm_curve': bpm_curve,
        'onsets': onset_infos, 'grid': grid, 'downbeat': downbeat, 'n_bars': n_bars,
        'centroid': cent, 'dominant': dominant,
        'segments': segments, 'events': events,
        'silence_ratio': float(1.0 - non_silent.mean()),
    }


# ---------- report printing ------------------------------------------------

RULE = '=' * 78


def print_timeline(ana):
    print('TIMELINE (1 char per second; L=loudness B=bass H=highs; '
          "' '=off ... '@'=max)")
    dur = int(ana['duration'])
    f_a = ana['f_a']
    width = 100

    def row(arr):
        out = []
        for sec in range(dur):
            i0, i1 = int(sec * f_a), min(int((sec + 1) * f_a), len(arr))
            out.append(bar_char(float(arr[i0:i1].mean())) if i1 > i0 else ' ')
        return out

    rows = {'L': row(ana['loud']), 'B': row(ana['bands']['bass']),
            'H': row(ana['bands']['high'])}
    for off in range(0, dur, width):
        chunk = min(width, dur - off)
        ruler = ''.join('|' if (off + i) % 10 == 0 else ' ' for i in range(chunk))
        print('      %s' % ruler)
        for key in ('L', 'B', 'H'):
            print('  %s   %s' % (key, ''.join(rows[key][off:off + chunk])))
        print('      %ds' % off)
    print()


def print_structure(ana):
    print('STRUCTURE (adaptive levels: silence / quiet / medium / loud)')
    print('  #   start      end      dur   level    bpm  bass mid high  '
          'pitch    character')
    for n, seg in enumerate(ana['segments'], 1):
        dom = seg['dominant_hz']
        pitch = '%-5s' % (note_name(dom) if dom > 0 else '-')
        bpm = '%4.0f' % seg['bpm'] if not math.isnan(seg['bpm']) else '   -'
        print('  %-3d %8s %8s %6.1fs %-8s %s %4.2f %4.2f %4.2f  %s  %s'
              % (n, fmt_time(seg['start']), fmt_time(seg['end']),
                 seg['end'] - seg['start'], LEVEL_NAMES[seg['level']], bpm,
                 seg['bass'], seg['mid'], seg['high'], pitch, seg['character']))
    print()


def print_beats(ana, limit=None):
    if limit is None:
        limit = max(10, int(300 * ana['details']))   # report size follows details
    onsets = ana['onsets']
    kinds = {}
    for o in onsets:
        kinds[o['type']] = kinds.get(o['type'], 0) + 1
    print('BEATS / ONSETS (%d hits: %s)' % (
        len(onsets), ', '.join('%s x%d' % (k, kinds[k])
                               for k in sorted(kinds, key=kinds.get, reverse=True))
              or '-'))
    print('  time      bar:beat  type       strength')
    for n, o in enumerate(onsets):
        if n == limit:
            print('  ... %d more (use --json for the full list)' % (len(onsets) - limit))
            break
        beat_idx = int((o['t'] - (ana['grid'][0] if ana['grid'] else 0))
                       / ana['beat_period']) if ana['grid'] else 0
        pos = '%d:%d' % (beat_idx // 4 + 1, beat_idx % 4 + 1) if ana['grid'] else '-'
        print('  %8s  %-8s  %-9s  %s'
              % (fmt_time(o['t']), pos, o['type'],
                 '*' * max(1, int(o['strength'] * 5 + 0.5))))
    print()
    print('BEAT GRID: %.0f BPM, period %.0f ms, grid starts at %s, '
          'downbeat every 4th beat, ~%d bars total'
          % (ana['bpm'], ana['beat_period'] * 1000,
             fmt_time(ana['grid'][0]) if ana['grid'] else '-', ana['n_bars']))
    print()


def print_events(ana):
    print('EVENTS')
    if not ana['events']:
        print('  (none detected)')
    for ev in ana['events']:
        span = '' if ev['t1'] - ev['t0'] < 0.05 else ' -> %s' % fmt_time(ev['t1'])
        print('  %-9s %s%s  %s' % (ev['type'].upper(), fmt_time(ev['t0']),
                                   span, ev['desc']))
    print()

    print('TEMPO OVER TIME (60..190 BPM, 1 char/sec, '
          "' '=unknown '.'=low '@'=high)")
    curve = ana['bpm_curve']
    f_a = ana['f_a']
    dur = int(ana['duration'])
    width = 100
    for off in range(0, dur, width):
        chunk = min(width, dur - off)
        line = []
        for sec in range(off, off + chunk):
            i0, i1 = int(sec * f_a), min(int((sec + 1) * f_a), len(curve))
            v = float(np.nanmean(curve[i0:i1])) if i1 > i0 else float('nan')
            if math.isnan(v):
                line.append(' ')
            else:
                line.append(bar_char(max(0.0, min(1.0, (v - 60) / 130.0))))
        print('  %4ds %s' % (off, ''.join(line)))
    print()


def print_report(path, ana):
    db = ana['db']
    print(RULE)
    print('AUDIO REPORT: %s' % os.path.basename(path))
    print(RULE)
    print('duration       : %s (%.1fs)' % (fmt_time(ana['duration']), ana['duration']))
    print('sample rate    : %d Hz (mono, analysis frame rate %.0f fps)'
          % (ana['rate'], ana['f_a']))
    print('resolution     : %.0f ms max timing resolution, details %.0f%%'
          % (ana['resolution'] * 1000.0, ana['details'] * 100.0))
    print('tempo          : ~%.0f BPM (beat period %.0f ms), meter guess 4/4'
          % (ana['bpm'], ana['beat_period'] * 1000))
    print('loudness       : mean %.1f dBFS, peak %.1f dBFS, span %.1f dB'
          % (float(np.median(db)), float(db.max()),
             float(np.percentile(db, 95) - np.percentile(db, 5))))
    print('silence        : %.1f%% of duration' % (100 * ana['silence_ratio']))
    dom_med = float(np.median(ana['dominant']))
    print('pitch centre   : ~%d Hz (%s), spectral centroid %.0f Hz avg'
          % (dom_med, note_name(dom_med),
             float(ana['centroid'].mean()) * ana['rate'] / 2.0))
    print('hits           : %d onsets, %d grid beats, ~%d bars'
          % (len(ana['onsets']), len(ana['grid']), ana['n_bars']))
    print()
    print_timeline(ana)
    print_structure(ana)
    print_beats(ana)
    print_events(ana)


# ---------- json export ----------------------------------------------------

def export_json(path, ana, out_path):
    f_a = ana['f_a']

    def arr(a, nd=4):
        return [round(float(v), nd) for v in a]

    data = {
        'file': os.path.abspath(path),
        'duration': round(ana['duration'], 3),
        'rate': ana['rate'],
        'frame_rate': round(f_a, 2),
        'details': round(ana['details'], 2),
        'resolution': round(ana['resolution'], 5),
        'bpm': round(ana['bpm'], 2),
        'beat_period': round(ana['beat_period'], 4),
        'downbeat_offset': round(ana['grid'][0], 3) if ana['grid'] else 0.0,
        'n_bars': ana['n_bars'],
        'times': arr(np.arange(ana['n_frames']) / f_a, 3),
        'loudness': arr(ana['loud']),
        'loudness_db': arr(ana['db'], 2),
        'bands': {name: arr(v) for name, v in ana['bands'].items()},
        'onset_strength': arr(ana['flux']),
        'centroid': arr(ana['centroid']),
        'dominant_hz': arr(ana['dominant'], 1),
        'bpm_curve': [None if math.isnan(v) else round(float(v), 1)
                      for v in ana['bpm_curve']],
        'onsets': [{'t': round(o['t'], 3), 'strength': round(o['strength'], 3),
                    'type': o['type']} for o in ana['onsets']],
        'beat_grid': [round(t, 3) for t in ana['grid']],
        'segments': [{'start': round(s['start'], 3), 'end': round(s['end'], 3),
                      'level': LEVEL_NAMES[s['level']],
                      'character': s['character'],
                      'bpm': None if math.isnan(s['bpm']) else round(s['bpm'], 1),
                      'bass': round(s['bass'], 3), 'mid': round(s['mid'], 3),
                      'high': round(s['high'], 3),
                      'centroid_hz': round(s['centroid'] * ana['rate'] / 2.0, 1),
                      'dominant_hz': round(s['dominant_hz'], 1),
                      'trend': s['trend']} for s in ana['segments']],
        'events': [{'type': e['type'], 't0': round(e['t0'], 3),
                    't1': round(e['t1'], 3), 'desc': e['desc']}
                   for e in ana['events']],
    }
    with open(out_path, 'w') as fh:
        json.dump(data, fh, indent=1)
    print('JSON export written to %s (%d kB)' % (out_path, os.path.getsize(out_path) // 1024))


# ---------- main -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Analyse an audio file and print a human readable '
                    'report of its musical features.')
    parser.add_argument('file', help='audio file: .wav|.mp3|.ogg|.flac ...')
    parser.add_argument('--details', type=float, default=0.5, metavar='0..1',
                        help='amount of detail to capture: 0.0 = only the '
                             'strongest beats and coarse sections, 1.0 = '
                             'maximum detail (default: 0.5)')
    parser.add_argument('--resolution', type=float, default=None, metavar='SEC',
                        help='maximum timing resolution in seconds; closer '
                             'features are merged and times snap to this '
                             'grid (default: ~23 ms)')
    parser.add_argument('--json', metavar='FILE',
                        help='also export all extracted data as JSON')
    args = parser.parse_args()

    details = max(0.0, min(1.0, args.details))
    if args.resolution is not None and args.resolution <= 0:
        parser.error('--resolution must be > 0 seconds')

    samples, rate = decode_audio(args.file)
    ana = analyze(samples, rate, details=details, resolution=args.resolution)
    print_report(args.file, ana)
    if args.json:
        export_json(args.file, ana, args.json)


if __name__ == '__main__':
    main()
