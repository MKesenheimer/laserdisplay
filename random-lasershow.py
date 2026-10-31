#!/usr/bin/env python3

"""
Random Lasershow Player (indefinite)

Generates an endless random laser show with dynamically created shapes
and effects. Plays until the user presses Ctrl+C.

usage: python random-lasershow.py [--fast] [--seed N]
"""

import os
import sys
import random
import time
import tomllib

try:
    import argparse
except ImportError:
    argparse = None

import LaserDisplay
from LaserDisplay import Scheduler
from LaserDisplay.Animate import (Rotation, Translation, Scale, ColorShift,
                                   FadeIn, FadeOut, Blink, Rainbow, Warp,
                                   Flip, Mirror, SpeedUp)

DEFAULT_SETTINGS = {
    'global': {'zoom': 0.1, 'mirror_x': 0, 'mirror_y': 0,
               'scan_rate': 7000, 'blanking_delay': 0},
}

SCALE = 255
CENTER = 128 * SCALE


def parse_args():
    parser = argparse.ArgumentParser(
        description='Generate an endless random laser show with dynamic shapes and effects.')
    parser.add_argument('--speed', type=float, default=1.0,
                        help='Playback speed: 1.0 = real time, >1 = faster, '
                             '<1 = slower, 0 = as fast as possible (no pacing)')
    parser.add_argument('--seed', type=int,
                        help='Random seed for reproducible randomness')
    parser.add_argument('--effects', type=str, default='./lasershows/effects',
                        help='Directory of effect XML files (default: ./lasershows/effects)')
    parser.add_argument('--min-shapes', type=int, default=1,
                        help='Minimum number of shapes on screen (default: 1)')
    parser.add_argument('--max-shapes', type=int, default=5,
                        help='Maximum number of shapes on screen (default: 5)')
    args = parser.parse_args()
    return args.speed, args.seed, args.effects, args.min_shapes, args.max_shapes


def load_settings(path):
    try:
        with open(path, 'rb') as f:
            return tomllib.load(f)
    except FileNotFoundError:
        print('No settings file at %s, using the built-in defaults' % path)
        return DEFAULT_SETTINGS
    except tomllib.TOMLDecodeError as e:
        print('Could not parse the settings file %s: %s' % (path, e))
        sys.exit(1)


def apply_settings(LD, settings):
    g = settings.get('global', {})
    if 'zoom' in g:
        LD.set_zoom(g['zoom'])
    if 'mirror_x' in g or 'mirror_y' in g:
        LD.set_mirror(g.get('mirror_x', 0), g.get('mirror_y', 0))
    if 'scan_rate' in g:
        LD.set_scan_rate(g['scan_rate'])
    if 'blanking_delay' in g:
        LD.set_blanking_delay(g['blanking_delay'])

    renderers = getattr(LD, 'renderers', None)
    if not renderers:
        return
    for name in sorted(n for n in settings if n.startswith('device ')):
        dev = int(name.split()[1])
        if not 1 <= dev <= len(renderers):
            continue
        d = settings[name]
        r = renderers[dev - 1]
        if 'zoom' in d:
            r.zoom = d['zoom']
        if 'mirror_x' in d:
            r.mirrorx = d['mirror_x']
        if 'mirror_y' in d:
            r.mirrory = d['mirror_y']
        if 'swap_xy' in d:
            r.swapxy = d['swap_xy']
        if 'scan_rate' in d:
            r.scan_rate = d['scan_rate']
        if 'blanking_delay' in d:
            r.blanking_delay_ms = d['blanking_delay']


def random_color():
    return tuple(random.randint(0, 255) * SCALE for _ in range(3))


class RandomShowDirector:
    """Directs an endless random show by scheduling shapes and effects dynamically."""

    def __init__(self, scheduler, min_shapes=1, max_shapes=5):
        self.scheduler = scheduler
        self.running = False
        self.shape_counter = 0
        self.active_shapes = set()
        self.retiring_shapes = set()
        self.min_shapes = min_shapes
        self.max_shapes = max_shapes

    def next_shape_name(self):
        name = 'random_%d' % self.shape_counter
        self.shape_counter += 1
        return name

    def random_rotation(self):
        return Rotation(speed=random.choice([-180, -90, -45, 45, 90, 180]))

    def random_translation(self):
        return Translation(
            vx=random.uniform(-50, 50) * SCALE,
            vy=random.uniform(-50, 50) * SCALE,
            ax=random.uniform(0, 40) * SCALE,
            ay=random.uniform(0, 40) * SCALE,
            fx=random.uniform(0.1, 1.0),
            fy=random.uniform(0.1, 1.0),
        )

    def random_scale(self):
        return Scale(
            min_factor=random.uniform(0.5, 1.0),
            max_factor=random.uniform(1.0, 2.0),
            frequency=random.uniform(0.1, 1.0),
        )

    def random_color_shift(self):
        return ColorShift(
            dr=random.uniform(-30, 30) * SCALE,
            dg=random.uniform(-30, 30) * SCALE,
            db=random.uniform(-30, 30) * SCALE,
        )

    def random_blink(self):
        return Blink(
            period=random.uniform(0.2, 2.0),
            duty=random.uniform(0.3, 0.7),
        )

    def random_rainbow(self):
        return Rainbow(
            cycles=random.uniform(0.5, 2.0),
            speed=random.uniform(0.1, 0.5),
        )

    def random_warp(self):
        return Warp(
            amplitude=random.uniform(5, 30) * SCALE,
            wavelength=random.uniform(50, 200) * SCALE,
            speed=random.uniform(0.5, 2.0),
            horizontal=random.choice([True, False]),
        )

    def random_flip(self):
        return Flip(
            axis=random.choice(['vertical', 'horizontal']),
            period=random.uniform(1.0, 3.0),
        )

    def random_mirror(self):
        return Mirror(axis=random.choice(['vertical', 'horizontal']))

    def random_speedup(self):
        return SpeedUp(factor=random.choice([-4.0, -2.0, -1.0, 1.0, 2.0, 4.0]))

    def random_fade_in(self):
        return FadeIn(duration=random.uniform(0.2, 1.0))

    def random_fade_out(self):
        return FadeOut(duration=random.uniform(0.2, 1.0))

    def random_effects(self, count=3):
        """Generate random sequence-level effect objects. Always includes
        at least one motion effect (rotation, translation, or scale) so
        shapes are never static."""
        motion_generators = [
            self.random_rotation, self.random_translation, self.random_scale
        ]
        other_generators = [
            self.random_color_shift, self.random_blink, self.random_rainbow,
            self.random_warp, self.random_flip, self.random_mirror,
            self.random_speedup, self.random_fade_in, self.random_fade_out
        ]

        effects = []

        # Always add one motion effect
        motion_gen = random.choice(motion_generators)
        try:
            effects.append(motion_gen())
        except Exception:
            pass

        # Add random number of additional effects (0 to count)
        num_additional = random.randint(0, count)
        all_generators = motion_generators + other_generators
        for _ in range(num_additional):
            gen = random.choice(all_generators)
            try:
                effects.append(gen())
            except Exception:
                pass

        return effects

    def create_random_circle(self, name=None):
        if name is None:
            name = self.next_shape_name()
        cx = random.randint(60, 190) * SCALE
        cy = random.randint(60, 190) * SCALE
        r = random.randint(10, 40) * SCALE
        npoints = random.randint(24, 48)
        color = random_color()
        self.scheduler.create_circle(name, cx, cy, r, npoints, color)
        return name

    def create_random_triangle(self, name=None):
        if name is None:
            name = self.next_shape_name()
        cx = random.randint(60, 190) * SCALE
        cy = random.randint(60, 190) * SCALE
        size = random.randint(10, 30) * SCALE
        x0, y0 = cx, cy + size
        x1, y1 = cx - size, cy - size
        x2, y2 = cx + size, cy - size
        npoints = random.randint(12, 24)
        color = random_color()
        self.scheduler.create_triangle(name, x0, y0, x1, y1, x2, y2, npoints, color)
        return name

    def create_random_line(self, name=None):
        if name is None:
            name = self.next_shape_name()
        x0 = random.randint(20, 100) * SCALE
        y0 = random.randint(20, 100) * SCALE
        x1 = random.randint(150, 230) * SCALE
        y1 = random.randint(150, 230) * SCALE
        npoints = random.randint(20, 40)
        color = random_color()
        self.scheduler.create_line(name, x0, y0, x1, y1, npoints, color)
        return name

    def create_random_ellipse(self, name=None):
        if name is None:
            name = self.next_shape_name()
        cx = random.randint(60, 190) * SCALE
        cy = random.randint(60, 190) * SCALE
        w = random.randint(30, 80) * SCALE
        h = random.randint(15, 40) * SCALE
        npoints = random.randint(24, 48)
        color = random_color()
        self.scheduler.create_ellipse(name, cx, cy, w, h, npoints, color)
        return name

    def create_random_shape(self, fade_in=False):
        """Create a random shape with random effects."""
        creators = [
            self.create_random_circle,
            self.create_random_triangle,
            self.create_random_line,
            self.create_random_ellipse,
        ]
        creator = random.choice(creators)
        name = creator()

        # Apply random effects
        effects = self.random_effects()
        if fade_in:
            effects.insert(0, FadeIn(duration=random.uniform(0.3, 0.8)))
        for effect in effects:
            self.scheduler.add_effect(name, effect)

        return name

    def schedule_sequence(self, at, seq_id):
        """Schedule a batch of shapes to play starting at time `at`.

        Batches crossfade: a batch's shapes fade out near the end of their
        life while the next batch fades in, so there is never a gap with
        nothing on screen. Shapes that have started fading out are tracked
        in `retiring_shapes` and no longer count against `max_shapes`, which
        is what lets the incoming batch be created without waiting."""
        # Only fully-active shapes count towards the min/max targets; shapes
        # already retiring are about to leave and must not block new ones.
        active = len(self.active_shapes)

        shapes_needed = self.min_shapes - active
        if shapes_needed <= 0:
            shapes_needed = random.randint(0, 1)  # sometimes add a new one
        shapes_needed = min(shapes_needed, self.max_shapes - active)
        if shapes_needed < 0:
            shapes_needed = 0

        shape_names = []
        for _ in range(shapes_needed):
            name = self.create_random_shape(fade_in=True)
            shape_names.append(name)
            self.active_shapes.add(name)

        if not shape_names:
            # Nothing created this round (at max with nothing retiring);
            # re-check after a short delay so a spot can open up.
            def start_next(at_time=at + random.uniform(0.5, 1.5), seq=seq_id + 1):
                if self.running:
                    self.schedule_sequence(at_time, seq)
            self.scheduler.schedule(at + random.uniform(0.5, 1.5), start_next)
            return

        # This batch's life, ending in a fade-out so the outgoing and
        # incoming batches overlap.
        seq_duration = random.uniform(3.0, 8.0)
        fade_duration = random.uniform(0.5, 1.0)
        fade_out_start = at + seq_duration - fade_duration
        destroy_at = at + seq_duration

        # Start fading the batch out: mark it retiring (frees its max slots)
        # and attach a FadeOut so it eases to black over fade_duration.
        def retire_shapes(names=shape_names, at_time=fade_out_start):
            for name in names:
                self.active_shapes.discard(name)
                self.retiring_shapes.add(name)
                try:
                    self.scheduler.add_effect(name, FadeOut(duration=fade_duration))
                except Exception:
                    pass

        self.scheduler.schedule(fade_out_start, retire_shapes)

        # Destroy the shapes once fully faded out.
        def destroy_shapes(names=shape_names, at_time=destroy_at):
            for name in names:
                self.retiring_shapes.discard(name)
                try:
                    self.scheduler.destroy(name)
                except Exception:
                    pass

        self.scheduler.schedule(destroy_at, destroy_shapes)

        # Start the next batch as soon as this one begins to fade, so the
        # incoming shapes rise in brightness while the outgoing ones fall.
        # retire_shapes is scheduled first above, so at this timestamp the
        # retiring shapes already no longer count against max_shapes.
        def start_next(at_time=fade_out_start, seq=seq_id + 1):
            if self.running:
                self.schedule_sequence(at_time, seq)

        self.scheduler.schedule(fade_out_start, start_next)

    def start(self):
        """Start the show."""
        self.running = True
        print('Starting random show...')
        self.schedule_sequence(0.0, 0)

    def stop(self):
        """Stop the show."""
        self.running = False
        print('Stopping show...')


def main():
    speed, seed, effects_dir, min_shapes, max_shapes = parse_args()

    if seed is not None:
        random.seed(seed)

    # Validate effects directory
    if not os.path.isdir(effects_dir):
        print('Warning: effects directory %s does not exist' % effects_dir)
    print('Effects directory: %s' % effects_dir)

    # Load settings
    settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'settings.toml')
    settings = load_settings(settings_file)

    # Create display
    LD = LaserDisplay.create()
    apply_settings(LD, settings)

    # Create scheduler
    scheduler = Scheduler(LD, fps=25)

    # Create director and start show
    director = RandomShowDirector(scheduler, min_shapes=min_shapes, max_shapes=max_shapes)
    director.start()

    if speed == 0:
        print('Playing random laser show at max speed (press Ctrl+C to stop)')
    else:
        print('Playing random laser show at %.1fx speed (press Ctrl+C to stop)' % speed)

    # Run on the main thread so that pygame's SDL event loop works
    try:
        scheduler.run(speed=speed)
    except KeyboardInterrupt:
        pass
    finally:
        director.stop()
        scheduler.stop()
        LD.close()
        print('Show complete.')


if __name__ == '__main__':
    main()
