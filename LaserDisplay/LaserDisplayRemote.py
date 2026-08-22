import socket
from .LaserDisplay import LaserDisplay

class LaserDisplayRemote(LaserDisplay):

    def __init__(self, server, port = 31337):
        try:
            self.remote = socket.create_connection((server, int(port)))
        except OSError:
            raise IOError('Cannot reach %s:%s ...' % (server, port))
        LaserDisplay.__init__(self)

    def __write(self, msg):
        self.remote.sendall(msg.encode('ascii'))

    def set_laser_configuration(self):
        self.__write('config %d %d\r\n' % (self.blanking_delay, self.scan_rate))

    def set_color(self, color):
        LaserDisplay.set_color(self, color)
        self.__write('color %d %d %d\r\n' % (self.color['R'],self.color['G'],self.color['B']))

    def show_frame(self):
        self.__write('show\r\n')

    def draw_point(self, x, y, flags = 0x01):
        x, y = self._output_transform(x, y)
        self.__write('point %f %f %d\r\n' % (x, y, flags))

    def draw_line(self, x1, y1, x2, y2):
        x1, y1 = self._output_transform(x1, y1)
        x2, y2 = self._output_transform(x2, y2)
        self.__write('line %f %f %f %f\r\n' % (x1, y1, x2, y2))

    def draw_rect(self, x, y, w, h):
        x1, y1 = self._output_transform(x, y)
        x2, y2 = self._output_transform(x + w, y + h)
        self.__write('rect %f %f %f %f\r\n' % (x1, y1, x2 - x1, y2 - y1))

    def draw_ellipse(self, cx, cy, rx, ry):
        cx, cy = self._output_transform(cx, cy)
        self.__write('ellipse %f %f %f %f\r\n' % (cx, cy, rx * self.zoom, ry * self.zoom))

    def draw_polyline(self, points):
        msg = 'polyline'
        for p in points:
            px, py = self._output_transform(p[0], p[1])
            msg += ' %f %f' % (px, py)
        self.__write(msg + '\r\n')

    def draw_quadratic_bezier(self, points, steps):
        msg = 'quadratic'
        for p in points:
            px, py = self._output_transform(p[0], p[1])
            msg += ' %f %f' % (px, py)
        self.__write(msg + '\r\n')

    def draw_cubic_bezier(self, points, steps):
        msg = 'cubic'
        for p in points:
            px, py = self._output_transform(p[0], p[1])
            msg += ' %f %f' % (px, py)
        self.__write(msg + '\r\n')
