# Notes

My own notes for this workspace: read at the start of work (`notes`), added to as I learn (`note`).
Keep each entry one or two lines, dated, with the project it came from. Move an entry when it stops being true.

## What works

- (yyyy-mm-dd, project) What I did, what it did for the film, when to do it again.
- (starter) Open on the evidence itself (the captured headline) with the question over it; the first frame is
  also the cover.
- (starter) One number per beat: a CountUp or a Receipt row lands on the word that says it
  (`"at": "line:6+0.4"`), not before.

## What flopped

- (yyyy-mm-dd, project) What I tried, what happened (retention, a comment, what I was told), what I do instead.

## House style

- Grounds: paper for explaining, night for the turn and the verdict. Text on a photo gets a plate
  (`style.bg`) or `style.stroke`; a component on a photo gets `"ground": "dark"` in its props.
- Colours: accent only for the one number that matters in a shot; gold for highlights; bad for deductions.
- Type: `display` (Smiley Sans) for headlines and verdicts, `sans` for numbers, body and captions; nothing under 40 px.
- Motion: every shot moves within its first half second; nothing holds still for more than 5 s.

## My components

- `PriceTag` (library/components): a swinging price tag, old price struck through at `strike_at`. Use for a
  changed price; give it a box at least 600 x 500 so its small lines stay over 40 px.
