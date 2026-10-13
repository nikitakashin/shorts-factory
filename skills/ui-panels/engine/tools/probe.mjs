// Loads a composition headless, reports JS errors and timeline/cue stats.
//   node tools/probe.mjs [--comp index.html] [--cues assets/audio/cues.json] [--sync-duration]
// --sync-duration rewrites every data-duration in the composition to the film's exact length.
import puppeteer from "puppeteer-core";
import path from "node:path";
import fs from "node:fs";
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : d; };
const comp = arg("--comp", "index.html");
const html = fs.readFileSync(comp, "utf8");
const W = +(html.match(/data-composition-id="[^"]+"[^>]*data-width="(\d+)"/) || [0, 1920])[1];
const Hh = +(html.match(/data-composition-id="[^"]+"[^>]*data-height="(\d+)"/) || [0, 1080])[1];
const b = await puppeteer.launch({ executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true, args: ["--allow-file-access-from-files"] });
const p = await b.newPage();
const errs = [];
p.on("pageerror", (e) => errs.push("pageerror: " + e.message));
p.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errs.push(m.type() + ": " + m.text()); });
await p.setViewport({ width: W, height: Hh });
await p.goto("file://" + path.resolve(comp), { waitUntil: "networkidle0" });
const info = await p.evaluate(() => {
  const id = Object.keys(window.__timelines || {})[0];
  return { timeline: id, dur: id ? window.__timelines[id].duration() : null, total: window.__total, cues: (window.__cues || []).length, nodes: document.querySelectorAll("svg *").length };
});
console.log(JSON.stringify({ comp, size: `${W}x${Hh}`, ...info }));
if (process.argv.includes("--cues")) {
  const out = arg("--cues", "assets/audio/cues.json");
  const data = await p.evaluate(() => ({ cues: window.__cues, music: window.__music, total: window.__total, bpm: window.HF.BPM }));
  fs.writeFileSync(out, JSON.stringify(data, null, 1));
  console.log("wrote", out);
}
if (process.argv.includes("--sync-duration") && info.total) {
  const total = String(+info.total.toFixed(6));
  const synced = html.replace(/data-duration="[0-9.]+"/g, `data-duration="${total}"`);
  if (synced !== html) { fs.writeFileSync(comp, synced); console.log("data-duration ->", total); }
}
// A score that has not been built yet is expected, not an error.
const audio = (html.match(/<audio[^>]*src="([^"]+)"/) || [])[1];
const audioMissing = audio && !fs.existsSync(path.join(path.dirname(comp), audio));
const shown = errs.filter((e) => !(audioMissing && /ERR_FILE_NOT_FOUND/.test(e)));
if (audioMissing) console.log(`note: ${audio} not built yet (tools/make-audio.mjs + tools/master.mjs)`);
console.log(shown.join("\n") || "no errors");
await b.close();
