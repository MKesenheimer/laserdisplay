#!/usr/bin/env python3

# Plays the animation timeline from shapes.xml with the Scheduler class.
#
# usage: python lasershow-player.py [--fast] TIMELINE.xml [MUSIC.wav|mp3|ogg|flac]
#
# --fast   Run in validation mode: no real-time pacing, no audio.
#          Runs through the full timeline as fast as possible to check
#          the XML file for correctness.
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


def play_audio(path):
    """Start playing an audio file; returns the pipeline for later cleanup."""
    Gst.init(None)
    uri = Gst.filename_to_uri(os.path.abspath(path))
    pipeline = Gst.parse_launch('playbin uri="%s"' % uri)
    pipeline.set_state(Gst.State.PLAYING)
    return pipeline


def main():
    fast = '--fast' in sys.argv
    if fast:
        sys.argv.remove('--fast')

    if len(sys.argv) < 2:
        print('Usage: lasershow-player.py [--fast] TIMELINE.xml [MUSIC.file]')
        sys.exit(1)

    LD = LaserDisplay.create()
    LD.set_zoom(0.3)
    LD.set_scan_rate(5000)
    LD.set_blanking_delay(1)

    scheduler = Scheduler(LD, fps=25)
    scheduler.load_xml(sys.argv[1])

    # In fast/validate mode: no audio, run through timeline quickly
    audio_pipeline = None
    if not fast and len(sys.argv) > 2:
        try:
            audio_pipeline = play_audio(sys.argv[2])
        except Exception as e:
            print('Could not start audio playback (%s), running visuals only' % e)

    if fast:
        print('Validating %s (fast-forward mode, no audio)...' % sys.argv[1])
    else:
        print('Playing %s' % sys.argv[1])

    try:
        scheduler.run(speed=0 if fast else 1)
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
