#!/usr/bin/env python3
# Benchmark the per-frame generation pipeline: how fast is each stage that
# produces the points a frame is made of, in ms/frame.
#
#   python frame-bench.py SHOW.xml [--seconds N]
#   python frame-bench.py --points N [--shapes S] [--effects E]
#   python frame-bench.py --sweep
#
# Two modes:
#
#   show mode (default, or SHOW.xml given)
#       Runs a real show through the Scheduler (no audio, no real-time
#       pacing) and reports the cost of each stage for the show's frames:
#         - scheduler core:  process events + effect transforms + visibility
#         - lumax encode:    __generate_shape_points + __generate_buffer, via
#                            a device-less renderer (pure CPU, no card)
#         - classic replay:  _draw_shape (the simulator / remote / local path)
#       plus the average and peak point count per frame.
#
#   points mode (--points / --sweep)
#       Synthetic scaling: N points/frame of random shapes with a few effects,
#       to see how each stage scales with point count. --sweep runs the
#       500 / 2000 / 8000 / 32000 point sizes in one table.
#
# No hardware, no audio, no window: pure CPU measurement, so the numbers are
# comparable across machines and before/after a change.

import argparse
import os
import sys
import time
import numpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import LaserDisplay
from LaserDisplay import Scheduler, Shape


# ----- device-less lumax renderer (encode path only, no card) -----

def deviceless_renderer():
    """a lumax_renderer with just the transform state set, so
    __generate_buffer can be timed without opening a USB device"""
    from LaserDisplay.lumax.python import lumaxlib
    r = object.__new__(lumaxlib.lumax_renderer)
    r.mirrorx, r.mirrory, r.zoom, r.swapxy = 0, 0, 0.1, 0
    return r


class _Stub:
    # __generate_shape_points only reads SCALE and SIZE
    SCALE = 255
    SIZE = 256


def bench_lumax(frames, reps=1):
    """encode a list of frames (each a list of shapes) through the lumax
    renderer path; returns (t_gsp, t_add, t_gen, n) in seconds/frame. Each
    frame is encoded `reps` times so a single synthetic frame gives a stable
    number; real show mode passes reps=1 (the many distinct frames already
    average out)."""
    from LaserDisplay.lumax.python import lumaxlib
    from LaserDisplay.LaserDisplayLumax import LaserDisplayLumax
    gen = lumaxlib.lumax_renderer._lumax_renderer__generate_buffer
    add = lumaxlib.lumax_renderer.add_shape_to_frame
    newf = lumaxlib.lumax_renderer.new_frame
    gsp = LaserDisplayLumax._LaserDisplayLumax__generate_shape_points
    stub = _Stub()

    r = deviceless_renderer()
    t_add = t_gen = t_gsp = 0.0
    n = 0
    for shapes in frames:
        for _ in range(reps):
            newf(r)
            t0 = time.perf_counter()
            pts_list = [gsp(stub, s) for s in shapes]
            t_gsp += time.perf_counter() - t0
            t0 = time.perf_counter()
            for pts in pts_list:
                add(r, lumaxlib.shape(pts))
            t_add += time.perf_counter() - t0
            t0 = time.perf_counter()
            gen(r)
            t_gen += time.perf_counter() - t0
            n += 1
    return t_gsp / n, t_add / n, t_gen / n, n


# ----- show mode -----

class MockDisplay(LaserDisplay.LaserDisplay):
    def __init__(self):
        LaserDisplay.LaserDisplay.__init__(self)
        self.frames = 0
        self.samples = []            # sampled frames (list of shapes)
        self.sample_every = 25       # one per second at 25 fps

    def show_frame(self):
        self.frames += 1
        if self.frames % self.sample_every == 0:
            self.samples.append(list(self.frame_shapes))
        self.frame_shapes = []

    def flush_frame(self):
        pass

    def draw_point(self, x, y, flags=0): pass
    def draw_line(self, x1, y1, x2, y2): pass
    def draw_polyline(self, points): pass
    def draw_rect(self, x, y, w, h): pass
    def draw_ellipse(self, cx, cy, rx, ry): pass
    def draw_quadratic_bezier(self, points, steps): pass
    def draw_cubic_bezier(self, points, steps): pass


def frame_point_counts(frames):
    counts = [sum(s.get_number_of_points() for s in fr) for fr in frames]
    if not counts:
        return 0.0, 0
    return sum(counts) / len(counts), max(counts)


def run_scheduler(show, seconds):
    disp = MockDisplay()
    sched = Scheduler(disp, fps=25)
    sched.load_xml(show)
    fps = sched.fps
    duration = seconds if sched.duration is None else min(seconds, sched.duration)
    n_frames = int(duration * fps)

    t_ev = t_up = t_re = 0.0
    orig_ev = sched._Scheduler__process_events
    orig_up = sched._Scheduler__update_shapes
    orig_re = sched._Scheduler__render

    def ev(now):
        nonlocal t_ev
        t0 = time.perf_counter(); orig_ev(now); t_ev += time.perf_counter() - t0

    def up(now):
        nonlocal t_up
        t0 = time.perf_counter(); orig_up(now); t_up += time.perf_counter() - t0

    def re():
        nonlocal t_re
        t0 = time.perf_counter(); orig_re(); t_re += time.perf_counter() - t0

    sched._Scheduler__process_events = ev
    sched._Scheduler__update_shapes = up
    sched._Scheduler__render = re

    t0 = time.perf_counter()
    virt = 0.0
    interval = 1.0 / fps
    for _ in range(n_frames):
        ev(virt)
        up(virt)
        re()
        virt += interval
    total = time.perf_counter() - t0
    return disp, total, t_ev, t_up, t_re, n_frames


def bench_replay(frames, reps=1):
    """price the classic-primitive replay (_draw_shape) for sampled frames;
    returns seconds/frame. Each frame is replayed `reps` times so a single
    synthetic frame gives a stable number; real show mode passes reps=1."""
    disp = MockDisplay()
    t = 0.0
    for shapes in frames:
        for _ in range(reps):
            t0 = time.perf_counter()
            for s in shapes:
                disp._draw_shape(s)
            t += time.perf_counter() - t0
    return t / (len(frames) * reps)


def show_mode(show, seconds):
    print('show: %s  (%.0f s of timeline, %d fps)'
          % (os.path.relpath(show, ROOT), seconds, 25))
    disp, total, t_ev, t_up, t_re, nf = run_scheduler(show, seconds)
    frames = disp.samples
    avg_pts, peak_pts = frame_point_counts(frames)
    print('\n== scheduler core, %d frames ==' % nf)
    print('  process_events      %8.2f ms/frame' % (1000 * t_ev / nf))
    print('  update_shapes       %8.2f ms/frame' % (1000 * t_up / nf))
    print('  render(collect)     %8.2f ms/frame' % (1000 * t_re / nf))
    print('  total               %8.2f ms/frame' % (1000 * total / nf))
    print('  avg points/frame %8.0f   peak %d   (sampled %d frames)'
          % (avg_pts, peak_pts, len(frames)))

    if not frames:
        return
    print('\n== lumax encode (per sampled frame, 1 renderer) ==')
    t_gsp, t_add, t_gen, n = bench_lumax(frames)
    print('  generate_shape_points %7.2f ms' % (1000 * t_gsp))
    print('  add_shape_to_frame    %7.2f ms' % (1000 * t_add))
    print('  generate_buffer       %7.2f ms  (ctypes encode)' % (1000 * t_gen))
    print('  subtotal              %7.2f ms   (x2 for two cards)'
          % (1000 * (t_gsp + t_add + t_gen)))

    print('\n== classic replay _draw_shape (simulator/remote path) ==')
    print('  _draw_shape           %7.2f ms/frame' % (1000 * bench_replay(frames)))


# ----- points mode (synthetic scaling) -----

def make_shapes(total_pts, nshapes=4, n_effects=4, seed=0):
    from LaserDisplay.Animate import Rotation, Translation, Warp, Rainbow
    rng = numpy.random.RandomState(seed)
    per = max(1, total_pts // nshapes)
    pool = [Rotation(speed=45), Translation(vx=20 * 255, vy=0),
            Warp(amplitude=10 * 255), Rainbow()][:n_effects]
    shapes = []
    for _ in range(nshapes):
        pts = rng.randint(0, 65025, size=(per, 5), dtype='uint16')
        shapes.append([Shape(pts), [type(f)(**f.__dict__) for f in pool]])
    return shapes


def bench_update(shapes, frames=200):
    """scheduler __update_shapes equivalent: base.copy() + effect chain"""
    bases = [s.get_points().astype('float64') for s, _ in shapes]
    effects = [fx for _, fx in shapes]
    t = 0.0
    for _ in range(frames):
        t0 = time.perf_counter()
        for base, fx in zip(bases, effects):
            pts = base.copy()
            for f in fx:
                pts = f.transform(pts, 1.0)
        t += time.perf_counter() - t0
    return t / frames


def points_mode(total_pts, nshapes, n_effects, label):
    shapes = make_shapes(total_pts, nshapes, n_effects)
    frame = [[sh for sh, _ in shapes]]   # one frame of plain Shapes
    # repeat the single synthetic frame enough for a stable number, scaled so
    # the larger frames aren't measured hundreds of times
    reps = max(5, min(100, 20000 // total_pts))
    tu = bench_update(shapes)
    t_gsp, t_add, t_gen, _ = bench_lumax(frame, reps=reps)
    tr = bench_replay(frame, reps=reps)
    print('%11d | update %7.2f ms | gsp %5.2f | lumax buf %7.2f | replay %6.2f'
          % (total_pts, 1000 * tu, 1000 * t_gsp, 1000 * t_gen, 1000 * tr))


def sweep_mode(nshapes, n_effects):
    print('points/frame | scheduler update | gsp    | lumax buf | replay')
    for total in (500, 2000, 8000, 32000):
        points_mode(total, nshapes, n_effects, str(total))


def main():
    ap = argparse.ArgumentParser(
        description='Benchmark the per-frame generation pipeline (ms/frame)',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('show', nargs='?', default=None,
                    help='show XML to benchmark (show mode; default: shed-my-skin)')
    ap.add_argument('--seconds', type=float, default=30.0,
                    help='how much of the show timeline to run (default 30)')
    ap.add_argument('--points', type=int, default=None,
                    help='synthetic mode: total points/frame to benchmark')
    ap.add_argument('--sweep', action='store_true',
                    help='synthetic mode: benchmark 500/2k/8k/32k points')
    ap.add_argument('--shapes', type=int, default=4,
                    help='synthetic mode: number of shapes per frame (default 4)')
    ap.add_argument('--effects', type=int, default=4,
                    help='synthetic mode: effects per shape (default 4)')
    args = ap.parse_args()

    if args.sweep:
        sweep_mode(args.shapes, args.effects)
    elif args.points is not None:
        print('points/frame | scheduler update | gsp    | lumax buf | replay')
        points_mode(args.points, args.shapes, args.effects, str(args.points))
    else:
        show = args.show
        if not show:
            show = os.path.join(ROOT, 'lasershows', 'shed-my-skin', 'shed-my-skin.xml')
        show_mode(show, args.seconds)


if __name__ == '__main__':
    main()
