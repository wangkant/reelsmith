# Instagram Reels

Profile `reels`. A full-screen 9:16 feed shown first mostly to people who do not follow the account; a Reel is judged
on watch time, likes and sends. Grades: official, reported, practice, unsure.

## The frame

- 1080×1920, 30 fps (23–60 accepted), H.264 or HEVC in MP4 with the moov atom first, closed GOP, 4:2:0, ≤ 25 Mbps;
  AAC ≤ 48 kHz (official[^graph]). Through the API: 3 s to 15 min, ≤ 300 MB (official[^graph]); in the app 3 min
  (reported, 2025-01[^three]). The profile: 3–180 s, target 15–60 s, 300 MB.
- Safe area x 66–950, y 270–1248, captions y 1048–1248: Meta keeps the top 14 % and the bottom 35 % free and 6 % at the
  sides (official, ads guide[^ads]). The action column right of x 880 reaches up to about y 1040 (practice[^krumzi]):
  keep anything that must be read in x 120–880, and keep caption lines short enough to end left of x 880.
- Cover: a frame (`thumb_offset`) or a 9:16 JPEG ≤ 8 MB (official[^graph]); the profile grid crops it to 3:4 from the
  middle, 1080×1440 (reported, 2025-01[^three]): the cover's words sit inside y 270–1248 to survive both.
- Hand over: `meta.title` as the opening line, `meta.desc` (≤ 2 200 characters, ≤ 20 @mentions, ≤ 5 hashtags;
  official[^graph] and reported[^tags]), `meta.sources`; a 1080×1920 cover JPEG; a note with the AI disclosure (yes
  or no and why), music source and licence or none, and whether C2PA metadata is present. Instagram takes no subtitle
  file (unsure); render a separate clean master, never a file exported from TikTok.

## The first seconds

- Watch time, likes and sends matter most; sends weigh slightly more with non-followers, likes with followers
  (reported, Mosseri 2025-01[^mosseri]). The first 2 s give a stranger a reason to watch and to send it on.
- Show or say the payoff in the first 1–2 s with the hook line on screen: many start Reels muted (practice). Spoken and
  written lines agree.
- Carried over from one Douyin channel (same swipe feed; practice, not measured on Instagram[^own]): the first
  spoken line states the verdict, not a question; frame 0 shows the subject doing the thing, with one headline and no
  card; captions do not repeat the headline while it is up.

## Pace and length

- Stay at or under 3 min: longer Reels are not recommended to new audiences (reported, help centre[^three]). Data
  tools put the strongest median views at 30–90 s (practice).
- Change the picture every 1.5–3 s in the first 10 s; nothing static longer than about 4 s (practice). Re-crop a clip
  rather than play it forward then backward (carried over from Douyin[^own]).
- The payoff by about 15 s (carried over: on the Douyin channel most viewers left within the first seconds[^own]).

## Words on screen and captions

- Burn captions in: two lines at most, 56–72 px with an outline or plate, in the captions band (practice).
  Instagram's auto-captions are an overlay the uploader turns on (unsure).
- Text above y 270 meets the "Reels" header; text right of x 880 below y 1040 meets the buttons (practice[^krumzi]).
- Instagram has named videos "largely covered by text", borders around the video and blurry or low-resolution video
  as reasons a Reel is shown less (reported, 2021[^creators]): the hook, the captions and at most one label at a time;
  never letterbox a 16:9 clip with bars, crop or reframe it.
- Big text carries the claim, not the narration's sentence; cards fill their box (carried over from Douyin[^own]).

## Sound

- Music in the file is the Reel's own audio; unlicensed commercial music can be muted or blocked (practice). Business
  accounts get a reduced library, chiefly Meta's Sound Collection (reported[^music]). Use licensed music or none.
- Music chosen in the app lays over the file's audio: deliver a clean mix and a voice-only stem (practice).
- A synthetic voice that imitates a real person is realistic audio and needs the AI disclosure (official[^label]).
  Master −14 LUFS (practice; no target published).

## The ending, title, cover and tags

- End on the last point and stop; no outro card, no "follow for more" over 1 s: unfinished views cost watch time
  (reported[^mosseri]).
- The ask that matters is a send: end on a line someone would forward to one person (reported[^mosseri]). No
  engagement bait.
- Caption text: the subject's searchable words first; at most 5 hashtags since 2025-12, and hashtags do not raise
  reach (reported[^tags]).
- Cover: a 1080×1920 JPEG whose title sits in y 270–1248, so the 3:4 grid crop keeps it (official[^graph],
  reported[^three]). Reels has no series feature; number parts only when part 1 exists (practice).

## What gets a film limited

- **AI disclosure (official, 2024-02[^label]).** Posting "a photorealistic video or realistic-sounding audio" that was
  digitally created or altered needs the AI disclosure at upload, with penalties for failing to. Meta also labels
  "AI info" from C2PA or IPTC indicators (official, 2024[^info]). The API has no field for it (unsure): the uploader
  switches it on. Handover: AI yes or no, what was generated (realistic people, scenes, voices), C2PA present or not.
- **Generated people (practice).** A generated face never stands for a named real person; no flags, slogans or
  uniforms in generated pictures.
- **Unoriginal content.** Visible logos or watermarks from other apps make a Reel less recommended (reported, 2021
  [^creators]); accounts posting unoriginal content 10+ times in 30 days stop being recommended (reported, 2024), and
  from 2026-04-30 accounts mostly reposting others' work are not recommended to non-followers; watermark removal or a
  minor crop is not a transformation (reported[^orig]). Supplied footage is transformed: commentary, re-edit, narration.
- **Finance, health, news.** Exaggerated health claims, get-rich-quick content and misinformation are not
  recommended (reported; Recommendations Guidelines[^recs]). Show sources for every number; no promised returns or
  cures.

## What is not known

- Whether a given account's in-app maximum is 3 or 20 min; whether Instagram takes subtitle files; the organic overlay
  (post a private grid Reel and screenshot it); retention thresholds (none published).

## Sources

[^graph]: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media (codec, size, length, caption, cover), read 2026-11-10; official.
[^three]: Engadget and Business Today (2025-01-20/21) on 3-minute Reels and the 3:4 grid; https://creatorflow.so/blog/how-long-can-instagram-reels-be (2026-10-30, quoting help.instagram.com/2720958398006062); read 2026-11-10; reported.
[^ads]: https://www.facebook.com/business/ads-guide/update/video/instagram-reels (safe zone: top 14 %, bottom 35 %, sides 6 %), read 2026-11-10; official (ads).
[^krumzi]: https://krumzi.com/tools/safe-zone-checker/instagram-reels (organic margins, checked by them 2026-11-02), read 2026-11-10; practice.
[^tags]: Social Media Today and Business Today (2025-12-19) on the 5-hashtag limit, read 2026-11-10; reported.
[^mosseri]: https://www.socialmediatoday.com/news/instagram-shares-algorithm-insights-2025/738034 (2025-01-22), read 2026-11-10; reported.
[^own]: Practice from one short-video channel made with reelsmith, reviewed in November 2026; its figures are not published.
[^creators]: Tubefilter (2021-02-10) quoting @creators, read 2026-11-10; reported.
[^music]: Soundstripe and Slipstream music guides on business-account libraries, read 2026-11-10; reported.
[^label]: https://about.fb.com/news/2024/02/labeling-ai-generated-images-on-facebook-instagram-and-threads (2024-02-06), read 2026-11-10; official.
[^info]: https://about.fb.com/news/2024/04/metas-approach-to-labeling-ai-generated-content-and-manipulated-media (updated 2024-09-12), read 2026-11-10; official.
[^orig]: Engadget (2024-04-30); Tubefilter and PetaPixel (2026-04-30) on unoriginal-content rules, read 2026-11-10; reported.
[^recs]: https://help.instagram.com/313829416281232 (Recommendations Guidelines; page not readable by fetch on 2026-11-10, content as reported), read 2026-11-10; reported.
