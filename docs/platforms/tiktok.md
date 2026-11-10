# TikTok

Profile `tiktok`. A full-screen 9:16 feed the viewer swipes at will; the film is judged in its first seconds and by
whether people finish it and pass it on. Grades: official, reported, practice, unsure.

## The frame

- 1080×1920, 30 fps (23–60 accepted), H.264 in MP4 (official[^api]). Publishing runs to 3 min for everyone, 5 or 10
  min for some accounts; ≤ 4 GB through the API (official[^api]). The profile: 15–180 s, 250 MB.
- Safe area x 120–880, y 240–1460, captions y 1260–1460. TikTok's own In-Feed template keeps 120 px at the sides and
  240 px at the top (reported, read from TikTok's file[^tpl]); organic posts carry the caption and @name from about
  y 1440 and the button column right of x 880 from about y 780 (practice[^krumzi]). Tall phones crop the sides.
- Cover: frame 0 by default, or a frame chosen at upload (API `video_cover_timestamp_ms`; official[^post]).
- Hand over: `meta.title` as the first line, `meta.desc` (≤ 2 200 characters through the API, official[^post];
  searchable words in the first 100, 3–5 specific hashtags), `meta.sources`; the cover frame's time; a note with the AI
  label (yes or no and why), branded or self-promotional content, music source and licence (or none), and whether
  the generators wrote C2PA metadata. No subtitle-file upload was found (unsure).

## The first seconds

- The recommender predicts per viewer whether they will finish, skip, like, share, comment, save or mark "Not
  interested", and how long they will watch (official[^recs]); a finished longer video is "a strong indicator of
  interest", and follower count is not a direct factor (official, 2020[^how]). Frame 0 is already the subject: no
  logo, black or fade-in; it is also the default cover, so it carries the promise in words.
- Say or show the payoff in the first 1–2 s and put the hook line on screen inside the safe area; the spoken and the
  written line agree (practice[^tips]).
- Carried over from one Douyin channel (same swipe-and-finish mechanism; practice, not measured on TikTok
  [^own]): the first spoken line states the verdict, not a question (question openers kept fewer viewers at five
  seconds); frame 0 shows the subject doing the thing, with one headline and no card; captions do not repeat
  the headline.

## Pace and length

- Change the picture every 1.5–3 s in the first 10 s; hold nothing static longer than about 4 s (practice). Re-crop
  a clip rather than play it forward then backward (carried over from Douyin[^own]).
- Under 60 s for reach. Over 60 s only for the Creator Rewards Program, which pays on original videos over a minute and
  scores originality, play duration, search value and engagement (reported, 2024[^crp]); never pad to 61 s.
- The payoff by about 15 s: on the Douyin channel most viewers left within the first seconds (carried over[^own]).
- Loops count as replays (practice): an ending that cuts cleanly into frame 0 helps; never fake it mid-sentence.

## Words on screen and captions

- Burn captions in: two lines at most, 32–42 characters a line, 56–72 px with a dark outline or plate, in the
  captions band (practice[^krumzi]). TikTok's own auto-captions are an overlay the uploader switches on and the agent
  cannot place (unsure).
- Nothing right of x 880 below y 780, nothing above y 240 (status bar, Following / For You) (practice[^krumzi]).
- The recommender and search read on-screen text, captions and spoken words (official[^recs]); search value is a
  Creator Rewards metric (reported[^crp]). Name the subject in words in the first on-screen line and the description.
- Big text carries the claim, not the narration's sentence; cards fill their box (carried over from Douyin[^own]).

## Sound

- TikTok calls itself "a sound-on experience" (official, ads[^tips]): every second has a voice or a deliberate sound.
- Music in the mp4 is published as original sound; unlicensed commercial music can be muted or the post blocked
  (practice). Business accounts may use only the Commercial Music Library (official[^cml]). Use licensed music or
  none, and deliver a clean mix (and a voice-only stem) so the uploader can add library music.
- Master −14 LUFS (practice; no target published).

## The ending, title, cover and tags

- End on the last point and stop: no outro card, no "follow for more" over 1 s; unfinished views cost completion
  (official[^how]). A question that invites a comment, or a reason to rewatch, fits the signals (official[^recs]).
- No engagement bait ("like if…", "comment YES"): content that tries to inflate likes or follows is ineligible for the
  For You feed (official[^cg]).
- Description: the subject's searchable words in the first 100 characters (practice), 3–5 specific hashtags.
- Cover: the frame whose hook text sits inside the safe area; give its time. Playlists group a series (practice).

## What gets a film limited

- **AI label (official, 2026-09-24[^cg]).** AI-generated or significantly edited content showing realistic scenes or
  people must carry the label; unlabelled, it "may be removed, restricted, or labeled". The label is the upload
  toggle (API `is_aigc`, official[^post]); "#ai" in the caption does not count (practice). TikTok auto-labels files
  with C2PA Content Credentials (official, 2024-05-09[^c2pa]) and adds an invisible watermark (official,
  2025-11[^wm]). Handover: AI yes or no, what was generated (realistic people, scenes, voices), and whether C2PA
  metadata is present, so the uploader switches the toggle on.
- **Generated people (practice).** A generated face never stands for a named real person; a synthetic voice that
  imitates one is realistic audio and needs the label. No flags, slogans or uniforms in generated pictures.
- **Unoriginal content.** "Unoriginal or reused material without anything new" is ineligible for the For You feed
  (official[^cg]). Never upload a file exported from another app; transform supplied footage (commentary, re-edit).
- **Commercial content.** Paid partnerships and self-promotion need the disclosure toggles (official[^post]);
  political ads are not allowed (official[^reg]).
- **Finance, health, news.** No fake investment offers or get-rich-quick schemes (official[^reg]); harmful
  misinformation is removed and unverified crisis claims are ineligible for the For You feed (official[^cg]). Show
  sources for every number; no promised returns, no cures.

## What is not known

- The organic safe area (TikTok publishes only the ads template): post a private grid video, screenshot two phones.
- The per-account maximum length (`creator_info/query`[^api]); retention thresholds; C2PA after a re-encode.

## Sources

[^api]: https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide , read 2026-11-10; official.
[^tpl]: https://socialync.io/tools/safe-zones/tiktok (scaling TikTok's In-Feed safe-zone template, linked from https://ads.tiktok.com/help/article/tiktok-auction-in-feed-ads ; checked by them 2026-10-11), read 2026-11-10; reported.
[^krumzi]: https://krumzi.com/tools/safe-zone-checker/tiktok (organic margins, checked by them 2026-11-02), read 2026-11-10; practice.
[^post]: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post (cover timestamp, caption length, is_aigc, brand toggles), read 2026-11-10; official.
[^recs]: https://www.tiktok.com/transparency/en/recommendation-system (undated), read 2026-11-10; official.
[^how]: https://newsroom.tiktok.com/how-tiktok-recommends-videos-for-you (2020-06-18), read 2026-11-10; official.
[^tips]: https://ads.tiktok.com/business/library/Auction_Ads_Creative_Tips.pdf , read 2026-11-10; official (ads).
[^own]: Practice from one short-video channel made with reelsmith, reviewed in November 2026; its figures are not published.
[^crp]: Social Media Today and ZDNet on the Creator Rewards Program (2024-03), read 2026-11-10; reported.
[^cml]: https://ads.tiktok.com/business/en-US/blog/audio-library-royalty-free-music , read 2026-11-10; official.
[^cg]: https://www.tiktok.com/community-guidelines/en/integrity-authenticity (effective 2026-09-24; also its For You feed eligibility section), read 2026-11-10; official.
[^reg]: https://www.tiktok.com/community-guidelines/en/regulated-commercial-activities , read 2026-11-10; official.
[^c2pa]: https://newsroom.tiktok.com/partnering-with-our-industry-to-advance-ai-transparency-and-literacy (2024-05-09), read 2026-11-10; official.
[^wm]: https://newsroom.tiktok.com/more-ways-to-spot-shape-and-understand-ai-content (2025-11-19), read 2026-11-10; official.
