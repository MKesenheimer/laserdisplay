#!/usr/bin/env python3

import LaserDisplay

LD = LaserDisplay.create()

LD.set_zoom(0.1)
LD.set_scan_rate(10000)

y=0
try:
    while True:
        y += 1
        if y > 255: y = 0
        LD.draw_point(128-10, y)
        LD.draw_line(128+10, 0, 128+10, y)
        LD.show_frame()
except KeyboardInterrupt:
    pass
finally:
    LD.close()
