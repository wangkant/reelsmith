---
name: reelsmith
description: Make or edit a video with reelsmith, a video editor the agent drives through MCP tools (an NLE timeline of tracks, clips, keyframes, text and components that reelsmith renders and checks), not a text-to-video model. Use when the user asks to create, cut, edit, caption, narrate, re-time or render a video, film, short, reel, explainer, slideshow or YouTube video, to turn their footage or pictures into one, or mentions reelsmith or a reelsmith project.json.
---

# reelsmith

reelsmith is a video editing app you operate with tools. You decide the story, the script, the voice, the
pictures and the cut; reelsmith keeps the timeline valid, times it to the narration, renders it with Remotion,
measures where words land on screen, masters the loudness and refuses to deliver a broken film. Nothing is
generated from one prompt: you build the film clip by clip and look at it as you go.

## Before you start

The reelsmith MCP server must be connected: its tools are `manual`, `notes`, `new_project`, `describe`, `edit`,
`undo`, `check`, `preview`, `render`, `review`, `library`, `speak`, `capture`, `draw`, `animate`, `import_asset`,
`assets` and others. If they are missing, tell the user to run `reelsmith setup <their agent>` and restart the
agent. Every tool is also a shell command (`reelsmith <tool> --help`) when no MCP client is attached.

## The loop

1. `manual` once. It is the full contract: the project format, the Time grammar, every edit op, the components and
   what blocks delivery. This skill is only the map; when they disagree, the manual wins.
2. `notes(project)`: what worked in this workspace before.
3. `new_project(project, profile?, title?)` makes the folder holding `project.json` (inside the workspace's
   `projects/` when there is one). The profile sets the canvas, fps, safe area and length limits.
4. Write `script.md` in the project (sources, angle, lines). Gather assets: `speak` narrates lines,
   `import_asset` brings in the user's own footage, music or pictures (a path or a URL), `capture` screenshots a
   web page as evidence, `draw` makes a picture, `animate` turns a picture into a short clip.
5. `edit(project, ops)` in batches: a batch applies whole or not at all, and `undo` reverts it. `describe` shows
   the timeline as text; `library` lists the components.
6. `check`, then `preview` the key moments and read the PNG stills. Fix what you see, repeat.
   `preview(sweep=true)` measures the whole film's layout as `render` will.
7. `render`, then `review` the delivered frames, then `note` what you learned.

## Rules that save a render

- Every tool takes `project` = the folder holding `project.json`. Tools never raise: an error result says what to
  fix, with clip ids and times.
- Anchor times on the narration (`"line:3"`, `"clip:c2.end-0.5"`, `"end-2"`) so the cut follows the voice when it
  is re-recorded. Clips on one track must not overlap; layer with more tracks.
- Look at the stills before you render; your picture of the frame is not the frame.
- Words stay inside the profile's safe area and above its minimum size; `render` refuses text outside it, black or
  frozen stretches and films outside the length limits.
- `speak`, `draw` and `animate` may cost money: they estimate first and refuse over the budget. Change only the
  lines or pictures that need it.
- `build/`, `out/` and `.history/` belong to reelsmith. `project.json` may be edited by hand (every tool validates
  it), but `edit` is atomic and undoable.
- Do what the user asked for (their footage, their length, their language); decide the rest yourself and write
  the reasons in `script.md`.
