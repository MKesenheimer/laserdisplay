#!/usr/bin/env python3

# Plays the animation timeline from shapes.xml with the Scheduler class.
#
# While it is running, events can be injected from other threads, for example:
#
#   scheduler.create_circle('ping', 128*255, 128*255, 30*255, 32)
#   scheduler.add_effect('ping', Rotation(speed=180))
#   scheduler.destroy('ping')

import os

import LaserDisplay
from LaserDisplay import Scheduler

LD = LaserDisplay.create()

scheduler = Scheduler(LD, fps=25)
scheduler.load_xml(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shapes.xml'))

try:
    scheduler.run()
except KeyboardInterrupt:
    pass
finally:
    scheduler.stop()

    # example of injecting an event while the animation is running:
    # scheduler.create_line('bye', 20*255, 128*255, 236*255, 128*255, 40)

    LD.close()
