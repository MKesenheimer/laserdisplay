#!/usr/bin/env python3

DEVICE = 'alsa_output.pci-0000_00_1b.0.analog-stereo.monitor'

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import struct
import numpy.fft
import LaserDisplay

Gst.init(None)

pipeline = Gst.parse_launch('pulsesrc device=%s ! audio/x-raw,format=S16LE,layout=interleaved ! appsink name=sink emit-signals=true' % DEVICE)
sink = pipeline.get_by_name('sink')
pipeline.set_state(Gst.State.PLAYING)

LD = LaserDisplay.create()

def setcolor(v):
    if v < 60:
        LD.set_color(LD.GREEN)
    elif v < 120:
        LD.set_color(LD.YELLOW)
    else:
        LD.set_color(LD.RED)

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
    data = info.data[:len(info.data)//2*2]
    raw = struct.unpack(str(len(data)//2)+'h', data)
    raw = numpy.log( numpy.abs(numpy.fft.fft(raw))**2 )

    idx = 0
    for i in range(0, 16):
        val = 0
        steps = int(round((1.20**i)*4))
        for _ in range(steps):
            val += raw[idx]
            idx += 1
        try:
            val = int( 1.5*numpy.exp(val/steps/6) )
        except Exception:
            val = 1
        setcolor(val)
        LD.draw_rect(i*16+3, 255-val, 10, val)

    LD.show_frame()
