import math
from random import random
from numpy import matrix

class LaserDisplay():

# constants

    RED = (255,0,0)
    GREEN = (0,255,0)
    BLUE = (0,0,255)
    CYAN = (0,255,255)
    MAGENTA = (255,0,255)
    YELLOW = (255,255,0)
    WHITE = (255,255,255)

    SIZE = 256

    GLYPHS = {
        '0': [(0.25, 0.49), (0.24, 0.24), (0.50, 0.25), (0.75, 0.25), (0.76, 0.49), (0.75, 0.76), (0.51, 0.76), (0.24, 0.75), (0.25, 0.49)],
        '1': [(0.30, 0.48), (0.49, 0.42), (0.53, 0.25), (0.54, 0.55), (0.53, 0.76)],
        '2': [(0.27, 0.49), (0.25, 0.26), (0.51, 0.25), (0.74, 0.25), (0.75, 0.42), (0.63, 0.62), (0.25, 0.74), (0.52, 0.75), (0.76, 0.75)],
        '3': [(0.26, 0.37), (0.25, 0.23), (0.53, 0.24), (0.95, 0.26), (0.56, 0.51), (0.92, 0.75), (0.53, 0.76), (0.26, 0.75), (0.26, 0.62)],
        '4': [(0.74, 0.50), (0.53, 0.50), (0.24, 0.51), (0.47, 0.39), (0.51, 0.24), (0.52, 0.50), (0.52, 0.75)],
        '5': [(0.75, 0.25), (0.52, 0.25), (0.25, 0.25), (0.25, 0.37), (0.25, 0.48), (0.75, 0.46), (0.75, 0.61), (0.75, 0.75), (0.25, 0.75)],
        '6': [(0.76, 0.37), (0.76, 0.24), (0.53, 0.24), (0.25, 0.24), (0.24, 0.48), (0.24, 0.75), (0.50, 0.76), (0.75, 0.75), (0.76, 0.61), (0.75, 0.49), (0.53, 0.49), (0.27, 0.51), (0.28, 0.64)],
        '7': [(0.24, 0.25), (0.51, 0.25), (0.75, 0.25), (0.43, 0.44), (0.26, 0.75)],
        '8': [(0.25, 0.36), (0.25, 0.24), (0.51, 0.24), (0.74, 0.25), (0.75, 0.35), (0.75, 0.46), (0.53, 0.48), (0.25, 0.47), (0.24, 0.60), (0.24, 0.75), (0.52, 0.76), (0.76, 0.75), (0.76, 0.65), (0.77, 0.53), (0.53, 0.48), (0.26, 0.47), (0.25, 0.35)],
        '9': [(0.75, 0.25), (0.25, 0.24), (0.24, 0.38), (0.25, 0.55), (0.49, 0.53), (0.71, 0.44), (0.76, 0.25), (0.75, 0.52), (0.74, 0.75)],
        ':': [(0.50, 0.40), (0.30, 0.50), (0.50, 0.60), (0.70, 0.50), (0.50, 0.40)]
    }

    def __init__(self):
        # set variables and the initial state
        self.blanking_delay = 0
        self.scan_rate = 10000
        self.noise = 0
        self.zoom = 1.0
        self.mirror_x = 0
        self.mirror_y = 0
        self.set_color(self.WHITE)
        self.ctm = None
        self.frame_shapes = []

# private functions

    def __gen_glyph_data(self, char, x, y, rx, ry):
        glyph_data = []
        for i in range(len(self.GLYPHS[char])):
            glyph_data.append([(int)(x+(self.GLYPHS[char][i][0])*rx),(int)(y+(self.GLYPHS[char][i][1])*ry)]);
        return glyph_data

# public functions

    def noise_clamp(self, value):
        min = 0
        max = self.SIZE - 1
        if self.noise > 0:
            value += random()*self.noise - self.noise/2
        if value > max: return max
        if value < min: return min
        return max - int(value)

    def set_noise(self, noise):
        self.noise = noise

    def set_zoom(self, zoom):
        # scales the output about the center of the frame (1.0 = full size)
        self.zoom = zoom

    def set_mirror(self, mirror_x, mirror_y):
        # mirrors the output horizontally/vertically (1 = mirrored, 0 = normal)
        self.mirror_x = 1 if mirror_x else 0
        self.mirror_y = 1 if mirror_y else 0

    def close(self):
        # stops the output and releases the device, if applicable
        pass

    def _output_transform(self, x, y):
        # applies zoom (about the center) and mirroring to a coordinate pair;
        # used by the backends that transform coordinates on the client side
        center = self.SIZE / 2.0
        x = center + (x - center) * self.zoom
        y = center + (y - center) * self.zoom
        if self.mirror_x:
            x = (self.SIZE - 1) - x
        if self.mirror_y:
            y = (self.SIZE - 1) - y
        return x, y

    def set_color(self, c):
        if len(c) == 3:
            self.color = {'R': int(c[0]), 'G': int(c[1]), 'B': int(c[2])}
        elif len(c) == 7:
            self.color = {'R': int(c[1:3],16), 'G': int(c[3:5],16), 'B': int(c[5:7],16)}
        if self.color['R'] < 0: self.color['R'] = 0
        if self.color['G'] < 0: self.color['G'] = 0
        if self.color['B'] < 0: self.color['B'] = 0
        if self.color['R'] > 255: self.color['R'] = 255
        if self.color['G'] > 255: self.color['G'] = 255
        if self.color['B'] > 255: self.color['B'] = 255

    def set_scan_rate(self, value):
        self.scan_rate = value
        self.set_laser_configuration()

    def set_blanking_delay(self, value):
        self.blanking_delay = value
        self.set_laser_configuration()

    def set_laser_configuration(self):
        raise NotImplementedError

    def set_time_offset(self, offset):
        # shifts the reference point of the display's time: the simulator's
        # on-screen counter starts at `offset` instead of at zero (used
        # together with --start-at when seeking into a show)
        pass

# routines that deal with frames consisting of shapes:
#
#   t1 = geometry.triangle(x0, y0, x1, y1, x2, y2, npoints, rd, gr, bl)
#   l1 = geometry.line(x0, y0, x1, y1, npoints, rd, gr, bl)
#
#   apply(t1, Translation(vx=dx_per_second), t)
#   apply(l1, Rotation(pivot_x=pivot_x, pivot_y=pivot_y), t)
#
#   LD.new_frame()
#   LD.add_shape_to_frame(t1)
#   LD.add_shape_to_frame(l1)
#   LD.show_frame()

    def new_frame(self):
        # starts a new frame consisting of shapes
        self.frame_shapes = []

    def add_shape_to_frame(self, shape):
        # adds a finalized shape to the current frame
        self.frame_shapes.append(shape)

    def show_frame(self):
        # displays the current frame; by default the shapes are replayed
        # through the classic drawing primitives, backends may override
        # this with a more efficient direct path
        for s in self.frame_shapes:
            self._draw_shape(s)
        self.frame_shapes = []
        self.flush_frame()

    def flush_frame(self):
        # sends the buffered drawing primitives of this frame to the device
        raise NotImplementedError

    def _draw_shape(self, shape):
        # renders a shape using the classic drawing primitives; shapes use
        # the 16 bit coordinate/color space (0 .. 255*255) with y pointing up,
        # the display uses 0 .. SIZE-1 with y pointing down
        pts = shape.get_points()
        n = len(pts)
        i = 0
        while i < n:
            r = int(pts[i, 2])
            g = int(pts[i, 3])
            b = int(pts[i, 4])
            if r == 0 and g == 0 and b == 0:
                # blanked point: splits the polyline (beam is moved off)
                i += 1
                continue
            # collect the run of consecutive points with identical color
            j = i + 1
            while j < n and int(pts[j, 2]) == r and int(pts[j, 3]) == g and int(pts[j, 4]) == b:
                j += 1
            self.set_color((min(r >> 8, 255), min(g >> 8, 255), min(b >> 8, 255)))
            run = [(float(p[0]) / 255.0, (self.SIZE - 1) - float(p[1]) / 255.0) for p in pts[i:j]]
            if len(run) == 1:
                self.draw_point(run[0][0], run[0][1])
            else:
                self.draw_polyline(run)
            i = j

    def draw_point(self, x, y, flags = 0):
        raise NotImplementedError

    def draw_line(self, x1, y1, x2, y2):
        raise NotImplementedError

    def draw_quadratic_bezier(self, points, steps):
        raise NotImplementedError

    def draw_cubic_bezier(self, points, steps):
        raise NotImplementedError

    def draw_rect(self, x, y, w, h):
        raise NotImplementedError

    def draw_ellipse(self, cx, cy, rx, ry):
        raise NotImplementedError

    def draw_polyline(self, points):
        raise NotImplementedError

    def draw_text(self, string, x, y, size, kerning_percentage = -0.3):
        for char in string:
            glyph_curve = self.__gen_glyph_data(char, x, y, size, size*2)
            self.draw_quadratic_bezier(glyph_curve, 5)
            x += int(size + size * kerning_percentage)

# routines that deal with coordinate system transforms:

    def init_transform(self):
        self.ctm = matrix([[1.0,0.0,0.0],[0.0,1.0,0.0],[0.0,0.0,1.0]])
        self.saved_matrix = self.ctm

    def apply_context_transforms(self, x,y):
        if self.ctm is None:
            return (x,y)
        else:
            vector = self.ctm*matrix([x,y,1]).transpose()
            return vector.item(0), vector.item(1)

    def save(self):
        self.saved_matrix = self.ctm

    def restore(self):
        self.ctm = self.saved_matrix

    def rotate(self, angle):
        self.ctm = matrix([[math.cos(angle), -math.sin(angle), 0.0], [math.sin(angle), math.cos(angle), 0.0], [0.0, 0.0, 1.0]])*self.ctm

    def translate(self, x, y):
        self.ctm = matrix([[1.0, 0.0, float(x)], [0.0, 1.0, float(y)], [0.0, 0.0, 1.0]])*self.ctm

    def scale(self, s):
        self.ctm = matrix([[float(s), 0.0, 0.0], [0.0, float(s), 0.0], [0.0, 0.0, 1.0]])*self.ctm

    def rotate_at(self,cx,cy,angle):
        self.translate(-cx,-cy)
        self.rotate(angle)
        self.translate(cx,cy)
