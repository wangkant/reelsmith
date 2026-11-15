# A performance film

A workspace with one project, `projects/salt`: a 13-second vertical film on why the sea is salty, made in code with
the stage kit ([docs/kit.md](../../docs/kit.md), "Stage kit"). Render it with

```sh
reelsmith render examples/performance/projects/salt
```

## Layout

| track | clips |
|---|---|
| `world` | `SaltShore`, 0 to `line:3`; `SaltDesk`, `line:3` to the end |
| `head` | the take, "Why is the sea salty?", 0 to 2.3 s |
| `cap` | captions from the voice in the performance style |

`SaltShore` is one world for two lines on an `Outdoors` set, four camera stops along it: salt crystals drop off a
rock into a river, trail each other down it to the sea, a sign drops in and swings; the sun rises, steam lifts
into a cloud, the shoreline retreats over a crust of salt and a heap of salt drops onto it. `SaltDesk` plays the
last line on a `Desk` set: a torn photo of a glass of seawater is taped down, a heap of salt drops into a dish and
squashes, and a tag with the number swings in. Every object is a path or a few shapes inside `Solid`; every move
is timed with `useCues().T` to a word. `library/components/salt/shore.tsx` holds the shore's pieces; files in a
subfolder are not registered as components.

## How it was made

- `voice/voice.json` was written by hand with plausible line timings, and `voice/voice.m4a` is 13.2 s of silence
  made with `ffmpeg -f lavfi -i anullsrc=r=48000:cl=mono -t 13.2 -c:a aac -b:a 24k voice.m4a`, so the example needs
  no provider. With `speak` the lines get a real voice and real timings, and every cue follows.
- `assets/glass.jpg` (232 × 338) is cut from a frame of `docs/media/sea.webp`. Its outline was read off an
  `AssetGrid` preview of the picture.
- `build/` and `out/` are not part of the example.
