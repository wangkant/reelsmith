// A tracing aid: one picture shown whole under a labelled grid, its edges marked in the source image's pixels, so
// a preview still gives the coordinates of a cut-out's outline. The labels are data-noinspect: it is not film text.
import { Img } from "remotion";
import { assetSrc, FONTS, isAsset, numOr, useClip } from "@reelsmith/kit";

const count = (v: unknown) => Math.max(2, Math.min(40, Math.round(numOr(v, 10))));

export default function AssetGrid({ props }: { props: any }) {
  const { w, h } = useClip();
  const ref = props?.asset;
  if (!isAsset(ref)) return null;
  const cols = count(props?.cols);
  const rows = count(props?.rows);
  const size = Array.isArray(ref.size) && ref.size[0] > 0 && ref.size[1] > 0 ? ref.size : null;
  const [iw, ih] = size ?? [1, 1];

  const font = Math.max(22, Math.min(40, Math.round(Math.min(w, h) / 36)));
  // room for the widest label on the left and one line of labels above and below
  const digits = String(Math.max(Math.round(iw), Math.round(ih))).length;
  const left = font * (0.62 * Math.max(4, digits) + 0.6);
  const top = font * 2;
  const scale = Math.min((w - left * 2) / iw, (h - top * 2) / ih);
  const pw = Math.max(1, iw * scale);
  const ph = Math.max(1, ih * scale);
  const x0 = (w - pw) / 2;
  const y0 = (h - ph) / 2;
  // without a known size the edges read as fractions of the picture
  const label = (k: number, n: number, px: number) => (size ? String(Math.round((px * k) / n)) : (k / n).toFixed(2));

  const xs = Array.from({ length: cols + 1 }, (_, k) => k);
  const ys = Array.from({ length: rows + 1 }, (_, k) => k);
  const text = { position: "absolute" as const, fontFamily: FONTS.sans, fontSize: font, fontWeight: 700, lineHeight: 1,
    color: "#FFFFFF", textShadow: "0 0 4px #000, 0 0 2px #000", whiteSpace: "pre" as const };

  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, background: "#1E1A16" }}>
      <Img src={assetSrc(ref)} style={{ position: "absolute", left: x0, top: y0, width: pw, height: ph }} />
      <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0 }}>
        {xs.map((k) => {
          const x = x0 + (pw * k) / cols;
          const strong = k % 5 === 0;
          return (
            <g key={`x${k}`}>
              <line x1={x} y1={y0} x2={x} y2={y0 + ph} stroke="#000" strokeOpacity={0.55} strokeWidth={strong ? 4 : 3} />
              <line x1={x} y1={y0} x2={x} y2={y0 + ph} stroke={strong ? "#FFE14D" : "#FFFFFF"} strokeWidth={strong ? 2 : 1.2} />
            </g>
          );
        })}
        {ys.map((k) => {
          const y = y0 + (ph * k) / rows;
          const strong = k % 5 === 0;
          return (
            <g key={`y${k}`}>
              <line x1={x0} y1={y} x2={x0 + pw} y2={y} stroke="#000" strokeOpacity={0.55} strokeWidth={strong ? 4 : 3} />
              <line x1={x0} y1={y} x2={x0 + pw} y2={y} stroke={strong ? "#FFE14D" : "#FFFFFF"} strokeWidth={strong ? 2 : 1.2} />
            </g>
          );
        })}
      </svg>
      <div data-noinspect="">
        {xs.map((k) => {
          const cx = x0 + (pw * k) / cols;
          const t = label(k, cols, iw);
          const width = font * 0.62 * t.length;
          // every second label when the columns are too narrow for them all
          if (k % (pw / cols < width * 1.15 ? 2 : 1) !== 0 && k !== cols) return null;
          return (
            <div key={`tx${k}`}>
              <div style={{ ...text, left: cx - width / 2, top: y0 - font * 1.65 }}>{t}</div>
              <div style={{ ...text, left: cx - width / 2, top: y0 + ph + font * 0.65 }}>{t}</div>
            </div>
          );
        })}
        {ys.map((k) => {
          const cy = y0 + (ph * k) / rows;
          if (k % (ph / rows < font * 1.1 ? 2 : 1) !== 0 && k !== rows) return null;
          const t = label(k, rows, ih);
          return (
            <div key={`ty${k}`}>
              <div style={{ ...text, left: x0 - font * 0.3 - font * 0.62 * t.length, top: cy - font / 2 }}>{t}</div>
              <div style={{ ...text, left: x0 + pw + font * 0.3, top: cy - font / 2 }}>{t}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
