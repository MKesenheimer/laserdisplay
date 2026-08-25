#!/usr/bin/env python3
"""
Patch the-greatest-show-on-earth.xml:
1. Reorder: shapes first, then events sorted ascending by time
2. Add mirror effect to star shapes
3. Fill blank gaps (>100ms) with animations
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom

tree = ET.parse('lasershows/the-greatest-show-on-earth.xml')
root = tree.getroot()
duration = float(root.get('duration', '1441'))

# =============================================================================
# STEP 1: Add mirror effect to star shapes
# =============================================================================
for event in root.findall('event'):
    for action in list(event):  # list() to allow modification
        if action.tag == 'create' and action.get('shape') in ('star1', 'star2', 'star3'):
            # Insert mirror effect right after the create
            mirror = ET.Element('effect')
            mirror.set('shape', action.get('shape'))
            mirror.set('type', 'mirror')
            mirror.set('axis', 'vertical')
            # Find position of this action and insert after
            idx = list(event).index(action)
            event.insert(idx + 1, mirror)

print("Added mirror effect to star shapes")

# =============================================================================
# STEP 2: Reorder XML - shapes first, then events sorted by time
# =============================================================================

# Extract all elements
shapes = []
events = []

for child in list(root):
    if child.tag == 'shape':
        shapes.append(child)
    elif child.tag == 'event':
        events.append(child)

# Sort events by time
events.sort(key=lambda e: float(e.get('at')))

# Clear root and rebuild
root.clear()
root.set('fps', '25')
root.set('duration', str(duration))

# Add shapes first
for shape in shapes:
    root.append(shape)

# Then sorted events
for event in events:
    root.append(event)

print(f"Reordered: {len(shapes)} shapes + {len(events)} events")

# =============================================================================
# STEP 3: Find blank gaps and fill them
# =============================================================================

# Recompute active shapes with sorted events to find gaps
active = set()
# Also track the last known "section" context for appropriate filler content
gaps_blank = []
last_time = 0.0

# First pass: find all gaps
for event in root.findall('event'):
    t = float(event.get('at'))
    if not active and t - last_time > 0.1:
        gaps_blank.append((last_time, t, t - last_time))
    for action in event:
        if action.tag == 'create':
            active.add(action.get('shape'))
        elif action.tag == 'destroy':
            active.discard(action.get('shape'))
    last_time = t

if active:
    gaps_blank.append((last_time, duration, duration - last_time))

# Filter to gaps > 100ms
gaps_to_fill = [(t0, t1, dt) for t0, t1, dt in gaps_blank if dt > 0.1]

print(f"\nGaps to fill (>100ms): {len(gaps_to_fill)}")
for t0, t1, dt in gaps_to_fill:
    print(f"  {t0:.1f}s -> {t1:.1f}s ({dt*1000:.0f}ms)")

# =============================================================================
# Define filler animations for gaps
# =============================================================================

# Strategy:
# - Early intro (0-87s): gentle stars wandering (already exists, skip)
# - Build-up gaps: small accents, faint stage warp
# - Verse gaps: breathing circles, gentle rotating shapes
# - Chorus gaps: moving circles, pinwheels
# - Climax gaps: high energy effects
# - Late ballad: sparse stars, gentle halos
# - Finale gaps: dramatic effects

filler_shapes = []
filler_events = []

def make_shape_xml(name, attrs):
    return ET.fromstring(f'<shape name="{name}" {attrs}/>')

def make_event_xml(at, actions):
    event = ET.Element('event')
    event.set('at', str(at))
    for action in ET.fromstring(f'<root>{actions}</root>'):
        event.append(action)
    return event

# Fill each gap with appropriate content based on position in show
for gap_start, gap_end, gap_duration in gaps_to_fill:
    t_mid = (gap_start + gap_end) / 2.0
    ratio = t_mid / duration  # 0.0 to 1.0

    # Determine section energy based on position
    if gap_duration < 0.5:
        continue  # Skip very small gaps

    # Define fillers by section
    if ratio < 0.06:
        # Very early (intro): sparse twinkling
        filler_events.append(make_event_xml(gap_start, f'''
            <create shape="star1"/>
            <effect shape="star1" type="blink" period="{gap_duration*0.8:.1f}" duty="0.3"/>
            <create shape="star2"/>
            <effect shape="star2" type="blink" period="{gap_duration*1.2:.1f}" duty="0.3"/>
            <create shape="star3"/>
            <effect shape="star3" type="blink" period="{gap_duration*1.0:.1f}" duty="0.25"/>
        '''))
        filler_events.append(make_event_xml(gap_end, '''
            <destroy shape="star1"/>
            <destroy shape="star2"/>
            <destroy shape="star3"/>
        '''))

    elif ratio < 0.12:
        # Pre-slam: subtle halos
        filler_events.append(make_event_xml(gap_start, f'''
            <create shape="halo_starblue"/>
            <effect shape="halo_starblue" type="scale" min="0.95" max="1.05" frequency="{1.0/gap_duration:.2f}"/>
            <create shape="spot_starblue"/>
            <effect shape="spot_starblue" type="scale" min="0.92" max="1.08" frequency="{1.2/gap_duration:.2f}"/>
        '''))
        filler_events.append(make_event_xml(gap_end, '''
            <destroy shape="halo_starblue"/>
            <destroy shape="spot_starblue"/>
        '''))

    elif ratio < 0.25:
        # First verses: gentle rotating star, breathing circle
        if gap_duration > 1.0:
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="rotating_star"/>
                <effect shape="rotating_star" type="rotation" speed="60"/>
                <effect shape="rotating_star" type="scale" min="0.9" max="1.1" frequency="{1.0/gap_duration:.2f}"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="rotating_star"/>
            '''))

    elif ratio < 0.45:
        # Warm sections: pinwheels, moving circles
        if gap_duration > 2.0:
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="pinwheel_A"/>
                <effect shape="pinwheel_A" type="rotation" speed="80"/>
                <create shape="pinwheel_B"/>
                <effect shape="pinwheel_B" type="rotation" speed="-80"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="pinwheel_A"/>
                <destroy shape="pinwheel_B"/>
            '''))
        elif gap_duration > 0.5:
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="breath_circle"/>
                <effect shape="breath_circle" type="scale" min="0.85" max="1.15" frequency="{1.5/gap_duration:.2f}"/>
                <effect shape="breath_circle" type="rainbow" cycles="1" speed="0.1"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="breath_circle"/>
            '''))

    elif ratio < 0.65:
        # Big bright body: energetic effects
        if gap_duration > 2.0:
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="move_circ_red"/>
                <effect shape="move_circ_red" type="translate_by_path" path="path_circ_1" velocity="70" phase="0"/>
                <create shape="move_circ_green"/>
                <effect shape="move_circ_green" type="translate_by_path" path="path_circ_1" velocity="70" phase="0.33"/>
                <create shape="move_circ_blue"/>
                <effect shape="move_circ_blue" type="translate_by_path" path="path_circ_1" velocity="70" phase="0.66"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="move_circ_red"/>
                <destroy shape="move_circ_green"/>
                <destroy shape="move_circ_blue"/>
            '''))
        elif gap_duration > 0.5:
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="breath_circle"/>
                <effect shape="breath_circle" type="scale" min="0.8" max="1.2" frequency="{2.0/gap_duration:.2f}"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="breath_circle"/>
            '''))

    elif ratio < 0.85:
        # Second verse: geometric objects, sine waves
        if gap_duration > 3.0:
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="geo_triangle"/>
                <effect shape="geo_triangle" type="translate_by_path" path="path_geo_3" velocity="35" closed="1"/>
                <create shape="geo_square"/>
                <effect shape="geo_square" type="translate_by_path" path="path_geo_3" velocity="35" closed="1" phase="0.25"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="geo_triangle"/>
                <destroy shape="geo_square"/>
            '''))
        elif gap_duration > 1.0:
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="sine_wave"/>
                <effect shape="sine_wave" type="rainbow" cycles="2" speed="0.1"/>
                <effect shape="sine_wave" type="translation" ax="3" fx="0.02"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="sine_wave"/>
            '''))
        else:
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="accent_1"/>
                <effect shape="accent_1" type="blink" period="{gap_duration*0.8:.1f}" duty="0.15"/>
                <create shape="accent_3"/>
                <effect shape="accent_3" type="blink" period="{gap_duration*1.0:.1f}" duty="0.15"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="accent_1"/>
                <destroy shape="accent_3"/>
            '''))

    elif ratio < 1.0:
        # Late sections: quieter, sparse
        if ratio > 0.93:
            # Near finale: dramatic effects
            if gap_duration > 3.0:
                filler_events.append(make_event_xml(gap_start, f'''
                    <create shape="breath_circle"/>
                    <effect shape="breath_circle" type="scale" min="0.7" max="1.3" frequency="{1.5/gap_duration:.2f}"/>
                    <effect shape="breath_circle" type="rainbow" cycles="2" speed="0.12"/>
                '''))
                filler_events.append(make_event_xml(gap_end, '''
                    <destroy shape="breath_circle"/>
                '''))
            else:
                filler_events.append(make_event_xml(gap_start, f'''
                    <create shape="rotating_star"/>
                    <effect shape="rotating_star" type="rotation" speed="120"/>
                '''))
                filler_events.append(make_event_xml(gap_end, '''
                    <destroy shape="rotating_star"/>
                '''))
        elif ratio > 0.85:
            # Second long ballad: gentle halos, stars
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="halo_starblue"/>
                <effect shape="halo_starblue" type="scale" min="0.93" max="1.07" frequency="{0.5/gap_duration:.2f}"/>
                <create shape="star1"/>
                <effect shape="star1" type="blink" period="{gap_duration*1.5:.1f}" duty="0.3"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="halo_starblue"/>
                <destroy shape="star1"/>
            '''))
        else:
            # Middle-late: sine waves
            filler_events.append(make_event_xml(gap_start, f'''
                <create shape="sine_wave"/>
                <effect shape="sine_wave" type="rainbow" cycles="1" speed="0.08"/>
            '''))
            filler_events.append(make_event_xml(gap_end, '''
                <destroy shape="sine_wave"/>
            '''))

# Merge existing events and filler events by time (proper sorted merge)
existing_events = list(root.findall('event'))
all_events = []

# Group by time: time -> [events]
time_groups = {}
for e in existing_events:
    t = float(e.get('at'))
    time_groups.setdefault(t, []).append(e)
for e in filler_events:
    t = float(e.get('at'))
    time_groups.setdefault(t, []).append(e)

# Sort by time and extend
for t in sorted(time_groups.keys()):
    all_events.extend(time_groups[t])

# Replace events in root
# Remove old event children, add merged events
for child in list(root):
    if child.tag == 'event':
        root.remove(child)

for event in all_events:
    root.append(event)

print(f"Filled {len(gaps_to_fill)} gaps with {len(filler_events)//2} fill blocks")

# =============================================================================
# Write the file
# =============================================================================

# Pretty print
xml_str = ET.tostring(root, encoding='unicode')
parsed = minidom.parseString(xml_str)
pretty = parsed.toprettyxml(indent='    ', encoding=None)

# Clean up extra blank lines
lines = [line for line in pretty.split('\n') if line.strip()]
pretty = '\n'.join(lines)

with open('lasershows/the-greatest-show-on-earth.xml', 'w') as f:
    f.write(pretty)

print("\nFile written successfully!")
print(f"Shapes: {len(shapes)}")
print(f"Events: {len(events)} + {len(filler_events)//2} fillers = {len(events) + len(filler_events)//2}")
print(f"Gaps filled: {len(gaps_to_fill)}")
