import sys
import time
import pygame
from .LaserDisplay import LaserDisplay

START_EPSILON = 0.05  # if the first mark is within this time of the clock
                      # start, no "Start" section is inserted


def number_repeats(labels):
    """Verse, Verse, Verse -> Verse, Verse 2, Verse 3"""
    counts = {}
    result = []
    for base in labels:
        n = counts.get(base, 0) + 1
        counts[base] = n
        result.append(base if n == 1 else '%s %d' % (base, n))
    return result


class LaserDisplaySimulator(LaserDisplay):

    SCALE = 2
    TIMESTAMP_TICK = 0.01   # 10 ms

    # keys that mark a section of the song; pressing one of them builds up
    # a section timeline on the console, like tools/song-stopwatch.py
    SECTION_KEYS = {
        'i': 'Intro',
        'v': 'Verse',
        'c': 'Chorus',
        'o': 'Outro',
        'b': 'Bridge',
        'm': 'Middle',
        's': 'Silent',
        'l': 'Loud',
    }

    # shown in the lower part of the window
    LEGEND = (
        '[i]ntro   [v]erse   [c]horus   [o]utro',
        '[b]ridge  [m]iddle  [s]ilent   [l]oud',
        '[mouse button] mark the time',
    )

    def __init__(self):
        LaserDisplay.__init__(self)
        try:
            pygame.init()
            self.surface = pygame.display.set_mode((self.SIZE*self.SCALE, self.SIZE*self.SCALE))
            self.surface.fill( (0,0,0) )
            pygame.display.set_caption('Laser Display Simulator')
            self._timestamp_font = pygame.font.Font(None, 20)
            self._timestamp_start = time.perf_counter()
            self._clock_start = 0.0
            self._marks = []
            self._open_prev = 0.0
            self._open_start = 0.0
            self._open_label = 'Start'
            self._timeline_open = False
        except:
            raise IOError('Could not initialize pygame')

    def __timestamp_ticks(self):
        # elapsed time in 10 ms steps
        return int((time.perf_counter() - self._timestamp_start) / self.TIMESTAMP_TICK)

    def __timestamp_text(self):
        # elapsed time, formatted as M:SS.cc
        minutes, rest = divmod(self.__timestamp_ticks(), 6000)
        seconds, centis = divmod(rest, 100)
        return '%d:%02d.%02d' % (minutes, seconds, centis)

    def __timestamp_seconds(self):
        # elapsed time as total seconds with 10 ms decimals
        return '%d.%02d' % divmod(self.__timestamp_ticks(), 100)

    def __print_timeline_line(self, line, replace=False):
        # prints a timeline line; with replace, the open line is rewritten
        # in place instead of a new line being printed (terminal only)
        if replace and sys.stdout.isatty():
            sys.stdout.write('\033[A\033[2K')
            sys.stdout.flush()
        print(line)

    def __open_line(self):
        # a section that just started; its end time is still unknown
        return '    +%05.2f:  %6.2f -' % (self._open_start - self._open_prev,
                                          self._open_start)

    def __open_timeline(self):
        # opens the section that starts with the clock, when the show starts
        if self._timeline_open:
            return
        self._timeline_open = True
        self._open_prev = self._open_start = self._clock_start
        self._open_label = 'Start'
        self.__print_timeline_line(self.__open_line())

    def __mark(self, t, label):
        # completes the open section at t and opens a new one with `label`
        numbered = number_repeats([l for _, l in self._marks] + [label])[-1]
        if not self._marks and t - self._clock_start <= START_EPSILON:
            # the first section starts with the song, no "Start" section
            self._open_label = numbered
            self._marks.append((self._open_start, numbered))
            return
        self.__print_timeline_line(
            '    +%05.2f:  %6.2f - %6.2f: %s'
            % (self._open_start - self._open_prev, self._open_start,
               t, self._open_label), replace=True)
        self._open_prev, self._open_start = self._open_start, t
        self._open_label = numbered
        self._marks.append((t, numbered))
        self.__print_timeline_line(self.__open_line())

    def close(self):
        # completes the open section with the end of the show
        if self._timeline_open:
            self.__print_timeline_line(
                '    +%05.2f:  %6.2f - end: %s'
                % (self._open_start - self._open_prev, self._open_start,
                   self._open_label), replace=True)

    def __process_events(self):
        # marks the sections for key presses and mouse buttons
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                label = self.SECTION_KEYS.get(pygame.key.name(event.key))
                if label is None:
                    continue
            elif event.type == pygame.MOUSEBUTTONDOWN:
                label = 'Mark'
            else:
                continue
            self.__mark(self.__timestamp_ticks()/100.0, label)

    def set_time_offset(self, offset):
        # the counter reads `offset` + time since this call
        self._timestamp_start = time.perf_counter() - offset
        self._clock_start = offset

    def __color(self):
        return pygame.Color(self.color['R'], self.color['G'], self.color['B'])

    def set_laser_configuration(self):
        pass

    def __draw_legend(self):
        # the key descriptions in the lower part of the window
        height = self._timestamp_font.get_height()
        for i, line in enumerate(self.LEGEND):
            stamp = self._timestamp_font.render(line, True, (128,128,128))
            y = self.surface.get_height() - height*(len(self.LEGEND)-i) - 4
            self.surface.blit(stamp, (4, y))

    def flush_frame(self):
        self.__open_timeline()
        self.__process_events()
        stamp = self._timestamp_font.render(self.__timestamp_text(), True, (128,128,128))
        self.surface.blit(stamp, (4,4))
        stamp = self._timestamp_font.render(self.__timestamp_seconds(), True, (128,128,128))
        self.surface.blit(stamp, (4,4 + stamp.get_height()))
        self.__draw_legend()
        pygame.display.flip()
        self.surface.fill( (0,0,0) )

    def draw_point(self, x, y, flags = 0x01):
        x,y = self.apply_context_transforms(x,y)
        x,y = self._output_transform(x,y)
        x,y = map(lambda a: a*self.SCALE, (x,y) )
        pygame.draw.rect(self.surface, self.__color(), pygame.Rect(x,y,self.SCALE,self.SCALE), 1)

    def draw_line(self, x1, y1, x2, y2):
        x1,y1 = self.apply_context_transforms(x1,y1)
        x2,y2 = self.apply_context_transforms(x2,y2)
        x1,y1 = self._output_transform(x1,y1)
        x2,y2 = self._output_transform(x2,y2)
        x1,y1,x2,y2 = map(lambda a: a*self.SCALE, (x1,y1,x2,y2) )
        pygame.draw.line(self.surface, self.__color(), (x1,y1), (x2,y2), self.SCALE)

    def draw_rect(self, x, y, w, h):
        x1,y1 = self._output_transform(x, y)
        x2,y2 = self._output_transform(x+w, y+h)
        x1,y1,x2,y2 = map(lambda a: a*self.SCALE, (x1,y1,x2,y2) )
        pygame.draw.rect(self.surface, self.__color(), pygame.Rect(x1,y1,x2-x1,y2-y1), self.SCALE)

    def draw_ellipse(self, cx, cy, rx, ry):
        if rx < 1 or ry < 1:
            return
        cx,cy = self._output_transform(cx, cy)
        rx *= self.zoom
        ry *= self.zoom
        cx,cy,rx,ry = map(lambda a: a*self.SCALE, (cx,cy,rx,ry) )
        pygame.draw.ellipse(self.surface, self.__color(), pygame.Rect(cx-rx,cy-ry,2*rx,2*ry), self.SCALE)

    def draw_polyline(self, points):
        points = [tuple(a*self.SCALE for a in self._output_transform(*p)) for p in points]
        pygame.draw.lines(self.surface, self.__color(), False, points, self.SCALE)

    def draw_quadratic_bezier(self, points, steps):
        if len(points) < 3:
            print('Quadratic Bezier curves have to have at least three points')
            return

        step_inc = 1.0/(steps)

        old_pos = tuple(a*self.SCALE for a in self._output_transform(points[0][0], points[0][1]))

        for i in range(0, len(points) - 2, 2):
            t = 0.0
            t_1 = 1.0
            for s in range(steps):
                t += step_inc
                t_1 = 1.0 - t
                px = t_1 * (t_1 * points[i]  [0] + t * points[i+1][0]) + \
                     t   * (t_1 * points[i+1][0] + t * points[i+2][0])
                py = t_1 * (t_1 * points[i]  [1] + t * points[i+1][1]) + \
                     t   * (t_1 * points[i+1][1] + t * points[i+2][1])
                pos = tuple(a*self.SCALE for a in self._output_transform(px, py))
                pygame.draw.line(self.surface, self.__color(), old_pos, pos, self.SCALE)
                old_pos = pos

    def draw_cubic_bezier(self, points, steps):
        if len(points) < 4:
            print('Cubic Bezier curves have to have at least four points')
            return

        step_inc = 1.0/(steps)

        old_pos = tuple(a*self.SCALE for a in self._output_transform(points[0][0], points[0][1]))

        for i in range(0, len(points) - 3, 2):
            t = 0.0
            t_1 = 1.0
            for s in range(steps):
                t += step_inc
                t_1 = 1.0 - t
                px = (t_1 * (t_1 * (t_1 * points[i][0] + t * points[i+1][0]) +
                             t   * (t_1 * points[i+1][0] + t * points[i+2][0])) +
                      t   * (t_1 * (t_1 * points[i+1][0] + t * points[i+2][0]) +
                             t   * (t_1 * points[i+2][0] + t * points[i+3][0])))
                py = (t_1 * (t_1 * (t_1 * points[i][1] + t * points[i+1][1]) +
                             t   * (t_1 * points[i+1][1] + t * points[i+2][1])) +
                      t   * (t_1 * (t_1 * points[i+1][1] + t * points[i+2][1]) +
                             t   * (t_1 * points[i+2][1] + t * points[i+3][1])))
                pos = tuple(a*self.SCALE for a in self._output_transform(px, py))
                pygame.draw.line(self.surface, self.__color(), old_pos, pos, self.SCALE)
                old_pos = pos
