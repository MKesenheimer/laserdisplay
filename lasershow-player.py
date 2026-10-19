#!/usr/bin/env python3

# Plays the animation timeline from shapes.xml with the Scheduler class.
#
# usage: python lasershow-player.py [--fast] [--start-at TIME] [--settings FILE]
#                                     TIMELINE.xml [MUSIC.wav|mp3|ogg|flac]
#
# --fast   Run in validation mode: no real-time pacing, no audio.
#          Runs through the full timeline as fast as possible to check
#          the XML file for correctness.
#
# --start-at TIME
#          Start at TIME instead of at the beginning, seeking into the show
#          like in a video player: shapes created before TIME are already on
#          screen with their effects already progressed, and the music (if
#          given) is seeked to the same position.  TIME is seconds or
#          M:SS[.d] (e.g. 90 or 1:30.5).
#
# --settings FILE
#          Read the laser system settings (per-device zoom, mirroring,
#          x-y swap, scan rate, blanking delay) from FILE instead of the
#          default settings.toml in the script's directory; see that file
#          for the format.
#
# If a music file is given (without --fast), its playback is started at the
# same moment as the animation, so all events in the timeline stay in sync
# with the music (both are paced by the wall clock).
#
# While it is running, events can be injected from other threads, for example:
#
#   scheduler.create_circle('ping', 128*255, 128*255, 30*255, 32)
#   scheduler.add_effect('ping', Rotation(speed=180))
#   scheduler.destroy('ping')

import os
import sys
import tomllib

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

import LaserDisplay
from LaserDisplay import Scheduler


def play_audio(path, start=0.0):
    """Start playing an audio file, optionally seeking to `start` seconds
    first; returns the pipeline for later cleanup."""
    Gst.init(None)
    uri = Gst.filename_to_uri(os.path.abspath(path))
    pipeline = Gst.parse_launch('playbin uri="%s"' % uri)
    pipeline.set_state(Gst.State.PLAYING)
    if start > 0:
        # wait until the pipeline is actually playing so the seek is not
        # lost, then jump to the start position
        pipeline.get_state(5 * Gst.SECOND)
        seek = Gst.Event.new_seek(1.0, Gst.Format.TIME, Gst.SeekFlags.FLUSH,
                                  Gst.SeekType.SET, int(start * Gst.SECOND),
                                  Gst.SeekType.NONE, 0)
        pipeline.send_event(seek)
    return pipeline


def parse_time(spec):
    """parses a time given in seconds ('90.5') or as M:SS[.d] ('1:30.5')"""
    try:
        if ':' in spec:
            minutes, seconds = spec.split(':', 1)
            return float(minutes) * 60 + float(seconds)
        return float(spec)
    except ValueError:
        raise ValueError("'%s' is not a valid time (use seconds or M:SS[.d])" % spec)

def usage():
    print('Usage: lasershow-player.py [--fast] [--start-at TIME] [--settings FILE] TIMELINE.xml [MUSIC.file]')

# Built-in laser system settings, used when no settings file is found;
# same structure and values as the shipped settings.toml.
DEFAULT_SETTINGS = {
    'global': {'zoom': 0.1, 'mirror_x': 0, 'mirror_y': 0,
               'scan_rate': 7000, 'blanking_delay': 1},
    'device 2': {'zoom': 0.05, 'mirror_x': 1, 'swap_xy': 1,
                 'blanking_delay': 10},
}


def load_settings(path):
    """reads the laser system settings from a TOML file; a missing file
    falls back to DEFAULT_SETTINGS, a malformed file aborts the player"""
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
    """applies the laser system settings: [global] to the display as a
    whole, then each [device N] section to device N (1 = first device) —
    only backends that expose one renderer per device (LaserDisplayLumax)
    support the per-device sections"""
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
        if any(name.startswith('device ') for name in settings):
            print('Warning: the backend has no per-device renderers, '
                  'ignoring the [device N] settings')
        return
    # in device order, so the last per-device blanking delay wins (the
    # lumax driver only supports one system-wide delay)
    for name in sorted(n for n in settings if n.startswith('device ')):
        dev = int(name.split()[1])
        if not 1 <= dev <= len(renderers):
            print('Warning: %s does not exist (%d device(s)), ignoring'
                  % (name, len(renderers)))
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
            r.lmx.set_blanking_delay(d['blanking_delay']) # TODO: make this individual per device


def main():
    fast = '--fast' in sys.argv
    if fast:
        sys.argv.remove('--fast')

    start = 0.0
    if '--start-at' in sys.argv:
        index = sys.argv.index('--start-at')
        if index + 1 >= len(sys.argv):
            usage()
            sys.exit(1)
        try:
            start = parse_time(sys.argv[index + 1])
        except ValueError as e:
            print(e)
            sys.exit(1)
        if start < 0:
            print('start time must not be negative')
            sys.exit(1)
        del sys.argv[index:index + 2]

    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    # laser system settings: default settings.toml next to this script,
    # overridable with --settings FILE
    settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'settings.toml')
    if '--settings' in sys.argv:
        index = sys.argv.index('--settings')
        if index + 1 >= len(sys.argv):
            usage()
            sys.exit(1)
        settings_file = sys.argv[index + 1]
        del sys.argv[index:index + 2]

    LD = LaserDisplay.create()
    LD.set_time_offset(start)
    apply_settings(LD, load_settings(settings_file))

    scheduler = Scheduler(LD, fps=25)
    scheduler.load_xml(sys.argv[1])

    if start > 0 and scheduler.duration is not None and start >= scheduler.duration:
        print('Warning: start time %.3g s is at or beyond the show duration (%.3g s)'
              % (start, scheduler.duration))

    # In fast/validate mode: no audio, run through timeline quickly
    audio_pipeline = None
    if not fast and len(sys.argv) > 2:
        try:
            audio_pipeline = play_audio(sys.argv[2], start)
        except Exception as e:
            print('Could not start audio playback (%s), running visuals only' % e)

    if fast:
        print('Validating %s (fast-forward mode, no audio)...' % sys.argv[1])
    elif start > 0:
        print('Playing %s, starting at %.3g s' % (sys.argv[1], start))
    else:
        print('Playing %s' % sys.argv[1])

    try:
        scheduler.run(speed=0 if fast else 1, start=start)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()

        if audio_pipeline is not None:
            audio_pipeline.set_state(Gst.State.NULL)

        LD.close()

        if fast:
            print('Validation complete.')


if __name__ == '__main__':
    main()
