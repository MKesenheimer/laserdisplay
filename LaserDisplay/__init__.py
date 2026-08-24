import os

from .LaserDisplay import LaserDisplay
from .Shape import Shape
from .Geometry import Geometry
from .Animate import (apply, Rotation, Translation, Scale, ColorShift, Blink,
                      DeletePoints, AddPoints, Morph, MultiColor, Rainbow,
                      Warp, MovePoints, TranslateByPath)
from .Scheduler import Scheduler

def create(mode = os.getenv('LASER')):
    if mode == 'local':
        from .LaserDisplayLocal import LaserDisplayLocal
        return LaserDisplayLocal()

    if mode == 'lumax':
        from .LaserDisplayLumax import LaserDisplayLumax
        return LaserDisplayLumax()

    if not mode is None and mode.startswith('remote'):
        from .LaserDisplayRemote import LaserDisplayRemote
        s = mode.split(':')
        if len(s) == 2:
            return LaserDisplayRemote(s[1])
        if len(s) == 3:
            return LaserDisplayRemote(s[1], s[2])

    # default is simulator
    from .LaserDisplaySimulator import LaserDisplaySimulator
    return LaserDisplaySimulator()

def createProxy(desc):
    if not isinstance(desc, list) and not isinstance(desc, tuple):
        raise ValueError('createProxy() method accepts only list and tuples')
    from .LaserDisplayProxy import LaserDisplayProxy
    return LaserDisplayProxy( [create(x) for x in desc] )
