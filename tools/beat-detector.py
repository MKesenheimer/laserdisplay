#!/usr/bin/env python3
# Detect the beats in an audio file and its song structure (intro, verse,
# chorus, bridge, instrumental, outro) and store the results as a single
# JSON file.
# With --validate the audio is played back with an audible "tick" on every
# stored beat so the detection can be checked by ear.
#
# usage: python beat-detector.py FILE [--json FILE.json]
#          python beat-detector.py FILE [--json FILE.json] --validate
#
#   FILE           audio file: .mp3|.m4a|.wav|.ogg|.flac ... (anything
#                  GStreamer can decode)
#   --json FILE    where to write / read the results
#                  (default: <FILE>.beats.json)
#   --no-segments  skip the structure analysis, only detect beats
#   --validate     do not detect; instead read the JSON and play the audio
#                  with a tick sound mixed in at every beat timestamp
#
# The JSON file contains:
#   { "file", "duration", "sample_rate", "bpm", "num_beats",
#     "beats": [seconds of every beat, ascending] }
# and, unless --no-segments is given, additionally:
#   { "segments": [ { "start", "end", "part", "level", "character",
#                     "centroid_hz", "dominant_hz", "trend" }, ... ] }
#   part         one of: intro, verse, chorus, bridge, instrumental, outro
#   level        loudness class: silence / quiet / medium / loud
#   character    human readable energy/timbre description
#   centroid_hz  mean spectral centroid (perceptual brightness)
#   dominant_hz  dominant frequency of the segment
#   trend        energy trend across the segment: rising / steady / falling

import sys
import os
import json
import argparse

import numpy as np

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

import librosa

import sounddevice

ANALYSIS_RATE = 22050     # rate used for beat detection
PLAYBACK_RATE = 44100     # rate used for the validation playback


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
    # without this the appsink paces the whole pipeline in real time
    sink.set_property('sync', False)

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


# ---------- beat detection -------------------------------------------------

def detect_beats(samples, rate):
    """Return (bpm, beat times in seconds) for a mono signal."""
    tempo, frames = librosa.beat.beat_track(y=samples, sr=rate)
    times = librosa.frames_to_time(frames, sr=rate)
    bpm = float(np.nanmean(tempo)) if np.size(tempo) else 0.0
    return bpm, times


def write_json(out_path, audio_path, rate, duration, bpm, beats,
               segments=None):
    data = {
        'file': os.path.abspath(audio_path),
        'duration': round(duration, 3),
        'sample_rate': rate,
        'bpm': round(bpm, 2),
        'num_beats': len(beats),
        'beats': [round(float(t), 4) for t in beats],
    }
    if segments is not None:
        data['segments'] = [{
            'start': round(s['start'], 3),
            'end': round(s['end'], 3),
            'part': s['part'],
            'level': LEVEL_NAMES[s['level']],
            'character': s['character'],
            'centroid_hz': round(s['centroid_hz'], 1),
            'dominant_hz': round(s['dominant_hz'], 1),
            'trend': s['trend'],
        } for s in segments]
    with open(out_path, 'w') as fh:
        json.dump(data, fh, indent=1)
    return data


# ---------- structure (song part) detection ---------------------------------

SILENCE_DB = -45.0        # frames below this dBFS count as silence
SEG_MIN_LEN = 4.0         # shortest structural segment (seconds)
REGION_MIN_LEN = 8.0      # shortest coarse dynamic region (seconds)
SUB_SPAN = 20.0           # target duration of a verse/chorus sub-segment (s)
SNAP_WINDOW = 0.6         # snap section boundaries to a beat within this window (s)
REP_SIM = 0.985           # chroma similarity for two sections to "match"
DOM_FMIN, DOM_FMAX = 30.0, 6000.0   # dominant frequency search range (Hz)
VOCAL_LO, VOCAL_HI = 250.0, 2500.0  # vocal proxy: mid band (Hz)
BASS_LO, BASS_HI = 40.0, 200.0      # vocal proxy: bass reference band (Hz)
EPS = 1e-12

LEVEL_NAMES = {0: 'silence', 1: 'quiet', 2: 'medium', 3: 'loud'}
LEVEL_WORDS = {1: 'sparse', 2: 'steady', 3: 'full-on'}


def _smooth(x, k=5):
    if k < 2 or len(x) < k:
        return x
    return np.convolve(x, np.ones(k) / k, mode='same')


def compute_features(samples, rate):
    """Frame-level features shared by the structure analysis and the
    per-segment frequency analysis (one STFT serves both)."""
    hop, n_fft = 512, 2048
    return {
        'S': np.abs(librosa.stft(samples, n_fft=n_fft, hop_length=hop)),
        'freqs': librosa.fft_frequencies(sr=rate, n_fft=n_fft),
        'f_a': rate / float(hop),
        'chroma': librosa.feature.chroma_stft(y=samples, sr=rate, hop_length=hop),
        'mfcc': librosa.feature.mfcc(y=samples, sr=rate, hop_length=hop),
        'rms': librosa.feature.rms(y=samples, hop_length=hop)[0],
        'centroid': librosa.feature.spectral_centroid(y=samples, sr=rate,
                                                     hop_length=hop)[0],
    }


def smoothed_loudness(feat):
    """RMS loudness curve, smoothed and normalised to 0..1."""
    rms = feat['rms']
    span = rms.max() - rms.min()
    loud = (rms - rms.min()) / span if span > 0 else rms * 0.0
    return _smooth(loud)


def merge_short(segs, loud, f_a):
    """Merge segments shorter than SEG_MIN_LEN into the neighbour with the
    closest average loudness, so the boundaries do not drift arbitrarily."""
    segs = [list(s) for s in segs]
    min_len = max(1, int(SEG_MIN_LEN * f_a))
    while len(segs) > 1:
        i = min(range(len(segs)), key=lambda j: segs[j][1] - segs[j][0])
        s, e = segs[i]
        if e - s >= min_len:
            break
        m = loud[s:e].mean()
        if i == 0:
            target = 1
        elif i == len(segs) - 1:
            target = i - 1
        else:
            lm = loud[segs[i - 1][0]:segs[i - 1][1]].mean()
            rm = loud[segs[i + 1][0]:segs[i + 1][1]].mean()
            target = i - 1 if abs(m - lm) <= abs(m - rm) else i + 1
        segs[target] = [min(segs[target][0], s), max(segs[target][1], e)]
        del segs[i]
    return segs


def _otsu_threshold(x):
    """1-D Otsu split: the threshold maximising the between-class variance,
    i.e. the gap between the quiet and the loud part of the distribution."""
    hist, edges = np.histogram(x, bins=256)
    hist = hist.astype(float)
    total = hist.sum()
    if total <= 0:
        return float(np.median(x))
    sum_i = np.cumsum(np.arange(len(hist)) * hist)   # weighted bin-index sum
    sum_tot = float(sum_i[-1])
    w_b = np.cumsum(hist)                            # background count
    w_f = total - w_b
    m_b = sum_i / np.maximum(w_b, 1e-12)
    m_f = (sum_tot - sum_i) / np.maximum(w_f, 1e-12)
    i = int(np.argmax((w_b / total) * (w_f / total) * (m_b - m_f) ** 2))
    return float(0.5 * (edges[i] + edges[i + 1]))


def _region_features(feat, cols):
    """Standardised clustering feature matrix (MFCC + chroma + energy +
    brightness) for the frames selected by `cols`."""
    X = np.concatenate([feat['mfcc'][:, cols], feat['chroma'][:, cols],
                        feat['rms'][None, cols], feat['centroid'][None, cols]],
                       axis=0)
    return (X - X.mean(axis=1, keepdims=True)) / (X.std(axis=1, keepdims=True) + EPS)


def energy_regions(feat):
    """Split the song into coarse dynamic regions.

    Frames above the median loudness form the loud regions (the
    verse/chorus material), the rest the quiet ones (intro, bridge, outro).
    Runs shorter than REGION_MIN_LEN are absorbed into the longer neighbour.
    Returns a list of (start, end, is_loud) in seconds covering the song."""
    f_a = feat['f_a']
    # smooth over a musical phrase (~2.5 s): the raw per-frame loudness
    # jitters around any mid-range threshold and would produce chattering
    db_s = _smooth(20.0 * np.log10(feat['rms'] + EPS), int(2.5 * f_a))
    audible = db_s > SILENCE_DB
    vals = db_s[audible] if audible.sum() >= 10 else db_s
    # the quiet and the loud parts of a song form the two modes of the
    # loudness distribution; Otsu's method finds their gap
    mask = db_s > _otsu_threshold(vals)

    idx = np.flatnonzero(np.diff(mask.astype(int))) + 1
    starts = np.concatenate(([0], idx))
    ends = np.concatenate((idx, [len(mask)]))
    runs = [[int(s), int(e), bool(mask[s])]
            for s, e in zip(starts, ends) if e > s]

    min_len = max(1, int(REGION_MIN_LEN * f_a))
    while True:
        short = [i for i, (s, e, _) in enumerate(runs) if e - s < min_len]
        if not short:
            break
        i = short[0]
        s, e, _ = runs[i]
        if i == 0:
            target = 1
        elif i == len(runs) - 1:
            target = i - 1
        else:
            left = runs[i - 1][1] - runs[i - 1][0]
            right = runs[i + 1][1] - runs[i + 1][0]
            target = i - 1 if left >= right else i + 1
        ts, te, tm = runs[target]
        runs[target] = [min(ts, s), max(te, e), tm]
        del runs[i]

    # absorbing a short run can leave two adjacent regions of the same
    # level; those belong together
    out = []
    for s, e, m in runs:
        if out and out[-1][2] == m:
            out[-1][1] = e
        else:
            out.append([s, e, m])

    return [(s / f_a, e / f_a, m) for s, e, m in out]


def cluster_region(feat, s_frame, e_frame):
    """Subdivide a loud region into its sub-parts (verses, choruses).

    A temporally constrained agglomerative clustering (librosa.segment.
    agglomerative) partitions the region's frames into at most 10 segments of
    roughly SUB_SPAN seconds each.  Returns [(start, end)] in seconds."""
    f_a = feat['f_a']
    n = e_frame - s_frame
    k = max(1, min(10, int(round(n / f_a / SUB_SPAN))))
    if k == 1 or n < int(2 * SEG_MIN_LEN * f_a):
        return [[s_frame / f_a, e_frame / f_a]]

    # cluster on every 2nd frame: halves the O(n^2) memory of the linkage
    # while keeping a ~90 ms timing resolution
    X = _region_features(feat, slice(s_frame, e_frame, 2))
    bounds = np.clip(librosa.segment.agglomerative(X, k) * 2, 0, n)
    segs = [[s_frame + int(bounds[i]), s_frame + int(bounds[i + 1])]
            for i in range(len(bounds) - 1)]
    segs[-1][1] = e_frame
    segs = merge_short(segs, smoothed_loudness(feat), f_a)
    return [[s / f_a, e / f_a] for s, e in segs]


def detect_structure(feat, beats):
    """Final segment boundaries of the song.

    The coarse dynamic regions found by energy_regions; every loud region is
    subdivided into its verse/chorus sub-parts, quiet regions stay whole.
    Returns (regions, segments): the (start, end, is_loud) regions in
    seconds and the final (start, end) segment boundaries in seconds."""
    f_a = feat['f_a']
    regions = energy_regions(feat)
    segs = []
    for s, e, is_loud in regions:
        if is_loud:
            segs.extend(cluster_region(feat, int(round(s * f_a)),
                                       int(round(e * f_a))))
        else:
            segs.append([s, e])
    segs = snap_to_beats([(float(s), float(e)) for s, e in segs], beats)
    return regions, segs


def snap_to_beats(segs, beats):
    """Nudge section boundaries onto the nearest beat if one lies within
    SNAP_WINDOW seconds (sections musically start on the beat grid)."""
    if not len(beats) or len(segs) < 2:
        return segs
    out = [segs[0]]
    for s, e in segs[1:]:
        j = int(np.searchsorted(beats, s))
        cands = beats[max(0, j - 1):j + 1]
        c = cands[np.argmin(np.abs(cands - s))]
        if abs(c - s) <= SNAP_WINDOW:
            s = float(c)
        out.append((s, e))
    return out


def classify_parts(raw, regions, duration, vocal_ref):
    """Heuristically assign each segment a part label.

    Quiet regions are named by position (intro, bridge, outro) and by the
    vocal proxy: the mid-band (250..2500 Hz) to bass energy ratio, which
    drops well below the loud regions' value in instrumental passages.
    Loud regions are subdivided by repetition and relative energy: a chorus
    is a sub-part that returns (similar chroma) and sits in the upper half
    of its region's loudness; everything else is a verse, and the last
    sub-part of the last region counts as an outro if it fades out."""
    n = len(raw)
    n_regions = len(regions)

    # how often each sub-part of a loud region returns, compared with all
    # other loud-region sub-parts (a chorus repeats across the song)
    chromas = np.stack([r['chroma'] for r in raw])
    sim = chromas @ chromas.T
    loud_idx = [i for i, r in enumerate(raw) if regions[r['region_idx']][2]]
    rep = np.zeros(n, dtype=int)
    for i in loud_idx:
        for j in loud_idx:
            if i != j and sim[i][j] >= REP_SIM:
                rep[i] += 1

    # loudness relative to the other sub-parts of the same region
    rel_loud = np.zeros(n)
    for ri in range(n_regions):
        members = [i for i in loud_idx if raw[i]['region_idx'] == ri]
        if not members:
            continue
        lo = min(raw[i]['loud'] for i in members)
        hi = max(raw[i]['loud'] for i in members)
        for i in members:
            rel_loud[i] = 1.0 if hi <= lo else (raw[i]['loud'] - lo) / (hi - lo)

    parts = []
    for i, r in enumerate(raw):
        is_loud = regions[r['region_idx']][2]
        first_region = r['region_idx'] == 0
        last_region = r['region_idx'] == n_regions - 1
        last_seg = i == n - 1
        chorus_like = (rep[i] >= 1 and rel_loud[i] >= 0.5) or rep[i] >= 2
        if not is_loud:
            if n_regions == 1:
                part = 'instrumental' if r['vocal'] < 0.6 * vocal_ref else 'verse'
            elif first_region:
                part = 'intro' if (r['end'] - r['start']) < 0.4 * duration \
                    else 'verse'
            elif last_region:
                part = 'outro'
            else:
                part = 'instrumental' if r['vocal'] < 0.6 * vocal_ref \
                    else 'bridge'
        else:
            if last_region and last_seg and \
                    (r['trend'] == 'falling' or r['loud'] < 0.45):
                part = 'outro'
            elif chorus_like:
                part = 'chorus'
            else:
                part = 'verse'
        parts.append(part)
    return parts


def analyse_segments(feat, rate, regions, segs, duration):
    """Characterise each segment: loudness level, timbre, energy trend and
    the dominant frequencies, plus the part label."""
    S, freqs, f_a = feat['S'], feat['freqs'], feat['f_a']
    nyq = rate / 2.0

    db_s = _smooth(20.0 * np.log10(feat['rms'] + EPS))
    loud = smoothed_loudness(feat)

    # adaptive loudness thresholds from the audible frames
    audible = db_s > SILENCE_DB
    vals = db_s[audible] if audible.sum() >= 10 else db_s
    q60, q90 = np.percentile(vals, [60, 90])

    dom_mask = (freqs >= DOM_FMIN) & (freqs < DOM_FMAX)
    mid_mask = (freqs >= VOCAL_LO) & (freqs < VOCAL_HI)
    low_mask = (freqs >= BASS_LO) & (freqs < BASS_HI)

    def vocal_proxy(s, e):
        return float(S[mid_mask, s:e].mean() / (S[low_mask, s:e].mean() + EPS))

    # the loud regions' vocal proxy is the reference for deciding whether a
    # quiet region is a (vocal) bridge or an instrumental one
    region_vocals = []
    for rs, re, is_loud in regions:
        region_vocals.append((is_loud,
                              vocal_proxy(int(rs * f_a), int(re * f_a))))
    loud_vocals = [v for l, v in region_vocals if l]
    vocal_ref = float(np.median(loud_vocals)) if loud_vocals \
        else float(np.median([v for _, v in region_vocals]))

    raw = []
    for start, end in segs:
        s = max(0, int(round(start * f_a)))
        e = min(S.shape[1], max(s + 1, int(round(end * f_a))))
        mid = 0.5 * (start + end)
        region_idx = next(i for i, (rs, re, _l) in enumerate(regions)
                          if rs <= mid < re or
                          (i == len(regions) - 1 and mid >= re))

        med_db = float(np.median(db_s[s:e]))
        if med_db < SILENCE_DB:
            level = 0
        elif med_db > q90:
            level = 3
        elif med_db > q60:
            level = 2
        else:
            level = 1

        y = loud[s:e]
        x = np.arange(len(y)) / f_a
        slope = float(np.polyfit(x, y, 1)[0]) if len(x) > 4 else 0.0
        trend = 'rising' if slope > 0.06 else 'falling' if slope < -0.06 else 'steady'

        centroid_hz = float(feat['centroid'][s:e].mean())
        S_seg = S[:, s:e]
        dom = freqs[dom_mask][S_seg[dom_mask].argmax(axis=0)] if dom_mask.any() \
            else np.zeros(e - s)

        words = ['silent'] if level == 0 else [LEVEL_WORDS[level]]
        if level:
            cent_norm = centroid_hz / nyq
            words.append('dark' if cent_norm < 0.09 else
                         'warm' if cent_norm < 0.16 else 'bright')
            if trend != 'steady':
                words.append(trend)

        chroma = feat['chroma'][:, s:e].mean(axis=1)
        cn = np.linalg.norm(chroma)
        if cn > 0:
            chroma = chroma / cn

        raw.append({
            'start': start, 'end': end,
            'level': level, 'character': ', '.join(words),
            'centroid_hz': centroid_hz,
            'dominant_hz': float(np.median(dom)),
            'trend': trend,
            'loud': float(y.mean()),
            'chroma': chroma,
            'vocal': vocal_proxy(s, e),
            'region_idx': region_idx,
        })

    for r, part in zip(raw, classify_parts(raw, regions, duration, vocal_ref)):
        r['part'] = part
    return raw


# ---------- validation playback --------------------------------------------

def make_tick(rate, freq=1500.0, dur=0.02, decay=0.005, gain=0.6):
    """A short decaying sine burst that cuts through most music."""
    t = np.arange(int(dur * rate)) / float(rate)
    return gain * np.sin(2.0 * np.pi * freq * t) * np.exp(-t / decay)


def mix_ticks(samples, rate, beat_times):
    """Add a tick to `samples` at each beat time (sample-accurate)."""
    mixed = samples.copy()
    tick = make_tick(rate)
    n = len(mixed)
    placed = 0
    for t in beat_times:
        i = int(round(t * rate))
        if i >= n:
            continue
        j = min(i + len(tick), n)
        mixed[i:j] += tick[:j - i]
        placed += 1
    return np.clip(mixed, -1.0, 1.0), placed


def validate(audio_path, json_path):
    with open(json_path) as fh:
        data = json.load(fh)
    beats = np.asarray(data['beats'], dtype=float)
    print('validating %s against %s' % (
        os.path.basename(audio_path), os.path.basename(json_path)))
    print('%d beats at ~%.1f BPM, duration %s' % (
        len(beats), data.get('bpm', 0.0), data.get('duration', '?')))

    samples, rate = decode_audio(audio_path, rate=PLAYBACK_RATE)
    if len(beats):
        over = beats[beats > len(samples) / float(rate)]
        if len(over):
            print('warning: %d beat(s) lie beyond the end of the audio '
                  '(file changed?)' % len(over))
    mixed, placed = mix_ticks(samples, rate, beats)
    if placed == 0:
        print('no beats to tick; playing the audio as-is')
    else:
        print('playing: you should hear a tick on every beat (Ctrl+C to stop)')
    sounddevice.play(mixed, rate, blocking=True)


# ---------- main -------------------------------------------------------------

def default_json_path(audio_path):
    root, _ = os.path.splitext(audio_path)
    return root + '.beats.json'


def fmt_time(t):
    t = max(0.0, t)
    return '%d:%04.1f' % (int(t // 60), t - 60 * int(t // 60))


def main():
    parser = argparse.ArgumentParser(
        description='Detect the beats and the song structure (intro, verse, '
                    'chorus, bridge, instrumental, outro) of an audio file '
                    'and write them to JSON, or play the audio with a tick '
                    'on every stored beat (--validate).')
    parser.add_argument('file', help='audio file: .mp3|.m4a|.wav|.ogg|.flac ...')
    parser.add_argument('--json', metavar='FILE', default=None,
                        help='results file, written for detection and read '
                             'for --validate (default: <FILE>.beats.json)')
    parser.add_argument('--no-segments', action='store_true',
                        help='skip the structure analysis, only detect beats')
    parser.add_argument('--validate', action='store_true',
                        help='play the audio with a tick at every beat stored '
                             'in the JSON file instead of detecting beats')
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        parser.error('no such audio file: %s' % args.file)

    json_path = args.json or default_json_path(args.file)

    if args.validate:
        if not os.path.isfile(json_path):
            parser.error('no such beat file: %s (run detection first)' % json_path)
        validate(args.file, json_path)
        return

    samples, rate = decode_audio(args.file, rate=ANALYSIS_RATE)
    duration = len(samples) / float(rate)

    progress_status('detecting beats ...')
    bpm, beats = detect_beats(samples, rate)
    progress_done()

    print('detected %d beats at ~%.1f BPM (duration %s)' % (
        len(beats), bpm, fmt_time(duration)))
    if len(beats) == 0:
        print('no beats detected in %s' % os.path.basename(args.file))
    else:
        first = ', '.join('%.3f' % t for t in beats[:8])
        more = ' ...' if len(beats) > 8 else ''
        print('  first beats: %s%s' % (first, more))

    segments = None
    if not args.no_segments:
        progress_status('analysing structure ...')
        feat = compute_features(samples, rate)
        regions, segs = detect_structure(feat, beats)
        segments = analyse_segments(feat, rate, regions, segs, duration)
        progress_done()

        print('structure: %d parts' % len(segments))
        for i, s in enumerate(segments, 1):
            print('  %2d  %s - %s  %-12s %-8s %6.1f Hz  %s' % (
                i, fmt_time(s['start']), fmt_time(s['end']), s['part'],
                LEVEL_NAMES[s['level']], s['dominant_hz'], s['character']))

    write_json(json_path, args.file, rate, duration, bpm, beats, segments)
    print('wrote %s' % json_path)


if __name__ == '__main__':
    main()
