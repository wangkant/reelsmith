// node test/presets-preview/render.mjs <out dir> [id-filter] [frame ...]   (cwd: renderer/)
// One bundle, then a PNG per matching composition and frame (default frame 89, the settled end).
import { getCompositions } from "@remotion/renderer";
import { bundlePreview, renderJobs } from "./bundle.mjs";

const [out, filter = "", ...frameArgs] = process.argv.slice(2);
if (!out) {
  console.error("usage: node test/presets-preview/render.mjs <out dir> [id-filter] [frame ...]");
  process.exit(2);
}
const frames = frameArgs.length ? frameArgs.map(Number) : [89];

const serveUrl = await bundlePreview();
const ids = (await getCompositions(serveUrl)).map((c) => c.id).filter((id) => id.includes(filter));
const { errors } = await renderJobs(serveUrl, ids.flatMap((id) => frames.map((frame) => ({ id, frame }))), out);
for (const e of errors) console.error(e);
console.log(JSON.stringify({ ok: true, count: ids.length * frames.length, out }));
