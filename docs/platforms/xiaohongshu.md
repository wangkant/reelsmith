# Xiaohongshu (小红书) video notes

Profile `xiaohongshu`. Notes are found in a two-column grid of covers (双列) and in search, then watched full screen;
saves (收藏), comments and search carry them. Grades: official, reported, practice, unsure; no template exists.

## The frame

- 1080×1920, 9:16, 30 fps, H.264 in MP4, 8–12 Mbps at 1080p (practice[^spec]). 3:4 (1080×1440) is accepted too and
  fills the width in the feed (practice[^spec][^canva]); the profile is 9:16 because the grid tile is the separately
  uploaded 3:4 cover, not the video, while the full-screen player is 9:16 (a 3:4 video there leaves bars, unsure).
  Keep faces and key text inside the middle 1080×1440 (y 240–1680) so a 3:4 crop also reads.
- Safe area x 120–960, y 240–1480, captions y 1280–1480 (conservative, unmeasured): back and share icons over the top
  ~140 px; the author row, title, folded description, progress bar and comment bar over roughly y > 1480; no button
  column on the right (practice[^spec]). The 120 px sides allow for tall phones that crop a filled 9:16 frame.
- Caps are unsettled: 5 min in the app, 15 with long-video permission (reported, 2020[^xs15]); 1–20 GB in different
  sources (unsure[^yxe]). The profile keeps 5 min and 1 GB. Cover: 3:4, 1080×1440, uploaded or a frame (practice).
- Hand over: `meta.title` (≤ 20 characters, reported[^tool]), `meta.desc` (a text note of 100–500 characters with the
  steps and 3–8 #话题; practice), `meta.sources`; a designed 1080×1440 cover; the 合集 and episode; a note with the AI
  declaration (what was generated), 声明原创 only if every asset is owned, a finance risk line, the music source, a
  voice-only mix and a music stem. No subtitle upload or chapters were found (unsure).

## The first seconds

- The click happens in the grid, before playback: the cover and title say exactly what the note gives, and the first
  second delivers that same promise, with no logo or greeting; a mismatch reads as clickbait and viewers leave
  (practice[^algo]).
- The payoff ("3 步…") as large text in frame 0 for 2–3 s: many watch the preview muted (practice).
- Carried over from one Douyin channel (practice[^own]; the full-screen player swipes the same way, but it was
  not measured here): the first spoken line states the verdict, not a question; frame 0 shows the subject doing the
  thing, with one headline and no card.

## Pace and length

- 30–90 s for tips, how-tos and explainers (the profile's target; a common guide says 15–60 s, practice[^spec]). Over
  2 min only on purpose: since 2026-05-26 a medium-to-long video push gives videos over 2 min their own lane, free 4K
  and traffic vouchers (reported[^long]).
- Cut every 2–4 s in list or tutorial notes and hold each step's text long enough to read; numbered steps and a recap
  card near the end make the note worth saving (practice[^algo]). Re-crop a clip rather than play it forward then
  backward (carried over from Douyin[^own]).

## Words on screen and captions

- Burn captions in: at most two lines of 14–16 characters, 56–64 px with stroke or shadow, centred in the captions
  band (practice).
- A persistent header (the topic in 6–10 characters) in y 240–420 is house style for tutorial notes and survives the
  3:4 crop (practice).
- Big text carries the claim or the step, not the narration's sentence; cards fill their box (carried over[^own]).
- No QR code, phone number, WeChat ID or "加V" anywhere in the frame: traffic diversion (引流) gets notes limited
  (official as reported[^fin]).

## Sound

- A synthetic voice is allowed and is AI-generated content: declare it (see the rules).
- No commercial song burned in: the 2026-04-27 rules name unauthorised use of copyrighted works (official as
  reported[^apr]). Use the in-app library at upload or music the creator owns; keep a bed 18–24 dB under the voice
  (practice). Master −14 LUFS (unsure: no target published).

## The ending, title, cover and tags

- End on a recap or checklist frame held 2–3 s (worth saving); a question to the viewer invites comments (practice).
- Title ≤ 20 characters (reported[^tool]), the searchable noun phrase first: many users search inside the app
  (practice[^algo]).
- Cover: 1080×1440, one subject and 4–10 large characters covering no more than 30 % of it, clear of the lower-right
  corner where the grid shows the like count (practice[^spec]). A cover that promises what the film does not deliver
  is a misleading cover.
- 3–8 #话题 in the body; number the episodes of a 合集 in the title or on the cover ("第3期") (practice).

## What gets a film limited

- **AI declaration (official as reported).** Declare AI generation in the note's declaration setting at publish.
  Since 2025-09-01 suspected AI content is labelled "疑似使用AI生成技术"[^sep]; since 2026-02-12 undeclared AI content
  the platform detects is labelled and its distribution limited[^feb]; since 2026-04-27 penalties are graded,
  limited reach, then a ban[^apr]. The national 标识办法 requires visible and metadata labels (official[^cac]).
  Handover: AI yes, what was generated (voice, pictures, clips); keep the generators' metadata and watermarks.
- **Faked experience.** AI-made "first-hand" reviews and visits are removed (about 120 000 from June to August 2026;
  reported[^fake]). Never present a generated picture as a real place, product or experience; a generated face never
  stands for a named real person; no flags, slogans or uniforms in generated pictures (practice).
- **Automated accounts.** From 2026-03-10 accounts that post entirely through AI hosting tools (AI托管) are banned;
  mass-produced low-quality AI notes are a named violation (official as reported[^host][^apr]). The agent hands the mp4
  to a human uploader.
- **Reposted footage.** Material carrying another platform's watermark or logo is limited (practice[^spec]).
- **Finance (2026-09-15), medical.** The 社区金融生态公约 bans hype, stock tips, misleading claims, diversion and fake
  investor personas; 医美 is under repeated crackdowns (official as reported[^fin]): explain, never advise or treat.

## What is not known

- Current length and size caps (read the hint under creator.xiaohongshu.com's upload box); the overlay (post a
  private 仅自己可见 grid video and screenshot two phones); the AI control's current name and place; ranking weights
  (the "CES" formula is folklore[^algo]).

## Sources

[^spec]: https://resouci.com/xiaohongshu-video-note-spec-2026/ (2026-09-24), read 2026-11-10; practice.
[^canva]: https://www.canva.cn/learn/xiaohongshu-note-cover/ (undated), read 2026-11-10; practice.
[^xs15]: https://www.jiemian.com/article/4835640.html (2020), read 2026-11-10; reported, old.
[^yxe]: https://xueyuan.yixiaoer.cn/article/34259 (2025-01-03), read 2026-11-10; practice.
[^tool]: https://clawhub.ai/Johnnyxu820/video-publish-all (uploader automation, 2026), read 2026-11-10; reported.
[^algo]: https://www.woshipm.com/ai/6201172.html and https://www.woshipm.com/operate/5865982.html , read 2026-11-10; practice, folklore for weights.
[^own]: Practice from one short-video channel made with reelsmith, reviewed in November 2026; its figures are not published.
[^long]: https://www.cls.cn/detail/2382224 (2026-05-27), read 2026-11-10; reported.
[^fin]: https://news.bjd.com.cn/2026/09/15/11959968.shtml (2026-09-15) and https://news.sina.cn/minsheng/2026-06-04/detail-iniafrtq3654165.d.html (2026-06-04), read 2026-11-10; official as reported.
[^apr]: https://tech.ifeng.com/c/8sfimNUBjzv (2026-04-27), read 2026-11-10; official as reported.
[^sep]: https://www.cls.cn/detail/2133981 (2025-09-02), read 2026-11-10; reported.
[^feb]: https://www.thepaper.cn/newsDetail_forward_32599956 (2026-02), read 2026-11-10; official as reported.
[^cac]: 《人工智能生成合成内容标识办法》 (2025-03-14, in force 2025-09-01), https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm , read 2026-11-10; official.
[^fake]: https://www.ithome.com/0/976/718.htm (2026-09-03; search snippet only, page returned 403), read 2026-11-10; reported.
[^host]: https://m.gmw.cn/2026-03/10/content_1304371172.htm (2026-03-10), read 2026-11-10; official as reported.
