#!/usr/bin/env python3
# display ILDA animations from a given file

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import LaserDisplay
import ILDA
import random

LD = LaserDisplay.create()
LD.set_zoom(0.1)
LD.set_scan_rate(10000)
LD.set_blanking_delay(0)

WIDTH = 200
HEIGHT = 200

ilda_file = open(sys.argv[1], 'rb')
ilda_frames = ILDA.readFrames(ilda_file)

frames = []
for f in ilda_frames:
  frame = []
  for p in f.iterPoints():
    frame.append([WIDTH/2 + (WIDTH/2)*p.x, HEIGHT/2 + (HEIGHT/2)*p.y])
  frames.append(frame)
ilda_file.close()

try:
  while True:
    for frame in frames:
      LD.set_color(LD.YELLOW)
      for _ in range(2):
        for point in frame:
          #LD.set_color(p.color)
          if random.random()<=0.5:
            LD.draw_point(point[0], point[1])
      LD.show_frame()
except KeyboardInterrupt:
  pass
finally:
  LD.close()
