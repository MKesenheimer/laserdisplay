You are creating a laser show for the song "Mother Earth" from "Within Temptation" in an XML file format. The laser show software reads in an XML file, where events synchronously are defined to the music. Don't use tools, like python programs to generate the XML files. Use the XML files `./lasershows/example.xml` and `./lasershows/example-sequences.xml` as a reference. You can also reference effects from other files, for example from `./lasershows/effects`. These references are called sequences. It is possible to add additional effects to referenced effects/sequences. Read `./lasershows/XML_FORMAT.md` to learn more about the output XML format.

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
- Decide on a color scheme early on. Keep this color scheme throughout the complete show.
- Read in `/lasershows/mother-earth/mother-earth.json`. This is the file that describes the beats at specific timestamps.
- Create an XML file `./lasershows/mother-earth/mother-earth.xml` that fits nicely to the song. Don't use more than four shapes at once, but also don't generate blank screens.
- Use slow moving and broad shapes for slower and quieter parts of the song, use fast moving and sharp shapes for faster and louder parts of the song.
- Add more dynamics to the events if the song is loud and fast. Less dynamics for slower and quieter parts.
- Use fading effects when transitioning to slower and quieter parts of the song.
- Make use of symmetry whenever it fits. Mirror accents left and right.
- Finally, use repeating patterns throughout the song for the user to easily recognize parts of the show.
- Make excessive use of the effect translate_by_path to move the shapes around. Move it faster for faster and louder parts of the song.
- Add variations to the verse and chorus in later parts of the song.
- In general, add many different shapes and effects and switch between them frequently during the song. A pattern or theme should only ever last a few seconds long. Everything longer than that is considered boring.
- After you built the base of the show, focus on accents. Observe the song closely and recognize every beat. Add objects that flash on every beat, or on every second beat. Mirror the objects to be horizontally symmetrical.
- Add fast moving accents, like fast moving lines - that fits to the beats of the song.
- The lasershow must strictly follow the timestamps defined in `/lasershows/mother-earth/mother-earth.json` and the timeline below. If the song proceeds to another part (for example from verse to chorus), the patterns of the lasershow must change at the exact time stamp.
- Be creative.

The timeline of the show is given below:

```
    +00.00:   0.00 -  20.84: Spheric
    +20.84:  20.84 -  47.90: Intro, instrumental
    +27.06:  47.90 -  82.34: Build-up, instrumental
    +34.44:  82.34 -  95.72: Cool-down, instrumental
    +13.38:  95.72 - 110.21: Verse 1, voice and loud instruments, driving
    +14.49: 110.21 - 123.25: Verse 2, voice and loud instruments, driving, added push
    +13.04: 123.25 - 150,64: Chorus, voice and loud instruments, driving, heavy
    +27.39: 150,64 - 164,37: Verse 3, voice and loud instruments, driving
    +13.73: 164,37 - 178,97: Verse 4, voice and loud instruments, driving, added push
    +14.60: 178,97 - 205,49: Chorus, voice and loud instruments, driving, heavy
    +26.52: 205,49 - 219,90: Cool-down, instrumental
    +14.41: 219,90 - 279,19: Choir, spheric, silent
    +59.29: 279,19 - 306,73: Build-up, instrumental
    +27.54: 306,73 - 328,52: Chorus, voice and loud instruments, driving, heavy
    +21.79: 328,52 - 342,54: Crescendo, added push
    +14.02: 342,54 - 349,56: Outro, climax, very heavy
    +07.02: 349,56 - end: fade out
```