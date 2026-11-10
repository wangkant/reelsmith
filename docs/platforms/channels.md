# WeChat Channels (微信视频号)

Profile `channels`. Videos play full screen, one at a time; reach rides on friends: a viewer's 推荐 shows the video to
their friends, and shares go to chats and Moments (朋友圈). The audience skews older and comes from WeChat. Grades:
official, reported, practice, unsure. No safe-zone template or open upload-spec page exists.

## The frame

- 1080×1920, 9:16, 30 fps, H.264 in MP4 (practice[^tool]); 16:9 (1080×608) and 6:7 (1080×1260) were the 2020 official
  sizes and still upload (practice[^cover]).
- Uploads to 60 min and 2 GB (reported, 2021[^1h]); the profile's caps.
- Safe area x 120–960, y 200–1500, captions y 1300–1500 (conservative, unmeasured): back and search over the top
  ~120 px; avatar, name, 关注, description and a link line bottom left, the like, 推荐, share and comment controls along
  the bottom from about y 1500; no right-hand column (practice[^generic]). 120 px sides allow for tall-phone crop.
- Cover: frame 1 by default, settable in 视频号助手 (practice[^cover]); its ratio there is unsure, and the profile grid
  crops: design frame 0 so a centred 3:4 crop (y 240–1680) still reads.
- Hand over: `meta.title` as the short title (短标题, 6–50 characters; under 6 fails to publish; reported[^tool]),
  `meta.desc` (≤ 1 000 characters with inline #话题; reported[^desc]), `meta.sources`; a 1080×1920 cover; the 合集
  name and episode; a note with the AI declaration (yes or no and what was generated), 声明原创 only if every asset is
  owned, a risk-warning line (风险提示) for money topics, the music source or "use the in-app library", and a
  voice-only mix plus a music stem. No subtitle-file upload or chapters were found (unsure).

## The first seconds

- Frame 0 plays full screen and doubles as the cover: make it a readable card (subject plus one claim) over a moving
  picture, and start talking within 0.5 s (practice[^cover]).
- Completion (完播率) is the signal practitioners weight most; a cited "under 20 s and below 10 % completion is rarely
  recommended" is folklore (unsure[^algo]).
- Carried over from one Douyin channel (practice[^own]; the same full-screen swipe, not measured here): the
  first spoken line states the verdict, not a question; frame 0 shows the subject doing the thing, with one headline
  and no card; the viewer's stake comes within the first two lines.

## Pace and length

- Talk-led explainers 1–3 min (the profile targets 60–180 s; practice); a tool driving the uploader suggests 1–10 min
  (reported[^tool]). A slower pace, one point per 15–30 s, suits this audience (practice).
- Change the picture every 2–4 s even when the talk is slow; one picture held 8–10 s reads as a slideshow, and a clip
  re-cropped beats one played forward then backward (carried over from Douyin[^own]).
- Never pad past the content; completion and average watch time matter (practice[^algo]).

## Words on screen and captions

- Burn captions in: at most two lines of 14–16 characters, centred in the captions band. Use larger type than on
  Douyin, 60–72 px for body text, for the older audience (practice).
- Big text carries the claim, not the narration's sentence; cards fill their box (carried over from Douyin[^own]).
- No QR code, phone number, WeChat ID or "加V" in the frame: traffic diversion (引流) gets videos limited
  (practice[^rules]).

## Sound

- A synthetic voice is allowed and is AI-generated content: declare it. Practitioners report that electronic
  voice-over with no person on camera (非真人出镜的电子配音) can count against originality and reach (practice[^rules]):
  give the voice your own writing, structure and pictures.
- No commercial song burned in; use the in-app library or owned music, a bed 18–24 dB under the voice (practice).
  Master −14 LUFS (unsure: no target published).

## The ending, title, cover and tags

- End on a line worth forwarding, such as a summary card someone would send to a family group, not a "follow me" plea:
  推荐 and shares carry reach (reported, the mechanism[^social]; practice, the advice).
- Short title 6–50 characters (reported[^tool]); #话题 inline in the description as "#话题"; number the episodes of a
  合集 in the title or on the cover (practice).
- Cover: frame 0 as a card, readable after a centred 3:4 crop (unsure[^cover]).

## What gets a film limited

- **AI declaration (official as reported, 2025-09-01[^ai]).** Declare AI generation at publish; the platform adds
  visible and metadata labels; never remove, crop or hide a platform label. The national 标识办法 requires both labels
  on AI-made video (official[^cac]). Handover: AI yes, what was generated (voice, pictures, clips); keep the
  generators' metadata and watermarks.
- **Staged and altered content.** Staged fake videos (虚假摆拍) are under a governance campaign since 2026-01-23, and
  malicious AI rewrites of films and historical figures (AI魔改) were removed by the thousands (reported[^fake]). A
  generated face never stands for a named real person; no flags, slogans or uniforms in generated pictures (practice).
- **Reused footage.** Re-cut footage of others' videos or livestreams without permission breaks the 视频号运营规范
  (official as reported[^rules]). Only footage the creator owns or licensed; no other platform's watermark.
- **Finance (视频号金融行业公约, 2026-04-01).** Professional titles need certification; banned: buy or sell timing and
  prices, promised returns, malicious bearishness, invented "insider" news, templated look-alike content, crypto
  promotion and luring viewers off-platform; personal views on money carry a risk warning (风险提示) (official as
  reported[^fin]). Explain, never advise.
- **Medical.** Health content from accounts without health certification is reported limited (practice[^rules]): no
  treatment claims; general information with sources.
- **News.** No platform rule found; Chinese law reserves original news reporting to licensed outlets, so frame news
  as commentary on named, reported sources (unsure).

## What is not known

- Current caps (read the hint on channels.weixin.qq.com's upload page); the overlay (post a private grid video and
  screenshot two phones); the cover ratio in 视频号助手; the AI control's current name; ranking weights.

## Sources

[^tool]: https://clawhub.ai/Johnnyxu820/weixin-video-publish (uploader automation, 2026), read 2026-11-10; reported.
[^cover]: https://www.digitaling.com/articles/377384.html (2020: sizes, default cover), read 2026-11-10; practice.
[^1h]: https://m.jiemian.com/article/6574895.html (about 2021), read 2026-11-10; reported, old.
[^generic]: https://reap.video/blog/short-form-video-safe-zones (other platforms' margins), read 2026-11-10; practice.
[^desc]: https://www.digitaling.com/articles/341137.html (2020), read 2026-11-10; reported.
[^algo]: https://www.woshipm.com/marketing/5574102.html , read 2026-11-10; practice, folklore for the threshold.
[^own]: Practice from one short-video channel made with reelsmith, reviewed in November 2026; its figures are not published.
[^rules]: https://m.sohu.com/a/740525276_439800 and https://www.ithome.com/0/870/269.htm , read 2026-11-10; practice, official as reported for the 运营规范.
[^social]: https://www.woshipm.com/it/4830242.html (2021; the 朋友赞过 entry, 2020-06), read 2026-11-10; reported.
[^ai]: https://news.bjd.com.cn/2025/08/31/11290505.shtml (2025-08-31), read 2026-11-10; official as reported.
[^cac]: 《人工智能生成合成内容标识办法》 (2025-03-14, in force 2025-09-01), https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm , read 2026-11-10; official.
[^fake]: https://www.yicai.com/news/103125654.html (2026; search snippet), read 2026-11-10; reported.
[^fin]: https://www.jiemian.com/article/14319235.html (2026-04-24), read 2026-11-10; official as reported.
