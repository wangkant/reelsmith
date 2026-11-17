# A film in layered photographs

A workspace with one project, `projects/balloon`: a 12-second vertical film on why a hot-air balloon rises, made
from four generated photographs that move as layers ([docs/kit.md](../../docs/kit.md), "Photograph components").
Render it with

```sh
reelsmith render examples/layers/projects/balloon
```

## Layout

| track | clips |
|---|---|
| `world` | `Balloon`, the whole film, reading every line |
| `head` | the take, "Why does a balloon rise?", 0 to 2.4 s |
| `cap` | captions from the voice |

`Balloon` is one `Lens` (hand-held drift, a warm grade that grows while the burner roars, a kick with a colour
fringe when it lights) around three scenes joined without a cut:

1. **The valley** (line 1, `balloon/valley.tsx`): the valley plate with its near treetops traced as a front; the
   balloon cut-out stands behind them, lit and hazed to sit in the morning light, and lifts a little on "lighter";
   warm air bends the sky above its crown (`Refract`); mist drifts (`Haze`), light falls through the air (`Rays`),
   pollen floats in front (`Motes`) and the meadow sways. The camera pushes in from the first frame.
2. **Inside** (line 2, `balloon/inside.tsx`): a `Join` pushes through the envelope into the view up from the
   basket. On "burner" the flame cut-out flares from the coil, its light falls on the fabric, the air above it
   shimmers, and on "heats" the envelope swells (`Warp`).
3. **The rise** (line 3): a whip pan back out to the valley; the balloon travels up out of the treetops
   (`Travel`: perspective scale, shade that lifts as it climbs), its basket coming clear of the trees.

Points traced on the pictures are in `balloon/trace.ts`; files in a subfolder are not registered as components.

## How it was made

- Four pictures from the Codex image provider (`draw`), then resized and saved as WebP: two plates
  (`valley.webp`, `inside.webp`, 1024 x 1536) and two cut-outs whose prompts ended with "Isolated object on a fully
  transparent background (PNG with alpha channel): no ground, no shadow, no background at all." (`balloon.webp`,
  `flame.webp`, trimmed to their alpha).
- `voice/voice.json` was written by hand with plausible line timings, and `voice/voice.m4a` is 12 s of silence
  (`ffmpeg -f lavfi -i anullsrc=r=48000:cl=mono -t 12 -c:a aac -b:a 24k voice.m4a`), so the example needs no
  provider. With `speak` the lines get a real voice and real timings, and every cue follows.
- `build/` and `out/` are not part of the example.
