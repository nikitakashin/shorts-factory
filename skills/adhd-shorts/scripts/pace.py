# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy"]
# ///
"""pace.py [--stats <json>] [--video <файл.mp4> ...] [папки проектов…] — темп монтажа в цифрах и связь с удержанием.

Идея из ресерча 2026-10-17 (b-roll-finder и др.): вкус «как у референсов» переводится в числа — склейки в минуту,
медиана плана, доля зумов, стикеры/звуки в минуту, слова в секунду. Свои шортсы считаются точно по edl_out.json,
чужие референсы (--video) — по детектору смены сцены ffmpeg (только склейки и медиана плана).
--stats — JSON «папка проекта → stayed/apv/avg/views» (по умолчанию ~/youtube/статистика-шортсов.json):
тогда в конце — корреляция метрик с «Продолжили смотреть» и досмотром. Выборка маленькая — это подсказки, не закон.
Без папок — все проекты из статистики. Печатает markdown-таблицу."""
import json, re, subprocess, sys
from pathlib import Path
import numpy as np

ROOT = Path.home() / "Movies/Shorts"
args = sys.argv[1:]; STATS = Path.home() / "youtube/статистика-шортсов.json"; VIDEOS = []; DIRS = []
while args:
    a = args.pop(0)
    if a == "--stats": STATS = Path(args.pop(0)).expanduser()
    elif a == "--video": VIDEOS.append(Path(args.pop(0)).expanduser())
    else: DIRS.append(a)
ST = {k: v for k, v in json.load(open(STATS)).items() if not k.startswith("_")} if STATS.exists() else {}
if not DIRS and not VIDEOS: DIRS = list(ST)

def wd_of(d):
    p = Path(d).expanduser(); p = p if p.is_absolute() else ROOT / d
    if not p.exists():   # ролики разложены по каналам, выгруженные — в <канал>/Archive/ (status.py, 2026-10-22)
        p = next((q for q in [*ROOT.glob(f"*/{d}"), *ROOT.glob(f"*/Archive/{d}")] if q.is_dir()), p)
    return p if p.name.startswith(".") else p / ".work"

def own(d):
    wd = wd_of(d); E = json.load(open(wd / "edl_out.json")); fps = E["fps"]; segs = E["segs"]
    dur = E["frames"] / fps; L = [s["n"] / fps for s in segs if s["n"] > 0]
    real = sum(1 for i in range(1, len(segs)) if not (abs(segs[i - 1]["b"] - segs[i]["a"]) < 0.02 and segs[i - 1].get("src") == segs[i].get("src")
                                                       and not segs[i].get("broll") and not segs[i - 1].get("broll")))
    zoom = sum(s["n"] for s in segs if max(s.get("z", 1), s.get("z2", s.get("z", 1))) > 1.02) / max(1, E["frames"])
    fx = json.load(open(wd / "fx.json")) if (wd / "fx.json").exists() else {}
    sl = json.load(open(wd / "sfx_list.json"))["sounds"] if (wd / "sfx_list.json").exists() else None   # старые проекты — без списка
    words = json.load(open(wd / "words_out.json")) if (wd / "words_out.json").exists() else []
    lay = json.load(open(wd / "layout.json")) if (wd / "layout.json").exists() else {}
    gfx = sum(m["e"] - m["s"] for m in lay.get("modes", [])) / dur
    scr = sum(c.get("dur", (c.get("b", 0) - c.get("a", 0))) for c in fx.get("screen", [])) / dur
    broll = sum(s["n"] for s in segs if s.get("broll")) / max(1, E["frames"])
    memes = sum(1 for x in sl if "Meme" in x.get("file", "")) if sl is not None else None
    return dict(dur=dur, cuts_min=real / dur * 60, shots_min=(len(L) - 1) / dur * 60, med_shot=float(np.median(L)) if L else 0,
                zoom=zoom, stick_min=len(fx.get("stickers", [])) / dur * 60, sfx_min=len(sl) / dur * 60 if sl is not None else None, memes=memes,
                wps=len(words) / dur if words else None, gfx=gfx + scr + broll, hook=bool(fx.get("hook")))

def ext(v):
    """Чужой ролик: смены сцены детектором ffmpeg (порог 0.3)."""
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", str(v), "-vf", "select='gt(scene,0.3)',showinfo", "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    ts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", out)]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(v)], capture_output=True, text=True).stdout or 0)
    b = [0.0] + ts + [dur]; L = np.diff(b)
    return dict(dur=dur, cuts_min=len(ts) / dur * 60 if dur else 0, shots_min=len(ts) / dur * 60 if dur else 0, med_shot=float(np.median(L)) if len(L) else 0)

rows = []
for d in DIRS:
    try: m = own(d)
    except FileNotFoundError as e: print(f"пропускаю {d}: {e}", file=sys.stderr); continue
    rows.append((d, ST.get(d, {}), m))
for v in VIDEOS: rows.append((v.name, {}, ext(v)))

COLS = [("dur", "длина, с", "{:.0f}"), ("cuts_min", "склейки/мин", "{:.1f}"), ("shots_min", "смены плана/мин", "{:.1f}"),
        ("med_shot", "медиана плана, с", "{:.2f}"), ("zoom", "доля зума", "{:.0%}"), ("stick_min", "стикеры/мин", "{:.1f}"),
        ("sfx_min", "звуки/мин", "{:.1f}"), ("memes", "мемы", "{}"), ("wps", "слов/с", "{:.2f}"), ("gfx", "графика/экран/b-roll", "{:.0%}")]
hdr = "| Шортс | Продолжили | Досмотр | " + " | ".join(c[1] for c in COLS) + " |"
out = [hdr, "|" + "---|" * (3 + len(COLS))]
for d, s, m in sorted(rows, key=lambda r: -(r[1].get("stayed") or 0)):
    cells = [(f.format(m[k]) if m.get(k) is not None else "—") for k, _, f in COLS]
    out.append(f"| {s.get('title', d)} | {s.get('stayed', '—')}{'%' if s.get('stayed') else ''} | {s.get('apv', '—')}{'%' if s.get('apv') else ''} | " + " | ".join(cells) + " |")
print("\n".join(out))

with_st = [(s, m) for _, s, m in rows if s.get("stayed")]
if len(with_st) >= 4:
    print(f"\nКорреляция Пирсона с удержанием (n = {len(with_st)}; |r| < 0.5 — шум):")
    print("| Метрика | r с «Продолжили» | r с досмотром |\n|---|---|---|")
    for k, name, _ in COLS:
        xs = [(m[k], s["stayed"], s.get("apv")) for s, m in with_st if m.get(k) is not None]
        if len(xs) < 4: continue
        x = np.array([a for a, _, _ in xs], float)
        if x.std() == 0: continue
        r1 = np.corrcoef(x, [b for _, b, _ in xs])[0, 1]
        ya = [(a, c) for a, _, c in xs if c is not None]
        r2 = np.corrcoef([a for a, _ in ya], [c for _, c in ya])[0, 1] if len(ya) >= 4 else float("nan")
        print(f"| {name} | {r1:+.2f} | {r2:+.2f} |")
