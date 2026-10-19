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
take effect with `LASER=lumax` (one renderer per card); the driver's blanking
delay is system-wide, so per-device values are applied in device order and the
last one wins.

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

## Next steps
- make the blanking delay settings (`set_blanking_delay`) individual for every device. Update `lasershow-player.py` and `LaserDisplayLumax.py`.