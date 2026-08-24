import os
import math
from random import random
import numpy
from .LaserDisplay import LaserDisplay
from .lumax import lumax_renderer

class LaserDisplayLumax(LaserDisplay):
    # lumaxlib uses a 0..255 coordinate/color space scaled by 255 (16 bit)
    SCALE = 255

    # distance (in display units) between interpolated points of a segment
    INTERP_STEP = 1

    # maximum number of interpolated points per segment
    MAX_INTERP = 128

    # Mirror output
    MIRROR_X = 1
    MIRROR_Y = 1

    def __init__(self):
        LaserDisplay.__init__(self)
        self.__buffer = []

        cwd = os.getcwd()
        # lumaxlib resolves its native library relative to the current working
        # directory ('./libs/liblumax_<platform>.so'); chdir to the driver
        # directory while constructing the renderer so the library is found
        # regardless of where the script was started.
        os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lumax'))
        try:
            self.renderer = lumax_renderer(mirrorx=self.MIRROR_X, mirrory=self.MIRROR_Y)
        finally:
            os.chdir(cwd)

        if not self.renderer.lhandle:
            raise IOError('Could not find lumax device ...')

# private functions
    def __clamp(self, value):
        if self.noise > 0:
            value += random() * self.noise - self.noise / 2
        if value < 0: return 0
        if value > self.SIZE - 1: return self.SIZE - 1
        return int(value)

    def __generate_buffer(self):
        # translate the buffered points (flags protocol of the local backend)
        # into lumax points: the device renders discrete points only, so
        # segments are interpolated and blanked points are inserted for the
        # beam travel between shapes
        points = []
        prev = None
        center = self.SIZE / 2.0
        for (x, y, flags, r, g, b) in self.__buffer:
            zx = min(max(center + (x - center) * self.zoom, 0), self.SIZE - 1)
            zy = min(max(center + (y - center) * self.zoom, 0), self.SIZE - 1)
            lx = int(zx * self.SCALE)
            ly = int((self.SIZE - 1 - zy) * self.SCALE)
            color = (r * self.SCALE, g * self.SCALE, b * self.SCALE)

            if flags == 0x01:        # isolated point
                points.append((lx, ly, 0, 0, 0))
                points.append((lx, ly, color[0], color[1], color[2]))
                prev = None
            elif flags == 0x03:      # start of a polyline
                points.append((lx, ly, 0, 0, 0))
                prev = (lx, ly)
            else:                    # 0x00 continue, 0x02 end
                if prev is None:
                    points.append((lx, ly, 0, 0, 0))
                else:
                    dist = math.hypot(lx - prev[0], ly - prev[1]) / self.SCALE
                    n = max(2, min(int(dist / self.INTERP_STEP), self.MAX_INTERP))
                    for i in range(1, n + 1):
                        t = float(i) / n
                        points.append((prev[0] + (lx - prev[0]) * t,
                                       prev[1] + (ly - prev[1]) * t,
                                       color[0], color[1], color[2]))
                if flags == 0x02:
                    prev = None
                else:
                    prev = (lx, ly)

        return numpy.array(points, dtype='uint16')

    def __generate_shape_points(self, shape):
        # translates the points of a shape into lumax points, applying the
        # global zoom (about the center of the frame) and flipping the y axis;
        # mirroring is done on the device side by the renderer
        pts = shape.get_points()
        x = pts[:, 0].astype('float64') / self.SCALE
        y = pts[:, 1].astype('float64') / self.SCALE
        center = self.SIZE / 2.0
        x = numpy.clip(center + (x - center) * self.zoom, 0, self.SIZE - 1)
        y = numpy.clip(center + (y - center) * self.zoom, 0, self.SIZE - 1)
        points = numpy.empty((len(pts), 5), dtype='uint16')
        points[:, 0] = numpy.rint(x * self.SCALE)
        points[:, 1] = numpy.rint((self.SIZE - 1 - y) * self.SCALE)
        points[:, 2:5] = pts[:, 2:5]
        return points

# public functions

    def set_mirror(self, mirror_x, mirror_y):
        LaserDisplay.set_mirror(self, mirror_x, mirror_y)
        # the lumax renderer mirrors on the device side (1 = flipped axis)
        self.renderer.mirrorx = self.mirror_x
        self.renderer.mirrory = self.mirror_y

    def set_blanking_delay(self, value):
        LaserDisplay.set_blanking_delay(self, value)
        # forward the delay to the lumax driver (lumaxlib.set_blanking_delay):
        # the diode cannot react instantly, so the driver shifts the light
        # channels (colors + TTL) forward by value * scan rate / 1000 points
        # to keep the beam from trailing the galvo position
        self.renderer.lmx.set_blanking_delay(value)

    def set_laser_configuration(self):
        # scan rate is passed to the device with every frame
        pass

    def close(self):
        # stops the laser output and releases the device
        self.renderer.close_device()

    def show_frame(self):
        # frames built from shapes are passed to the lumax renderer directly
        if self.frame_shapes:
            for s in self.frame_shapes:
                if s.get_number_of_points() > 0:
                    self.renderer.add_points_to_frame(self.__generate_shape_points(s))
            self.frame_shapes = []
            if self.renderer.totnpoints > 0:
                # lumax accepts 250..70000 pps
                speed = max(250, min(int(self.scan_rate), 70000))
                self.renderer.send_frame(speed)
                self.renderer.new_frame()
        else:
            self.flush_frame()

    def flush_frame(self):
        if len(self.__buffer):
            self.renderer.add_points_to_frame(self.__generate_buffer())
            # lumax accepts 250..70000 pps
            speed = max(250, min(int(self.scan_rate), 70000))
            self.renderer.send_frame(speed)
            self.renderer.new_frame()
        self.__buffer = []

    def draw_point(self, x, y, flags = 0x01):
        x,y = self.apply_context_transforms(x,y)
        x = self.__clamp(x)
        y = self.__clamp(y)
        self.__buffer += [(x, y, flags, self.color['R'], self.color['G'], self.color['B'])]

    def draw_line(self, x1, y1, x2, y2):
        self.draw_point(x1, y1, 0x03)
        self.draw_point(x2, y2, 0x02)

    def draw_rect(self, x, y, w, h):
        self.draw_point(x  , y  , 0x03)
        self.draw_point(x+w, y  , 0x00)
        self.draw_point(x+w, y+h, 0x00)
        self.draw_point(x  , y+h, 0x00)
        self.draw_point(x  ,   y, 0x02)

    def draw_ellipse(self, cx, cy, rx, ry):
        if rx < 1 or ry < 1:
            return
        steps = int(math.sqrt(rx>ry and rx or ry)*2)
        i = 0
        self.draw_point(cx+rx*math.cos(2*math.pi/steps*i),cy+ry*math.sin(2*math.pi/steps*i),0x03)
        for i in range(1,steps):
            self.draw_point(cx+rx*math.cos(2*math.pi/steps*i),cy+ry*math.sin(2*math.pi/steps*i),0x00)
        i = 0
        self.draw_point(cx+rx*math.cos(2*math.pi/steps*i),cy+ry*math.sin(2*math.pi/steps*i),0x02)

    def draw_polyline(self, points):
        self.draw_point( points[0][0], points[0][1], 0x03)
        for i in range(len(points)-2):
            self.draw_point( points[i][0], points[i][1], 0x00)
        i = len(points)-1
        self.draw_point( points[i][0], points[i][1], 0x02)

    def draw_quadratic_bezier(self, points, steps):
        if len(points) < 3:
            print('Quadratic Bezier curves have to have at least three points')
            return

        step_inc = 1.0/(steps)

        self.draw_point(points[0][0], points[0][1], 0x03)

        flags = 0x00
        for i in range(0, len(points) - 2, 2):
            t = 0.0
            t_1 = 1.0
            for s in range(steps):
                t += step_inc
                t_1 = 1.0 - t
                if s == steps - 1 and i >= len(points) - 3:
                    flags = 0x02
                self.draw_point(t_1 * (t_1 * points[i]  [0] + t * points[i+1][0]) + \
                                t   * (t_1 * points[i+1][0] + t * points[i+2][0]),  \
                                t_1 * (t_1 * points[i]  [1] + t * points[i+1][1]) + \
                                t   * (t_1 * points[i+1][1] + t * points[i+2][1]), flags)

    def draw_cubic_bezier(self, points, steps):
        if len(points) < 4:
            print('Cubic Bezier curves have to have at least four points')
            return

        step_inc = 1.0/(steps)

        self.draw_point(points[0][0], points[0][1], 0x03)

        flags = 0x00
        for i in range(0, len(points) - 3, 2):
            t = 0.0
            t_1 = 1.0
            for s in range(steps):
                t += step_inc
                t_1 = 1.0 - t
                if s == steps - 1 and i >= len(points) - 4:
                    flags = 0x02
                self.draw_point(t_1 * (t_1 * (t_1 * points[i][0] + t * points[i+1][0]) + \
                                t   * (t_1 * points[i+1][0] + t * points[i+2][0])) +
                                t   * (t_1 * (t_1 * points[i+1][0] + t * points[i+2][0]) + \
                                t   * (t_1 * points[i+2][0] + t * points[i+3][0])),  \
                                t_1 * (t_1 * (t_1 * points[i][1] + t * points[i+1][1]) + \
                                t   * (t_1 * points[i+1][1] + t * points[i+2][1])) +
                                t   * (t_1 * (t_1 * points[i+1][1] + t * points[i+2][1]) + \
                                t   * (t_1 * points[i+2][1] + t * points[i+3][1])), flags)
