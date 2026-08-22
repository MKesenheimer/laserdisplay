import math
import numpy

MAX = 255 * 255
SCALE = 255


class Animate:
    """
    Applies transformations in-place to shape objects, for example translation,
    rotation, color shifts, deleting or adding points or blanking every n-th
    point. Shapes use the 16 bit coordinate/color space (0 .. 255*255).
    """

    MAX = 255 * 255

    @staticmethod
    def __set_points(shape, pts):
        shape.points = numpy.clip(numpy.rint(pts), 0, Animate.MAX).astype('uint16')
        shape.npoints = len(shape.points)

    @staticmethod
    def apply_translation(shape, dx, dy):
        # moves the shape by (dx, dy)
        pts = shape.points.astype('float64')
        pts[:, 0] += dx
        pts[:, 1] += dy
        Animate.__set_points(shape, pts)

    @staticmethod
    def apply_rotation(shape, pivot_x, pivot_y, angle_deg):
        # rotates the shape around the pivot point (counter-clockwise for positive angles)
        pts = shape.points.astype('float64')
        angle = math.radians(angle_deg)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        x = pts[:, 0] - pivot_x
        y = pts[:, 1] - pivot_y
        pts[:, 0] = cos_a * x - sin_a * y + pivot_x
        pts[:, 1] = sin_a * x + cos_a * y + pivot_y
        Animate.__set_points(shape, pts)

    @staticmethod
    def apply_scale(shape, factor, center_x=128 * 255, center_y=128 * 255):
        # scales the shape about the given center point (1.0 = unchanged)
        pts = shape.points.astype('float64')
        pts[:, 0] = (pts[:, 0] - center_x) * factor + center_x
        pts[:, 1] = (pts[:, 1] - center_y) * factor + center_y
        Animate.__set_points(shape, pts)

    @staticmethod
    def apply_color_shift(shape, dr, dg, db):
        # shifts the color of all points by (dr, dg, db), values are clamped to 0..255*255
        pts = shape.points.astype('int32')
        pts[:, 2] += int(dr)
        pts[:, 3] += int(dg)
        pts[:, 4] += int(db)
        shape.points = numpy.clip(pts, 0, Animate.MAX).astype('uint16')

    @staticmethod
    def apply_blank(shape, n):
        # blanks (turns the beam off at) every n-th point
        if n < 1:
            return
        shape.points[::n, 2] = 0
        shape.points[::n, 3] = 0
        shape.points[::n, 4] = 0

    @staticmethod
    def apply_delete_points(shape, n):
        # removes every n-th point from the shape
        if n < 2:
            return
        mask = numpy.ones(len(shape.points), dtype='bool')
        mask[::n] = False
        Animate.__set_points(shape, shape.points[mask])

    @staticmethod
    def apply_add_points(shape, subdivisions=1):
        # inserts `subdivisions` interpolated points between each pair of consecutive points
        if subdivisions < 1 or shape.npoints < 2:
            return
        p = shape.points.astype('float64')
        segments = []
        for i in range(len(p) - 1):
            for k in range(0, subdivisions + 1):
                t = k / float(subdivisions + 1)
                segments.append(p[i] + (p[i + 1] - p[i]) * t)
        segments.append(p[-1])
        Animate.__set_points(shape, numpy.array(segments))


# ---------------------------------------------------------------------------
# Continuous effects. Every effect is evaluated from absolute time, so they
# are drift-free and can be combined freely: each frame the caller starts
# from a copy of the original points of the shape and pipes it through all
# attached effects.
# ---------------------------------------------------------------------------

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
    """moves the shape with constant velocity plus optional sinusoidal wobble"""

    def __init__(self, vx=0.0, vy=0.0, ax=0.0, ay=0.0, fx=0.25, fy=0.25, phase=0.0):
        self.vx = float(vx)              # units per second
        self.vy = float(vy)
        self.ax = float(ax)              # wobble amplitude / frequency (Hz)
        self.ay = float(ay)
        self.fx = float(fx)
        self.fy = float(fy)
        self.phase = float(phase)

    def transform(self, pts, dt):
        out = pts.copy()
        out[:, 0] += self.vx * dt + self.ax * math.sin(2 * math.pi * self.fx * dt + self.phase)
        out[:, 1] += self.vy * dt + self.ay * math.sin(2 * math.pi * self.fy * dt + self.phase)
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
