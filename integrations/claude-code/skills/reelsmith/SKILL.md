---
name: reelsmith
description: Make or edit a video with reelsmith, a video editing harness the agent drives through MCP tools (an NLE timeline of tracks, clips, keyframes, text and components that reelsmith renders and checks), not a text-to-video model. Use when the user asks to cut, trim, edit, caption, subtitle, narrate, re-time or render a video, film, recording, talk, vlog, short, reel, explainer, slideshow or YouTube video, to turn their footage or pictures into one, or mentions reelsmith or a reelsmith project.json.
---

# reelsmith

reelsmith is a video editing app you operate with tools. You decide the cut, the story, the words and the
pictures; reelsmith keeps the timeline valid, renders it with Remotion, measures where words land on screen, masters
the loudness and refuses to deliver a broken film. Nothing is generated from one prompt: you build the film clip by
clip and look at it as you go. Any canvas (landscape by default, vertical, square or custom) and any language.

## Before you start

The reelsmith MCP server must be connected: its tools are `manual`, `notes`, `new_project`, `describe`, `edit`,
`undo`, `check`, `preview`, `render`, `review`, `library`, the footage tools `probe`, `frames`, `scenes`, `silences`
and `transcribe`, and the asset tools `import_asset`, `speak`, `capture`, `draw`, `animate` and `assets`. If they
are missing, tell the user to run `reelsmith setup <their agent>` and restart the agent. Every tool is also a shell
command (`reelsmith <tool> --help`) when no MCP client is attached.

## The loop

1. `manual` once. It is the full contract: the project format, the Time grammar, every edit op, the components and
   what blocks delivery. This skill is only the map; when they disagree, the manual wins.
2. `notes(project)`: what worked in this workspace before.
3. `new_project(project, profile?, locale?, title?)` makes the folder holding `project.json` (inside the workspace's
   `projects/` when there is one). The profile sets the canvas, fps, safe area and any length limits (default
   `landscape` 1920×1080; `vertical`, `square`, `youtube`, `tiktok`, `shorts`...); the locale (BCP-47, default `en`)
   is the film's language.
4. Bring in the material the user asked for:
   - **Their footage**: `import_asset` it, then look before you cut: `probe` (length, size, sound), `frames` (stills
     at source seconds with a contact sheet), `scenes` (shot cuts), `silences` (quiet ranges), `transcribe` (every
     word with its time). Cut at source times, `"src:<clip>@<seconds>"`, with `ripple_delete` and `trim_clip`; join
     shots with a `transition`; captions follow the speech with a captions track whose `source` is `"clip:<id>"`.
   - **A film from a script**: write `script.md` (sources, angle, lines), `speak` the lines, `capture` a web page as
     evidence, `draw` a picture, `animate` a picture into a short clip, `import_asset` music or pictures.
5. `edit(project, ops)` in batches: a batch applies whole or not at all, and `undo` reverts it. `describe` shows
   the timeline as text; `library` lists the components.
6. `check`, then `preview` the key moments and read the PNG stills. Fix what you see, repeat.
   `preview(sweep=true)` measures the whole film's layout as `render` will.
7. `render`, then `review` the delivered frames, then `note` what you learned.

## Rules that save a render

- Every tool takes `project` = the folder holding `project.json`. Tools never raise: an error result says what to
  fix, with clip ids and times.
- Anchor times on what they follow, so the cut holds when something moves: `"src:a@41.2"` (a moment of a
  recording), `"line:3"` (the narration), `"clip:c2.end-0.5"`, `"mark:punch"`, `"end-2"`. Clips on one track must
  not overlap (except a transition's overlap); layer with more tracks.
- Look at the stills before you render; your picture of the frame is not the frame.
- Words stay inside the profile's safe area and above its minimum size; `render` refuses text outside it, a mostly
  black film, and whatever the profile itself forbids (no sound, frozen stretches, a length outside its limits).
- `speak`, `animate` and `transcribe` cost money and `draw` spends limited tries: each estimates first and refuses
  over the budget. Transcribe a recording once; re-speak only the lines that changed.
- `build/`, `out/` and `.history/` belong to reelsmith. `project.json` may be edited by hand (every tool validates
  it), but `edit` is atomic and undoable.
- Do what the user asked for (their footage, their length, their language); decide the rest yourself and write
  the reasons in `script.md`.
