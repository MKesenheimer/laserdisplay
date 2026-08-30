You are creating a laser show for the song `Shed my Skin` from `Within Temptation` in an XML file format. The song is heavy with deep and heavy guitars, loud drum set, but a melodic and clear vocal.

The laser show software reads in an XML file, where events synchronously are defined to the music. Don't use tools, like python programs to generate the XML files. Use the XML files `./lasershows/example.xml` and `./lasershows/example-sequences.xml` as a reference. You can also reference effects from other files, for example from `./lasershows/effects`. These references are called sequences. It is possible to add additional effects to referenced effects/sequences. Read `./lasershows/XML_FORMAT.md` to learn more about the output XML format.

Events can be:
- create: creating shapes in different colors
- move: moving shapes
- rotate: rotating shapes
- scale: scaling shapes
- destroy: destroying shapes
- color_shift: shifting colors of shapes continously
- blink: switching the shape periodically on and off, optionally blanking every n-th point
- delete_point: deleting and adding points to shapes
- morph: morphing one shape to another
- multi_color: coloring consecutive parts of a shape in different colors
- rainbow: adding a rainbow color to a shape
- warp: warping a shape with a travelling sine wave
- move_points: moving individual points of shapes
- translate_by_path: moving shapes along predefined paths (which are also of type shapes)

Shapes can be:
- circles
- ellipses
- lines
- triangles
- tetragons
- other self generated shapes

Your tasks:
- Read in `./lasershows/shed-my-skin/shed-my-skin.json`. This is the file that lists the beats at specific timestamps. See below for the segments of the song at specific timestamps.
- Create an XML file `./lasershows/shed-my-skin/shed-my-skin.xml` that fits nicely to the song. Don't use more than four shapes at once, but also don't generate blank screens.
- Use slow moving and broad shapes for slower and quieter parts of the song, use fast moving and sharp shapes for faster and louder parts of the song.
- Add more dynamics to the events if the song is loud and fast. Less dynamics for slower and quieter parts.
- Use fading effects when transitioning to slower and quieter parts of the song.
- Make use of symmetry whenever it fits. Mirror accents left and right.
- Finally, use repeating patterns throughout the song for the user to easily recognize parts of the show.
- Make excessive use of the effects `translate_by_path`, `translate_to` and `rotate_by` to move the shapes around. Move them faster for faster and louder parts of the song.
- Add variations to the verse and chorus in later parts of the song.
- In general, add different shapes and effects and switch between them frequently during the song. A pattern or theme should only ever last a few seconds long. Everything longer than that is considered boring.
- After you built the base of the show, focus on accents. Observe the song closely and recognize every beat. Add objects that flash on every beat, or on every second beat. Mirror the objects to be horizontally symmetrical.
- Add fast moving accents, like fast moving lines - that fits to the beats of the song.
- The lasershow must strictly follow the timestamps defined in `./lasershows/shed-my-skin/shed-my-skin.json` and defined by the segments below. If the song proceeds to another part (for example from verse to chorus), the patterns of the lasershow must change at the exact time stamp.
- Be creative.


Segments of the song `Shed my Skin`:
    +00.00:    0.00 -   13.26: Chorus 1: violine melody and vocal; wavy patterns and circles; color-theme ice-blue and orange
    +10.16:   13.26 -  23.54: Middle 1: sharp objects moving around; color-theme red and orange
    +10.28:   23.54 -  33.79: Verse 1: song gets a little quieter; round patterns; color-theme ice-blue and orange
    +10.25:   33.79 -  44.10: Verse 2: same as before; color-theme ice-blue and orange
    +10.31:   44.10 -  54.26: Bridge 1: song builds up; more shapes; color-theme green and magenta
    +10.16:   54.26 -  64.70: Bridge 2: same as before
    +10.44:   64.70 -  85.10: Middle 2: cool-down; color-theme ice-blue and orange
    +20.40:   85.10 -  95.42: Chorus 2: crescendo; sharp objects moving around; color-theme red and orange
    +10.32:   95.42 - 105.66: Chorus 3: same as before
    +10.24:  105.66 - 115.94: Middle 3: cool-down; color-theme ice-blue and orange
    +10.28:  115.94 - 126.30: Verse 3: round patterns; color-theme ice-blue and orange
    +10.36:  126.30 - 136.54: Verse 4: same as before
    +10.24:  136.54 - 146.70: Bridge 3: song builds up; more shapes; color-theme green and magenta
    +10.16:  146.70 - 157.10: Bridge 4: same as before
    +10.40:  157.10 - 162.10: Middle 4: cool-down; color-theme ice-blue and orange
    +05.00:  162.10 - 172.42: Chorus 4: crescendo; sharp objects moving around; color-theme red and orange
    +10.32:  172.42 - 182.70: Chorus 5: same as before
    +10.28:  182.70 - 203.22: Loud: very heavy and "evil" middle part; flickering objects; color-theme red and white
    +20.52:  203.22 - 223.70: Middle 5: cool-down; color-theme ice-blue and orange
    +20.48:  223.70 - 234.06: Chorus 6: crescendo; sharp objects moving around; color-theme red and orange
    +10.36:  234.06 - 244.62: Chorus 7: same as before
    +10.56:  244.62 - end: Outro: heavy; color-theme red and white; fade-out to the end.