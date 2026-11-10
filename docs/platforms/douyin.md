# Douyin (抖音)

Profiles `douyin` (feed) and `douyin-long`. Grades: official, reported, practice, unsure. "One channel": a Douyin
channel made with reelsmith, reviewed from its own platform numbers (practice[^own]).

## The frame

- 1080×1920, 30 fps, H.264 + AAC (practice[^spec]), landscape only for landscape footage (practice[^mid]). Uploads
  ≥ 720p, to 15 min (60 for some accounts), 4 GB (reported, 2021[^web]); 90 s and 80 MB are reelsmith's caps.
- Safe x 120–880, y 240–1460, captions y 1260–1460 (practice[^safe]). UI: top ~230 px; a right rail x ≥ 880 at
  y 720–1640; @name, title, music and progress bar from y 1480; a 20:9 phone crops 50–110 px a side (practice[^safe]).
  The cover is frame 0, cropped 3:4 from the middle (y 240–1680) on the profile grid (practice[^cover]).
- Hand over: `meta.title`, `meta.desc` (1–3 sentences, 3–5 #话题, no links), `meta.sources`; the cover (crop
  `crop=1080:1440:0:240`); a note: declarations (AI, fiction, time/place or source), 合集 (none for a one-off), a
  pinned comment, a domain flag (finance, medical, legal, else none). No subtitle upload exists (unsure).

## The first seconds

- The ranker predicts per viewer the chance to finish (完播), like, comment, share and follow (reported, 2025[^algo]);
  an early swipe lowers all (traffic pools are folklore[^folk]). Subject and claim on screen by 1 s; no logo, "大家好".
- The first spoken line states the verdict, never a question: on one channel, films that opened on a spoken question
  kept fewer viewers at five seconds, and films that opened on the verdict were watched longer and finished more
  often (practice[^own]).
- Frame 0 shows the story's own object or person doing what line 1 says (a cracked phone flexed, a passenger in a
  train vestibule), not a prop (a payslip on a desk): the channel's best openings did so (practice[^own]). No check
  sees it: on the cover crop the object must show clear of the headline.
- Frame 0 carries one headline: no news or quote card before line 2, no captions repeating it, and the same claim
  and polarity as line 1 (a headline saying the opposite of the spoken line lost the most viewers early[^own]).

## Pace and length

- Payoff by 15 s: on one channel most viewers left long before the end, while the point to take away nearly always
  came after 15 s (practice[^own]). Verdict and the viewer's stake (their money, usually 你) by 8 s, payoff
  by 15 s, then story and evidence; names and background where used. Lines 2–4 each add a fact: no "事情是这样".
- Cut every 2–4 s, the first change by about 4 s; a picture held 8–10 s reads as a slideshow (earlier cuts went with
  better early retention, though only weakly[^own]). Reuse a clip by re-cropping it (closer, another pan,
  `flip_x`) between other shots, not forward then backward, which made long holds (practice[^own]).
- Length: caps 20–90 s, target 45–75 s (advice). Length showed no relation to seconds watched (practice[^own]):
  never shorten a film to raise its finish rate or say shorter gets more plays. Judge by 5 s retention and seconds
  watched (5 s retention rose with plays on that channel). `douyin-long`, 90–180 s: a how-to or checklist worth saving;
  saves (收藏) and return visits are named targets (reported[^algo]).

## Words on screen and captions

- Captions burned in: one line, 36–66 px, white on the default plate or a dark stroke, y 1260–1460 (practice[^safe]).
- Big text: the claim, ≤ 14 characters on two lines, never the narration's sentence; big text plus captions repeated
  the voice for much of the narration on one channel, least in its best film (practice[^own]).
- Cards fill half the safe area's height or more, main lines ≥ 48 px (a preset's secondary lines, Parties roles or
  Versus tags, are smaller by design); a card drawn small inside a large box cannot be read (practice[^own]).
- Footage at full brightness (`filter.brightness` 1, never under 0.85; no `blur` under cards): dimming made films
  murky. A floor only: brightness showed no relation to plays, nor did the count of spoken numbers (practice[^own]).

## Sound

- A natural voice carries the film; flat TTS reads as 营销号 (practice); a brisk, unhurried pace worked[^own].
  Master −10 LUFS, peak −1 dBTP; no normalisation target is published (practice).
- No commercial song burned in: library music (曲库) chosen at upload is licensed in the app; burned-in audio becomes
  the post's 原声 and is copyright-checked (practice[^music]). Keep a bed ≥ 18 dB under the voice.

## The ending, title, cover and tags

- End on the line the viewer keeps or forwards (what to do when it happens to them) and cut within 1 s; no end card,
  no "点赞关注" (practice[^algo]). A question in the pinned comment invites comments (reported[^algo]).
- Title (作品标题) ≤ 30 characters (unsure). Question titles did no harm; complaint titles (凭什么, 凭啥)
  held viewers worse (practice[^own]). Misleading titles or covers and engagement bait are 恶意营销 (reported[^ying]).
- Cover: the claim in 2–4 lines of big type in y 240–600. 3–5 specific #话题 (#热门 does nothing; practice); one 合集
  per recurring format (reported, 2019[^series]).

## What gets a film limited

- **AI content (official, from 2025-09-01).** AI-made pictures, audio and video carry a visible label and one in the
  file's metadata; removing either is forbidden[^cac25]. The uploader declares it (自主声明 → 内容由AI生成); an
  undeclared film gets a platform label and can be limited until fixed, repeats lose posting or monetisation
  (reported[^ai][^ai2][^ai3][^ai4]). Handover: AI yes, and what was generated (voice, pictures, clips, music); keep the
  generators' metadata. One declaration per film; on news the time/place or source label wins (reported[^decl]).
  Generated text counts too (Art. 3): if only the script was generated, say so and leave the call to the owner.
- **Generated people and symbols (practice).** A generated face never stands for a named real person (show the
  object, the document, a person from behind); no flags, slogans or uniforms in generated pictures.
- **Declarations (official, 2023[^cac]).** News: place and time of own footage, sources, date of old news; staged
  scenes: 情景演绎，仅供娱乐. Retell sources in your own type, never a screenshot; no URL, QR code or WeChat ID (引流).
- **Finance, medical, legal (2025).** Uncertified accounts publish no professional advice, stock price call,
  diagnosis, dosage or legal opinion, also not dressed as 科普 (reported[^fin][^med][^law]): explain, never advise.
- **Reused footage.** Others' material with a watermark shown or blurred, outside clips with only effects, text or a
  line of narration added, near-identical batch films: all count against a 健康分 (reported[^ying][^copy]).

## What is not known

- Limits by account (length, size, title, topics): creator.douyin.com's upload form. The overlay by phone (screenshot
  a private grid video); loudness normalisation; whether one channel's finance findings hold for other subjects.

## Sources

[^own]: Practice from one short-video channel made with reelsmith, reviewed in November 2026; its figures are not published.
[^spec]: https://www.toolbox365.cn/tutorials/video-compress-platform-upload-specs-2026/ (2026-05-05), read 2026-11-10; practice.
[^web]: IT之家 on the Douyin web uploader (about 2021), via https://tech.ifeng.com/c/87Fik28UzKh , read 2026-11-10; reported, old.
[^mid]: zhihu.com/p/651109827 and zhihu.com/p/523261668 (中视频伙伴计划, 2022–23), read 2026-11-10; reported.
[^cover]: https://www.ubrand.com/blog/250 (2024 cover sizes), read 2026-11-10; practice.
[^safe]: reelsmith `reelsmith/profiles.py` DOUYIN (phone measurements); side crop: a 20:9 screen shows 1350 px of a frame scaled ×1.25, about 108 px lost per side; read 2026-11-10; practice.
[^algo]: 界面新闻 via 财联社, "抖音首次公开算法原理" (2025-04-16), https://www.cls.cn/detail/2005910 , read 2026-11-10; reported.
[^folk]: https://www.cnblogs.com/flyingsir/articles/19139938 (2025-10-14) and https://www.woshipm.com/operate/6200947.html , read 2026-11-10; folklore.
[^music]: https://www.douyin.com/shipin/7263842825769453603 (剪映 copyright-check tutorial), read 2026-11-10; practice.
[^ying]: IT之家 on 《"恶意营销号"治理规范》 (2025-04), https://www.ithome.com/0/849/586.htm , read 2026-11-10; reported.
[^copy]: 澎湃 on 抖音集团《关于内容原创度建议的公告》 (2026-03-13), https://m.thepaper.cn/newsDetail_forward_32767365 ; 虎嗅 on hidden watermarks (2026-03-05), https://www.huxiu.com/article/4839245.html ; read 2026-11-10; reported.
[^cac25]: 《人工智能生成合成内容标识办法》 (2025-03-14, in force 2025-09-01), https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm , read 2026-11-10; official.
[^ai]: 澎湃 on the 2025-09-01 platform notices, https://m.thepaper.cn/newsDetail_forward_31523045 ; 科技日报 https://www.stdaily.com/web/gdxw/2025-09/02/content_393775.html ; read 2026-11-10; reported.
[^ai2]: https://bothn.com/post/172 (check of 2026 AI-label claims, citing Douyin's 2026-09-03 notice), read 2026-11-10; reported.
[^ai3]: 腾讯新闻 on Douyin's AI label (2023-09-08), https://news.qq.com/rain/a/20230908A04KIN00 , read 2026-11-10; reported.
[^ai4]: 央广网 interview with Douyin's content-safety VP (2026-05), via https://www.sohu.com/a/1013059969_121761735 , read 2026-11-10; reported.
[^decl]: IT之家 0/717/772 and https://www.toutiao.com/zixun/7495193369656903716 (declaration rules, one per film, priority), read 2026-11-10; reported.
[^cac]: 中央网信办《关于加强"自媒体"管理的通知》 (2023-07-10), https://www.chinanews.com.cn/gn/2023/07-10/10040043.shtml , read 2026-11-10; official.
[^fin]: 《抖音社区财经行业公约(试行)》 (2025-12-16), 科创板日报 via 财联社 (2025-12-17), https://www.cls.cn/detail/2232505 , read 2026-11-10; reported.
[^med]: 第一财经 (2025-08-01 notice), https://www.yicai.com/news/102754213.html ; https://www.cls.cn/detail/2230799 ; read 2026-11-10; reported.
[^law]: IT之家 0/905/343 and yzwb.net (2025-11-25) on 《抖音社区法律行业公约》 (2025-11-24), read 2026-11-10; reported.
[^series]: 投资界 (2019-09), https://news.pedaily.cn/201909/446358.shtml , read 2026-11-10; reported, old.
