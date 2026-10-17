# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""assemble_long.py <plan.json> — полное горизонтальное видео из глав: заставки между главами, музыка по главам.

plan.json:
{
 "out": "<папка проекта>",               # full.mp4, full_audio.wav, chapters.txt
 "work": "<рабочая папка>",              # кадры, заставки, промежуточные файлы
 "fps": 60,
 "cards": {"slot": 4.6, "in": 0.4, "out": 3.9, "seed": 7, "designs": [1, 2, 3, 4, 5]},
 "music": {"dir": "~/Samples/Background Music", "bed_lufs": -22, "card_lufs": -21, "fade": 0.4},
 "sections": [
   {"title": null, "track": "bang", "clips": [{"file": "a.mp4"}, {"file": "main.mp4", "from": 0, "to": 22.8}]},
   {"title": "Почему не готовые сервисы", "lead": "3–4 часа на один шорт", "track": "my bad", "clips": [...]},
   ...
 ]
}
Секция с "title" начинается с заставки (дизайн — случайный из cards.designs, без повторов подряд). Клип — готовое
видео со звуком (уже −14 LUFS): "from"/"to" — кусок в секундах (по умолчанию весь файл).
Заставка: шаблон assets/chapter_cards/template.html (HyperFrames): въезжает поверх последнего кадра прошлой главы,
уходит, открывая первый кадр следующей; под ней вжухи на входе и выходе.
Музыка: трек секции начинается на её заставке (громче, card_lufs) и идёт подложкой под главой (bed_lufs) с
приглушением за голосом (sidechain); между главами — короткий перехлёст. Трек короче главы — повторяется."""
import json, os, random, re, shutil, subprocess, sys
from pathlib import Path
import numpy as np, soundfile as sf

MUSIC_ONLY = "--music-only" in sys.argv   # пересобрать только музыку и сведение (видео и заставки — из прошлого прогона)
PLAN = json.load(open(sys.argv[1])); OUT = Path(PLAN["out"]).expanduser(); WK = Path(PLAN["work"]).expanduser(); WK.mkdir(parents=True, exist_ok=True)
FPS = PLAN.get("fps", 60); SR = 48000
CC = dict(slot=4.6, **{"in": 0.4}, out=3.9, seed=7, designs=[1, 2, 3, 4, 5]) | PLAN.get("cards", {})
MU = dict(dir="~/Samples/Background Music", bed_lufs=-18, card_lufs=-21, fade=0.4) | PLAN.get("music", {})
SKILL = Path(__file__).resolve().parent.parent
CARDS_HOME = Path(os.environ.get("CARDS_HOME", Path.home() / "Movies/Shorts/_cards"))
def run(a, **k): return subprocess.run(a, check=True, **k)
def dur(f): return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout)

# ---------- 1. куски и порядок ----------
secs = PLAN["sections"]
for s in secs:
    for c in s["clips"]:
        c["file"] = str(Path(c["file"]).expanduser()); c.setdefault("from", 0.0)
        c.setdefault("to", dur(c["file"])); c["dur"] = round((c["to"] - c["from"]) * FPS) / FPS
chap = [s for s in secs if s.get("title")]
rng = random.Random(CC["seed"]); seq = []
while len(seq) < len(chap):
    pool = CC["designs"][:]; rng.shuffle(pool)
    if seq and pool[0] == seq[-1]: pool.append(pool.pop(0))
    seq += pool
for s, d in zip(chap, seq): s["design"] = d

# ---------- 2. кадры для фона заставок: последний кадр до неё и первый после ----------
def vdur(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True).stdout.strip() or dur(f))
def frame(f, t, out):   # видео части бывает короче её звука — кадр берём не дальше конца видео
    t = min(max(0, t), vdur(f) - 2 / FPS)
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", f, "-frames:v", "1", "-q:v", "2", "-strict", "unofficial", str(out)])
media = CARDS_HOME / "assets/media"; media.mkdir(parents=True, exist_ok=True)
if not MUSIC_ONLY:
    for f in media.glob("card*"): f.unlink()
prev_last = None
for i, s in enumerate(secs):
    if MUSIC_ONLY: break
    if s.get("title"):
        k = chap.index(s) + 1; a, b = media / f"card{k:02d}_a.jpg", media / f"card{k:02d}_b.jpg"
        lc = prev_last; frame(lc["file"], lc["to"] - 1.5 / FPS, a)
        fc = s["clips"][0]; frame(fc["file"], fc["from"] + 0.5 / FPS, b)
        s["prev"], s["next"] = f"assets/media/{a.name}", f"assets/media/{b.name}"
    prev_last = s["clips"][-1]

# ---------- 3. заставки (HyperFrames) ----------
cards_mp4 = WK / "cards.mp4"
if chap and not MUSIC_ONLY:
    # длину композиции HyperFrames читает из атрибута ДО запуска скриптов — ставим её прямо в HTML
    # (2026-10-14: с длиной из шаблона отрендерилась одна заставка из 12, видео ушло от звука)
    html = (SKILL / "assets/chapter_cards/template.html").read_text().replace('data-duration="5"', f'data-duration="{len(chap) * CC["slot"]:.3f}"')
    (CARDS_HOME / "index.html").write_text(html)
    data = dict(slot=CC["slot"], **{"in": CC["in"]}, out=CC["out"], cards=[
        dict(n=chap.index(s) + 1, total=len(chap), title=s["title"], lead=s.get("lead", ""), design=s["design"],
             prev=s["prev"], next=s["next"], list=[c["title"] for c in chap]) for s in chap])
    (CARDS_HOME / "assets/cards.js").write_text("window.CARDS = " + json.dumps(data, ensure_ascii=False) + ";\n")
    env = dict(os.environ, DO_NOT_TRACK="1", HYPERFRAMES_SKIP_SKILLS="1")
    run(["npx", "hyperframes", "render", ".", "-o", str(cards_mp4), "-f", str(FPS), "--crf", "10", "--quiet"], cwd=CARDS_HOME, env=env)
    cd_ = vdur(cards_mp4)
    if abs(cd_ - len(chap) * CC["slot"]) > 0.1: raise SystemExit(f"заставки: {cd_:.2f} с вместо {len(chap) * CC['slot']:.2f} — композиция обрезана")
    print(f"заставки: {len(chap)} шт., дизайны {[s['design'] for s in chap]}", flush=True)

# ---------- 4. склейка видео и «диалога» (голос+звуки частей, вжухи заставок) ----------
kit = json.load(open(SKILL / "assets/sfx_kit.json")); libs = {k: Path(v).expanduser() for k, v in kit.get("libs", {}).items()}
import glob
def role_files(r):
    out = []
    for p in kit["roles"][r]["files"]:
        lib, rel = p.split(":", 1) if ":" in p and p.split(":", 1)[0] in libs else ("", p)
        out += sorted(glob.glob(str(libs.get(lib, Path(kit.get("root", "~")).expanduser()) / rel)))
    return out
WH = role_files("whoosh")
pieces, t, marks = [], 0.0, []          # pieces: (kind, file, from, dur); marks: (t, section index, card?)
for i, s in enumerate(secs):
    if s.get("title"):
        k = chap.index(s)
        pieces.append(("card", str(cards_mp4), k * CC["slot"], CC["slot"])); marks.append((t, i, True)); t += CC["slot"]
    else: marks.append((t, i, False))
    s["t_body"] = t
    for c in s["clips"]: pieces.append(("clip", c["file"], c["from"], c["dur"])); t += c["dur"]
    s["t_end"] = t
TOTAL = t
args = ["ffmpeg", "-v", "error", "-y"]; fc = []; vi = []
for j, (kind, f, a, d) in enumerate(pieces):
    args += ["-ss", f"{a:.4f}", "-t", f"{d:.4f}", "-i", f]
    # tpad: видео части бывает короче её звука на пару кадров — иначе всё после неё уехало бы от звука
    fc.append(f"[{j}:v]fps={FPS},scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,tpad=stop_mode=clone:stop_duration=0.5,trim=duration={d:.4f},setpts=PTS-STARTPTS[v{j}]")
    vi.append(f"[v{j}]")
fc.append("".join(vi) + f"concat=n={len(pieces)}:v=1:a=0[v]")
video_only = WK / "long_video.mp4"
if not MUSIC_ONLY: run(args + ["-filter_complex", ";".join(fc), "-map", "[v]", "-c:v", "libx264", "-crf", "15", "-preset", "medium", "-pix_fmt", "yuv420p", str(video_only)])
if abs(vdur(video_only) - TOTAL) > 0.1: raise SystemExit(f"склейка: видео {vdur(video_only):.2f} с, а должно быть {TOTAL:.2f} — что-то не попало")
print(f"видео склеено: {TOTAL:.2f} с", flush=True)

def load(f, a=0.0, d=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{a:.4f}"] + (["-t", f"{d:.4f}"] if d else []) + ["-i", str(f), "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    x = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32).reshape(-1, 2).astype(np.float64)
    return x
N = int(round(TOTAL * SR)); dlg = np.zeros((N, 2)); t = 0.0
for kind, f, a, d in ([] if MUSIC_ONLY else pieces):
    n = int(round(d * SR)); k0 = int(round(t * SR))
    if kind == "clip":
        x = load(f, a, d)[:n]; dlg[k0:k0 + len(x)] += x
    else:
        for off, w in ((CC["in"] - 0.08, WH[0] if WH else None), (CC["out"] - 0.08, WH[1 % len(WH)] if WH else None)):
            if not w: continue
            x = load(w); x = x / (np.abs(x).max() + 1e-9) * 0.35; s0 = k0 + int(off * SR); dlg[s0:s0 + len(x)] += x[: max(0, N - s0)]
    t += d
if not MUSIC_ONLY: sf.write(WK / "dialog.wav", dlg, SR)

# ---------- 5. музыка ----------
def lufs(f):
    o = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float([l for l in o.splitlines() if l.strip().startswith("I:")][-1].split()[1])
mdir = Path(MU["dir"]).expanduser(); tracks = sorted(mdir.glob("*.mp3")) + sorted(mdir.glob("*.wav"))
def track(name):
    m = [p for p in tracks if p.name.lower().startswith(name.lower())]
    if not m: raise SystemExit(f"музыка: нет трека «{name}» в {mdir}")
    return m[0]
mus = np.zeros((N, 2)); fade = MU["fade"]
for i, s in enumerate(secs):
    if not s.get("track"): continue
    p = track(s["track"]); L = lufs(p); x = load(p)
    t0 = marks[i][0]; t1 = s["t_end"] + (fade if i + 1 < len(secs) else 0); n = int(round((t1 - t0) * SR))
    while len(x) < n:                                                   # трек короче главы — повтор с перехлёстом 1 с
        xf = int(SR); x = np.concatenate([x[:-xf], x[-xf:] * np.linspace(1, 0, xf)[:, None] + x[:xf] * np.linspace(0, 1, xf)[:, None], x[xf:]])
    x = x[:n].copy()
    g_bed, g_card = 10 ** ((MU["bed_lufs"] - L) / 20), 10 ** ((MU["card_lufs"] - L) / 20)
    env = np.full(n, g_bed); tb = s["t_body"] - t0
    if s.get("title"):
        nb = int(tb * SR); env[:nb] = g_card; r = min(int(0.9 * SR), n - nb)
        env[nb:nb + r] = np.linspace(g_card, g_bed, r)                  # после заставки — плавно в подложку
    if i == len(secs) - 1:                                              # финал: последние 2.5 с громче и затухание
        r = int(2.5 * SR); env[-r:] = np.linspace(g_bed, g_card, r) * np.linspace(1, 0, r) ** .5
    fi = int(0.25 * SR); env[:fi] *= np.linspace(0, 1, fi); fo = int(fade * SR); env[-fo:] *= np.linspace(1, 0, fo)
    k0 = int(t0 * SR); mus[k0:k0 + n] += x * env[:, None]
sf.write(WK / "music.wav", mus, SR)
print("музыка готова", flush=True)

# ---------- 6. сведение: музыка приглушается за голосом, −14 LUFS ----------
mix = WK / "long_mix.wav"
F = ("[1:a]asplit=2[sc][d];[0:a][sc]sidechaincompress=threshold=0.03:ratio=2.5:attack=20:release=400:makeup=1[m];"
     "[d][m]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11")
J = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(WK / "music.wav"), "-i", str(WK / "dialog.wav"), "-filter_complex", F + ":print_format=json", "-f", "null", "-"],
                   capture_output=True, text=True).stderr
j = json.loads(J[J.rindex("{"):J.rindex("}") + 1])
meas = f"measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}"
run(["ffmpeg", "-v", "error", "-y", "-i", str(WK / "music.wav"), "-i", str(WK / "dialog.wav"), "-filter_complex",
     F + f":{meas}:linear=true,alimiter=limit=0.7:level=disabled[a]", "-map", "[a]", "-ar", str(SR), str(mix)])
run(["ffmpeg", "-v", "error", "-y", "-i", str(video_only), "-i", str(mix), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
     "-shortest", "-movflags", "+faststart", str(OUT / "full.mp4")])
shutil.copy(mix, OUT / "full_audio.wav")

# ---------- 7. главы для YouTube ----------
def mmss(x): return f"{int(x // 60)}:{int(x % 60):02d}"
lines = ["0:00 " + (secs[0].get("chapter") or "Вступление")]
for i, s in enumerate(secs[1:], 1):
    if s.get("title"): lines.append(f"{mmss(marks[i][0])} {s['title']}")
    elif s.get("chapter"): lines.append(f"{mmss(marks[i][0])} {s['chapter']}")
(OUT / "chapters.txt").write_text("\n".join(lines) + "\n")
o = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(OUT / "full.mp4"), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
print("\n".join(l for l in o.splitlines() if re.match(r"\s+(I:|Peak:)", l)))
print(f"→ {OUT / 'full.mp4'}  {mmss(TOTAL)}\n" + "\n".join(lines))
