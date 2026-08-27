#!/usr/bin/env python3

# Plays the animation timeline from shapes.xml with the Scheduler class.
#
# usage: python lasershow-player.py [--fast] [--start-at TIME] TIMELINE.xml [MUSIC.wav|mp3|ogg|flac]
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


USAGE = 'Usage: lasershow-player.py [--fast] [--start-at TIME] TIMELINE.xml [MUSIC.file]'


def main():
    fast = '--fast' in sys.argv
    if fast:
        sys.argv.remove('--fast')

    start = 0.0
    if '--start-at' in sys.argv:
        index = sys.argv.index('--start-at')
        if index + 1 >= len(sys.argv):
            print(USAGE)
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
        print(USAGE)
        sys.exit(1)

    LD = LaserDisplay.create()
    LD.set_zoom(0.3)
    LD.set_scan_rate(7000)
    LD.set_blanking_delay(1)

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
