// Icons come from components/icons.tsx only: no emoji or symbol glyphs in the UI (they render as
// empty boxes without an emoji font, ignore the theme and look different on every platform).
// Arrows inside running text ("Settings → My Account") are allowed; comments are ignored.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const BANNED = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B50}\u{2B06}\u{2B07}\u{25B2}\u{25BC}\u{2605}\u{2606}]/u;
const files = [];
const walk = (d) => readdirSync(d).forEach((f) => { const p = join(d, f); statSync(p).isDirectory() ? walk(p) : /\.(tsx|ts)$/.test(p) && files.push(p); });
walk(new URL("../src", import.meta.url).pathname);
const hits = [];
for (const f of files) {
  readFileSync(f, "utf8").split("\n").forEach((line, i) => {
    const t = line.trim();
    if (t.startsWith("//") || t.startsWith("/*") || t.startsWith("*")) return;
    if (BANNED.test(line)) hits.push(`${f}:${i + 1}: ${t.slice(0, 120)}`);
  });
}
if (hits.length) {
  console.error("Emoji / symbol glyphs found — use an icon from components/icons.tsx instead:\n" + hits.join("\n"));
  process.exit(1);
}
console.log(`check-icons: ${files.length} files clean`);
