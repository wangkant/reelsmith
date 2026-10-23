// node scripts/segment.mjs < {"texts": ["...", ...]}
// Word boundaries for caption phrase splitting (resolve.py), from Intl.Segmenter("zh", {granularity: "word"}).
// stdout: {"words": [[len, ...], ...]} - each text as consecutive segment lengths in code points (Python's str
// indices), covering the whole text; spaces and punctuation are segments of their own.
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
let texts = [];
try {
  const input = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  texts = Array.isArray(input.texts) ? input.texts : [];
} catch (err) {
  process.stderr.write(`segment.mjs: stdin is not JSON: ${err.message}\n`);
  process.exit(2);
}
const segmenter = new Intl.Segmenter("zh", { granularity: "word" });
const words = texts.map((t) => Array.from(segmenter.segment(String(t ?? "")), (s) => Array.from(s.segment).length));
process.stdout.write(JSON.stringify({ words }));
