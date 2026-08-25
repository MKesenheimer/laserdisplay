"""
Effects for shape animations. Every effect is evaluated from absolute time,
so they are drift-free and can be combined freely: each frame the caller
starts from a copy of the original points of the shape and pipes it through
all attached effects.

Shapes use the 16 bit coordinate/color space (0 .. 255*255). The module-level
apply() function applies an effect in-place to a shape.
"""

import math

import numpy

MAX = 255 * 255
SCALE = 255


def apply(shape, effect, dt=0.0):
    """applies an effect in-place to a shape (one-shot transformations)"""
    pts = effect.transform(shape.get_points().astype('float64'), dt)
    shape.points = numpy.clip(numpy.rint(pts), 0, MAX).astype('uint16')
    shape.npoints = len(shape.points)


class Rotation:
    """rotates the shape continuously around a pivot point"""

    def __init__(self, pivot_x=128 * SCALE, pivot_y=128 * SCALE, speed=45.0, phase=0.0):
        self.pivot_x = float(pivot_x)
        self.pivot_y = float(pivot_y)
        self.speed = float(speed)        # degrees per second
        self.phase = float(phase)

    def transform(self, pts, dt):
        angle = math.radians(self.phase + self.speed * dt)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        out = pts.copy()
        x = out[:, 0] - self.pivot_x
        y = out[:, 1] - self.pivot_y
        out[:, 0] = cos_a * x - sin_a * y + self.pivot_x
        out[:, 1] = sin_a * x + cos_a * y + self.pivot_y
        return out


class Translation:
    """moves the shape with constant velocity plus optional sinusoidal wobble.
    By default the shape wraps around the screen: when its center leaves the
    screen it re-appears at the opposite side (x = 0 maps to x = 255, and
    likewise for y). Pass wrap=False to let the shape leave the screen for
    good."""

    def __init__(self, vx=0.0, vy=0.0, ax=0.0, ay=0.0, fx=0.25, fy=0.25,
                 phase=0.0, wrap=True):
        self.vx = float(vx)              # units per second
        self.vy = float(vy)
        self.ax = float(ax)              # wobble amplitude / frequency (Hz)
        self.ay = float(ay)
        self.fx = float(fx)
        self.fy = float(fy)
        self.phase = float(phase)
        self.wrap = bool(wrap)

    def transform(self, pts, dt):
        out = pts.copy()
        out[:, 0] += self.vx * dt + self.ax * math.sin(2 * math.pi * self.fx * dt + self.phase)
        out[:, 1] += self.vy * dt + self.ay * math.sin(2 * math.pi * self.fy * dt + self.phase)
        if self.wrap and len(out) > 0:
            # shift the whole shape by a whole number of screen widths so
            # that its center lies in 0..MAX: while the center is on the
            # screen the shape stays put, once it has left it re-appears at
            # the opposite side
            cx = out[:, 0].mean()
            cy = out[:, 1].mean()
            out[:, 0] += (cx % MAX) - cx
            out[:, 1] += (cy % MAX) - cy
        return out


class Scale:
    """scales the shape about a center point; pulsing if frequency > 0"""

    def __init__(self, factor=1.0, min_factor=0.8, max_factor=1.2, frequency=0.0,
                 center_x=128 * SCALE, center_y=128 * SCALE):
        self.factor = float(factor)
        self.min_factor = float(min_factor)
        self.max_factor = float(max_factor)
        self.frequency = float(frequency)
        self.center_x = float(center_x)
        self.center_y = float(center_y)

    def transform(self, pts, dt):
        f = self.factor
        if self.frequency > 0:
            f = self.min_factor + (self.max_factor - self.min_factor) * \
                0.5 * (1.0 + math.sin(2 * math.pi * self.frequency * dt))
        out = pts.copy()
        out[:, 0] = (out[:, 0] - self.center_x) * f + self.center_x
        out[:, 1] = (out[:, 1] - self.center_y) * f + self.center_y
        return out


class ColorShift:
    """shifts the color of the shape continuously (units per second)"""

    def __init__(self, dr=0.0, dg=0.0, db=0.0):
        self.dr = float(dr)
        self.dg = float(dg)
        self.db = float(db)

    def transform(self, pts, dt):
        out = pts.copy()
        out[:, 2] += self.dr * dt
        out[:, 3] += self.dg * dt
        out[:, 4] += self.db * dt
        return out


class Blink:
    """switches the shape on/off periodically and optionally blanks every n-th point"""

    def __init__(self, period=1.0, duty=0.5, every=0):
        self.period = float(period)
        self.duty = float(duty)
        self.every = int(every)

    def transform(self, pts, dt):
        out = pts.copy()
        if (dt % self.period) >= self.period * self.duty:
            out[:, 2:5] = 0
        elif self.every > 1:
            out[::self.every, 2:5] = 0
        return out


class DeletePoints:
    """removes every n-th point from the shape"""

    def __init__(self, n):
        self.n = int(n)

    def transform(self, pts, dt):
        if self.n < 2:
            return pts
        mask = numpy.ones(len(pts), dtype='bool')
        mask[::self.n] = False
        return pts[mask]


class AddPoints:
    """inserts `subdivisions` interpolated points between each pair of
    consecutive points"""

    def __init__(self, subdivisions=1):
        self.subdivisions = int(subdivisions)

    def transform(self, pts, dt):
        if self.subdivisions < 1 or len(pts) < 2:
            return pts
        p = pts.astype('float64')
        segments = []
        for i in range(len(p) - 1):
            for k in range(0, self.subdivisions + 1):
                t = k / float(self.subdivisions + 1)
                segments.append(p[i] + (p[i + 1] - p[i]) * t)
        segments.append(p[-1])
        return numpy.array(segments)


class Morph:
    """morphs the shape into another shape; the target can be given as a Shape
    object or an (npoints, 5) point array. Both outlines are resampled to a
    common number of points and blended over `duration` seconds (colors are
    interpolated as well). With bounce=True the morph reverses after reaching
    the target and keeps oscillating."""

    def __init__(self, target, duration=1.0, bounce=False, closed=True, smooth=True):
        if hasattr(target, 'get_points'):
            target = target.get_points()
        self.target = numpy.asarray(target, dtype='float64')
        self.duration = float(duration)
        self.bounce = bool(bounce)
        self.closed = bool(closed)
        self.smooth = bool(smooth)
        self._aligned = None             # resampled+aligned target for a given npoints

    def transform(self, pts, dt):
        n = len(pts)
        if n == 0 or len(self.target) == 0:
            return pts
        # prepare the target once per point count: resampled to n points and
        # rotated/reversed so corresponding points are close together
        if self._aligned is None or len(self._aligned) != n:
            aligned = _resample(self.target, n, self.closed)
            if self.closed and n > 2:
                aligned = _align(xy(pts), aligned)
            self._aligned = aligned
        if self.duration <= 0:
            p = 1.0
        elif self.bounce:
            p = 1.0 - abs((dt / self.duration) % 2.0 - 1.0)
        else:
            p = min(dt / self.duration, 1.0)
        if self.smooth:
            p = _ease(p)
        src = pts.astype('float64')
        return src * (1.0 - p) + self._aligned * p


class MultiColor:
    """colors consecutive parts of the shape in different colors; the colors
    are given in internal units (0 .. 255*255), either as separate arguments
    or as a single list"""

    def __init__(self, *colors):
        if len(colors) == 1 and isinstance(colors[0], (list, tuple)):
            colors = tuple(colors[0])
        self.colors = numpy.asarray(colors, dtype='float64').reshape(-1, 3)

    def transform(self, pts, dt):
        out = pts.copy()
        n = len(out)
        if n == 0:
            return out
        cols = numpy.asarray(self.colors, dtype='float64').reshape(-1, 3)
        part = numpy.arange(n) * len(cols) // n      # part index of each point
        out[:, 2:5] = cols[part]
        return out


class Rainbow:
    """colors the shape with a rainbow gradient along its outline; `cycles`
    is the number of full color spectra along the shape, `speed` drifts the
    gradient (spectra per second)"""

    def __init__(self, cycles=1.0, speed=0.1, phase=0.0, saturation=1.0, brightness=1.0):
        self.cycles = float(cycles)
        self.speed = float(speed)
        self.phase = float(phase)
        self.saturation = float(saturation)
        self.brightness = float(brightness)

    def transform(self, pts, dt):
        out = pts.copy()
        n = len(out)
        if n == 0:
            return out
        frac = _arclength_fraction(out[:, :2])
        hue = frac * self.cycles + self.speed * dt + self.phase
        r, g, b = _hsv_to_rgb(hue % 1.0, self.saturation, self.brightness)
        out[:, 2] = r * MAX
        out[:, 3] = g * MAX
        out[:, 4] = b * MAX
        return out


class Warp:
    """warps the shape with a travelling sine wave; with horizontal=True the
    wave travels along the x axis and displaces the points vertically"""

    def __init__(self, amplitude=15 * SCALE, wavelength=100 * SCALE,
                 speed=1.0, phase=0.0, horizontal=True):
        self.amplitude = float(amplitude)
        self.wavelength = float(wavelength)
        self.speed = float(speed)        # wavelengths per second
        self.phase = float(phase)
        self.horizontal = bool(horizontal)

    def transform(self, pts, dt):
        out = pts.copy()
        drive = out[:, 0] if self.horizontal else out[:, 1]
        disp = self.amplitude * numpy.sin(
            2 * math.pi * drive / self.wavelength - 2 * math.pi * self.speed * dt + self.phase)
        if self.horizontal:
            out[:, 1] += disp
        else:
            out[:, 0] += disp
        return out


class MovePoints:
    """moves part of a shape to another position; the part is selected by a
    slice ('last 3 points': slice(-3, None)), a (start, end) range or a list
    of point indices (a single int selects one point). The part is moved by
    the offset (dx, dy), or towards the absolute position target=(x, y)
    keeping its inner arrangement. With duration > 0 the movement is animated
    over that many seconds."""

    def __init__(self, selection, dx=0.0, dy=0.0, target=None, duration=0.0):
        self.selection = selection
        self.offset = numpy.array([float(dx), float(dy)])
        self.target = None if target is None else numpy.array([float(target[0]), float(target[1])])
        self.duration = float(duration)

    def _mask(self, n):
        mask = numpy.zeros(n, dtype='bool')
        sel = self.selection
        if isinstance(sel, slice):
            mask[sel] = True
        elif isinstance(sel, tuple) and len(sel) == 2:
            mask[slice(int(sel[0]), int(sel[1]))] = True
        elif isinstance(sel, (int, numpy.integer)):
            mask[int(sel)] = True
        else:
            indices = numpy.asarray(list(sel), dtype='int64')   # e.g. [0, 5, 9]
            mask[indices] = True
        return mask

    def transform(self, pts, dt):
        out = pts.copy()
        mask = self._mask(len(out))
        if not mask.any():
            return out
        offset = self.offset
        if self.target is not None:
            offset = self.target - out[mask, :2].mean(axis=0)
        if self.duration > 0:
            offset = offset * _ease(min(dt / self.duration, 1.0))
        out[mask, :2] += offset
        return out


class TranslateByPath:
    """moves the shape along a path: the shape's center follows the outline
    of the path with a constant velocity (path units per second). The path is
    given as a Shape object (or an (n, 5) point array) and is traversed in
    the order of its points. With closed=True (default) the path is treated
    as a closed loop and the shape keeps moving on it (a negative velocity
    runs backwards); with closed=False the shape stops at the end of the
    path. With phase the starting position can be shifted by that fraction
    (0..1) of the path's total length."""

    def __init__(self, path, velocity=50.0 * SCALE, closed=True, phase=0.0):
        if hasattr(path, 'get_points'):
            path = path.get_points()
        path = numpy.asarray(path, dtype='float64')
        self.velocity = float(velocity)
        self.closed = bool(closed)
        self.phase = float(phase)
        verts = path[:, :2]
        if self.closed and len(verts) > 1:
            verts = numpy.vstack([verts, verts[:1]])   # close the loop
        self._verts = verts
        seg = numpy.sqrt(((verts[1:] - verts[:-1]) ** 2).sum(axis=1))
        self._s = numpy.concatenate([[0.0], numpy.cumsum(seg)])
        self._total = self._s[-1]

    def transform(self, pts, dt):
        out = pts.copy()
        if len(out) == 0 or self._total <= 0:
            return out
        s = self.velocity * dt + self.phase * self._total
        if self.closed:
            s = s % self._total
        else:
            s = min(max(s, 0.0), self._total)
        x = numpy.interp(s, self._s, self._verts[:, 0])
        y = numpy.interp(s, self._s, self._verts[:, 1])
        center = out[:, :2].mean(axis=0)
        out[:, 0] += x - center[0]
        out[:, 1] += y - center[1]
        return out


class Flip:
    """flips the shape at the middle vertical axis (left/right, the default)
    or the middle horizontal axis (top/bottom) of the frame. With period > 0
    the shape flips back and forth between the mirrored and the original
    position, smoothly easing through the axis, every period seconds
    (period 0 = fixed flip); phase shifts the flip cycle in seconds.
    Effects are applied in the order they are attached, so a flip attached
    after other effects flips their combined result."""

    def __init__(self, axis='vertical', period=0.0, phase=0.0):
        if axis not in ('vertical', 'horizontal'):
            raise ValueError("axis must be 'vertical' or 'horizontal'")
        self.axis = axis
        self.period = float(period)
        self.phase = float(phase)

    def transform(self, pts, dt):
        out = pts.copy()
        m = 1.0                            # +1 flipped, -1 unflipped
        if self.period > 0:
            tri = 1.0 - abs(((dt + self.phase) / (self.period / 2.0)) % 2.0 - 1.0)
            m = 1.0 - 2.0 * _ease(tri)
        c = 128 * SCALE                    # middle of the frame
        if self.axis == 'vertical':
            out[:, 0] = c - m * (out[:, 0] - c)
        else:
            out[:, 1] = c - m * (out[:, 1] - c)
        return out


class Mirror:
    """adds an exactly mirrored copy of the shape, leaving the original
    untouched: with axis='vertical' (the default) the copy is mirrored
    left/right at the middle vertical axis of the frame, with
    axis='horizontal' top/bottom at the middle horizontal axis. A blanked
    (color zero) point between the two halves keeps the beam off while the
    scanner travels from the original to the copy, so no line is drawn
    between them. Effects attached after the mirror act on both the original
    and the copy."""

    def __init__(self, axis='vertical'):
        if axis not in ('vertical', 'horizontal'):
            raise ValueError("axis must be 'vertical' or 'horizontal'")
        self.axis = axis

    def transform(self, pts, dt):
        out = pts.copy()
        if len(out) == 0:
            return out
        m = out.copy()
        c = 2 * 128 * SCALE                # 2 * middle of the frame
        if self.axis == 'vertical':
            m[:, 0] = c - m[:, 0]
        else:
            m[:, 1] = c - m[:, 1]
        blank = m[:1].copy()               # beam off at the seam
        blank[:, 2:5] = 0
        return numpy.vstack([out, blank, m])


class SpeedUp:
    """changes the speed at which the animations of the shape run: with
    factor=2.0 the effects on the shape run twice as fast, with factor=0.5
    half as fast, and with a negative factor they run in reverse (the
    animation plays back towards where it was when the speedup was
    attached). It is not a point transformation itself — transform() is
    the identity — but a marker effect: the scheduler applies it by
    re-scaling the time the shape's effects are evaluated with, so it
    affects every effect on the shape (or on all shapes of a sequence),
    both the ones attached before and the ones attached after it."""

    def __init__(self, factor=1.0):
        self.factor = float(factor)

    def transform(self, pts, dt):
        return pts


# ---------------------------------------------------------------------------
# helper functions
# ---------------------------------------------------------------------------

def xy(pts):
    """returns the coordinate columns (x, y) of a point array"""
    return pts[:, :2].astype('float64')


def _ease(p):
    # smoothstep easing for animated progress values in 0..1
    return p * p * (3.0 - 2.0 * p)


def _resample(pts, n, closed):
    # resamples a polyline (closed loops are closed by wrapping back to the
    # start point) to n points equally spaced along its arclength; colors are
    # interpolated linearly
    pts = numpy.asarray(pts, dtype='float64')
    path = pts[:, :2]
    loop = closed and len(path) > 1
    if loop:
        path = numpy.vstack([path, path[:1]])     # close the loop
    dist = numpy.sqrt(((path[1:] - path[:-1]) ** 2).sum(axis=1))
    s = numpy.concatenate([[0.0], numpy.cumsum(dist)])
    total = s[-1]
    if total <= 0:
        return numpy.repeat(pts[:1], n, axis=0)
    samples = numpy.linspace(0.0, total, n, endpoint=not closed)
    out = numpy.empty((n, 5))
    for c in range(5):
        column = pts[:, c]
        vertices = numpy.concatenate([column, column[:1]]) if loop else column
        out[:, c] = numpy.interp(samples, s, vertices)
    return out


def _align(src_xy, tgt):
    # permutes the points of the resampled target so that they best match the
    # source points: searches all cyclic shifts of the target outline, forward
    # and reversed, and takes the shift with the smallest total squared distance
    n = len(tgt)
    d2 = ((src_xy[:, None, :] - tgt[None, :, :2]) ** 2).sum(axis=2)
    idx = numpy.arange(n)
    best_cost, best_map = None, None
    for reverse in (False, True):
        for k in range(n):
            j = ((idx - k) % n) if reverse else ((idx + k) % n)
            cost = d2[idx, j].sum()
            if best_cost is None or cost < best_cost:
                best_cost, best_map = cost, j
    return tgt[best_map]


def _arclength_fraction(path):
    # position of each vertex along the polyline, normalized to 0..1
    seg = numpy.sqrt(((path[1:] - path[:-1]) ** 2).sum(axis=1))
    s = numpy.concatenate([[0.0], numpy.cumsum(seg)])
    if s[-1] <= 0:
        return numpy.arange(len(path)) / max(len(path) - 1, 1)
    return s / s[-1]


def _hsv_to_rgb(h, s, v):
    # vectorized HSV -> RGB conversion; h, s, v are arrays/scalars in 0..1
    h = numpy.asarray(h, dtype='float64')
    i = numpy.floor(h * 6.0).astype('int64') % 6
    f = h * 6.0 - numpy.floor(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    r = numpy.choose(i, [v, q, p, p, t, v])
    g = numpy.choose(i, [t, v, v, q, p, p])
    b = numpy.choose(i, [p, p, t, v, v, q])
    return r, g, b
