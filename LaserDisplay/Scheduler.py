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

Effect types: rotation, translation, scale, color_shift, blink, rainbow,
warp, multi_color (colors="r,g,b;r,g,b;..."), move_points
(points="3:7"/"-10:"/"0,5,9", moved by dx/dy or towards tx/ty), morph
(blends the shape into the shape given with target=<shape name>) and
translate_by_path (moves the shape along the outline of the path given
with path=<shape name> at velocity units/second, starting at the fraction
phase of the path's length; the path shape is defined but never created).
"""

import heapq
import threading
import time
import xml.etree.ElementTree as ElementTree

import numpy

from .Animate import (apply, Rotation, Translation, Scale, ColorShift, Blink,
                      Morph, MultiColor, Rainbow, Warp, MovePoints,
                      TranslateByPath)
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
    'ellipse':  (('cx', 'cy', 'w', 'h'), ('npoints',)),
    'tetragon': (('x0', 'y0', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3'), ('npoints',)),
}

# effects understood by the XML format:
#   parameter -> (default, kind); kind 'coord'/'color' are given in 0..255 and
#   scaled to the internal 16 bit range, kind 'raw' is used as-is.
#   'morph', 'multi_color', 'move_points' and 'translate_by_path' need
#   list/reference parameters and are parsed separately in __effect_builder()
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
    'rainbow':     {'cycles': (1.0, 'raw'), 'speed': (0.1, 'raw'), 'phase': (0.0, 'raw'),
                    'saturation': (1.0, 'raw'), 'brightness': (1.0, 'raw')},
    'warp':        {'amplitude': (15.0, 'coord'), 'wavelength': (100.0, 'coord'),
                    'speed': (1.0, 'raw'), 'phase': (0.0, 'raw'), 'horizontal': (1, 'raw')},
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
            'ellipse':  lambda: Geometry.ellipse(*args[:4], args[4], *color),
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
            factory = self.__effect_builder(action.get('type'), params,
                                            "effect for shape '%s'" % name)
            return lambda: self.add_effect(name, factory())
        raise ValueError("unknown action <%s> in event" % action.tag)

    def __effect_builder(self, type, params, context):
        """returns a zero-argument factory that creates the effect object;
        factories run when their event fires, so parameters referencing other
        shapes (morph targets) are resolved at that time"""
        if type == 'morph':
            return self.__morph_factory(params, context)
        if type == 'multi_color':
            colors = self.__parse_colors(params.pop('colors', None), context)
            if params:
                raise ValueError("%s: unknown parameter(s) %s" % (context, sorted(params)))
            return lambda: MultiColor(colors)
        if type == 'move_points':
            return self.__move_points_factory(params, context)
        if type == 'translate_by_path':
            return self.__translate_by_path_factory(params, context)
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
                   'color_shift': ColorShift, 'blink': Blink,
                   'rainbow': Rainbow, 'warp': Warp}
        return lambda: classes[type](**kwargs)

    def __morph_factory(self, params, context):
        target_name = params.pop('target', None)
        if not target_name:
            raise ValueError("%s: morph needs a target=<shape name> parameter" % context)
        try:
            duration = float(params.pop('duration', 1.0))
            bounce = bool(int(float(params.pop('bounce', 0))))
            smooth = bool(int(float(params.pop('smooth', 1))))
        except ValueError as e:
            raise ValueError("%s: invalid morph parameter (%s)" % (context, e))
        if params:
            raise ValueError("%s: unknown parameter(s) %s" % (context, sorted(params)))

        def factory():
            with self._lock:
                if target_name not in self._definitions:
                    raise KeyError("no shape defined with name '%s'" % target_name)
                builder, _ = self._definitions[target_name]
            return Morph(builder().get_points(), duration=duration,
                         bounce=bounce, smooth=smooth)
        return factory

    @staticmethod
    def __parse_colors(spec, context):
        # parses colors="r,g,b;r,g,b;..." (values 0..255)
        if not spec:
            raise ValueError("%s: multi_color needs a colors=\"r,g,b;r,g,b;...\" "
                             "parameter" % context)
        try:
            return [tuple(float(v) * SCALE for v in triplet.split(','))
                    for triplet in spec.split(';')]
        except ValueError:
            raise ValueError("%s: invalid colors specification '%s'" % (context, spec))

    @staticmethod
    def __parse_selection(spec, context):
        # parses points="3:7" | points="-10:" | points="0,5,9" | points="4"
        if not spec:
            raise ValueError("%s: move_points needs a points=<selection> parameter"
                             % context)
        try:
            if ':' in spec:
                first, last = spec.split(':', 1)
                return slice(int(first) if first.strip() else None,
                             int(last) if last.strip() else None)
            indices = [int(part) for part in spec.split(',') if part.strip()]
            return indices[0] if len(indices) == 1 else indices
        except ValueError:
            raise ValueError("%s: invalid point selection '%s'" % (context, spec))

    def __move_points_factory(self, params, context):
        selection = self.__parse_selection(params.pop('points', None), context)
        try:
            dx = float(params.pop('dx', 0.0)) * SCALE
            dy = float(params.pop('dy', 0.0)) * SCALE
            duration = float(params.pop('duration', 0.0))
            tx, ty = params.pop('tx', None), params.pop('ty', None)
            if (tx is None) != (ty is None):
                raise ValueError("tx and ty must be given together")
            target = None if tx is None else (float(tx) * SCALE, float(ty) * SCALE)
        except ValueError as e:
            raise ValueError("%s: invalid move_points parameter (%s)" % (context, e))
        if params:
            raise ValueError("%s: unknown parameter(s) %s" % (context, sorted(params)))
        return lambda: MovePoints(selection, dx=dx, dy=dy, target=target,
                                  duration=duration)

    def __translate_by_path_factory(self, params, context):
        path_name = params.pop('path', None)
        if not path_name:
            raise ValueError("%s: translate_by_path needs a path=<shape name> "
                             "parameter" % context)
        try:
            velocity = float(params.pop('velocity', 50.0)) * SCALE
            closed = bool(int(float(params.pop('closed', 1))))
            phase = float(params.pop('phase', 0.0))
        except ValueError as e:
            raise ValueError("%s: invalid translate_by_path parameter (%s)"
                             % (context, e))
        if params:
            raise ValueError("%s: unknown parameter(s) %s" % (context, sorted(params)))

        def factory():
            with self._lock:
                if path_name not in self._definitions:
                    raise KeyError("no shape defined with name '%s'" % path_name)
                builder, _ = self._definitions[path_name]
            return TranslateByPath(builder(), velocity=velocity, closed=closed,
                                   phase=phase)
        return factory

# ----- main loop -----

    def run(self, duration=None, speed=1.0):
        """runs the animation until its duration has passed or stop() is called;
        blocks the calling thread. speed scales animation time against the
        wall clock: 1.0 is real time, values above 1 run faster, and 0 runs
        as fast as possible (no pacing; for validating timeline files)"""
        if duration is None:
            duration = self.duration
        interval = 1.0 / self.fps
        with self._lock:
            self._running = True
        epoch = time.perf_counter()
        next_frame = epoch
        virt = 0.0
        try:
            while True:
                with self._lock:
                    if not self._running:
                        break
                if speed > 0:
                    virt = (time.perf_counter() - epoch) * speed
                with self._lock:
                    self._time = virt
                self.__process_events(virt)
                self.__update_shapes(virt)
                self.__render()
                if duration is not None and virt >= duration:
                    break
                if speed > 0:
                    next_frame += interval / speed
                    rest = next_frame - time.perf_counter()
                    if rest > 0:
                        time.sleep(rest)
                    else:
                        next_frame = time.perf_counter()   # fell behind, catch up
                else:
                    virt += interval   # unpaced: one virtual frame per loop
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

    def create_ellipse(self, name, cx, cy, w, h, npoints,
                       color=(MAX, MAX, MAX), blank_n=0):
        """creates an ellipse immediately (internal coordinate/color units)"""
        self.__create_now(Geometry.ellipse(cx, cy, w, h, npoints, *color), name, blank_n)

    def create_tetragon(self, name, x0, y0, x1, y1, x2, y2, x3, y3, npoints,
                        color=(MAX, MAX, MAX), blank_n=0):
        """creates a tetragon immediately (internal coordinate/color units)"""
        self.__create_now(
            Geometry.tetragon(x0, y0, x1, y1, x2, y2, x3, y3, npoints, *color), name, blank_n)

    def destroy(self, name):
        """removes a shape from the animation"""
        with self._lock:
            if name not in self._active:
                raise KeyError(f" no active shape with name '%s'" % name)
            del self._active[name]

    def add_effect(self, name, effect):
        """attaches a continuous effect (Rotation, Translation, ...) to an
        active shape, starting now"""
        with self._lock:
            if name not in self._active:
                raise KeyError(f"no active shape with name '%s'" % name)
            self._active[name].effects.append((self._time, effect))

# ----- internals -----

    def __create_now(self, shape, name, blank_n):
        with self._lock:
            self.__activate(name, shape, blank_n)

    def __activate(self, name, shape, blank_n):
        # caller must hold the lock
        if blank_n > 1:
            # duty=1.0: never fully off, just blank (beam off at) every n-th point
            apply(shape, Blink(duty=1.0, every=blank_n))
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
