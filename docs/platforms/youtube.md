# YouTube: long-form and Shorts

Profiles `youtube` (16:9 long-form) and `shorts` (9:16). A square or vertical file of 3:00 or less is a Short;
anything wider than square is long-form at any length (official[^3min]). Choose before writing the script: opening,
pace, safe area, music and handover differ. Grades: official, reported, practice, unsure.

## The frame

- Long-form 1920×1080 (3840×2160 if the sources allow), Shorts 1080×1920; frame rate as the source (24–60); H.264
  High, AAC 48 kHz, MP4 with the moov atom first; 1080p SDR about 8 Mbps at ≤ 30 fps (official[^enc]).
- Length: 15:00 until the account is phone-verified, then 12 h; 256 GB (official[^long]). Unless told the account is
  verified, keep long-form ≤ 14:59. Shorts ≤ 3:00 (official[^3min]); the profile caps 15–180 s.
- Long-form: no organic overlay template exists (unsure); the profile keeps a 5 % margin, x 96–1824, y 54–1026.
  Controls, YouTube's CC box (bottom ~15 %) and the end screen (last 5–20 s[^end]) sit over it: captions above y 860.
- Shorts safe area x 60–880, y 288–1248, captions y 1048–1248: Google's vertical safe zone blocks the top 288 px
  (search, menu), the bottom 672 px (channel, subscribe, title, sound) and the right 192 px (buttons) (reported[^sz]).
  Whether tall phones crop the sides is unsure: on a 20:9 screen a filled 9:16 frame would lose ~97 px a side.
- Hand over: `meta.title` (≤ 100 characters), `meta.desc` (≤ 5 000 bytes, about 1 600 CJK characters; official[^api]),
  `meta.sources`; the srt (official[^cc]); `out/chapters.txt`; a thumbnail ≥ 1920×1080 under 2 MB (Shorts: the cover
  frame's time); a note with "AI use", `madeForKids`, end-screen start, mid-roll points, music and footage licences.

## The first seconds

- Shorts are tested on viewers who did not choose them; Studio reports "viewed vs. swiped away" (reported[^sherman]).
  Subject, conflict or payoff on screen and audible in frame 0; no logo, title card or greeting.
- Long-form is chosen from thumbnail and title, then judged on watch time and satisfaction surveys (official,
  2021[^recs]). The first 10–30 s confirm the title's promise in the same words or image, then deliver; new uploads
  reach strangers as well as subscribers (reported, 2026[^beaupre]), so no opening only fans follow.
- Shorts, carried over from one Douyin channel (practice[^own]; same swipe feed, not measured here): the
  first spoken line states the verdict, not a question; frame 0 shows the subject doing the thing, with one headline
  and no card; the payoff comes by about 15 s.

## Pace and length

- Shorts: 30–60 s by default. Past 60 s any Content ID claim blocks the Short worldwide (official[^3min]) and most
  Shorts-library songs cover only up to 90 s (reported[^lib]): go longer only with fully owned audio and footage.
- Long-form: mid-roll ads need ≥ 8:00; if monetised, aim 8–15 min and leave a pause (silence, transition) at each
  break, since YouTube flags mid-sentence slots (official[^mid]).
- Cut rate (practice): Shorts change the picture every 1–3 s, long-form explainers every 3–8 s with b-roll over the
  narration. Re-crop a clip rather than play it forward then backward (carried over from Douyin[^own]).
- "Image slideshows or scrolling text with minimal narrative" cannot be monetised, nor template-made films (official,
  2025-07-15[^ypp]): each film has its own script, argument and visuals; fast cuts over stills are not substance.

## Words on screen and captions

- Upload the srt with every video even when captions are burned in; CC draws inside the frame (official[^cc]).
- Shorts: burn captions in (muted viewing), two lines at most, 60–80 px, in y 1048–1248 (practice[^sz]).
- Long-form: on-screen text for labels, numbers, names and chapter cards, not the whole narration; nothing under
  ~40 px at 1080p, since phones are the main screen (practice, unsure).
- Chapters (first `00:00`, ≥ 3, each ≥ 10 s; official[^chap]) match the on-screen section cards.

## Sound

- 48 kHz (official[^enc]); YouTube normalises playback to an unpublished target: master −14 LUFS (practice).
- Music: any copyrighted track draws a Content ID claim (revenue taken or video blocked; a Short over 1:00 blocked
  worldwide; official[^3min]). Use the YouTube Audio Library, licence-free music with the project, or none.
- Your own cloned voice needs no disclosure; a synthetic voice that makes a real person seem to say something does
  (official[^ai]). A voice reading someone else's text without commentary is not monetisable (official[^ypp]).

## The ending, title, cover and tags

- Long-form: the end screen takes the last 5–20 s of a film ≥ 25 s, up to 4 elements (official[^end]): end the
  content just before, and keep those 20 s calm and clear of the element areas. A long sign-off costs watch time.
- Shorts loop: an ending that runs into frame 0 gains replays, counted as views since 2025-03 (reported[^views]);
  description links do not click, one related video can be set (reported[^links]).
- Title ≤ 100 characters (official[^api]), the subject in the first 60–70 (practice). Title and thumbnail describe
  what the film delivers: misleading ones are spam (official[^spam]); news clickbait is removed (reported[^clickbait]).
- Thumbnail 16:9, matching the content: Test & compare picks by watch-time share, not clicks (official[^ab]). Shorts
  custom covers are YPP-only (official[^thumb]): make an early frame a cover, subject plus ≤ 5 words.
- 1–3 hashtags in the description, never over 60 (official[^tags]); tags ≤ 500 characters matter little (practice).

## What gets a film limited

- **AI disclosure (official[^ai]).** Set "AI use" = Yes (API `containsSyntheticMedia`) when the film shows realistic
  generated or altered people, events or places, or AI music as the focus; not for animation, colour fixes, captions
  or your own cloned voice. YouTube also labels from C2PA metadata or its own detection; repeated failure to disclose
  leads to removal or loss of YPP. Disclosure alone does not reduce reach. Handover: "AI use" yes or no with the
  reason (which pictures, clips or voices are realistic and generated); keep the generators' C2PA metadata.
- **Mass-produced and reused content (official, 2025-07-15[^ypp]).** Template-looking or generic AI films, or others'
  footage without significant commentary, are not monetisable, even with permission; whole channels lose YPP, and
  about 16 channels were terminated in 2026-01 (reported[^slop]). No clip with another platform's watermark.
- **Generated people (practice).** A generated face never stands for a named real person; no flags, slogans, uniforms.
- **Medical:** no claims against health authorities (official[^med]). **Ads:** profanity in title or thumbnail, or
  gore in the first 7 s, means no ads (official[^ads]). **Finance:** only the scam rule was found (official[^spam]).

## What is not known

- The organic Shorts overlay and side crop (post an unlisted grid Short, screenshot it); the loudness target; Shorts
  ranking thresholds; whether chapters, cards and end screens work on Shorts.

## Sources

[^3min]: https://support.google.com/youtube/answer/15424877 (three-minute Shorts), read 2026-11-10; official.
[^enc]: https://support.google.com/youtube/answer/1722171 (recommended upload encoding), read 2026-11-10; official.
[^long]: https://support.google.com/youtube/answer/71673 (videos longer than 15 minutes), read 2026-11-10; official.
[^end]: https://support.google.com/youtube/answer/6388789 (end screens), read 2026-11-10; official.
[^sz]: https://socialync.io/tools/safe-zones/youtube-shorts (Google's vertical-ad safe zone, checked by them 2026-10-11); diagram at https://support.google.com/google-ads/answer/13547298 ; read 2026-11-10; reported.
[^api]: https://developers.google.com/youtube/v3/docs/videos (title, description, tags, containsSyntheticMedia), read 2026-11-10; official.
[^cc]: https://support.google.com/youtube/answer/2734698 (subtitle formats), read 2026-11-10; official.
[^sherman]: https://vidiq.com/blog/post/youtube-shorts-algorithm/ (updated 2026-10-09, quoting Todd Sherman); https://buffer.com Shorts analytics guide; read 2026-11-10; reported.
[^recs]: https://blog.youtube/inside-youtube/on-youtubes-recommendation-system/ (2021-09-15), read 2026-11-10; official.
[^beaupre]: https://ppc.land/subscribers-skip-90-of-uploads-in-their-feed-youtube-director-says/ (2026-09-01), read 2026-11-10; reported.
[^own]: Practice from one short-video channel made with reelsmith, reviewed in November 2026; its figures are not published.
[^lib]: Shorts audio help as quoted in search results ("up to 90 seconds in a 3 minute Short"), read 2026-11-10; reported.
[^mid]: https://support.google.com/youtube/answer/6175006 (mid-roll ads), read 2026-11-10; official.
[^ypp]: https://support.google.com/youtube/answer/1311392 (YPP policies, inauthentic and reused content, 2025-07-15), read 2026-11-10; official.
[^chap]: https://support.google.com/youtube/answer/9884579 (chapters), read 2026-11-10; official.
[^ai]: https://support.google.com/youtube/answer/14328491 (disclosing altered or synthetic content), read 2026-11-10; official.
[^views]: https://techcrunch.com/2025/03/26/youtube-is-changing-how-youtube-shorts-views-are-counted , read 2026-11-10; reported.
[^links]: https://www.tubefilter.com/2023/08/10/youtube-shorts-comments-spam/ , read 2026-11-10; reported.
[^spam]: https://support.google.com/youtube/answer/2801973 (spam, deceptive practices and scams), read 2026-11-10; official.
[^clickbait]: https://techcrunch.com/2024/12/18/youtube-says-it-will-start-cracking-down-on-videos-with-clickbait-titles-in-india , read 2026-11-10; reported.
[^ab]: https://support.google.com/youtube/answer/16391400 (Test & compare), read 2026-11-10; official.
[^thumb]: https://blog.youtube/news-and-events/youtube-studio-custom-thumbnail-updates/ (2026-07-24), read 2026-11-10; official.
[^tags]: https://support.google.com/youtube/answer/6390658 (hashtags), read 2026-11-10; official.
[^slop]: https://www.tubefilter.com/2026/01/29/youtube-ai-slop-channel-crackdown-bans/ , read 2026-11-10; reported.
[^med]: https://support.google.com/youtube/answer/13813322 (medical misinformation), read 2026-11-10; official.
[^ads]: https://support.google.com/youtube/answer/6162278 (advertiser-friendly guidelines), read 2026-11-10; official.
