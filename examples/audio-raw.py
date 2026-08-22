#!/usr/bin/env python3

DEVICE = 'alsa_output.pci-0000_00_1b.0.analog-stereo.monitor'

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import struct
import LaserDisplay

Gst.init(None)

def open_pipeline():
    # pulsesrc monitors the system audio output on Linux; on other systems
    # fall back to the platform default audio source (e.g. microphone)
    for source in ('pulsesrc device=%s' % DEVICE, 'autoaudiosrc'):
        try:
            pipeline = Gst.parse_launch(
                '%s ! audio/x-raw,format=S16LE,layout=interleaved ! '
                'appsink name=sink emit-signals=true' % source)
            if pipeline.set_state(Gst.State.PLAYING) != Gst.StateChangeReturn.FAILURE:
                return pipeline
            pipeline.set_state(Gst.State.NULL)
        except Exception:
            pass
    raise IOError('Could not open an audio source')

pipeline = open_pipeline()
sink = pipeline.get_by_name('sink')

LD = LaserDisplay.create()

LD.set_zoom(0.1)
LD.set_scan_rate(10000)

def setcolor(v):
    if abs(v-128) < 20:
        LD.set_color(LD.GREEN)
    elif abs(v-128) < 40:
        LD.set_color(LD.YELLOW)
    else:
        LD.set_color(LD.RED)

try:
    while True:
        try:
            sample = sink.emit('pull-sample')
        except Exception:
            print('err')
            break
        if sample is None:
            break
        ok, info = sample.get_buffer().map(Gst.MapFlags.READ)
        if not ok:
            continue
        raw = struct.unpack(str(len(info.data)//2)+'h', info.data[:len(info.data)//2*2])
        rawlen = len(raw)

        setcolor(128+raw[0]//128)
        LD.draw_point(0, 128+raw[0]//128, 0x03 )
        for i in range(1,255):
            setcolor(128+raw[int(rawlen/256.0*i)]//128)
            LD.draw_point(i, 128+raw[int(rawlen/256.0*i)]//128, 0x00 )
        setcolor(128+raw[rawlen-1]//128)
        LD.draw_point(255, 128+raw[rawlen-1]//128, 0x02 )
        LD.show_frame()
except KeyboardInterrupt:
    pass
finally:
    pipeline.set_state(Gst.State.NULL)
    LD.close()
