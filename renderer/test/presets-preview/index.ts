// Preset preview: every preset and examples/workspace/library/components/PriceTag at its meta example, in an
// 840x700 box ("<Name>-base") plus "-dark", "-narrow" (420x700), "-wide" (840x340), "-tall" (320x760) and
// "-small" (320x320), and "x-..." compositions for other props and edge cases. The dashed outline is the clip box.
//   cd renderer && node test/presets-preview/render.mjs <out dir> [id filter] [frame ...]   (default frame 89)
//   node test/presets-preview/check.mjs [out dir]        (renders, then checks text sizes, overlaps, timing)
//   node test/presets-preview/kit-test.mjs               (kit helpers, no browser)
//   npx tsc --noEmit -p test/presets-preview              (presets + library)
//   python test/presets-preview/check_meta.py                                          (meta schemas)
//   python test/presets-preview/fixtures.py                          (redraws the made-up captures in public/)
import { registerRoot } from "remotion";
import { Root } from "./Root";

registerRoot(Root);
