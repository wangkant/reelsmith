# A performance film

A workspace with one project, `projects/salt`: a 13-second vertical film on why the sea is salty, made in code with
the stage kit ([docs/kit.md](../../docs/kit.md), "Stage kit"). Render it with

```sh
reelsmith render examples/performance/projects/salt
```

## Layout

| track | clips |
|---|---|
| `ground` | `SaltGround`, 0 to the end: kraft paper over a wooden table, warm light, a slow drift |
| `scenes` | `SaltRiver` (`line:1`), `SaltSun` (`line:2`), `SaltGlass` (`line:3` to the end) |
| `head` | the take, "Why is the sea salty?", 0 to 2.3 s |
| `cap` | captions from the voice in the performance style |

`SaltRiver` and `SaltSun` are drawn objects: a river inked down the page carries salt grains into the sea, the sun
lifts the sea into a cloud and leaves a pile of salt. `SaltGlass` is a cut-out: a torn photo of a glass of seawater,
the water line marked, a label, a loupe on the salt and a tag with the number. Every move is timed with
`useCues().T` to a word of the line the scene plays under. `library/components/salt/parts.tsx` holds the pieces
two scenes share; files in a subfolder are not registered as components.

## How it was made

- `voice/voice.json` was written by hand with plausible line timings, and `voice/voice.m4a` is 13.2 s of silence
  made with `ffmpeg -f lavfi -i anullsrc=r=48000:cl=mono -t 13.2 -c:a aac -b:a 24k voice.m4a`, so the example needs
  no provider. With `speak` the lines get a real voice and real timings, and every cue follows.
- `assets/glass.jpg` (232 × 338) is cut from a frame of `docs/media/sea.webp`. Its outline was read off an
  `AssetGrid` preview of the picture.
- `build/` and `out/` are not part of the example.
