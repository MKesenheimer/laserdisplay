#!/usr/bin/env python3

# Demonstrates the shape pipeline: shapes are generated with Geometry,
# transformed with Animate and displayed as a frame via
# new_frame() / add_shape_to_frame() / show_frame().

import math

import LaserDisplay
from LaserDisplay import Geometry, Animate

LD = LaserDisplay.create()
LD.set_scan_rate(10000)
LD.set_zoom(0.1)

SIZE = 255 * 255      # shape coordinate/color space (16 bit)
CENTER = SIZE // 2    # center of the frame

angle = 0.0
try:
    while True:
        # triangle rotating about the center of the frame
        t1 = Geometry.triangle(CENTER - 60 * 255, CENTER - 40 * 255,
                               CENTER + 60 * 255, CENTER - 40 * 255,
                               CENTER,            CENTER + 70 * 255,
                               20, 255 * 255, 0, 0)
        Animate.apply_rotation(t1, CENTER, CENTER, angle)

        # line moving up and down, every 5th point is blanked (dashed line)
        offset = int(50 * 255 * math.sin(math.radians(angle)))
        l1 = Geometry.line(40 * 255, CENTER + offset,
                           216 * 255, CENTER + offset,
                           30, 0, 255 * 255, 0)
        Animate.apply_blank(l1, 5)

        # circle pulsing its radius
        radius = int((30 + 20 * math.sin(math.radians(2 * angle))) * 255)
        c1 = Geometry.circle(CENTER, CENTER, radius, 40, 0, 0, 255 * 255)

        LD.new_frame()
        LD.add_shape_to_frame(t1)
        LD.add_shape_to_frame(l1)
        LD.add_shape_to_frame(c1)
        LD.show_frame()

        angle += 0.5
except KeyboardInterrupt:
    pass
finally:
    LD.close()
