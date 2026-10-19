# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

LaserDisplay is a Python 3 framework for driving show lasers, plus the laser-show
content it plays. The repo has two halves: the `LaserDisplay/` package (backends,
drawing APIs, shape/effects engine, XML timeline scheduler) and the show content
in `lasershows/` (music-synchronized XML shows, an `effects/` library, and per-show
beat-detection reports).

## Setup

```
git clone --recurse-submodules <url>      # or: git submodule update --init
python -m venv venv && source venv/bin/activate
pip install -e .
```

- `LaserDisplay/lumax` is a git submodule (C USB driver + ctypes bindings for lumax
  laser cards; see its own `CLAUDE.md` inside).
- The venv runs Python 3.14. `pyproject.toml` dependencies are incomplete: the
  `local` backend also needs `pyusb`, and `tools/beat-detector.py`, the audio
  examples, and `lasershow-player.py` audio playback need GStreamer + `librosa` +
  `sounddevice` (installed on top of `PyGObject`).
- There is no test suite and no linter.

## Common commands

```
# play a show (backend chosen via $LASER, default = pygame simulator window)
python lasershow-player.py [--fast] [--start-at TIME] [--settings FILE] lasershows/<show>/<show>.xml [MUSIC.m4a|mp3|...]

# validate a show XML without real-time pacing or audio (runs as fast as possible)
python lasershow-player.py --fast lasershows/<show>/<show>.xml

# run any example on a different backend
LASER=lumax python examples/cube.py
LASER=remote:localhost python examples/clock.py

# client/server mode: server owns the device (port 31337), clients point at it
python server-simulator.py | server-hardware.py | server-lumax.py
LASER=lumax python server-svglaser.py     # port 8000: web SVG editor + renders POSTed SVGs
curl --data-urlencode "svg@file.svg" http://localhost:8000/

# beat detection for show creation (writes <file>.beats.json; --validate plays back with ticks)
venv/bin/python tools/beat-detector.py SONG.m4a
```

`--start-at` accepts seconds or `M:SS[.d]` (e.g. `1:30.5`) and seeks the show and
music together.

The laser system settings (zoom, mirroring, x-y swap, scan rate, blanking
delay — globally and per device in `[device N]` sections) live in
`settings.toml` at the repo root; `--settings FILE` overrides them, a missing
file falls back to the player's built-in defaults. The device sections only
take effect with `LASER=lumax` (one renderer per card). The driver's blanking
delay is process-wide, but the backend pushes each card's value right before
that card's frame is encoded, so per-device `blanking_delay` works.

## Architecture

### Backends

`LaserDisplay.create(mode=os.getenv('LASER'))` in `LaserDisplay/__init__.py` is the
factory: unset → `LaserDisplaySimulator` (pygame), `lumax` → `LaserDisplayLumax`,
`local` → `LaserDisplayLocal`, `remote:host[:port]` → `LaserDisplayRemote`.
`createProxy([modes])` wraps several displays and fans every drawing call out to
all of them (multiple lumax cards).

All backends subclass `LaserDisplay` (`LaserDisplay/LaserDisplay.py`), which
provides two drawing APIs:

1. Classic primitives (`draw_point/line/rect/ellipse/polyline/quadratic_bezier/
   cubic_bezier/text`) in display coordinates 0–255, y **down**, origin top-left.
   Frames are sent with `flush_frame()`.
2. Shape API: `new_frame()` / `add_shape_to_frame(shape)` / `show_frame()`.
   By default `show_frame()` replays each shape through the classic primitives
   (`_draw_shape`); a backend may override it with a direct path (the lumax
   backend buffers points and renders them itself).

**Coordinate spaces — three, easy to mix up:**
- Display: 0..255, y down, top-left origin (classic primitives, remote protocol).
- Shape: numpy `uint16` arrays of shape (n, 5) = [x, y, r, g, b], 16-bit range
  0..255*255, y **up** (bottom-left origin). `_draw_shape` converts to display
  space: `y' = (SIZE-1) - y/255`, colors `>> 8`. A blanked point (r=g=b=0) splits
  a polyline so the beam travels with the beam off.
- XML: 0..255, y up. The Scheduler scales to 16-bit when loading.

Zoom/mirroring (`set_zoom`/`set_mirror`) scale about the frame center. Backends
that transform on the client side run every point through `_output_transform()`
(remote does); the lumax backend instead bakes mirroring into the device
(`MIRROR_X/Y = 1`).

`LaserDisplayRemote` speaks a line-oriented text protocol over TCP (default port
31337): `point/line/rect/ellipse/polyline/quadratic/cubic/color/show/config`,
CRLF-terminated. `LaserServer` (Twisted `LineOnlyReceiver`) parses the same lines
and dispatches to a backend chosen by `start(backend=...)`.

The simulator is more than a renderer: it draws a wall-clock timer and, like
`tools/song-stopwatch.py`, lets you press `i/v/c/o/b/m/s/l` keys and mouse
clicks during a show to mark song sections and build up a section timeline.

### Shape / effects engine

- `Shape` — just a `uint16` (n, 5) point array.
- `Geometry` — static builders (`line`, `line_points`, `triangle`, `circle`,
  `ellipse`, `tetragon`) returning `Shape` in 16-bit space.
- `Animate` — effect classes, each with `transform(pts, dt)`; `apply(shape,
  effect, t)` evaluates them. Effects are **recomputed from the shape's original
  points every frame** (never incrementally), so they are drift-free and
  composable in any order/number. `SpeedUp` is the exception: it rescales the
  effective time `dt` of a shape's other effects and is handled by the Scheduler,
  not as a point transform.

### Scheduler (`LaserDisplay/Scheduler.py`)

Plays an XML timeline (`<animation>` with `<shape>`, `<event>`, `<sequence>`
elements) at a fixed fps (default 25). The complete format reference is
`lasershows/XML_FORMAT.md` — read it before writing or changing show XML or the
parser. Key behaviors:

- `<sequence name="X" file="path.xml"/>` pulls in another file's shapes and
  events; `file` resolves relative to the referencing file's directory; nested
  sequences work; circular references are rejected. Starting a sequence shifts
  its events relative to the creating event; sequence-level `<effect>`s apply to
  every shape the sequence creates; `<destroy sequence="X"/>` removes its shapes
  and cancels its remaining events.
- All runtime methods are thread-safe: with `run_in_background()`, shapes,
  effects and one-shot callbacks can be injected from other threads
  (`create_*`, `add_effect`, `destroy`, `schedule(at, fn)`, `stop`).
- `run(speed=...)` scales wall-clock pacing; `speed=0` is the fast/validate mode
  used by `lasershow-player.py --fast`.

### SVG path

`SvgProcessor` (pycairo-based) converts SVG documents into the classic drawing
primitives; used by `examples/showsvg.py` and `server-svglaser.py`. The browser
editor in `svglaser/` (jquery + svgcanvas.js) POSTs SVGs to that server.

## Laser-show workflow

Each show lives in `lasershows/<show-name>/` and contains: the song audio
(`.m4a`/`.mp3`), a beat report `<name>.json` (from `tools/beat-detector.py`:
beat timestamps + song-structure segments), the show `<name>.xml`, and often a
`prompt.md` describing the song and the show's creative direction.

`lasershows/effects/` is a library of small, single-purpose show snippets
(~70 files, each an `<animation>` with one or a few shapes + effects) that are
reused via `<sequence>` references — new shows are largely compositions of these
plus custom shapes, with sequence-level effects added at the reference site.

Creating a show for a song is done with the `create-lasershow` skill
(`/create-lasershow <song> <band> <beat report> <output xml>`), which encodes the
creative conventions (color scheme, ≤4 simultaneous shapes, accents on beats,
symmetry, fast pattern changes). It expects `lasershows/example.xml` and
`example-sequences.xml` as references.

**Validating show output: never via screenshots** — the backend cannot do image
recognition of the pygame window. Validate shows with
`python lasershow-player.py --fast <show>.xml` (runs the full timeline and
surfaces XML/parser errors), and by reading the XML against `XML_FORMAT.md`.

## Next Steps

Frame-generation pipeline review (2026-10-19) and the Python-side fixes that
followed it. Per-frame numbers are measured with `tools/frame-bench.py`
(added 2026-10-19) on the dev Mac (Apple silicon, venv Python 3.14):
`python tools/frame-bench.py <show>.xml` benchmarks a real show, `--sweep` runs
the 500/2k/8k/32k-point synthetic scaling, and `--points N` one size. It is
pure CPU (no hardware, no audio, no window), so the numbers reproduce
before/after a change.

**Status:** items 2–6 are done. Item 1 (the lumax card-query latency) is the
only remaining item and needs a hardware check before it is touched. Within
item 5, the Rainbow arclength cache and the dead-code cleanups were
deliberately **not** done (see that item).

### 1. (open) Lumax: the 30 ms card-query is the dominant latency

`lumaxlib.py send_frame()` calls `wait_for_buffer(handle, 17)` after every
`Lumax_SendFrame`; that enters the timeout branch of `Lumax_WaitForBuffer`
(`liblumax.c` ~line 739), which purges, writes the query, then does an
**unconditional `usleep(30000)`** before the first read — so each call costs
≥30 ms even when the card answers instantly, and the 17 ms deadline can never
take effect. With two cards served sequentially that is ≥60 ms/frame, over the
40 ms (25 fps) budget: on real hardware the show is paced by card queries, not
by the scheduler. Verify on the cards first, then fix. Options, in increasing
order of change: shorten the first poll to 2–5 ms (cards answer in ~5 ms) and
poll until the deadline; or use the `TimeToWait`/`TimeUntilFree` value
`Lumax_SendFrame` already reads from the frame-end reply and drop the second
round-trip; or wait for buffer-free *before* sending (the reference VB flow
does this) instead of after; and/or send to both cards first, wait once.
This is the only remaining CPU→device gap; the encode and replay work below no
longer competes with it.

### 2. (done) Vectorize `lumaxlib.lumax_renderer.__generate_buffer()`

Replaced the per-point Python loop (numpy scalar reads + scalar `xout`/`yout`
helpers + 5 ctypes writes/point) with one vectorized build: the whole frame is
assembled as a single C-contiguous `(total, 9)` uint16 array `[x, y, r, g, b,
Ch6, Ch7, Ch8, TTL]` (leading center point, then per-shape
`[blank@first, lit points, blank@last]`), zoom/clip/mirror applied with numpy,
and mapped onto the ctypes struct array in one copy
(`(_lpoint * total).from_buffer(arr)` — `_lpoint` is 9 contiguous uint16s, no
padding, so the layout is byte-identical). `_lpoints` is now a thin wrapper
(`length` + `struct_arr`) around that buffer; the old `_lpoints(n)` zero-fill
loop is gone. Verified byte-identical to the old loop across
zoom×mirrorx×mirrory×swapxy permutations and multi-shape frames with blanks.

`__generate_buffer` ms/frame, `--sweep` (1 renderer):

```
points | before | after
   500 |   1.68 |  0.05   (34×)
  2000 |   6.59 |  0.06   (110×)
  8000 |  27.76 |  0.10   (278×)
 32000 | 103.43 |  0.25   (414×)
```

~4 µs/point → ~0.01 µs/point; the encode is now sub-millisecond at every size
that matters, so it no longer competes with the 40 ms budget (×2 cards).

### 3. (done) Vectorize `LaserDisplay._draw_shape()` (simulator/remote/local replay)

Replaced the per-point scalar while loop with numpy run detection: color-run
boundaries are found with one comparison over the color columns
(`change[0]=True; change[1:] = (color[1:] != color[:-1]).any(axis=1)`), each
maximal constant-color stretch is a segment and a segment that is not blank
(r=g=b=0) is a run; blank segments draw nothing and split the polyline. Display
coordinates are computed once for all points and sliced per run; a 1-point run
calls `draw_point`, a longer one calls `draw_polyline` with a numpy `(m, 2)`
array. Semantics preserved exactly (blank points split runs, single lit points
become points, equal-color adjacency is one polyline) — verified identical call
sequences to the old loop on frames with blanks, single points and multi-run
shapes.

`LaserDisplayRemote` polylines/quadratic/cubic are built in one pass:
`__write_points` applies the `_output_transform` math to the whole array and
formats the message body with `numpy.savetxt` into a single `sendall` (byte-
identical to the old per-point `'%f %f'`, including the empty case).

Replay (`_draw_shape`) ms/frame, `--sweep` (random-color shapes, every point its
own run — the worst case for the new run loop; real shows have a few long runs
and do better):

```
points | before | after
   500 |   0.75 |  0.59
  2000 |   3.01 |  2.29
  8000 |  12.36 |  8.93
 32000 |  47.76 | 35.52
```

Even in the adversarial isolated-run case the precompute makes the new path
~1.3–1.4× faster; on realistic (few-long-run) shapes the win is larger, and
`shed-my-skin` replay dropped 0.11 → 0.05 ms/frame (2.2×).

### 4. (done) Lumax: plain list in `add_shape_to_frame()`

`lumax_renderer.shapes` is now a plain Python list (`__init__` and `new_frame`
reset to `[]`; `add_shape_to_frame` appends) instead of a `numpy.append`'d
object array — `numpy.append` is O(n) per call (a k-shape frame cost O(k²)) and
produced an object array that only masqueraded as a list. `len()`, iteration
and `get_points()` all work unchanged; demos keep working.

### 5. (done, with deliberate skips) Minor items

Done:
- `Scheduler.__update_shapes` stores the per-frame float64 result in a new
  `entry.display_points` instead of overwriting `entry.shape.points` (a uint16
  by contract); `__render` reads `display_points`. `entry.base` remains the
  sole original-points source.
- `Scheduler.__visible_shape` is now `__visible_points(pts)` (takes the array
  directly) with a single chained mask
  `((pts[:, 0:2] >= 0) & (pts[:, 0:2] <= MAX)).all(axis=1)` instead of four
  separate comparisons.
- The simulator renders the 3 legend strings once in `__init__` (cached
  surfaces) and re-renders the two timestamp surfaces only when the 10 ms tick
  changes, replacing 5 font renders/frame with blits.

Deliberately skipped (by decision):
- **Rainbow arclength cache** — caching `_arclength_fraction()` per point count
  would freeze the gradient for any future show that puts a geometry-altering
  effect (`warp`/`morph`) ahead of `rainbow` in the chain; the gain is a few µs,
  not worth the latent correctness risk.
- **Dead code** — `AddPoints`/`DeletePoints` (exported from
  `LaserDisplay/__init__.py` but unused), the legacy `shape`/`geometry` classes
  in `lumaxlib.py` (used only by the demos), and `LaserDisplay.noise_clamp()`
  (shadows `min`/`max`, only the local backend uses it) all left in place.

### 6. (done) Benchmark harness — `tools/frame-bench.py`

Added. Given a show XML it runs the Scheduler (mock display, no audio, no
real-time pacing) and reports ms/frame for the scheduler core (process events /
update shapes / render, via phase timing), the lumax encode
(`__generate_shape_points` + `__generate_buffer` on a device-less renderer), and
the `_draw_shape` replay, plus average/peak points/frame. `--sweep` /
`--points N` add the synthetic scaling. No hardware, no audio, no window.
Rule of thumb now: a few hundred points/frame is free on the CPU side at every
stage; the lumax encode is sub-millisecond, and the real-time bottleneck on
hardware is item 1's card query, not the encode.