#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import PyGML
from datetime import datetime
import LaserDisplay
import random

def readFile():
    gmlFile = open(sys.argv[1], 'r')
    gml = PyGML.GML(gmlFile)
    gmlFile.close()
    return gml

WIDTH = 256
HEIGHT = 256
if len(sys.argv) >= 3:
  TOTAL_TIME=float(sys.argv[2])
else:
  TOTAL_TIME=10

TIME_STRETCH = 1
ZOOM=1.0
DELTA = 1

DEGRADATION = 0.40
#DEGRADATION is the percentage of points that we ignore in order to render
# faster in the laser display. Unfortunately we are not able to render too
# complex content in our display without resulting in a lot of blinking.

gml = readFile()
LD = LaserDisplay.create()
LD.set_scan_rate(10000)
LD.set_zoom(0.1)
LD.set_blanking_delay(0)
LD.set_color(LD.RED)

t0=datetime.now()
num_frame=0
try:
    while True:
      delta = datetime.now() - t0
      t = delta.total_seconds()
      t = float(t)/TIME_STRETCH

      if t > TOTAL_TIME:
        t0=datetime.now()

      num_frame+=1
      print(num_frame, t)
      for stroke in gml.iterStrokes():
          p = None
          for point in stroke.iterPoints():
              if point.time <= t and t <= point.time+DELTA and random.random()<(1-DEGRADATION):
                if p is not None:
                  LD.draw_line(WIDTH/2 + ZOOM*p.x*WIDTH/2, HEIGHT/2 + ZOOM*p.y*HEIGHT/2, WIDTH/2 + ZOOM*point.x*WIDTH/2, HEIGHT/2 + ZOOM*point.y*HEIGHT/2)
                p = point
      LD.show_frame()
except KeyboardInterrupt:
    pass
finally:
    LD.close()
