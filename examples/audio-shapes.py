#!/usr/bin/env python3
# analyse an audio file (rhythm, melody, recurring patterns) and render an
# animated geometric show that follows the music
#
# usage: LASER=... python audio-shapes.py FILE.wav|mp3|ogg|flac

import sys
import os
import math
import time

import numpy as np

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

import LaserDisplay

FPS = 25            # animation frame rate
SIZE = 256          # laser coordinate space
CENTER = SIZE / 2.0

# frequency range considered for the melody colour mapping
F_MIN = 80.0
F_MAX = 5000.0


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


# ---------- analysis -------------------------------------------------------

def normalize(x):
    span = x.max() - x.min()
    return (x - x.min()) / span if span > 0 else x * 0.0


def smooth(x, k=3):
    return np.convolve(x, np.ones(k) / k, mode='same')


def analyze(samples, rate):
    """Compute per-frame features: band energies, onsets, tempo, melody."""
    N = 1024                      # fft window
    hop = 512                     # hop between windows
    f_a = rate / hop              # analysis frame rate (~43 fps)

    n_frames = max(0, (len(samples) - N) // hop)

    progress_status('analysing: computing spectrogram ...')
    window = np.hanning(N)
    frames = np.lib.stride_tricks.sliding_window_view(samples, N)[::hop][:n_frames] * window
    spec = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(N, 1.0 / rate)

    progress_status('analysing: frequency bands ...')
    def band(lo, hi):
        mask = (freqs >= lo) & (freqs < hi)
        return normalize(smooth(spec[:, mask].mean(axis=1)))

    bass = band(20, 140)      # kick / drums
    mid = band(140, 2000)     # melody body
    high = band(2000, 8000)   # hi-hats / presence
    loud = normalize(smooth(np.sqrt((frames ** 2).mean(axis=1))))

    # onset strength: spectral flux (energy the spectrum gains between frames);
    # its peaks mark note/beat events, i.e. the recurring rhythm pattern
    progress_status('analysing: onset detection ...')
    flux = np.maximum(0.0, np.diff(spec, axis=0)).sum(axis=1)
    flux = smooth(normalize(flux))

    # tempo: autocorrelation of the onset envelope; the lag with the strongest
    # recurrence inside 60..190 BPM is the beat period
    progress_status('analysing: tempo estimation ...')
    centered = flux - flux.mean()
    ac = np.correlate(centered, centered, mode='full')[len(centered) - 1:]
    lags = np.arange(len(ac)) / f_a
    mask = (lags >= 60.0 / 190) & (lags <= 60.0 / 60)
    beat_period = float(lags[mask][np.argmax(ac[mask])]) if mask.any() else 0.5
    bpm = 60.0 / beat_period

    # onset peak picking with a minimum spacing of half a beat
    thresh = flux.mean() + flux.std()
    min_gap = int(f_a * beat_period / 2)
    onsets = []
    for i in range(1, len(flux) - 1):
        if flux[i] > thresh and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]:
            if not onsets or i - onsets[-1] >= min_gap:
                onsets.append(i)

    # melody: dominant frequency per frame -> hue
    progress_status('analysing: melody extraction ...')
    mel_mask = (freqs >= F_MIN) & (freqs <= F_MAX)
    mel_freqs = freqs[mel_mask]
    dominant = mel_freqs[spec[:, mel_mask].argmax(axis=1)]

    progress_done()

    duration = len(samples) / float(rate)
    print('duration %.1fs, tempo ~%.0f BPM, %d onsets detected'
          % (duration, bpm, len(onsets)))

    return {
        'f_a': f_a,
        'n_frames': n_frames,
        'bass': bass, 'mid': mid, 'high': high, 'loud': loud,
        'flux': flux, 'onset_times': [i / f_a for i in onsets],
        'beat_period': beat_period, 'bpm': bpm,
        'dominant': dominant, 'duration': duration,
    }


# ---------- drawing helpers ------------------------------------------------

def hsv_to_rgb(h, s, v):
    i = int(h * 6.0) % 6
    f = h * 6.0 - int(h * 6.0)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return (int(r * 255), int(g * 255), int(b * 255))


def polygon(points):
    # close the shape by repeating the first point at the end
    return points + [points[0]]


def draw_circle(LD, cx, cy, r, rotation=0.0, segments=16):
    pts = [[cx + r * math.cos(rotation + 2 * math.pi * i / segments),
            cy + r * math.sin(rotation + 2 * math.pi * i / segments)]
           for i in range(segments)]
    LD.draw_polyline(polygon(pts))


def draw_regular(LD, cx, cy, r, corners, rotation):
    pts = [[cx + r * math.cos(rotation + 2 * math.pi * i / corners - math.pi / 2),
            cy + r * math.sin(rotation + 2 * math.pi * i / corners - math.pi / 2)]
           for i in range(corners)]
    LD.draw_polyline(polygon(pts))


def play_audio(path):
    """Start playing the audio file; returns the pipeline for later cleanup."""
    Gst.init(None)
    uri = Gst.filename_to_uri(os.path.abspath(path))
    pipeline = Gst.parse_launch('playbin uri="%s"' % uri)
    pipeline.set_state(Gst.State.PLAYING)
    return pipeline


# ---------- main -----------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print('Usage: LASER=... python %s FILE.wav|mp3|ogg|flac' % sys.argv[0])
        sys.exit(1)

    samples, rate = decode_audio(sys.argv[1])
    ana = analyze(samples, rate)

    LD = LaserDisplay.create()
    LD.set_zoom(0.1)
    LD.set_scan_rate(5000)
    LD.set_blanking_delay(0)

    # play the music while the show runs; both are paced by the wall clock
    try:
        audio_pipeline = play_audio(sys.argv[1])
    except Exception as e:
        print('Could not start audio playback (%s), showing visuals only' % e)
        audio_pipeline = None

    f_a = ana['f_a']
    n = ana['n_frames']
    beat = ana['beat_period']
    onsets = ana['onset_times']
    onset_idx = 0
    last_onset = -10.0
    spin_kick = 0.0

    SHAPES = [draw_circle, lambda ld, cx, cy, r, rot: draw_regular(ld, cx, cy, r, 4, rot),
              lambda ld, cx, cy, r, rot: draw_regular(ld, cx, cy, r, 3, rot)]

    total_frames = int(ana['duration'] * FPS)
    start = time.time()

    try:
        for k in range(total_frames):
            t = k / float(FPS)

            # nearest analysis frame
            i = min(int(t * f_a), n - 1)
            bass_v = ana['bass'][i]
            mid_v = ana['mid'][i]
            high_v = ana['high'][i]
            loud_v = ana['loud'][i]

            # flash after each detected onset (rhythm events)
            while onset_idx < len(onsets) and onsets[onset_idx] <= t:
                last_onset = onsets[onset_idx]
                onset_idx += 1
            flash = math.exp(-(t - last_onset) * 8.0)

            # pulse within the recurring beat period
            phase = (t % beat) / beat
            beat_pulse = math.exp(-phase * 4.0)

            # melody pitch -> hue, loudness -> brightness
            dom = ana['dominant'][i]
            hue = ((np.log2(max(dom, F_MIN)) - np.log2(F_MIN)) /
                   (np.log2(F_MAX) - np.log2(F_MIN)))
            bright = 0.35 + 0.65 * loud_v

            # central shape: pulses with the bass, spins faster on beats,
            # switches between circle/square/triangle every 8 bars-ish
            beats_so_far = t / beat
            shape_fn = SHAPES[int(beats_so_far // 8) % len(SHAPES)]
            spin_kick += 0.35 * beat_pulse
            angle = 2 * math.pi * beats_so_far * 0.25 + spin_kick
            radius = (30 + 45 * bass_v) * (1.0 + 0.3 * flash)
            radius = min(radius, CENTER - 12)

            LD.set_color(hsv_to_rgb(hue, 0.85, bright))
            shape_fn(LD, CENTER, CENTER, radius, angle)

            # satellites orbiting the center, driven by the melody body
            orbit_r = 70 + 30 * mid_v
            sat_r = 3 + 6 * high_v
            LD.set_color(hsv_to_rgb((hue + 0.5) % 1.0, 0.85, bright))
            for j in range(6):
                a = -angle * 1.5 + 2 * math.pi * j / 6
                sx = CENTER + orbit_r * math.cos(a)
                sy = CENTER + orbit_r * math.sin(a)
                draw_circle(LD, sx, sy, sat_r, segments=8)

            # radial lines whose length follows the highs, counter-rotating
            line_len = 15 + 55 * high_v + 20 * flash
            LD.set_color(hsv_to_rgb(hue, 0.25, bright))
            inner = CENTER - 18
            for j in range(8):
                a = angle * 0.5 + 2 * math.pi * j / 8
                LD.draw_line(CENTER + inner * math.cos(a), CENTER + inner * math.sin(a),
                             CENTER + (inner + line_len) * math.cos(a),
                             CENTER + (inner + line_len) * math.sin(a))

            LD.show_frame()

            # pace to real time so animations match the original tempo
            target = start + (k + 1) / float(FPS)
            delay = target - time.time()
            if delay > 0:
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        if audio_pipeline is not None:
            audio_pipeline.set_state(Gst.State.NULL)
        LD.close()


if __name__ == '__main__':
    main()
