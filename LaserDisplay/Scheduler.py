"""
Scheduler for shape animations.

The Scheduler runs the main loop at a fixed frame rate, keeps track of the
active shapes and applies continuous effects to them. Shapes are created
and destroyed by events; events can either come from an XML timeline
(see load_xml()) or be injected programmatically while the animation is
running (the public methods are thread-safe):

    LD = LaserDisplay.create()
    s = Scheduler(LD, fps=25)
    s.load_xml('shapes.xml')
    s.run_in_background()
    ...
    s.create_triangle('surprise', ...)      # injected at runtime
    s.destroy('surprise')
    ...
    s.stop()

XML timeline format (coordinates/colors use the familiar 0..255 range,
y points up, times are seconds):

    <animation fps="25" duration="16">
        <shape name="tri" type="triangle" x0="88" y0="98" x1="168" y1="98"
               x2="128" y2="170" npoints="24" red="255" green="120" blue="0"/>
        <event at="0.0">
            <create shape="tri"/>
            <effect shape="tri" type="rotation" speed="45"/>
        </event>
        <event at="5.0">
            <destroy shape="tri"/>
        </event>
    </animation>
"""

import heapq
import threading
import time
import xml.etree.ElementTree as ElementTree

import numpy

from .Animate import Animate, Rotation, Translation, Scale, ColorShift, Blink
from .Geometry import Geometry

MAX = 255 * 255
SCALE = 255


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

# geometry types understood by the XML format:
#   required parameters, parameters that are scaled from 0..255 to 16 bit
_GEOMETRY_PARAMS = {
    'line':     (('x0', 'y0', 'x1', 'y1'), ('npoints',)),
    'triangle': (('x0', 'y0', 'x1', 'y1', 'x2', 'y2'), ('npoints',)),
    'circle':   (('cx', 'cy', 'r'), ('npoints',)),
    'tetragon': (('x0', 'y0', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3'), ('npoints',)),
}

# effects understood by the XML format:
#   parameter -> (default, kind); kind 'coord'/'color' are given in 0..255 and
#   scaled to the internal 16 bit range, kind 'raw' is used as-is
_EFFECT_PARAMS = {
    'rotation':    {'pivot_x': (None, 'coord'), 'pivot_y': (None, 'coord'),
                    'speed': (45.0, 'raw'), 'phase': (0.0, 'raw')},
    'translation': {'vx': (0.0, 'coord'), 'vy': (0.0, 'coord'),
                    'ax': (0.0, 'coord'), 'ay': (0.0, 'coord'),
                    'fx': (0.25, 'raw'), 'fy': (0.25, 'raw'), 'phase': (0.0, 'raw')},
    'scale':       {'factor': (1.0, 'raw'), 'min': (0.8, 'raw'), 'max': (1.2, 'raw'),
                    'frequency': (0.0, 'raw'),
                    'center_x': (None, 'coord'), 'center_y': (None, 'coord')},
    'color_shift': {'dr': (0.0, 'color'), 'dg': (0.0, 'color'), 'db': (0.0, 'color')},
    'blink':       {'period': (1.0, 'raw'), 'duty': (0.5, 'raw'), 'every': (0, 'raw')},
}

CENTER = 128 * SCALE


class _ActiveShape:
    # runtime state of one active shape
    def __init__(self, shape):
        self.shape = shape
        self.base = shape.get_points().astype('float64')
        self.effects = []                # list of (start_time, effect)


class Scheduler:

    def __init__(self, laser_display, fps=25):
        self.display = laser_display
        self.fps = fps
        self.duration = None             # seconds; None = run until stop()
        self._definitions = {}           # name -> (builder(), blank_n)
        self._active = {}                # name -> _ActiveShape
        self._events = []                # heap of (time, seq, function)
        self._seq = 0
        self._time = 0.0
        self._running = False
        self._lock = threading.RLock()

# ----- loading -----

    def load_xml(self, filename):
        """reads the animation timeline from an XML file"""
        root = ElementTree.parse(filename).getroot()
        if root.tag != 'animation':
            raise ValueError("expected an <animation> root element")
        if root.get('fps'):
            self.fps = float(root.get('fps'))
        if root.get('duration'):
            self.duration = float(root.get('duration'))

        for node in root:
            if node.tag == 'shape':
                self.__define_from_xml(node)
            elif node.tag == 'event':
                at = float(node.get('at'))
                for action in node:
                    function = self.__action_from_xml(action)
                    if function is not None:
                        self.schedule(at, function)

    def __define_from_xml(self, node):
        name = node.get('name')
        if not name:
            raise ValueError("<shape> element needs a name")
        builder, blank_n = self.__geometry_builder(node.get('type'), dict(node.attrib),
                                                   "shape '%s'" % name)
        with self._lock:
            self._definitions[name] = (builder, blank_n)

    def __geometry_builder(self, type, params, context):
        if type not in _GEOMETRY_PARAMS:
            raise ValueError("%s: unknown geometry type '%s'" % (context, type))
        coords, raws = _GEOMETRY_PARAMS[type]
        params.pop('name', None)
        params.pop('type', None)
        blank_n = int(params.pop('blank', 0))

        try:
            args = [float(params[key]) * SCALE for key in coords]
            args += [int(params[key]) for key in raws]
            color = tuple(int(params.get(c, 255)) * SCALE for c in ('red', 'green', 'blue'))
        except KeyError as e:
            raise ValueError("%s: missing parameter %s" % (context, e))
        except ValueError as e:
            raise ValueError("%s: invalid parameter (%s)" % (context, e))

        builders = {
            'line':     lambda: Geometry.line(*args[:4], args[4], *color),
            'triangle': lambda: Geometry.triangle(*args[:6], args[6], *color),
            'circle':   lambda: Geometry.circle(*args[:3], args[3], *color),
            'tetragon': lambda: Geometry.tetragon(*args[:8], args[8], *color),
        }
        return builders[type], blank_n

    def __action_from_xml(self, action):
        if action.tag == 'create':
            name = action.get('shape')
            return lambda: self.create(name)
        if action.tag == 'destroy':
            name = action.get('shape')
            return lambda: self.destroy(name)
        if action.tag == 'effect':
            name = action.get('shape')
            params = dict(action.attrib)
            params.pop('shape', None)
            params.pop('type', None)
            effect = self.__effect_builder(action.get('type'), params,
                                           "effect for shape '%s'" % name)
            return lambda: self.add_effect(name, effect)
        raise ValueError("unknown action <%s> in event" % action.tag)

    def __effect_builder(self, type, params, context):
        if type not in _EFFECT_PARAMS:
            raise ValueError("%s: unknown effect type '%s'" % (context, type))
        kwargs = {}
        for key, (default, kind) in _EFFECT_PARAMS[type].items():
            value = params.pop(key, None)
            if value is None:
                value = CENTER if default is None else default
            elif kind == 'coord' or kind == 'color':
                value = float(value) * SCALE
            else:
                value = float(value)
            kwargs[key] = value
        if params:
            raise ValueError("%s: unknown parameter(s) %s" % (context, sorted(params)))
        # XML attribute names that differ from the effect constructor arguments
        aliases = {'min': 'min_factor', 'max': 'max_factor'}
        kwargs = {aliases.get(k, k): v for k, v in kwargs.items()}
        classes = {'rotation': Rotation, 'translation': Translation, 'scale': Scale,
                   'color_shift': ColorShift, 'blink': Blink}
        return classes[type](**kwargs)

# ----- main loop -----

    def run(self, duration=None):
        """runs the animation until its duration has passed or stop() is called;
        blocks the calling thread"""
        if duration is None:
            duration = self.duration
        interval = 1.0 / self.fps
        with self._lock:
            self._running = True
        epoch = time.perf_counter()
        next_frame = epoch
        try:
            while True:
                with self._lock:
                    if not self._running:
                        break
                now = time.perf_counter() - epoch
                with self._lock:
                    self._time = now
                self.__process_events(now)
                self.__update_shapes(now)
                self.__render()
                if duration is not None and now >= duration:
                    break
                next_frame += interval
                rest = next_frame - time.perf_counter()
                if rest > 0:
                    time.sleep(rest)
                else:
                    next_frame = time.perf_counter()   # fell behind, catch up
        finally:
            with self._lock:
                self._running = False

    def run_in_background(self, duration=None):
        """runs the animation in a daemon thread; events can be injected into
        the scheduler while it is running"""
        thread = threading.Thread(target=self.run, args=(duration,), daemon=True)
        thread.start()
        return thread

    def stop(self):
        with self._lock:
            self._running = False

    def current_time(self):
        with self._lock:
            return self._time

# ----- public event api (thread-safe, usable while the animation runs) -----

    def schedule(self, at, function):
        """schedules a function call at the given animation time (seconds)"""
        with self._lock:
            heapq.heappush(self._events, (float(at), self._seq, function))
            self._seq += 1

    def define_shape(self, name, type, blank_n=0, **params):
        """defines a named shape (parameters like in the XML format, coordinates
        and colors given in the 0..255 range); it can later be activated with
        create()"""
        builder, _ = self.__geometry_builder(type, dict(name=name, **params), "shape '%s'" % name)
        with self._lock:
            self._definitions[name] = (builder, blank_n)

    def create(self, name):
        """creates/activates a previously defined shape"""
        with self._lock:
            if name not in self._definitions:
                raise KeyError("no shape defined with name '%s'" % name)
            builder, blank_n = self._definitions[name]
            self.__activate(name, builder(), blank_n)

    def create_triangle(self, name, x0, y0, x1, y1, x2, y2, npoints,
                        color=(MAX, MAX, MAX), blank_n=0):
        """creates a triangle immediately (internal coordinate/color units)"""
        self.__create_now(Geometry.triangle(x0, y0, x1, y1, x2, y2, npoints, *color), name, blank_n)

    def create_line(self, name, x0, y0, x1, y1, npoints,
                    color=(MAX, MAX, MAX), blank_n=0):
        """creates a line immediately (internal coordinate/color units)"""
        self.__create_now(Geometry.line(x0, y0, x1, y1, npoints, *color), name, blank_n)

    def create_circle(self, name, cx, cy, r, npoints,
                      color=(MAX, MAX, MAX), blank_n=0):
        """creates a circle immediately (internal coordinate/color units)"""
        self.__create_now(Geometry.circle(cx, cy, r, npoints, *color), name, blank_n)

    def create_tetragon(self, name, x0, y0, x1, y1, x2, y2, x3, y3, npoints,
                        color=(MAX, MAX, MAX), blank_n=0):
        """creates a tetragon immediately (internal coordinate/color units)"""
        self.__create_now(
            Geometry.tetragon(x0, y0, x1, y1, x2, y2, x3, y3, npoints, *color), name, blank_n)

    def destroy(self, name):
        """removes a shape from the animation"""
        with self._lock:
            if name not in self._active:
                raise KeyError("no active shape with name '%s'" % name)
            del self._active[name]

    def add_effect(self, name, effect):
        """attaches a continuous effect (Rotation, Translation, ...) to an
        active shape, starting now"""
        with self._lock:
            if name not in self._active:
                raise KeyError("no active shape with name '%s'" % name)
            self._active[name].effects.append((self._time, effect))

# ----- internals -----

    def __create_now(self, shape, name, blank_n):
        if blank_n > 1:
            Animate.apply_blank(shape, blank_n)
        with self._lock:
            self.__activate(name, shape, 0)

    def __activate(self, name, shape, blank_n):
        # caller must hold the lock
        if blank_n > 1:
            Animate.apply_blank(shape, blank_n)
        self._active[name] = _ActiveShape(shape)

    def __process_events(self, now):
        while True:
            with self._lock:
                if not self._events or self._events[0][0] > now:
                    break
                _, _, function = heapq.heappop(self._events)
            function()

    def __update_shapes(self, now):
        # recomputes every active shape from its original points by piping it
        # through all of its attached effects
        with self._lock:
            entries = list(self._active.values())
        for entry in entries:
            pts = entry.base.copy()
            for (start, effect) in entry.effects:
                if now >= start:
                    pts = effect.transform(pts, now - start)
            entry.shape.points = numpy.clip(numpy.rint(pts), 0, MAX).astype('uint16')
            entry.shape.npoints = len(entry.shape.points)

    def __render(self):
        with self._lock:
            shapes = [entry.shape for entry in self._active.values()]
        self.display.new_frame()
        for s in shapes:
            self.display.add_shape_to_frame(s)
        self.display.show_frame()
