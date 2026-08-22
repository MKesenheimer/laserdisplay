#!/usr/bin/env python3

import http.server
import urllib.parse
import threading
import queue
import time

q = queue.Queue()

class MyHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if 'content-length' in self.headers:
            length= int( self.headers['content-length'] )
            content = self.rfile.read(length)
            svg = urllib.parse.unquote_plus(content[4:].decode('utf-8'))
            q.put(svg)
        self.send_response(200)
        self.end_headers()

server_address = ('', 8000)
httpd = http.server.HTTPServer(server_address, MyHandler)
MyHandler.q = q

print('listening on 8000 ...')

def laser_loop(q):
    import LaserDisplay
    from LaserDisplay.SvgProcessor import SvgProcessor

    LD = LaserDisplay.create()

    LD.set_scan_rate(10000)
    LD.set_zoom(0.1)
    LD.set_blanking_delay(0)

    sp = SvgProcessor(LD)
    svg = None

    try:
        while True:
            if not q.empty():
                svg = q.get()
            if not svg is None:
                sp.parseString(svg, 255.0/595.0)
                LD.show_frame()
                time.sleep(1.0/25.0)
    except KeyboardInterrupt:
        pass
    finally:
        LD.close()

# the laser output (pygame window) must live on the main thread; only the
# plain-python HTTP server runs in a worker thread
threading.Thread(target=httpd.serve_forever, daemon=True).start()
laser_loop(q)
