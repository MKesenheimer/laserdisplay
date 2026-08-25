# XML file format

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
        <!-- the bubble pulses and flips between both sides of the frame -->
        <create shape="bubble"/>
        <effect shape="bubble" type="scale" min="0.5" max="1.4" frequency="0.5"/>
        <effect shape="bubble" type="flip" axis="vertical" period="2"/>
    </event>

    <event at="6.0">
        <!-- the spinner slowly turns from orange to magenta -->
        <effect shape="spinner" type="color_shift" dr="-85" dg="-45" db="100"/>
        <effect shape="wobble" type="blink" period="1.2"/>
        <!-- the wobble line gains an exact mirror copy on the other side -->
        <effect shape="wobble" type="mirror" axis="horizontal"/>
    </event>

    <event at="13.0">
        <destroy shape="square"/>
    </event>
</animation>
```

## Units

All numbers in the XML use the friendly scale:

- coordinates, radii, amplitudes and colors: `0–255`
- the y axis points **up** (`y="0"` is the bottom of the frame)
- times, periods: seconds
- rotation speeds: degrees per second (positive = counter-clockwise)
- translation velocities: units per second (`0–255` scale)
- frequencies: hertz
- the values are converted to the internal 16 bit laser range automatically

## `<shape>` — a named shape definition

Defines a shape once; it becomes visible when a `<create>` event references
its name.

| Attribute               | Meaning                                              |
|-------------------------|------------------------------------------------------|
| `name`                  | unique name referenced by events                     |
| `type`                  | `line`, `triangle`, `circle`, `ellipse` or `tetragon` |
| `npoints`               | number of points interpolated along the outline      |
| `red`, `green`, `blue`  | color, each `0–255` (default `255`)                  |
| `blank`                 | optional; blank every n-th point (dashed outlines)   |

The remaining attributes are the geometry coordinates:

| Type        | Attributes                             |
|-------------|----------------------------------------|
| `line`      | `x0 y0 x1 y1`                          |
| `triangle`  | `x0 y0 x1 y1 x2 y2`                    |
| `circle`    | `cx cy r`                              |
| `ellipse`   | `cx cy w h` (center, horizontal/vertical dimension) |
| `tetragon`  | `x0 y0 x1 y1 x2 y2 x3 y3`              |

## `<event>` — actions at a timestamp

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

## `<effect>` — continuous effects

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
| `rainbow`      | `cycles` (spectra along the shape, default 1.0), `speed` (spectra/s drift, default 0.1), `phase`, `saturation`, `brightness` |
| `warp`         | travelling sine wave: `amplitude` (default 15), `wavelength` (default 100), `speed` (wavelengths/s), `phase` (radians), `horizontal` (`1`/`0`) |
| `multi_color`  | required `colors="r,g,b;r,g,b;..."` — colors consecutive parts of the shape (values `0–255`)           |
| `move_points`  | required `points` selection — `"3:7"` range, `"-10:"` last points, `"0,5,9"` indices or a single index; moved by `dx`, `dy` or towards `tx`, `ty` (both required for a target); `duration` (s) animates the move |
| `morph`        | required `target` — name of another defined shape the shape blends into; `duration` (s, default 1.0), `bounce` (`1` = oscillate), `smooth` (`1` = eased) |
| `translate_by_path` | required `path` — name of another defined shape (paths are usually defined but never created); the shape's center follows the outline of that path with `velocity` (units/s, default 50, negative = backwards); `closed` (`1` = loop around the path, default, `0` = stop at the end); `phase` (starting position as a fraction 0–1 of the path's length, default 0) |
| `flip` | flips the shape in place (including the effects attached before it) at the middle vertical (default, left/right) or horizontal (top/bottom) axis of the frame: `axis` (`vertical`/`horizontal`); `period` (s, default 0 = fixed flip, >0 = flips between mirrored and original position every `period` seconds); `phase` (s, shifts the flip cycle) |
| `mirror` | adds an exactly mirrored copy of the shape (the original is left untouched; a blanked point between both halves keeps the beam off while travelling to the copy, so no line is drawn between them): `axis` (`vertical` = left/right copy, default, `horizontal` = top/bottom copy) |