import numpy


class Shape:
    def __init__(self, points=None, color=None):
        """
        constructor.
        empty:            Shape()
        colored points:   Shape(points)        points: (npoints, 5) array (x, y, r, g, b)
        coords + color:   Shape(points, color) points: (npoints, 2), color: (npoints, 3) or (1, 3)
        """
        if points is None:
            self.points = numpy.empty((0, 5), dtype='uint16')
            self.npoints = 0
            return

        if color is None:
            self.points = points
            self.npoints = len(points)
            return

        """
        Alternative:
        define a shape by numpy arrays for coordinates and color.
        points: for example: numpy.array([[0, 1], [2, 3], [4, 5]])
        color: for example: numpy.array([[128, 255, 128], [255, 255, 128], [128, 255, 255]])
        note: points and color must be equal in size, or color must be of size 1 (one color for all points)
        """
        plength = len(points)
        clength = len(color)
        if plength == 0 or clength == 0:
            raise Exception("[ERROR] Arrays must not be empty.")

        if plength != clength and clength != 1:
            raise Exception("[ERROR] Points and color array must be equal in size, or color array must be of size 1.")

        self.points = numpy.empty((plength, 5), dtype='uint16')
        for i in range(0, plength):
            self.points[i, 0] = points[i, 0]
            self.points[i, 1] = points[i, 1]
            self.points[i, 2] = color[i % clength, 0]
            self.points[i, 3] = color[i % clength, 1]
            self.points[i, 4] = color[i % clength, 2]

        self.npoints = plength

    def get_points(self):
        return self.points

    def get_number_of_points(self):
        return self.npoints
