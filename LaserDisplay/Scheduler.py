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

Other XML files can be referenced with <sequence name="NAME" file="PATH"/>
elements: the referenced file's shapes are defined and its events form the
sequence NAME, which is started with <create sequence="NAME"/> inside an
event; the file's timeline (using its own absolute times) then plays
relative to the time of the creating event.  PATH is resolved relative to
the directory of the referencing file.  <effect sequence="NAME" .../>
actions in the same event attach effects to all shapes the sequence
creates (and to the shapes of nested sequences), starting at the time the
sequence is created.  A running sequence is stopped with
<destroy sequence="NAME"/> in a later event: the shapes it created
(including those of nested sequences) are removed and its remaining
timeline events no longer fire.

Effect types: rotation, translation, scale, color_shift, blink, rainbow,
warp, multi_color (colors="r,g,b;r,g,b;..."), move_points
(points="3:7"/"-10:"/"0,5,9", moved by dx/dy or towards tx/ty), morph
(blends the shape into the shape given with target=<shape name>),
translate_by_path (moves the shape along the outline of the path given
with path=<shape name> at velocity units/second, starting at the fraction
phase of the path's length; the path shape is defined but never created),
flip (mirrors the shape and its already applied effects in place at the
middle vertical (axis="vertical", the default) or horizontal
(axis="horizontal") frame axis; with period > 0 it flips between mirrored
and original every period seconds, phase shifts the flip cycle), mirror
(adds an exactly mirrored copy of the shape, vertical or horizontal; the
original shape is left untouched) and speedup (changes the speed at which
all animations of the shape run: factor > 1 faster, 0 < factor < 1 slower,
negative = reverse; affects every effect on the shape, including effects
attached later, and via <effect sequence=.../> every shape of a sequence).
"""

import heapq
import os
import threading
import time
import xml.etree.ElementTree as ElementTree

import numpy

from .Animate import (apply, Rotation, Translation, Scale, ColorShift, Blink,
                      Morph, MultiColor, Rainbow, Warp, MovePoints,
                      TranslateByPath, Flip, Mirror, SpeedUp)
from .Geometry import Geometry
from .Shape import Shape

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
                    'fx': (0.25, 'raw'), 'fy': (0.25, 'raw'), 'phase': (0.0, 'raw'),
                    'wrap': (1, 'raw')},
    'scale':       {'factor': (1.0, 'raw'), 'min': (0.8, 'raw'), 'max': (1.2, 'raw'),
                    'frequency': (0.0, 'raw'),
                    'center_x': (None, 'coord'), 'center_y': (None, 'coord')},
    'color_shift': {'dr': (0.0, 'color'), 'dg': (0.0, 'color'), 'db': (0.0, 'color')},
    'blink':       {'period': (1.0, 'raw'), 'duty': (0.5, 'raw'), 'every': (0, 'raw')},
    'rainbow':     {'cycles': (1.0, 'raw'), 'speed': (0.1, 'raw'), 'phase': (0.0, 'raw'),
                    'saturation': (1.0, 'raw'), 'brightness': (1.0, 'raw')},
    'warp':        {'amplitude': (15.0, 'coord'), 'wavelength': (100.0, 'coord'),
                    'speed': (1.0, 'raw'), 'phase': (0.0, 'raw'), 'horizontal': (1, 'raw')},
    'speedup':     {'factor': (1.0, 'raw')},
}

CENTER = 128 * SCALE


class _ActiveShape:
    # runtime state of one active shape
    def __init__(self, shape):
        self.shape = shape
        self.base = shape.get_points().astype('float64')
        self.effects = []                # list of (start, anim_start, effect)
        # animation time of the shape: the time its effects are evaluated
        # with. Normally it equals the animation (wall) time; speedup
        # effects re-base it so it flows at another rate.  It is piecewise
        # linear: for wall times at/after the last change,
        # anim_time(wall) = _speed_offset + _factor * (wall - _speed_change)
        self._speed_change = 0.0         # wall time of the last speed change
        self._speed_offset = 0.0         # animation time at that moment
        self._factor = 1.0               # current animation speed

    def anim_time(self, wall):
        # the animation time that corresponds to the given wall time
        return self._speed_offset + self._factor * (wall - self._speed_change)

    def set_speed(self, factor, wall):
        # changes the speed of the shape's animations to `factor` from the
        # given wall time on; the animation time stays continuous, so the
        # effects keep moving from their current state (a negative factor
        # plays them back in reverse)
        self._speed_offset = self.anim_time(wall)
        self._speed_change = wall
        self._factor = float(factor)


class _SequenceInstance:
    # runtime state of one running sequence instance (created with
    # <create sequence="NAME"/> or create_sequence()); remembers the
    # shapes its timeline created (and those of the sequences nested in
    # it) so destroy_sequence() can remove them all, and can be
    # cancelled so the timeline's remaining events no longer fire
    def __init__(self, name):
        self.name = name
        self.parent = None            # enclosing instance (nested sequence)
        self.children = []            # instances of nested sequences
        self.members = set()          # shape names this timeline created
        self.cancelled = False

    def add_member(self, name):
        # the shape belongs to this instance and to all enclosing ones
        # (caller must hold the scheduler lock)
        node = self
        while node is not None:
            node.members.add(name)
            node = node.parent


class Scheduler:

    def __init__(self, laser_display, fps=25):
        self.display = laser_display
        self.fps = fps
        self.duration = None             # seconds; None = run until stop()
        self._definitions = {}           # name -> (builder(), blank_n)
        self._sequences = {}             # name -> list of (time, action spec)
        self._sequence_instances = {}    # name -> list of _SequenceInstance
        self._loading_files = set()      # files currently being loaded (cycle check)
        self._active = {}                # name -> _ActiveShape
        self._events = []                # heap of (time, seq, function)
        self._seq = 0
        self._time = 0.0
        self._running = False
        self._lock = threading.RLock()

# ----- loading -----

    def load_xml(self, filename):
        """reads the animation timeline from an XML file.

        Besides <shape> and <event> elements, the file may contain
        <sequence name="NAME" file="PATH"/> elements that reference other
        XML files: the referenced file's shapes are defined and its events
        form the sequence NAME, which can be started with
        <create sequence="NAME"/> (see create_sequence()).  PATH is
        resolved relative to the directory of the referencing file.
        <effect sequence="NAME" .../> actions in the same event attach
        effects to all shapes the sequence creates, and
        <destroy sequence="NAME"/> actions in a later event stop a
        running sequence (see destroy_sequence()).
        """
        self._loading_files = set()
        root, events = self.__load_file(filename)
        if root.get('fps'):
            self.fps = float(root.get('fps'))
        if root.get('duration'):
            self.duration = float(root.get('duration'))
        for at, specs in events:
            self.schedule(at, self.__make_event(specs, at))

    def __load_file(self, filename):
        """parses the file and returns (root, events) where events is a
        list of (at, [action specs]) pairs, one entry per <event>.
        <shape> definitions are registered as a side effect and nested
        <sequence> references are resolved relative to the file's
        directory; circular references are rejected"""
        path = os.path.abspath(filename)
        if path in self._loading_files:
            raise ValueError("circular <sequence> reference involving '%s'"
                             % filename)
        self._loading_files.add(path)
        try:
            root = ElementTree.parse(filename).getroot()
        except ElementTree.ParseError as e:
            raise ValueError("'%s' is not a valid XML file (%s)"
                             % (filename, e))
        except OSError as e:
            raise ValueError("cannot read '%s' (%s)" % (filename, e))
        if root.tag != 'animation':
            raise ValueError("'%s' needs an <animation> root element" % filename)
        events = []
        try:
            for node in root:
                if node.tag == 'shape':
                    self.__define_from_xml(node)
                elif node.tag == 'sequence':
                    self.__define_sequence(node, os.path.dirname(path))
                elif node.tag == 'event':
                    at = float(node.get('at'))
                    specs = [self.__action_spec(action) for action in node]
                    self.__check_event(specs)
                    events.append((at, specs))
        finally:
            self._loading_files.discard(path)
        return root, events

    @staticmethod
    def __check_event(specs):
        # <effect sequence="X"/> is only valid together with a
        # <create sequence="X"/> in the same event
        created = {spec[1] for spec in specs if spec[0] == 'create_sequence'}
        for spec in specs:
            if spec[0] == 'effect_sequence' and spec[1] not in created:
                raise ValueError("effect for sequence '%s' needs a "
                                 "<create sequence=\"%s\"/> in the same "
                                 "event" % (spec[1], spec[1]))

    def __define_sequence(self, node, base_dir):
        """registers the events of the file referenced by a <sequence>
        element as a named sequence; the file is loaded right away (its
        shapes become defined), its events are stored until the sequence
        is created"""
        name = node.get('name')
        if not name:
            raise ValueError("<sequence> element needs a name attribute")
        path = node.get('file')
        if not path:
            raise ValueError("<sequence> element needs a file="
                             "path-to-an-XML-file attribute")
        _, events = self.__load_file(os.path.join(base_dir, path))
        with self._lock:
            self._sequences[name] = events

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

    def __action_spec(self, action):
        """parses an action element inside an <event> and returns a
        description of the action; the actual function is created when the
        event is scheduled (see __make_event()), so that <create sequence>
        actions can be re-based when their containing timeline is shifted
        and sequence effects can be paired with their creating event"""
        if action.tag == 'create':
            name = action.get('shape')
            if name is not None:
                return ('create', name)
            name = action.get('sequence')
            if name is not None:
                return ('create_sequence', name)
            raise ValueError("<create> element needs a shape= or "
                             "sequence= attribute")
        if action.tag == 'destroy':
            name = action.get('shape')
            if name is not None:
                return ('destroy', name)
            name = action.get('sequence')
            if name is not None:
                return ('destroy_sequence', name)
            raise ValueError("<destroy> element needs a shape= or "
                             "sequence= attribute")
        if action.tag == 'effect':
            seq_name = action.get('sequence')
            if seq_name is not None:
                params = dict(action.attrib)
                params.pop('sequence', None)
                params.pop('type', None)
                factory = self.__effect_builder(action.get('type'), params,
                                                "effect for sequence '%s'" % seq_name)
                return ('effect_sequence', seq_name, factory)
            name = action.get('shape')
            params = dict(action.attrib)
            params.pop('shape', None)
            params.pop('type', None)
            factory = self.__effect_builder(action.get('type'), params,
                                            "effect for shape '%s'" % name)
            return ('effect', name, factory)
        raise ValueError("unknown action <%s> in event" % action.tag)

    def __make_event(self, specs, at, seq_effects=None, inst=None):
        """creates the function that runs all actions of one event at time
        `at`.  `seq_effects` is a list of (factory, start) pairs: the
        effects of the enclosing sequence instance, applied to every shape
        the event creates and inherited by nested sequences; `inst` is the
        sequence instance whose timeline this event belongs to (None for
        the main timeline): once the instance has been destroyed the event
        is skipped, and the shapes it creates are registered as its
        members"""
        # pair <create sequence="X"/> with the <effect sequence="X"/>
        # actions of this event
        paired = {}
        for spec in specs:
            if spec[0] == 'effect_sequence':
                paired.setdefault(spec[1], []).append(spec[2])

        def run():
            if inst is not None:
                with self._lock:
                    if inst.cancelled:
                        return
            for spec in specs:
                kind = spec[0]
                if kind == 'create':
                    self.create(spec[1])
                    if inst is not None:
                        with self._lock:
                            inst.add_member(spec[1])
                    if seq_effects:
                        for factory, start in seq_effects:
                            self.__attach_effect(spec[1], factory(), start)
                elif kind == 'destroy':
                    self.destroy(spec[1])
                elif kind == 'destroy_sequence':
                    self.destroy_sequence(spec[1])
                elif kind == 'effect':
                    # start the effect at the event's own time (not the
                    # current one), so that seeking (run(start=...)) finds
                    # it already progressed like all other timeline state
                    self.__attach_effect(spec[1], spec[2](), at)
                elif kind == 'effect_sequence':
                    pass    # already applied via the paired create_sequence
                elif kind == 'create_sequence':
                    child = self.create_sequence(spec[1], at,
                                                 effects=paired.get(spec[1], []),
                                                 inherited=seq_effects)
                    if inst is not None:
                        with self._lock:
                            child.parent = inst
                            inst.children.append(child)
        return run

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
        if type == 'flip':
            return self.__flip_factory(params, context)
        if type == 'mirror':
            return self.__mirror_factory(params, context)
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
                   'rainbow': Rainbow, 'warp': Warp, 'speedup': SpeedUp}
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

    def __flip_factory(self, params, context):
        axis = params.pop('axis', 'vertical')
        if axis not in ('vertical', 'horizontal'):
            raise ValueError("%s: flip axis must be 'vertical' or "
                             "'horizontal'" % context)
        try:
            period = float(params.pop('period', 0.0))
            phase = float(params.pop('phase', 0.0))
        except ValueError as e:
            raise ValueError("%s: invalid flip parameter (%s)" % (context, e))
        if params:
            raise ValueError("%s: unknown parameter(s) %s" % (context, sorted(params)))
        return lambda: Flip(axis=axis, period=period, phase=phase)

    def __mirror_factory(self, params, context):
        axis = params.pop('axis', 'vertical')
        if axis not in ('vertical', 'horizontal'):
            raise ValueError("%s: mirror axis must be 'vertical' or "
                             "'horizontal'" % context)
        if params:
            raise ValueError("%s: unknown parameter(s) %s" % (context, sorted(params)))
        return lambda: Mirror(axis=axis)

# ----- main loop -----

    def run(self, duration=None, speed=1.0, start=0.0):
        """runs the animation until its duration has passed or stop() is called;
        blocks the calling thread. speed scales animation time against the
        wall clock: 1.0 is real time, values above 1 run faster, and 0 runs
        as fast as possible (no pacing; for validating timeline files).
        start shifts the virtual clock: the animation begins at the given
        time instead of 0, as if it had already been running since the
        beginning — all earlier events fire at once, so shapes created
        earlier are already active and their effects are already
        progressed to `start`"""
        if duration is None:
            duration = self.duration
        interval = 1.0 / self.fps
        with self._lock:
            self._running = True
        epoch = time.perf_counter()
        next_frame = epoch
        virt = start
        try:
            while True:
                with self._lock:
                    if not self._running:
                        break
                if speed > 0:
                    virt = (time.perf_counter() - epoch) * speed + start
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

    def create_sequence(self, name, at=None, effects=None, inherited=None):
        """starts a sequence referenced via <sequence>: all events of the
        referenced file fire at their own timestamps shifted by `at`, so
        the file's timeline (which uses absolute times) plays relative to
        that moment; `at` defaults to the current animation time.

        `effects` (effect objects or zero-argument factories) are applied
        to every shape the sequence creates, starting at `at`; `inherited`
        is the list of (factory, start) pairs of an enclosing sequence, so
        that nested sequences keep moving in sync with the group they are
        part of.

        Returns the running instance; destroy_sequence() (or a
        <destroy sequence="NAME"/> event) stops it and removes the shapes
        it created."""
        with self._lock:
            if name not in self._sequences:
                raise KeyError("no sequence defined with name '%s'" % name)
            timeline = list(self._sequences[name])
            if at is None:
                at = self._time
            instance = _SequenceInstance(name)
            self._sequence_instances.setdefault(name, []).append(instance)
        seq_effects = list(inherited or [])
        for effect in (effects or []):
            factory = effect if callable(effect) else (lambda e=effect: e)
            seq_effects.append((factory, at))
        for event_at, specs in timeline:
            self.schedule(at + event_at,
                          self.__make_event(specs, at + event_at, seq_effects,
                                            instance))
        return instance

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
        """removes a shape from the animation.  Silently skips shapes that are
        not currently active (e.g. duplicates of destroy elements)."""
        with self._lock:
            if name not in self._active:
                return
            del self._active[name]

    def destroy_sequence(self, name):
        """stops the running instance(s) of a sequence (see
        <destroy sequence="NAME"/>): their remaining timeline events no
        longer fire and all shapes they created (including the shapes of
        the sequences nested in them) are removed.  Silently skips names
        that have no running instance."""
        with self._lock:
            instances = list(self._sequence_instances.get(name, ()))
        for instance in instances:
            self.__cancel_instance(instance)

    def __cancel_instance(self, instance):
        # cancels one sequence instance (and the instances of the
        # sequences nested in it) and removes the shapes they created;
        # idempotent
        with self._lock:
            if instance.cancelled:
                return
            instance.cancelled = True
            children = list(instance.children)
            members = set(instance.members)
        for child in children:
            self.__cancel_instance(child)
        for member in members:
            self.destroy(member)

    def add_effect(self, name, effect):
        """attaches a continuous effect (Rotation, Translation, ...) to an
        active shape, starting now; a SpeedUp instead changes the speed of
        the shape's animations from now on.  Silently skips shapes that
        are not currently active (e.g. effects referencing a shape
        destroyed in a previous event)."""
        with self._lock:
            start = self._time
        self.__attach_effect(name, effect, start)

    def __attach_effect(self, name, effect, start):
        # like add_effect(), but with an explicit start time (used for
        # sequence effects, which start when the sequence is created);
        # speedup effects re-scale the shape's animation time instead of
        # being stored as a point transformation
        with self._lock:
            if name not in self._active:
                return
            entry = self._active[name]
            if isinstance(effect, SpeedUp):
                entry.set_speed(effect.factor, start)
            else:
                entry.effects.append((start, entry.anim_time(start), effect))

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
        # through all of its attached effects; points that leave the screen
        # keep their true coordinates in the shape (they are only filtered
        # when the shape is added to the output buffer, see __render())
        with self._lock:
            entries = list(self._active.values())
        for entry in entries:
            pts = entry.base.copy()
            for (start, anim_start, effect) in entry.effects:
                if now >= start:
                    pts = effect.transform(pts, entry.anim_time(now) - anim_start)
            entry.shape.points = pts
            entry.shape.npoints = len(pts)

    def __render(self):
        with self._lock:
            shapes = [self.__visible_shape(entry.shape)
                      for entry in self._active.values()]
        self.display.new_frame()
        for s in shapes:
            if s is not None:
                self.display.add_shape_to_frame(s)
        self.display.show_frame()

    @staticmethod
    def __visible_shape(shape):
        # returns a new shape holding only the points that lie on the screen
        # (0 .. MAX), or None if the shape has no visible points; the given
        # shape keeps all of its points
        pts = shape.get_points()
        if len(pts) == 0:
            return None
        mask = (pts[:, 0] >= 0) & (pts[:, 0] <= MAX) & \
               (pts[:, 1] >= 0) & (pts[:, 1] <= MAX)
        if not mask.any():
            return None
        return Shape(numpy.rint(pts[mask]).astype('uint16'))
