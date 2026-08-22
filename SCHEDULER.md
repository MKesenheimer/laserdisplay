# Scheduler and XML animation timelines

The `Scheduler` class (`LaserDisplay/Scheduler.py`) plays an animation made
of laser shapes. It runs the main loop at a fixed frame rate, keeps track of
which shapes are active, applies continuous effects to them every frame and
displays each frame through the usual LaserDisplay backends.

Events drive the animation: they create shapes, attach effects and destroy
shapes at given timestamps. Events come either from a human-readable XML
timeline file or are injected programmatically while the animation is running
(all public scheduler methods are thread-safe).

A complete example timeline and runner can be found in
`examples/shapes.xml` and `examples/scheduler.py`.

## Usage

```python
import LaserDisplay
from LaserDisplay import Scheduler

LD = LaserDisplay.create()          # backend chosen via $LASER
scheduler = Scheduler(LD, fps=25)
scheduler.load_xml('shapes.xml')
scheduler.run()                     # blocks until the duration has passed
LD.close()
```

| Method                              | Meaning                                                        |
|-------------------------------------|----------------------------------------------------------------|
| `Scheduler(display, fps=25)`        | create a scheduler for a LaserDisplay instance                 |
| `load_xml(filename)`                | read an XML timeline (see below)                               |
| `run(duration=None)`                | run the main loop; blocks the calling thread                   |
| `run_in_background(duration=None)`  | run the main loop in a daemon thread, returns the thread       |
| `stop()`                            | stop the main loop (safe to call from other threads)           |
| `current_time()`                    | current animation time in seconds                              |
| `schedule(at, function)`            | call `function` when the animation reaches time `at`           |

## XML file format

The root element is `<animation>`; it accepts the attributes

| Attribute  | Meaning                                                     |
|------------|-------------------------------------------------------------|
| `fps`      | frame rate of the main loop (default 25)                     |
| `duration` | total length in seconds; without it the loop runs until `stop()` |

It contains two kinds of children: `<shape>` definitions and `<event>`
entries. Events may appear in any order — they are executed when the
animation time reaches their timestamp.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<animation fps="25" duration="16">

    <!-- ==================== shape definitions ==================== -->

    <!-- triangle spinning around the center of the frame -->
    <shape name="spinner" type="triangle"
           x0="88" y0="98" x1="168" y1="98" x2="128" y2="170"
           npoints="24" red="255" green="120" blue="0"/>

    <!-- dashed line wobbling up and down -->
    <shape name="wobble" type="line"
           x0="30" y0="60" x1="226" y1="60"
           npoints="40" red="0" green="255" blue="80" blank="5"/>

    <!-- circle pulsing its radius -->
    <shape name="bubble" type="circle"
           cx="150" cy="165" r="35"
           npoints="48" red="40" green="120" blue="255"/>

    <!-- square drifting diagonally -->
    <shape name="square" type="tetragon"
           x0="90" y0="90" x1="166" y1="90" x2="166" y2="166" x3="90" y3="166"
           npoints="12" red="255" green="255" blue="255"/>

    <!-- ======================== timeline ========================= -->

    <event at="0.0">
        <create shape="spinner"/>
        <create shape="wobble"/>
        <effect shape="spinner" type="rotation" speed="45"/>
        <effect shape="wobble" type="translation" ay="45" fy="0.25"/>
    </event>

    <event at="3.0">
        <create shape="bubble"/>
        <effect shape="bubble" type="scale" min="0.5" max="1.4" frequency="0.5"/>
    </event>

    <event at="6.0">
        <!-- the spinner slowly turns from orange to magenta -->
        <effect shape="spinner" type="color_shift" dr="-85" dg="-45" db="100"/>
        <effect shape="wobble" type="blink" period="1.2"/>
    </event>

    <event at="13.0">
        <destroy shape="square"/>
    </event>
</animation>
```

### Units

All numbers in the XML use the friendly scale:

- coordinates, radii, amplitudes and colors: `0–255`
- the y axis points **up** (`y="0"` is the bottom of the frame)
- times, periods: seconds
- rotation speeds: degrees per second (positive = counter-clockwise)
- translation velocities: units per second (`0–255` scale)
- frequencies: hertz
- the values are converted to the internal 16 bit laser range automatically

### `<shape>` — a named shape definition

Defines a shape once; it becomes visible when a `<create>` event references
its name.

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

### `<event>` — actions at a timestamp

```xml
<event at="SECONDS">
    <create  shape="NAME"/>
    <destroy shape="NAME"/>
    <effect  shape="NAME" type="EFFECT_TYPE" param="value" .../>
</event>
```

An event may contain any number of actions; all of them fire when the
animation time reaches `at`:

| Action                                    | Meaning                                 |
|-------------------------------------------|------------------------------------------|
| `<create shape="NAME"/>`                  | activate a previously defined shape      |
| `<destroy shape="NAME"/>`                 | remove a shape from the animation        |
| `<effect shape="NAME" type="..." .../>`   | attach a continuous effect, starting now |

### `<effect>` — continuous effects

Effects are re-computed from the shape's original points on every frame, so
they do not accumulate rounding drift and can be combined freely. When several
effects are attached to one shape they are applied in the order in which they
were attached. All attributes are optional unless noted otherwise.

| `type`         | Attributes                                                                                             |
|----------------|--------------------------------------------------------------------------------------------------------|
| `rotation`     | `pivot_x`, `pivot_y` (default: frame center), `speed` (deg/s, default 45), `phase` (degrees)           |
| `translation`  | `vx`, `vy` (units/s) plus optional wobble `ax`, `ay` (amplitude) and `fx`, `fy` (Hz), `phase` (radians) |
| `scale`        | static `factor` (default 1.0), or pulsing with `min`, `max`, `frequency`; `center_x`, `center_y` (default: center) |
| `color_shift`  | `dr`, `dg`, `db` — color change per second (negative values fade a channel out)                        |
| `blink`        | `period` (s, default 1.0), `duty` (on-fraction 0–1, default 0.5), `every` (blank every n-th point while on) |

## Runtime events

While the animation runs in the background, shapes and effects can be created,
modified and destroyed from any thread:

```python
from LaserDisplay import Rotation

scheduler.run_in_background()
...
scheduler.create_circle('ping', cx, cy, r, npoints)     # immediate activation
scheduler.add_effect('ping', Rotation(speed=180))
scheduler.destroy('ping')
scheduler.schedule(5.0, some_function)                  # call at animation time 5s
...
scheduler.stop()
```

The immediate creation methods are `create_triangle`, `create_line`,
`create_circle` and `create_tetragon`; they take internal 16 bit coordinate
and color values (`0 .. 255*255`). Effects are plain objects from
`LaserDisplay.Animate` (`Rotation`, `Translation`, `Scale`, `ColorShift`,
`Blink`). Shapes that were defined in the XML (or via `define_shape()`) can be
activated later with `create(name)`.
