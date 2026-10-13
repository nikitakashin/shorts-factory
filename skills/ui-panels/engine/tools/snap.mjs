// Frame snapshots + contact sheet (без drawtext: в brew-ffmpeg его нет; порядок кадров = порядок --at) for any composition (eventful seeks, like the renderer).
//   node tools/snap.mjs --comp shorts.html --at 1,2.5,4 --out scratch/snaps [--cols 4] [--w 360]
import puppeteer from "puppeteer-core";
import { execFileSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const comp = arg("--comp", "index.html");
const times = arg("--at", "0").split(",").map(Number);
const out = arg("--out", "scratch/snaps");
const cols = +arg("--cols", 4);
const tw = +arg("--w", 0);
const html = fs.readFileSync(comp, "utf8");
const W = +(html.match(/data-composition-id="[^"]+"[^>]*data-width="(\d+)"/) || [0, 1920])[1];
const H = +(html.match(/data-composition-id="[^"]+"[^>]*data-height="(\d+)"/) || [0, 1080])[1];
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
const b = await puppeteer.launch({ executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true, args: ["--allow-file-access-from-files", "--force-color-profile=srgb"] });
const p = await b.newPage();
await p.setViewport({ width: W, height: H });
await p.goto("file://" + path.resolve(comp), { waitUntil: "networkidle0" });
await p.evaluate(() => document.fonts.ready);
const files = [];
for (const [i, t] of times.entries()) {
  await p.evaluate((tt) => { const tl = Object.values(window.__timelines)[0]; tl.seek(tt, false); }, t);
  const f = path.join(out, `f-${String(i).padStart(2, "0")}-${t.toFixed(2)}s.png`);
  await p.screenshot({ path: f });
  files.push(f);
}
await b.close();
const cellW = tw || (W > H ? 480 : 270);
const label = (f) => path.basename(f).replace(/^f-\d+-/, "").replace(".png", "");
const inputs = files.flatMap((f) => ["-i", f]);
const rows = Math.ceil(files.length / cols);
const filters = files.map((f, i) => `[${i}:v]scale=${cellW}:-1,pad=iw+4:ih+4:2:2:white[v${i}]`);
const pads = [];
for (let i = files.length; i < rows * cols; i++) { filters.push(`[0:v]scale=${cellW}:-1,pad=iw+4:ih+4:2:2:white,drawbox=c=black:t=fill[v${i}]`); pads.push(i); }
const all = Array.from({ length: rows * cols }, (_, i) => `[v${i}]`).join("");
filters.push(`${all}xstack=inputs=${rows * cols}:layout=${Array.from({ length: rows * cols }, (_, i) => `${(i % cols) ? Array.from({ length: i % cols }, () => "w0").join("+") : "0"}_${Math.floor(i / cols) ? Array.from({ length: Math.floor(i / cols) }, () => "h0").join("+") : "0"}`).join("|")}:fill=black[o]`);
execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", ...inputs, "-filter_complex", filters.join(";"), "-map", "[o]", "-frames:v", "1", path.join(out, "sheet.jpg")]);
console.log(path.join(out, "sheet.jpg"), files.length, "frames");
