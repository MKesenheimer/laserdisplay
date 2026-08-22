"""
Minimal parser for the Graffiti Markup Language (.gml), as produced by
000000book.com and related tools. Supports files with explicit <stroke>
grouping as well as flat <pt> sequences.
"""

import xml.etree.ElementTree as ET


class Point:
    def __init__(self, x=0.0, y=0.0, z=0.0, time=0.0):
        self.x = x
        self.y = y
        self.z = z
        self.time = time

    def __repr__(self):
        return '<PyGML.Point (%s, %s) time=%s>' % (self.x, self.y, self.time)


class Stroke:
    def __init__(self, points=None):
        self.points = points if points is not None else []

    def iterPoints(self):
        return iter(self.points)


class GML:
    def __init__(self, source):
        root = ET.parse(source).getroot()
        self.strokes = []
        # newer files group points under <tag>/<drawing>, older ones under <recording>
        drawing = root.find('tag/drawing')
        if drawing is None:
            drawing = root.find('recording')
        if drawing is None:
            return
        stroke_elements = drawing.findall('stroke')
        if stroke_elements:
            for s in stroke_elements:
                self.strokes.append(Stroke([_parse_point(p) for p in s.findall('pt')]))
        else:
            # flat <pt> sequence without explicit stroke grouping
            self.strokes.append(Stroke([_parse_point(p) for p in drawing.findall('pt')]))

    def iterStrokes(self):
        return iter(self.strokes)


def _parse_point(elem):
    return Point(float(elem.findtext('x', 0)),
                 float(elem.findtext('y', 0)),
                 float(elem.findtext('z', 0)),
                 float(elem.findtext('time', 0)))
