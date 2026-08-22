# LaserDisplay

Python 3 framework for driving show lasers. It provides a common drawing API
(`draw_line`, `draw_rect`, `draw_ellipse`, bezier curves, text, transforms,
zoom/mirror) on top of several backends: a pygame simulator, USB hardware
(lumax, local USB devices), and a TCP client/server mode so that rendering
clients can run on a different machine than the one connected to the laser.

## Installation

The lumax driver is included as a git submodule, therefore clone with
`--recurse-submodules` (or run `git submodule update --init` afterwards):

```
git clone --recurse-submodules <repository-url>
cd laserdisplay
python -m venv venv
source venv/bin/activate
pip install -e .
```

Optional dependencies for the audio examples (GStreamer 1.x + PyGObject):

- Debian/Ubuntu: `apt install python3-gi gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good`
- macOS (Homebrew): `brew install gstreamer gst-plugins-base gst-plugins-good && pip install PyGObject`

## Backends

Which backend is used is controlled by the environment variable `LASER` via
the factory method `LaserDisplay.create()`:

| `LASER`                      | Backend                                            |
|------------------------------|----------------------------------------------------|
| *(unset)*                    | pygame simulator window (default)                  |
| `lumax`                      | lumax device over USB                              |
| `local`                      | local USB laser device (vendor id `0x3333`)        |
| `remote:host`                | remote LaserDisplay server, default port `31337`   |
| `remote:host:port`           | remote LaserDisplay server on a custom port        |

Example:

```
LASER=lumax python examples/cube.py
```

## Client/server mode

The drawing protocol is spoken over TCP, so the laser-driving process can run
on one machine while clients render from anywhere on the network. Start a
server that owns the hardware:

```
python server-simulator.py              # renders into the simulator window
python server-hardware.py               # drives the local USB device
python server-lumax.py                  # drives the lumax device
LASER=lumax python server-svglaser.py   # accepts SVG uploads and displays them on the device
```

For the latter command, you can post SVG files to the server via:

```
curl --data-urlencode "svg@examples/files/ccc.svg" http://localhost:8000/
```

Each server listens on port `31337`. Then point clients at it:

```
LASER=remote:127.0.0.1:31337 python examples/cube.py
```

or, using the default port:

```
LASER=remote:localhost python examples/clock.py
```

## Examples

All examples live in `examples/` and select their backend through `LASER`.

| Example                    | Description                                                        |
|----------------------------|--------------------------------------------------------------------|
| `pointline.py`             | minimal demo: one moving point and line                            |
| `cube.py`                  | rotating wireframe cube                                            |
| `clock.py`                 | analog clock                                                       |
| `shapes.py`                | shape pipeline demo: Geometry shapes transformed with Animate      |
| `scheduler.py`             | plays the XML animation timeline `shapes.xml` (see below)          |
| `pong.py`                  | playable pong — controls: player 1 `q`/`a`, player 2 `o`/`l`, `esc` quits (opens a control window when not running in the simulator) |
| `bezier-screensaver.py`    | flying quadratic bezier curves                                     |
| `spaceship.py`             | transformed bezier spaceship                                       |
| `showsvg.py FILE.svg`      | renders SVG vector graphics (samples in `examples/files/`)         |
| `example_GML.py FILE.gml SECONDS` | plays Graffiti Markup Language taggings (samples in `examples/files/`); replays every `SECONDS` |
| `example_ILDA.py FILE.ild` | plays ILDA laser frame files (reader/writer in `ILDA.py`)          |
| `audio-fft.py`             | 16-band FFT spectrum analyser reacting to system audio             |
| `audio-raw.py`             | oscilloscope-style waveform of the audio signal                    |
| `audio-shapes.py FILE`     | analyses an audio file (tempo, onsets, melody via FFT) and renders geometric shapes animated to the music; plays the file during the show |
| `youscope.py`              | YOUSCOPE emulator; requires `youscope-wave.wav` (see script)       |

Notes:

- The audio examples capture audio with GStreamer. On Linux they monitor the
  PulseAudio output named by the `DEVICE` constant at the top of the scripts;
  on other platforms they fall back to the platform's default audio source
  (e.g. microphone).
- `bedit.py` in `examples/` is an experimental interactive bezier editor
  (pygame window, mouse input).

## SVG web editor (svglaser)

`server-svglaser.py` starts an HTTP server on port `8000` which both serves
the browser-based SVG editor from `svglaser/` and renders whatever SVG
document is POSTed to it (25 fps):

```
python server-svglaser.py
```

Then open <http://localhost:8000/>, draw something and press the **LASER**
button to display it on the laser (or simulator). The **SVG** button exports
the drawing as an `.svg` file. Drawings can also be posted programmatically:

```
curl --data-urlencode "svg@drawing.svg" http://localhost:8000/
```

## Writing your own animation

```python
import LaserDisplay

LD = LaserDisplay.create()          # backend chosen via $LASER
LD.set_zoom(0.5)                    # scale output about the center (default 1.0)
LD.set_mirror(1, 0)                 # mirror horizontally
LD.set_scan_rate(10000)             # scanner speed in points per second

LD.set_color(LD.RED)
LD.draw_line(0, 0, 255, 255)
LD.show_frame()
```

Coordinates are in the range `0–255` on both axes, origin in the upper left
corner. All backends support `set_zoom()` and `set_mirror()`; drawing happens
into a frame buffer and is sent to the display with `show_frame()`. Scripts
should wrap their main loop in `try/except KeyboardInterrupt` and call
`LD.close()` in a `finally` block so the output is stopped cleanly on Ctrl-C.

## Shape animations

Instead of drawing primitives one by one, frames can be composed from shapes
(`LaserDisplay/Shape.py`, `Geometry.py`) that are transformed by the `Animate`
class (`LaserDisplay/Animate.py`):

```python
from LaserDisplay import Geometry, Animate

t1 = Geometry.triangle(x0, y0, x1, y1, x2, y2, npoints, rd, gr, bl)
Animate.apply_rotation(t1, pivot_x, pivot_y, angle)   # in-place, per frame

LD.new_frame()
LD.add_shape_to_frame(t1)
LD.show_frame()
```

Shapes use a 16 bit coordinate/color space (`0 .. 255*255`, y pointing up).
`Animate` provides the in-place transformations `apply_translation`,
`apply_rotation`, `apply_scale`, `apply_color_shift`, `apply_blank` (beam off
at every n-th point), `apply_delete_points` and `apply_add_points`.

## Scheduler and XML animation timelines

The `Scheduler` (`LaserDisplay/Scheduler.py`) plays a timeline of events at a
fixed frame rate (default 25 fps). It keeps track of the active shapes,
applies continuous effects to them every frame and renders the frame via the
shape API. Events come from a human-readable XML file and can additionally be
injected programmatically while the animation is running (all scheduler
methods are thread-safe):

```python
import LaserDisplay
from LaserDisplay import Scheduler

LD = LaserDisplay.create()
scheduler = Scheduler(LD, fps=25)
scheduler.load_xml('shapes.xml')
scheduler.run()                     # or run_in_background() for injection
```

A ready-made timeline plus runner can be found in
`examples/shapes.xml` and `examples/scheduler.py`. The complete XML format
reference is in [SCHEDULER.md](SCHEDULER.md).

### XML file format

The root element `<animation>` accepts the attributes `fps` (frame rate) and
`duration` (seconds; without it the timeline runs until `stop()` is called).
It contains two kinds of children: `<shape>` definitions and `<event>` entries.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<animation fps="25" duration="16">

    <!-- shape definitions, activated later by <create> events -->
    <shape name="spinner" type="triangle"
           x0="88" y0="98" x1="168" y1="98" x2="128" y2="170"
           npoints="24" red="255" green="120" blue="0"/>

    <shape name="wobble" type="line"
           x0="30" y0="60" x1="226" y1="60"
           npoints="40" red="0" green="255" blue="80" blank="5"/>

    <!-- the timeline; events may appear in any order -->
    <event at="0.0">
        <create shape="spinner"/>
        <effect shape="spinner" type="rotation" speed="45"/>
    </event>

    <event at="13.0">
        <destroy shape="spinner"/>
    </event>
</animation>
```

All numbers in the XML use the friendly `0–255` scale (they are converted to
the internal 16 bit range automatically). The y axis points **up**: `y="0"` is
the bottom of the frame. Times are seconds, events are executed when the
animation time reaches their `at` value.

#### `<shape>` — a named shape definition

| Attribute               | Meaning                                              |
|-------------------------|------------------------------------------------------|
| `name`                  | unique name referenced by events                     |
| `type`                  | `line`, `triangle`, `circle` or `tetragon`           |
| `npoints`               | number of points interpolated along the outline      |
| `red`, `green`, `blue`  | color, each `0–255` (default `255`)                  |
| `blank`                 | optional; blank every n-th point (dashed outlines)   |

The remaining attributes are the geometry coordinates:

| Type        | Attributes                             |
|-------------|----------------------------------------|
| `line`      | `x0 y0 x1 y1`                          |
| `triangle`  | `x0 y0 x1 y1 x2 y2`                    |
| `circle`    | `cx cy r`                              |
| `tetragon`  | `x0 y0 x1 y1 x2 y2 x3 y3`              |

#### `<event>` — actions at a timestamp

An `<event at="SECONDS">` contains any number of actions:

| Action                                   | Meaning                                    |
|------------------------------------------|--------------------------------------------|
| `<create shape="NAME"/>`                 | activate a defined shape                    |
| `<destroy shape="NAME"/>`                | remove a shape from the animation           |
| `<effect shape="NAME" type="..." .../>`  | attach a continuous effect, starting now    |

#### `<effect>` — continuous effects

Effects are re-computed from the shape's original points every frame, so they
do not drift and can be combined freely (they are applied in the order they
are attached). Coordinates/amplitudes use the `0–255` scale, speeds are in
degrees or units per second, frequencies in hertz.

| `type`         | Attributes (all optional unless noted)                                                                 |
|----------------|--------------------------------------------------------------------------------------------------------|
| `rotation`     | `pivot_x`, `pivot_y` (default: frame center), `speed` (deg/s, default 45), `phase` (degrees)           |
| `translation`  | `vx`, `vy` (units/s) plus optional wobble `ax`, `ay` (amplitude) and `fx`, `fy` (Hz), `phase` (radians) |
| `scale`        | static `factor`, or pulsing with `min`, `max`, `frequency`; `center_x`, `center_y` (default: center)   |
| `color_shift`  | `dr`, `dg`, `db` — color change per second (negative values fade a channel out)                        |
| `blink`        | `period` (s), `duty` (on-fraction 0–1), `every` (blank every n-th point while on)                      |

### Runtime events

While the animation runs in the background, shapes and effects can be created
from any thread:

```python
from LaserDisplay import Rotation

scheduler.run_in_background()
...
scheduler.create_circle('ping', cx, cy, r, npoints)
scheduler.add_effect('ping', Rotation(speed=180))
scheduler.destroy('ping')
scheduler.schedule(5.0, some_function)   # call at animation time 5s
scheduler.stop()
```
