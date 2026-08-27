#!/usr/bin/env python3
# A stopwatch for songs.
#
# The clock starts when you press the first key.  From then on, press a key
# whenever a new section of the song starts; the program records the
# timestamp of every key press.  Press enter (or q) when the song ends and
# the program prints a table of all sections:
#
#     +20.84:   0.00 -  20.84: Start
#     +27.06:  20.84 -  47.90: Intro
#     +34.44:  47.90 -  82.34: Verse
#     +13.38:  82.34 -  95.72: Chorus
#     +14.49:  95.72 - 110.21: Verse 2
#     +109.69: 110.21 -    end: Chorus 2
#
# The first column is the length of the section, the second column its start
# and end time.  All times are seconds with 10 ms resolution.
#
# usage: python3 tools/song-stopwatch.py
#
# keys:
#   i  intro         v  verse        c  chorus       o  outro
#   b  bridge        m  middle       s  silent       l  loud
#   enter / q        stop the clock and print the table
#   backspace        remove the most recent mark

import curses
import time

TICK = 0.01           # clock resolution: 10 ms
START_EPSILON = 0.05  # if the first mark is within this time, the song and
                      # the clock started together -> no "Start" section

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


# ---------- output ---------------------------------------------------------

def number_repeats(labels):
    """Verse, Verse, Verse -> Verse, Verse 2, Verse 3"""
    counts = {}
    result = []
    for base in labels:
        n = counts.get(base, 0) + 1
        counts[base] = n
        result.append(base if n == 1 else '%s %d' % (base, n))
    return result


def format_table(marks, stop_time):
    """marks: [(time, section), ...] -> the section table as a string."""
    if not marks:
        return '    (no sections marked)'
    labels = number_repeats([label for _, label in marks])
    events = [(t, lab) for (t, _), lab in zip(marks, labels)]
    if events[0][0] > START_EPSILON:
        events = [(0.0, 'Start')] + events
    lines = []
    for i, (start, label) in enumerate(events):
        end = events[i + 1][0] if i + 1 < len(events) else stop_time
        end_text = '%6.2f' % end if i + 1 < len(events) else 'end'
        lines.append('    +%05.2f:  %6.2f - %s: %s'
                     % (end - start, start, end_text, label))
    return '\n'.join(lines)


# ---------- terminal ui ----------------------------------------------------

def put(stdscr, y, x, text, attr=0):
    """addstr that never raises when the text does not fit."""
    if y < 0 or not text:
        return
    h, w = stdscr.getmaxyx()
    text = text[:max(0, w - x)]
    if not text or y >= h:
        return
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


def draw_legend(stdscr, y):
    put(stdscr, y, 2, '[i]ntro   [v]erse   [c]horus   [o]utro')
    put(stdscr, y + 1, 2, '[b]ridge  [m]iddle  [s]ilent   [l]oud')
    put(stdscr, y + 2, 2, '[enter/q] stop        [backspace] undo last mark')


def format_clock(t):
    minutes = int(t // 60)
    return '%8.2f  (%02d:%05.2f)' % (t, minutes, t - minutes * 60)


def draw_ready(stdscr):
    stdscr.erase()
    h, _ = stdscr.getmaxyx()
    put(stdscr, 1, 2, 'Song Stopwatch', curses.A_BOLD)
    put(stdscr, 3, 2, 'Press any key to start the clock.')
    draw_legend(stdscr, max(6, h - 5))
    stdscr.refresh()


def draw_live(stdscr, elapsed, marks):
    stdscr.erase()
    h, _ = stdscr.getmaxyx()
    put(stdscr, 0, 2, format_clock(elapsed), curses.A_BOLD)
    if marks:
        t, label = marks[-1]
        put(stdscr, 1, 2, 'current: %s (since %6.2f)' % (label, t),
            curses.A_DIM)
    top = max(0, len(marks) - (h - 7))
    for i in range(top, len(marks)):
        t, label = marks[i]
        y = 3 + (i - top)
        put(stdscr, y, 4, '%6.2f' % t, curses.A_DIM)
        put(stdscr, y, 14, label)
    draw_legend(stdscr, h - 4)
    stdscr.refresh()


# ---------- input ----------------------------------------------------------

def is_stop(key):
    return key in (10, 13, curses.KEY_ENTER) or key == ord('q')


def is_backspace(key):
    return key in (8, 127, curses.KEY_BACKSPACE)


def section_of(key):
    if 32 <= key < 127:
        return SECTION_KEYS.get(chr(key).lower())
    return None


def run(stdscr):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.nodelay(True)
    stdscr.keypad(True)

    # any key starts the clock
    key = -1
    while key == -1:
        draw_ready(stdscr)
        key = stdscr.getch()
        if key == -1:
            time.sleep(TICK)

    start = time.perf_counter()
    marks = []
    label = section_of(key)
    if label:
        marks.append((0.0, label))

    while True:
        elapsed = time.perf_counter() - start
        draw_live(stdscr, elapsed, marks)
        key = stdscr.getch()
        if key == -1:
            time.sleep(TICK)
            continue
        if is_stop(key):
            return marks, time.perf_counter() - start
        if is_backspace(key):
            if marks:
                marks.pop()
            continue
        label = section_of(key)
        if label:
            marks.append((time.perf_counter() - start, label))


def main():
    marks, stop_time = curses.wrapper(run)
    print()
    print(format_table(marks, stop_time))
    print()
    print('Total: %6.2f s' % stop_time)


if __name__ == '__main__':
    main()
