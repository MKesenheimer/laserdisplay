#!/usr/bin/env python3

import sys
import LaserDisplay
from LaserDisplay.SvgProcessor import SvgProcessor

if len(sys.argv) < 2:
    print('Usage: showsvg filename.svg')
    sys.exit(1)

LD = LaserDisplay.create()

LD.set_zoom(0.1)
LD.set_scan_rate(10000)
LD.set_blanking_delay(0)

sp = SvgProcessor(LD)

try:
    while True:
        sp.parseFile(sys.argv[1])
        LD.show_frame()
except KeyboardInterrupt:
    pass
finally:
    LD.close()
