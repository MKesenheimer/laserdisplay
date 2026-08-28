import math
import numpy

from .Shape import Shape

DEBUG = 0

class Geometry:
    @staticmethod
    def __circle_point(x, y, r, i, npoints):
        th = 2 * math.pi / npoints * i
        xunit = int(r * math.cos(th) + x)
        yunit = int(r * math.sin(th) + y)
        return xunit, yunit

    @staticmethod
    def circle(x0, y0, r, npoints, rd, gr, bl):
        points = numpy.empty((npoints, 2), dtype='uint16')
        colors = numpy.array([[rd, gr, bl]])
        for i in range(0, npoints):
            x, y = Geometry.__circle_point(x0, y0, r, i, npoints)
            points[i, 0] = x
            points[i, 1] = y
        return Shape(points, colors)

    @staticmethod
    def ellipse(x0, y0, w, h, npoints, rd, gr, bl):
        points = numpy.empty((npoints, 2), dtype='uint16')
        colors = numpy.array([[rd, gr, bl]])
        rx = 0.5 * w
        ry = 0.5 * h
        for i in range(0, npoints):
            th = 2 * math.pi / npoints * i
            points[i, 0] = int(rx * math.cos(th) + x0)
            points[i, 1] = int(ry * math.sin(th) + y0)
        return Shape(points, colors)

    @staticmethod
    def line(x0, y0, x1, y1, npoints, rd, gr, bl):
        if npoints < 2:
            npoints = 2
        lx = numpy.linspace(x0, x1, npoints)
        ly = numpy.linspace(y0, y1, npoints)
        points = numpy.empty((npoints, 5), dtype='uint16')
        for i in range(0, npoints):
            points[i, 0] = lx[i]
            points[i, 1] = ly[i]
            points[i, 2] = rd
            points[i, 3] = gr
            points[i, 4] = bl
        return Shape(points)

    @staticmethod
    def line_points(x0, y0, npoints, spacing, rd, gr, bl):
        # a row of single dots: a blanked (color zero) point at each dot's
        # position keeps the beam off while the scanner travels from the
        # previous dot, so no line is drawn between the dots (same
        # convention as the Mirror effect)
        if npoints < 1:
            npoints = 1
        points = numpy.empty((2 * npoints - 1, 5), dtype='uint16')
        offset = (npoints - 1) / 2.0
        index = 0
        for i in range(0, npoints):
            x = int((i - offset) * spacing + x0)
            y = int(y0)
            if i > 0:
                points[index, 0] = x
                points[index, 1] = y
                points[index, 2] = 0
                points[index, 3] = 0
                points[index, 4] = 0
                index += 1
            points[index, 0] = x
            points[index, 1] = y
            points[index, 2] = rd
            points[index, 3] = gr
            points[index, 4] = bl
            index += 1
        return Shape(points)

    @staticmethod
    def triangle(x0, y0, x1, y1, x2, y2, npoints, rd, gr, bl):
        if npoints < 2:
            npoints = 2
        lx1 = numpy.linspace(x0, x1, npoints)
        ly1 = numpy.linspace(y0, y1, npoints)
        lx2 = numpy.linspace(x1, x2, npoints)
        ly2 = numpy.linspace(y1, y2, npoints)
        lx3 = numpy.linspace(x2, x0, npoints)
        ly3 = numpy.linspace(y2, y0, npoints)
        points = numpy.empty((3 * npoints - 2, 5), dtype='uint16')
        index = 0
        for i in range(0, npoints - 1):
            points[index, 0] = lx1[i]
            points[index, 1] = ly1[i]
            points[index, 2] = rd
            points[index, 3] = gr
            points[index, 4] = bl
            index += 1
        for i in range(0, npoints - 1):
            points[index, 0] = lx2[i]
            points[index, 1] = ly2[i]
            points[index, 2] = rd
            points[index, 3] = gr
            points[index, 4] = bl
            index += 1
        for i in range(0, npoints):
            points[index, 0] = lx3[i]
            points[index, 1] = ly3[i]
            points[index, 2] = rd
            points[index, 3] = gr
            points[index, 4] = bl
            index += 1
        return Shape(points)

    @staticmethod
    def tetragon(x0, y0, x1, y1, x2, y2, x3, y3, npoints, rd, gr, bl):
        if npoints < 2:
            npoints = 2
        lx1 = numpy.linspace(x0, x1, npoints)
        ly1 = numpy.linspace(y0, y1, npoints)
        lx2 = numpy.linspace(x1, x2, npoints)
        ly2 = numpy.linspace(y1, y2, npoints)
        lx3 = numpy.linspace(x2, x3, npoints)
        ly3 = numpy.linspace(y2, y3, npoints)
        lx4 = numpy.linspace(x3, x0, npoints)
        ly4 = numpy.linspace(y3, y0, npoints)
        points = numpy.empty((4 * npoints - 3, 5), dtype='uint16')
        index = 0
        for i in range(0, npoints - 1):
            points[index, 0] = lx1[i]
            points[index, 1] = ly1[i]
            points[index, 2] = rd
            points[index, 3] = gr
            points[index, 4] = bl
            index += 1
        for i in range(0, npoints - 1):
            points[index, 0] = lx2[i]
            points[index, 1] = ly2[i]
            points[index, 2] = rd
            points[index, 3] = gr
            points[index, 4] = bl
            index += 1
        for i in range(0, npoints - 1):
            points[index, 0] = lx3[i]
            points[index, 1] = ly3[i]
            points[index, 2] = rd
            points[index, 3] = gr
            points[index, 4] = bl
            index += 1
        for i in range(0, npoints):
            points[index, 0] = lx4[i]
            points[index, 1] = ly4[i]
            points[index, 2] = rd
            points[index, 3] = gr
            points[index, 4] = bl
            index += 1
        return Shape(points)