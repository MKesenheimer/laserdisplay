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
| `pong.py`                  | playable pong — controls: player 1 `q`/`a`, player 2 `o`/`l`, `esc` quits (opens a control window when not running in the simulator) |
| `bezier-screensaver.py`    | flying quadratic bezier curves                                     |
| `spaceship.py`             | transformed bezier spaceship                                       |
| `showsvg.py FILE.svg`      | renders SVG vector graphics (samples in `examples/files/`)         |
| `example_GML.py FILE.gml SECONDS` | plays Graffiti Markup Language taggings (samples in `examples/files/`); replays every `SECONDS` |
| `example_ILDA.py FILE.ild` | plays ILDA laser frame files (reader/writer in `ILDA.py`)          |
| `audio-fft.py`             | 16-band FFT spectrum analyser reacting to system audio             |
| `audio-raw.py`             | oscilloscope-style waveform of the audio signal                    |
| `youscope.py`              | YOUSCOPE emulator; requires `youscope-wave.wav` (see script)       |

Notes:

- The audio examples capture audio with GStreamer. On Linux they monitor the
  PulseAudio output named by the `DEVICE` constant at the top of the scripts;
  on other platforms they fall back to the platform's default audio source
  (e.g. microphone).
- `bedit.py` in `examples/` is an experimental interactive bezier editor
  (pygame window, mouse input).

## SVG web editor (svglaser)

`server-svglaser.py` starts an HTTP server on port `8000` which renders
whatever SVG document is POSTed to it (25 fps):

```
python server-svglaser.py
```

The `svglaser/` directory contains a browser-based SVG editor whose drawings
can be sent to the server, e.g.:

```
curl --data-binary 'svg=<svg xmlns="http://www.w3.org/2000/svg"><line x1="10" y1="10" x2="200" y2="200"/></svg>' http://localhost:8000/
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
