#!/usr/bin/env python3

# Demonstrates the shape pipeline: shapes are generated with Geometry,
# transformed with effect classes (Rotation, Translation, Scale, Blink, ...)
# and displayed as a frame via new_frame() / add_shape_to_frame() / show_frame().

import time

import LaserDisplay
from LaserDisplay import Geometry, Rotation, Translation, Scale, Blink, apply

LD = LaserDisplay.create()
LD.set_scan_rate(10000)
LD.set_zoom(0.1)

SIZE = 255 * 255      # shape coordinate/color space (16 bit)
CENTER = SIZE // 2    # center of the frame

spin = Rotation(pivot_x=CENTER, pivot_y=CENTER, speed=45.0)   # degrees per second
wobble = Translation(ay=50 * 255, fy=0.25)                    # sinusoidal vertical wobble
dash = Blink(duty=1.0, every=5)                               # beam off at every 5th point
pulse = Scale(min_factor=0.4, max_factor=1.6, frequency=0.5,
              center_x=CENTER, center_y=CENTER)               # pulsing radius

start = time.perf_counter()
try:
    while True:
        t = time.perf_counter() - start

        # triangle spinning about the center of the frame
        t1 = Geometry.triangle(CENTER - 60 * 255, CENTER - 40 * 255,
                               CENTER + 60 * 255, CENTER - 40 * 255,
                               CENTER,            CENTER + 70 * 255,
                               20, 255 * 255, 0, 0)
        apply(t1, spin, t)

        # horizontal line wobbling up and down, drawn dashed
        l1 = Geometry.line(40 * 255, CENTER, 216 * 255, CENTER,
                           30, 0, 255 * 255, 0)
        apply(l1, wobble, t)
        apply(l1, dash, t)

        # circle pulsing its radius
        c1 = Geometry.circle(CENTER, CENTER, 30 * 255, 40, 0, 0, 255 * 255)
        apply(c1, pulse, t)

        LD.new_frame()
        LD.add_shape_to_frame(t1)
        LD.add_shape_to_frame(l1)
        LD.add_shape_to_frame(c1)
        LD.show_frame()
except KeyboardInterrupt:
    pass
finally:
    LD.close()
