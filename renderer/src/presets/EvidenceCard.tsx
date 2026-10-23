// A captured page on a white card: the evidence crop (the same one the evidence clip type draws) hugging its proving
// sentence, a highlighter sweeping across it, the source under the card. The card hugs the crop's panel (its cut edges
// fade into the card's white); the source line is never under 28 px (two lines before it gets smaller).
import { useCurrentFrame } from "remotion";
import {
  ease, EvidenceCrop, evidenceLayout, fitLines, FONTS, frameOr, isAsset, numOr, onGround, textWidth, themeColor, toFrames, useClip,
} from "@reelsmith/kit";

const MIN_SOURCE = 28;

/** "www.example.org" -> "example.org"; a site name ("示例日报") stays as it is. */
const siteName = (site?: string) => {
  const s = String(site ?? "").trim();
  return /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(s) ? s.replace(/^(www|m|wap|mobile)\./i, "") : s;
};

export default function EvidenceCard({ props }: { props: any }) {
  const { w, h, fps, theme } = useClip();
  const f = useCurrentFrame();
  const ev = props?.asset;
  if (!isAsset(ev)) return null;

  const ink = onGround(theme, props?.ground);
  const site = siteName(ev.site);
  const source = props?.source !== undefined ? String(props.source).trim() : site ? `来源：${site}` : "";
  const srcMax = Math.max(MIN_SOURCE, Math.min(40, h * 0.06, w * 0.06));
  const fitted = source ? fitLines(source, w, srcMax, MIN_SOURCE, FONTS.sans, 600) : { size: 0, lines: [] as string[] };
  const tagSize = source ? Math.max(MIN_SOURCE, fitted.size) : 0;
  // a source too long for two lines at the floor wraps further rather than shrinking
  const tagRows = fitted.lines.reduce((n, l) => n + Math.max(1, Math.ceil(textWidth(l, tagSize, FONTS.sans, 600) / Math.max(1, w))), 0);
  const tagH = tagRows * tagSize * 1.3;
  const tagGap = source ? tagSize * 0.45 : 0;
  const pad = Math.max(10, Math.min(36, w * 0.045));
  const inner = w - pad * 2;
  const maxWin = Math.max(10, h - tagH - tagGap - pad * 2);
  const context = Math.max(0, numOr(props?.context, 120));

  // the crop's panel hugs the sentence plus up to `context` page px above and below; the card hugs the panel
  const L = evidenceLayout(ev, inner, maxWin, context);
  const winW = L ? Math.min(inner, L.panel.w) : inner;
  const winH = L ? Math.min(maxWin, L.panel.h) : maxWin;
  const cardW = winW + pad * 2;
  const cardH = winH + pad * 2;
  const cardLeft = (w - cardW) / 2;
  const cardTop = Math.max(0, (h - tagH - tagGap - cardH) / 2);
  // the source starts under the card's left edge unless it would run past the box
  const tagW = Math.max(0, ...fitted.lines.map((l) => textWidth(l, tagSize, FONTS.sans, 600)));
  const tagLeft = Math.max(0, Math.min(cardLeft, w - tagW - 2));
  const settle = 1.03 - 0.03 * ease(f, 0, 40);
  const highlight = props?.highlight === false ? null : {
    at: frameOr(props?.highlight_at, Math.round(0.3 * fps)),
    dur: Math.max(1, toFrames(Math.max(0.05, numOr(props?.highlight_dur, 0.8)), fps)),
    color: themeColor(theme, props?.highlight_color, "gold"),
  };

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{
        position: "absolute", left: cardLeft, top: cardTop, width: cardW, height: cardH, padding: pad, boxSizing: "border-box",
        background: "#FFFFFF", borderRadius: Math.min(18, pad * 0.6), transform: `scale(${settle})`,
        boxShadow: ink.dark ? "0 30px 80px rgba(0,0,0,0.55)" : "0 24px 60px rgba(30,26,22,0.24)",
      }}>
        <div style={{ position: "relative", width: winW, height: winH, overflow: "hidden" }}>
          <EvidenceCrop ev={ev} w={winW} h={winH} highlight={highlight} context={context} />
        </div>
      </div>
      {source ? (
        <div style={{
          position: "absolute", left: tagLeft, width: w - tagLeft, top: Math.min(h - tagH, cardTop + cardH + tagGap), height: tagH,
          fontFamily: FONTS.sans, fontWeight: 600, fontSize: tagSize, lineHeight: 1.3, color: ink.muted,
          whiteSpace: "pre-wrap", overflowWrap: "anywhere", opacity: ease(f, 6, 16),
        }}>{fitted.lines.join("\n")}</div>
      ) : null}
    </div>
  );
}
