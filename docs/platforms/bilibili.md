# Bilibili (哔哩哔哩, B站)

Profiles `bilibili` (landscape 横屏, the main form) and `bilibili-story` (vertical Story Mode). Grades: official,
reported, practice, unsure. The help centre and upload page need a login, so many limits are reported or unsure.

## The frame

- `bilibili`: 1920×1080, H.264 + AAC (practice[^spec]); 1080p up to 60 fps, average ≤ 6 000 kbps, peak ≤ 24 000,
  a keyframe at least every 10 s (reported[^spec]). Size and length caps are unsettled (unsure[^size]): none set.
- Safe area x 96–1824, y 54–1000, captions y 800–1000 (conservative: no template exists; a 5 % margin and the
  bottom 80 px left to the progress bar; practice). 弹幕 fly across from the top rows down, how far is a viewer
  setting (reported[^danmaku]): keep words that must be read out of the top third.
- `bilibili-story`: 1080×1920; Bilibili publishes no vertical size or overlay (unsure[^story]). Safe x 120–880,
  y 300–1400, captions y 1200–1400 (conservative, unmeasured); the like, coin, favourite, comment and share column
  sits right of x 880. Story Mode videos run up to 10 min (reported, 2021[^story]).
- Cover (封面): 4:3 at 1200×900 since late 2023, shown 4:3 in the mobile feed and 16:9 on PC and in search: 4–8
  large characters and the subject in the central 1280×720 band of a 1280×960 design (practice[^cover]), on frame 0
  x 240–1680, y 135–945 (no check measures it); start captions after frame 0 to keep them off it.
- Hand over: `meta.title` (< 80 characters), `meta.desc` (简介 < 250 characters), `meta.sources`; tags (≥ 1, < 200
  characters in all) and the 分区; 自制 or 转载 with its source (reported[^api]); the 创作者声明 to tick; the srt;
  `out/chapters.txt` (optional under about 5 min; no rule is published, so keep YouTube's); covers at 1920×1080
  (frame 0) and 1280×960 (`crop=1440:1080:240:0,scale=1280:960`); a pinned comment (置顶评论) with sources.

## The first seconds

- The viewer picked the video from cover and title; the opening confirms that promise at once: no logo, jingle or
  "大家好我是…" (practice). Bilibili's quality measure is minutes watched (播放分钟数), and the creator centre shows
  average play progress (平均播放进度) per video (reported, 2023[^minutes]): the start begins a long watch.
- Say the answer early and spend the rest showing why. A spoken question as the first line lost viewers on a Douyin
  channel (practice[^own]); on Bilibili this is carried over, not measured.
- Story Mode is swiped like Douyin: claim and a moving picture in the first second, the verdict as line 1, one
  headline and no card at frame 0 (carried over from one Douyin channel, see douyin.md[^own]).
- Fixed traffic stages and weights ("完播率 40 %") come from vendor blogs, not Bilibili (unsure[^folk]).

## Pace and length

- Landscape films long enough to carry an idea: explainers and 知识区 5–15 min, commentary 3–8 min, a news brief
  2–4 min; one minute is a weak fit (practice; a brief's length wins). Bilibili counts minutes (reported[^minutes]).
- Change the picture every 3–6 s in a narrated explainer; cutting faster without new information costs play progress
  (practice). Narration stays clear at 1.5× (reported[^minutes]). No 5 s without motion: a slow push on a chart counts.
- Story Mode: 30–90 s unless the subject needs more (practice); the payoff by about 15 s (carried over from Douyin,
  where most viewers left within the first seconds[^own]).
- A series goes in a 合集 (each ranked alone; 电磁力 ≥ Lv.3, official 2022, may be stale[^heji]); 分P for one work.

## Words on screen and captions

- Burn Chinese captions in one clean band (plain box or outline, one or two lines): Bilibili's AI translation erases
  burned Chinese subtitles and re-renders them (reported, 2025[^ai-sub]). Deliver the srt too (CC subtitles exist;
  the upload format is unsure[^ai-sub]).
- Titles, numbers and labels that must be read go to y 360–800 while captions show (under the 弹幕 rows of the top
  third, above the captions band), down to y 1000 without captions (unsure, inferred from the settings[^danmaku]).
- More text is accepted than on Douyin; hold a block long enough to read twice at 1.5× (practice).

## Sound

- A synthetic voice is allowed and makes the film AI-synthesised content: declare it (official[^decl]). Cleared or
  royalty-free music only (owners file claims, 版权方投诉), ducked under the voice; −14 LUFS, no spec found (unsure).

## The ending, title, cover and tags

- End with content, then a short ask for 三连 (like 点赞, coin 投币, favourite 收藏 at once): normal at the end, not in
  the first 30 s. Reported positive signals: plays, likes, coins, favourites, follows, shares (reported[^signals]).
  An end card 5–10 s at most (practice).
- Title < 80 characters (reported[^api]); 15–30 in practice, subject and angle, no promise the film does not keep.
- Tags: 5–10 (the 分区 subject, two or three specific terms, a series name); the 分区 (知识, 科技, 资讯, 生活…) sets
  which pool the video enters (practice[^api]).

## What gets a film limited

- **AI content (official, from 2025-09-01).** The national 标识办法 requires a visible label on a video's opening frame
  and around playback, an implicit label in the metadata, and the uploader's own declaration (Arts. 4, 6, 10[^cac]).
  GB 45438-2025: text naming AI ("AI生成" or "人工智能生成合成") at an edge or corner, height ≥ 5 % of the short side
  (≥ 54 px at 1080), on screen ≥ 2 s at the start (reported[^gb]). Bilibili: 更多设置 › 创作者声明 ›
  "该视频使用人工智能合成技术"; one declaration per video and AI comes first; undeclared AI is labelled by the platform
  (official, 2023 and 2025[^decl][^aidecl]). Handover: AI yes, what was generated (voice, pictures, clips), and the
  burned label's frame, corner and seconds; keep the generators' metadata. Generated text counts too (Art. 3):
  if only the script was generated, say so and leave the call to the owner.
- **News.** An original video on current events states where and when its footage was shot in the 简介; a repost is
  转载 with its source (official, 2023[^decl][^zimeiti]). Fiction is declared as such (official[^decl]).
- **Finance, education, medical, legal.** These fields need verified accounts (official, 2023[^zimeiti]): no advice,
  stock picks, diagnosis or legal opinion; explain public facts with sources.
- **Faces, voices, footage.** Using a real person's face or voice with AI (盗脸, 偷声) is the target of a national
  campaign, 2026-11 to year end (official[^nrta]). A generated face never stands for a named real person; no flags,
  slogans or uniforms in generated pictures; no other platform's watermark in an original video (practice).

## What is not known

- Size and length caps by account, the web 简介 limit and tag count (创作中心 › 投稿, logged in); the default 弹幕
  area; the Story Mode overlay (a grid video on a phone); subtitle format (srt or .bcc) and chapter rules.

## Sources

[^spec]: https://www.bilibili.com/opus/891367754490183699 (user-compiled upload parameters, edited 2024-04-22), read 2026-11-10; reported.
[^size]: https://deervideo.net/guide/bilibili-video-upload-format (2026-06-07) and https://shankongmao.com/content/special-news/16125 , read 2026-11-10; unsure.
[^story]: https://www.jiemian.com/article/7326460.html and https://www.bilibili.com/read/cv26484164/ (Story Mode launch, seconds to 10 min), read 2026-11-10; reported.
[^danmaku]: https://www.woshipm.com/pd/3853131.html (danmaku 显示区域, 防挡字幕), read 2026-11-10; reported.
[^cover]: https://www.bilibili.com/opus/517638323328040669 (creator note, edited 2023-12-28: 4:3 1200×900, the 1280×960 method), read 2026-11-10; practice.
[^api]: https://bilibili.apifox.cn/api-23706538 (mirror of the open-platform 视频稿件提交 doc, 2022: title < 80, tags < 200, desc < 250, copyright 1/2), read 2026-11-10; reported.
[^minutes]: https://m.jiemian.com/article/9971524.html (2023-08-23, 播放时长指数, 平均播放进度) and https://www.jiemian.com/article/9700084.html (2023-06, minutes over plays; speed affects counts), read 2026-11-10; reported.
[^own]: Practice from one short-video channel made with reelsmith, reviewed in November 2026; its figures are not published.
[^gb]: GB 45438-2025 (issued 2025-02-28, in force 2025-09-01), §5.4 and Appendix E as summarised at https://www.geopolitechs.org/p/chinas-mandatory-national-standards (2025-03-16), read 2026-11-10; reported.
[^folk]: https://www.jzl.com/news/bilibili-14 (vendor blog, 2026-09-21), read 2026-11-10; folklore.
[^heji]: https://www.bilibili.com/opus/737624392331165747 (customer-service guide, 2022-12: 合集 at 电磁力 ≥ Lv.3, 信用分 ≥ 60), read 2026-11-10; official, may be stale.
[^ai-sub]: https://www.yzwb.net/news/kj/202508/t20250801_244653.html and https://www.itiger.com/news/2556878833 (AI 原声翻译, 2025-08), read 2026-11-10; reported.
[^decl]: https://tech.ifeng.com/c/8T50a3S3NwZ and https://technode.com/2023/09/15/bilibili-requires-users-to-tag-ai-generated-content (创作者声明, 2023-09-20: seven declarations, priority, 时事 time and place, 转载 source), read 2026-11-10; official as quoted.
[^aidecl]: https://m.thepaper.cn/newsDetail_forward_31523045 (Bilibili notice 2025-08-29 for the 2025-09-01 rules), read 2026-11-10; reported.
[^signals]: https://www.woshipm.com/ai/5851759.html (analysis of Bilibili's 2023-05 algorithm descriptions), read 2026-11-10; reported.
[^cac]: 《人工智能生成合成内容标识办法》 (2025-03-14, in force 2025-09-01), https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm , read 2026-11-10; official.
[^zimeiti]: 《关于加强"自媒体"管理的通知》 (2023-07-10), https://www.cac.gov.cn/2023-07/10/c_1690638496047430.htm , read 2026-11-10; official.
[^nrta]: https://www.stdaily.com/web/gdxw/2026-11/07/content_610029.html (NRTA campaign 2026-11-01 to year end: 盗脸, 偷声, misleading titles and covers), read 2026-11-10; official as reported.
