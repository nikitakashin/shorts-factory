# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy","opencv-python-headless<4.13","pillow","soundfile"]
# ///
"""render.py <workdir> — картинка + SFX для СДВГ-шортса.

Читает: edl_out.json (build_voice.py), words_out.json (transcribe.py по voice.wav), fx.json.
UI-панели (скилл ui-panels): если рядом лежат layout.json и gfx.mp4, графика встаёт сверху (split: лицо
внизу, субтитры на стыке) или на весь кадр (full), а звуки панелей добавляются в sfx.wav.
Пишет:  video.mp4 (без звука, 1080x1920, fps из EDL) и sfx.wav (эффекты, та же длина, что voice.wav).
Субтитры и стикеры рисуются через Pillow: в brew-сборке ffmpeg часто нет drawtext/libass.
Сообщения «Broken pipe» от декодеров — норма: план дочитывается ровно до n кадров, хвост бросаем."""
import json, math, random, re, subprocess, sys
from pathlib import Path
import cv2, numpy as np, soundfile as sf
from PIL import Image, ImageDraw, ImageFont

WD = Path(sys.argv[1])
E = json.load(open(WD / "edl_out.json")); FX = json.load(open(WD / "fx.json"))
FPS = E["fps"]; W, H = 1080, 1920; NF = E["frames"]; SRC = E["src"]
# Горизонтальный ролик из вертикальной съёмки ("canvas": "landscape" в fx.json): выход 1920×1080,
# вертикальный кадр (со всеми зумами/тряской) — столбик 608×1080 поверх размытого фона; при UI-панели
# графика занимает левые 1312 px, лицо — справа. Субтитры фразами внизу, стикеры/хук — в координатах 1920×1080.
LAND = FX.get("canvas") == "landscape"
OW, OH = (1920, 1080) if LAND else (W, H)
COLW = round(OH * W / H)            # ширина столбика лица в горизонтали (608)
if not Path(SRC).is_file():   # иначе декодер молча отдаёт ноль кадров и весь ролик выходит чёрным
    raise SystemExit(f"Исходник не найден: {SRC}\nЕго переименовали/удалили? Укажи новый путь в edl.json и edl_out.json.")
CAP = dict(y=1380, size=118, max_words=2, max_chars=13, gap=0.3, hold=0.35, lead=0.04,
           color="#FFFFFF", active="#FFE500", stroke=12, pop=0.22, font=None) | FX.get("caption", {})

LAY = json.load(open(WD / "layout.json")) if (WD / "layout.json").exists() and (WD / "gfx.mp4").exists() else None
if (WD / "panels.json").exists() and LAY is None and "--sfx-only" not in sys.argv:
    # 2026-10-09: рендер графики прервался («render_cancelled_parent_exited»), gfx.mp4 не появился —
    # и ролик молча собрался без панелей. Лучше упасть.
    raise SystemExit("Есть panels.json, но нет gfx.mp4/layout.json — сначала render_gfx.sh (и дождись его конца)")
SPLIT = int(LAY["split"]) if LAY else 0
def mode_at(t):
    for m in (LAY or {}).get("modes", []):
        if m["s"] <= t < m["e"]: return m["mode"]
    return "face"
CAPY = {"face": CAP["y"], "split": SPLIT, "full": CAP["y"]} | (LAY or {}).get("caption_y", {})
if LAY: print(f"UI-панели: {len(LAY['modes'])} шт., стык на {SPLIT}px")

def rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
FONT_CANDIDATES = [CAP["font"], str(Path(__file__).resolve().parent.parent / "assets/fonts/Montserrat.ttf"),
                   str(Path.home() / ".cache/content-factory/fonts/Montserrat.ttf"),
                   "/System/Library/Fonts/Supplemental/Arial Black.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
FONT = next(f for f in FONT_CANDIDATES if f and Path(f).is_file())
def font(sz, wt=900):
    f = ImageFont.truetype(FONT, int(sz))
    try: f.set_variation_by_axes([wt])
    except Exception: pass
    return f

# ---------- слова → токены субтитров ----------
raw = json.load(open(WD / "words_out.json"))
def norm(w): return re.sub(r"[^\wёЁ.\-₽]", "", w.lower()).strip(".")
fixes = {norm(k): v for k, v in FX.get("fixes", {}).items()}
seqs = [([norm(x) for x in r["seq"]], r["to"]) for r in FX.get("replace", [])]
toks = []; i = 0
while i < len(raw):
    w = raw[i]; s, e = w["s"], w["e"]; txt = re.sub(r"[,?!…]|\.+$", "", w["w"]); last = w["w"]
    hit = next(((L, to) for L, to in seqs if [norm(x["w"]) for x in raw[i:i + len(L)]] == L), None)
    if hit:
        L, to = hit; txt = to; e = raw[i + len(L) - 1]["e"]; last = raw[i + len(L) - 1]["w"]; i += len(L) - 1
    else:
        while i + 1 < len(raw) and re.match(r"^[-.]\w", raw[i + 1]["w"]):   # 20 .8 / телеграм -канал / 26 -я
            i += 1; txt += re.sub(r"[,?!…]|\.+$", "", raw[i]["w"]); e = raw[i]["e"]; last = raw[i]["w"]
        k = norm(txt)
        if k in fixes: txt = fixes[k]
    if txt:
        toks.append(dict(t=txt.upper() if CAP.get("upper", True) else txt, s=s, e=e, end=bool(re.search(r"[.?!,…]$", last))))
    i += 1
chunks = []; cur = []
for t in toks:
    if cur and (len(cur) >= CAP["max_words"] or len(" ".join(x["t"] for x in cur + [t])) > CAP["max_chars"]
                or t["s"] - cur[-1]["e"] > CAP["gap"]):
        chunks.append(cur); cur = []
    cur.append(t)
    if t["end"]: chunks.append(cur); cur = []
if cur: chunks.append(cur)
for j, c in enumerate(chunks):
    nxt = chunks[j + 1][0]["s"] - CAP["lead"] if j + 1 < len(chunks) else NF / FPS
    chunks[j] = dict(ws=c, s=c[0]["s"] - CAP["lead"], e=min(nxt, c[-1]["e"] + CAP["hold"]))
(WD / "captions.txt").write_text("\n".join(f'{c["s"]:6.2f}-{c["e"]:6.2f}  ' + " ".join(w["t"] for w in c["ws"]) for c in chunks))
print(f"{len(toks)} слов, {len(chunks)} фраз субтитров → captions.txt")

seg_t = [s["f0"] / FPS for s in E["segs"]]
def at(spec, after=0.0):
    """число → секунды выхода; "seg:N" → начало плана N; "СЛОВО" → первое слово, содержащее его, после `after` сек."""
    if isinstance(spec, (int, float)): return float(spec)
    if spec.startswith("seg:"): return seg_t[int(spec[4:])]
    for t in toks:
        if t["s"] >= after and spec.upper() in t["t"].upper(): return t["s"]
    raise SystemExit(f"fx.json: слово «{spec}» после {after}s не найдено в субтитрах (см. captions.txt)")
def T(d): return at(d["at"], d.get("after", 0.0))

# ---------- отрисовка ----------
cache = {}
def caption_img(ci, act):
    if (ci, act) in cache: return cache[(ci, act)]
    ws = chunks[ci]["ws"]; sz = CAP["size"]; st = CAP["stroke"]
    while True:
        f = font(sz); sp = int(sz * 0.28)
        widths = [f.getbbox(w["t"], stroke_width=st)[2] for w in ws]
        tot = sum(widths) + sp * (len(ws) - 1)
        if tot <= CAP.get("max_w", OW - 100 if LAND else W - 100) or sz < 40: break
        sz -= 6
    im = Image.new("RGBA", (tot + 40, int(sz * 1.5) + 40), (0, 0, 0, 0)); d = ImageDraw.Draw(im); x = 20
    for k, w in enumerate(ws):
        d.text((x, 20), w["t"], font=f, fill=rgb(CAP["active"] if k == act else CAP["color"]) + (255,),
               stroke_width=st, stroke_fill=(0, 0, 0, 255))
        x += widths[k] + sp
    cache[(ci, act)] = a = np.array(im); return a

def sticker(text, bg="#E61E28", fg="#FFFFFF", size=100, rot=-6, **_):
    f = font(size); sp = int(size * 0.18)          # "\n" в тексте — несколько строк (для хука)
    bb = ImageDraw.Draw(Image.new("RGBA", (1, 1))).multiline_textbbox((0, 0), text, font=f, spacing=sp, align="center")
    pw, ph = int(round(bb[2])) + 60, int(round(bb[3])) + 50
    im = Image.new("RGBA", (pw, ph), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=26, fill=rgb(bg) + (255,), outline=(0, 0, 0, 255), width=8)
    d.multiline_text((30, 18), text, font=f, fill=rgb(fg) + (255,), spacing=sp, align="center")
    return np.array(im.rotate(rot, expand=True, resample=Image.BICUBIC))

def blend(fr, img, cx, cy, scale=1.0):
    if scale != 1.0: img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    FH_, FW_ = fr.shape[:2]
    h, w = img.shape[:2]; x0, y0 = int(cx - w / 2), int(cy - h / 2)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(FW_, x0 + w), min(FH_, y0 + h)
    if xa >= xb or ya >= yb: return
    sub = img[ya - y0:yb - y0, xa - x0:xb - x0]; al = sub[..., 3:4].astype(np.float32) / 255
    roi = fr[ya:yb, xa:xb]; roi[:] = (roi * (1 - al) + sub[..., :3] * al).astype(np.uint8)

def ease(p): return 1 - (1 - min(1, max(0, p))) ** 3

STICK = [(T(s), s.get("dur", 1.3), sticker(**s), s.get("x", 540), s.get("y", 340), s.get("instant", False))
         for s in FX.get("stickers", [])]
# Хук: плашка с главной мыслью видна ЦЕЛИКОМ с первого кадра (без анимации появления). Половина ленты решает
# листать за ~1 с, а субтитры по 1–2 слова собирают мысль за 3 с (первый шортс: «продолжили смотреть» 49.6%).
HOOK = FX.get("hook")
if HOOK:
    HOOK = dict(dict(at=0.0, dur=2.6, bg="#FFE500", fg="#000000", size=92, rot=-3, y=300, instant=True, sound="pop"), **HOOK)
    STICK.insert(0, (0.0, HOOK["dur"], sticker(**HOOK), HOOK.get("x", 540), HOOK["y"], True))
# для черновика CapCut (capcut_draft.py): субтитры по словам и плашки с уже посчитанными временами
_stk = ([dict(HOOK, t=0.0)] if HOOK else []) + [dict(dict(dur=1.3, x=540, y=340, bg="#E61E28", fg="#FFFFFF", size=100, rot=-6), **s, t=T(s)) for s in FX.get("stickers", [])]
(WD / "stickers").mkdir(exist_ok=True)
for _i, _d in enumerate(_stk):        # плашки картинками — в CapCut текст с подложкой из файла не встаёт
    Image.fromarray(sticker(**_d)).save(WD / "stickers" / f"{_i:02d}.png"); _d["png"] = str(WD / "stickers" / f"{_i:02d}.png")
json.dump(dict(caption=CAP, landscape=LAND, chunks=[dict(s=c["s"], e=c["e"], ws=[dict(t=w["t"], s=w["s"], e=w["e"]) for w in c["ws"]]) for c in chunks],
               stickers=[{k: v for k, v in d.items() if k in ("text", "t", "dur", "x", "y", "bg", "fg", "size", "rot", "png")} for d in _stk]),
          open(WD / "overlays.json", "w"), ensure_ascii=False, indent=1)
SHAKE = [(T(s), s.get("dur", 0.4), s.get("amp", 16)) for s in FX.get("shake", [])]
FLASH = [T(s) for s in FX.get("flash", [])]
PUNCH = [(T(s), s.get("amount", 0.18)) for s in FX.get("punch", [])]

# ---------- SFX: библиотека сэмплов (fx.json "kit") или синтез как запасной вариант ----------
SR = 48000; SFX = dict(whoosh=0.35, pop=0.6, boom=0.85, ticks=0.5, end_pop=0.6)
if FX.get("sfx") is False: SFX = {k: 0.0 for k in SFX}                # "sfx": false — ролик только с голосом
elif not FX.get("kit"): SFX |= FX.get("sfx", {})                      # для синтеза "sfx" — громкости; для kit — множители
rng = np.random.default_rng(3)
def env(n, a, d): t = np.arange(n) / SR; return np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / d)
def whoosh(dur=0.32, f0=300, f1=3000):
    n = int(dur * SR); x = rng.standard_normal(n); y = np.zeros(n); fc = np.geomspace(f0, f1, n); lp = bp = 0.0
    for k in range(n):
        g = fc[k] / SR * 2 * math.pi; lp += g * bp; hp = x[k] - lp - 0.6 * bp; bp += g * hp; y[k] = bp
    y *= np.sin(np.linspace(0, math.pi, n)) ** 2; return y / (np.abs(y).max() + 1e-9) * 0.5
def pop(f0=900, f1=180, dur=0.09):
    n = int(dur * SR); ph = 2 * math.pi * np.cumsum(np.geomspace(f0, f1, n)) / SR; return np.sin(ph) * env(n, 0.002, 0.03) * 0.7
def boom(dur=0.9):
    n = int(dur * SR); ph = 2 * math.pi * np.cumsum(np.geomspace(110, 38, n)) / SR
    return np.tanh((np.sin(ph) * env(n, 0.003, 0.28) + 0.25 * rng.standard_normal(n) * env(n, 0.001, 0.03)) * 2) * 0.8
def tick(): n = int(0.02 * SR); return rng.standard_normal(n) * env(n, 0.0005, 0.004) * 0.6
voice, _ = sf.read(WD / "voice.wav"); sfx = np.zeros((len(voice), 2))
SFX_LOG = []
def put(sig, t, g):
    if sig.ndim == 1: sig = np.stack([sig, sig], 1)
    k = int(max(0, t) * SR); sig = sig[: max(0, len(sfx) - k)]; sfx[k:k + len(sig)] += sig * g
cuts = [k for k in range(1, len(E["segs"]))   # вжух на склейке, где меняется крупность или начинается/кончается b-roll
        if E["segs"][k].get("z", 1) != E["segs"][k - 1].get("z", 1) or E["segs"][k].get("broll") or E["segs"][k - 1].get("broll")]
brolls = [(seg_t[k], s["n"] / FPS) for k, s in enumerate(E["segs"]) if s.get("broll") and not s.get("endcard")]

# --- библиотека сэмплов (fx.json "kit": путь к kit-файлу; относительный — от assets/ скилла) ---
def load_kit():
    k = FX.get("kit")
    if not k or FX.get("sfx") is False: return None
    p = Path(k).expanduser()
    if not p.is_absolute(): p = Path(__file__).resolve().parent.parent / "assets" / k
    kit = json.load(open(p))
    libs = {k: str(Path(v).expanduser()) for k, v in kit.get("libs", {}).items()}
    if "root" in kit: libs.setdefault("", str(Path(kit["root"]).expanduser()))
    kit["libs"] = libs; return kit
KIT = load_kit()
if KIT:
    import glob
    _dec, _peak, _pools, krng = {}, {}, {}, random.Random(FX.get("seed", 7))
    def decode(f):
        if f not in _dec:   # 96k/24bit → 48k float стерео через ffmpeg, нормализация пика к 1.0
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-ar", str(SR), "-ac", "2", "-f", "f32le", "-"],
                                 capture_output=True, check=True).stdout
            a = np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64); _peak[f] = np.abs(a).max() + 1e-9; _dec[f] = a / _peak[f]
        return _dec[f]
    def pick(spec):
        """spec — имя роли из kit или путь/glob "lib:путь" (lib — ключ из kit.libs, без префикса — основная библиотека).
        Варианты идут по кругу в перемешанном порядке (без повторов подряд)."""
        role = KIT["roles"].get(spec, {"files": [spec]})
        if spec not in _pools:
            files = set()
            for p in role["files"]:
                lib, rel = p.split(":", 1) if ":" in p and p.split(":", 1)[0] in KIT["libs"] else ("", p)
                full = Path(KIT["libs"].get(lib, "")) / rel
                # точное имя файла берём как есть: в мемных именах бывают [ ] * ?, ломающие glob
                files |= {str(full)} if full.is_file() else set(glob.glob(str(full), recursive=True))
            files = sorted(files)
            if not files: raise SystemExit(f"SFX: нет файлов для «{spec}» (библиотеки: {KIT['libs']})")
            krng.shuffle(files); _pools[spec] = [files, 0]
        files, i = _pools[spec]; _pools[spec][1] += 1
        return files[i % len(files)], role
    def place(spec, t, gain_db=None, dur=None, mult=1.0, max_len=None):
        if not spec or mult == 0: return
        f, r = pick(spec); a = decode(f)
        if r.get("mode") == "bed" and dur:          # подложка на длину b-roll: повтор + фейды
            n = int(dur * SR); a = np.tile(a, (n // len(a) + 1, 1))[:n].copy()
            fd = min(int(0.04 * SR), n // 4); a[:fd] *= np.linspace(0, 1, fd)[:, None]; a[-fd:] *= np.linspace(1, 0, fd)[:, None]
            off = 0
        else:
            ml = max_len or r.get("max_len")      # обрезка длинных мемов: из записи fx.json или из роли kit
            if ml and len(a) > ml * SR:
                a = a[: int(ml * SR)].copy(); fd = int(0.12 * SR); a[-fd:] *= np.linspace(1, 0, fd)[:, None]
            e = np.abs(a).max(1); hop = SR // 200
            env_ = np.array([e[i:i + hop].max() for i in range(0, len(e), hop)])
            # peak — пик сэмпла ровно в момент t (вжух на склейке); onset — атака на t (удар на слове)
            off = (env_.argmax() if r.get("align") == "peak" else np.argmax(env_ > env_.max() * 0.1)) * hop
        g = 10 ** ((gain_db if gain_db is not None else r.get("gain_db", -8)) / 20) * mult
        k0 = int(t * SR) - off; skip = 0
        if k0 < 0: a = a[-k0:]; skip = -k0; k0 = 0
        put(a, k0 / SR, g)
        # для черновика CapCut (capcut_draft.py): какой файл, где, с какого места и на какой громкости
        SFX_LOG.append(dict(file=f, t=round(k0 / SR, 4), src=round(skip / SR, 4), dur=round(len(a) / SR, 4),
                            gain=float(g / _peak[f]), peak=float(_peak[f]), spec=spec))
    M = FX.get("sfx", {}) if isinstance(FX.get("sfx"), dict) else {}
    for k in cuts: place("whoosh", seg_t[k], mult=M.get("whoosh", 1.0))
    for s in FX.get("stickers", []): place(s.get("sound", "pop"), T(s), s.get("gain_db"), mult=M.get("pop", 1.0), max_len=s.get("max_len"))
    for s in FX.get("boom", []): place(s.get("sound", "boom"), T(s), s.get("gain_db"), mult=M.get("boom", 1.0))
    for t, d in brolls: place("ticks", t, dur=d, mult=M.get("ticks", 1.0))
    for s in FX.get("sounds", []): place(s["sound"], T(s), s.get("gain_db"), max_len=s.get("max_len"))
    if HOOK and HOOK.get("sound"): place(HOOK["sound"], 0.0, HOOK.get("gain_db"))
    for k, s in enumerate(E["segs"]):
        if s.get("endcard"): place((FX.get("endcard") or {}).get("sound", "sparkle"), seg_t[k])
    for s in (LAY or {}).get("sounds", []): place(s["sound"], s["t"], s.get("gain_db"))
    if FX.get("end_pop", True) and chunks: place("end", chunks[-1]["s"], mult=M.get("end_pop", 1.0))
    print(f"SFX из библиотеки: {len(_dec)} разных сэмплов")
else:                                                # синтез — когда библиотеки нет
    WH = [whoosh(), whoosh(0.25, 600, 5000)]
    for k in cuts: put(WH[k % 2], seg_t[k] - 0.12, SFX["whoosh"])
    for t, *_ in STICK: put(pop(), t, SFX["pop"])
    for s in FX.get("boom", []): put(boom(), T(s), SFX["boom"])
    for t, d in brolls:
        for j in range(int(d / 0.12)): put(tick(), t + j * 0.12, SFX["ticks"])
    if FX.get("end_pop", True) and chunks: put(pop(1400, 300, 0.12), chunks[-1]["s"], SFX["end_pop"])
    for s in (LAY or {}).get("sounds", []): put(WH[0] if s["sound"] == "whoosh" else pop(), s["t"] - (0.12 if s["sound"] == "whoosh" else 0), SFX["whoosh" if s["sound"] == "whoosh" else "pop"])
if FX.get("sfx") is False: sfx[:] = 0
sfx *= 10 ** (FX.get("sfx_gain_db", -3) / 20)   # общий уровень всех SFX; автор просил «чутка потише» (2026-10-09) → по умолчанию −3 дБ
sf.write(WD / "sfx.wav", sfx, SR)
json.dump(dict(global_gain=10 ** (FX.get("sfx_gain_db", -3) / 20), sounds=SFX_LOG), open(WD / "sfx_list.json", "w"), ensure_ascii=False, indent=1)
if "--sfx-only" in sys.argv: print("→", WD / "sfx.wav"); sys.exit(0)   # быстро перебрать звуки без перерендера картинки

# ---------- видео ----------
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-r", str(FPS),
    "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(FX.get("crf", 17)), "-pix_fmt", "yuv420p", str(WD / "video.mp4")],
    stdin=subprocess.PIPE)
BAR = FX.get("progress_bar", "#FFE500"); FACE_Y = FX.get("face_y", 800); fi = 0
# Финальная заставка (план с "endcard": true): обложка полного видео + призыв. В Shorts ссылка «Связанное
# видео» стоит внизу экрана — поэтому «ССЫЛКА ВНИЗУ». Только для вертикали.
EC = FX.get("endcard") or {}
EC_BG = EC_IMG = EC_ST = None
if EC.get("image") and not LAND:
    _ci = cv2.cvtColor(cv2.imread(str(Path(EC["image"]).expanduser())), cv2.COLOR_BGR2RGB)
    _h, _w = _ci.shape[:2]; _s = max(W / _w, H / _h)
    _bg = cv2.resize(_ci, (int(_w * _s) + 1, int(_h * _s) + 1)); _y0 = (_bg.shape[0] - H) // 2; _x0 = (_bg.shape[1] - W) // 2
    EC_BG = (cv2.GaussianBlur(_bg[_y0:_y0 + H, _x0:_x0 + W], (0, 0), 25) * 0.45).astype(np.uint8)
    EC_IMG = cv2.resize(_ci, (1000, int(_h * 1000 / _w)), interpolation=cv2.INTER_AREA)
    EC_IMG = np.dstack([EC_IMG, np.full(EC_IMG.shape[:2], 255, np.uint8)])
    EC_ST = [sticker(EC.get("title", "СМОТРИ ПОЛНОЕ ВИДЕО"), bg="#FFE500", fg="#000000", size=78, rot=-3),
             sticker(EC.get("sub", "ССЫЛКА ВНИЗУ"), bg="#E61E28", size=70, rot=3)]
def endcard_frame(q):
    fr = EC_BG.copy()
    blend(fr, EC_IMG, W / 2, 900, 0.86 + 0.14 * ease(q * 3) + 0.03 * q)
    blend(fr, EC_ST[0], W / 2, 430, 1.0 if q > 0.08 else 0.5 + 0.5 * ease(q / 0.08))
    if q > 0.25: blend(fr, EC_ST[1], W / 2, 1420, 1.0 if q > 0.33 else 0.5 + 0.5 * ease((q - 0.25) / 0.08))
    return fr
# графика панелей читается кадр в кадр с выходом (gfx.mp4 той же длины, что голос)
GW, GH = ((LAY or {}).get("gfx_w", W), (LAY or {}).get("gfx_h", H))
gdec = subprocess.Popen(["ffmpeg", "-v", "quiet", "-i", str(WD / "gfx.mp4"), "-an", "-vf", f"fps={FPS},scale={GW}:{GH},format=rgb24",
    "-f", "rawvideo", "-"], stdout=subprocess.PIPE) if LAY else None
glast = np.zeros((GH, GW, 3), np.uint8); FACE_POS = (LAY or {}).get("face_pos", 0.5)
def landscape(fr, glast, md):
    """Вертикальный кадр → 1920×1080: размытый фон + столбик лица (справа при панели, по центру без неё)."""
    small = cv2.resize(fr, (108, 192), interpolation=cv2.INTER_AREA)
    yc = int(min(max(0, FACE_Y / H * 192 - 30), 192 - 61))
    bg = cv2.GaussianBlur(small[yc:yc + 61], (0, 0), 5)
    bg = (cv2.resize(bg, (OW, OH), interpolation=cv2.INTER_LINEAR) * 0.55).astype(np.uint8)
    col = cv2.resize(fr, (COLW, OH), interpolation=cv2.INTER_AREA)
    if md:
        bg[:, :GW] = glast[:OH, :GW]; bg[:, OW - COLW:] = col
    else:
        x0 = (OW - COLW) // 2; bg[:, x0:x0 + COLW] = col
    return bg
for k, s in enumerate(E["segs"]):
    dec = subprocess.Popen(["ffmpeg", "-v", "quiet", "-ss", f"{s['a']}", "-t", f"{s['b'] - s['a'] + 0.1}", "-i", SRC, "-an",
        "-vf", f"setpts=(PTS-STARTPTS)/{s['sp_eff']},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},format=rgb24",
        "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    last = np.zeros((H, W, 3), np.uint8)
    # Первый кадр: его зритель видит в ленте и за ~1 с решает, листать ли. У телефонной съёмки начало часто
    # смазано (рука ещё ведёт камеру к лицу). Ищем в первых first_frame_window с (1.2) резкий кадр С ЛИЦОМ
    # и держим его до этого момента — вместе с наездом z2 это читается как стоп-кадр-интро; звук идёт как есть.
    pre = []
    if k == 0 and FX.get("first_frame_sharp", True):
        for _ in range(min(s["n"], int(FX.get("first_frame_window", 1.2) * FPS))):
            b_ = dec.stdout.read(W * H * 3)
            if len(b_) == W * H * 3: pre.append(np.frombuffer(b_, np.uint8).reshape(H, W, 3))
        if pre:
            FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            score = []
            for f_ in pre:
                g_ = cv2.cvtColor(cv2.resize(f_, (270, 480)), cv2.COLOR_RGB2GRAY)
                fa = max((w_ * h_ for *_, w_, h_ in FACE.detectMultiScale(g_, 1.1, 4, minSize=(40, 40))), default=0)
                score.append(cv2.Laplacian(g_, cv2.CV_64F).var() * (np.sqrt(fa) if fa else 0.05))
            best = int(np.argmax(score)); pre = [pre[max(i_, best)] for i_ in range(len(pre))]
            if best: print(f"первый кадр: держу резкий кадр с лицом ({best / FPS:.2f} с стоп-кадра)")
    got = len(pre)
    if s.get("endcard") and EC_BG is not None:
        for j in range(s["n"]):
            fr = endcard_frame(j / max(1, s["n"] - 1))
            if BAR: fr[0:12, : int(W * (fi + 1) / NF)] = rgb(BAR)
            enc.stdin.write(fr.tobytes()); fi += 1
        dec.stdout.close(); dec.wait(); print(f"план {k:02d} — заставка ({fi}/{NF})", flush=True); continue
    for j in range(s["n"]):
        if j < len(pre): last = pre[j]
        else:
            buf = dec.stdout.read(W * H * 3)
            if len(buf) == W * H * 3: last = np.frombuffer(buf, np.uint8).reshape(H, W, 3); got += 1
            elif got == 0 and j == 0: raise SystemExit(f"План {k}: из исходника не прочитано ни одного кадра ({s['a']}–{s['b']} с)")
        t = fi / FPS; p = j / max(1, s["n"] - 1)
        z0 = s.get("z", 1.0); z = zb = z0 + (s.get("z2", z0) - z0) * p     # статичная крупность или плавный наезд
        z *= 1 + FX.get("cut_punch", 0.07) * (1 - ease(j / 6))               # толчок на каждой склейке
        for tz, amt in PUNCH:                                                 # резкий зум на акценте
            d = t - tz
            if 0 <= d < 0.5: z *= 1 + amt * (ease(d / 0.08) if d < 0.08 else 1 - ease(d / 0.5))
        dx = dy = 0.0
        for ts, d, amp in SHAKE:
            if 0 <= t - ts < d: a_ = amp * (1 - (t - ts) / d); dx += random.uniform(-a_, a_); dy += random.uniform(-a_, a_)
        cw, ch = W / z, H / z; cx = s.get("cx", W / 2) + dx
        cy = s.get("cy", FACE_Y if z > 1.01 else H / 2) + dy
        x0 = min(max(0, cx - cw / 2), W - cw); y0 = min(max(0, cy - ch / 2), H - ch)
        fr = cv2.warpAffine(last, np.float32([[z, 0, -x0 * z], [0, z, -y0 * z]]), (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        for tf in FLASH:
            if 0 <= t - tf < 0.12: a_ = (1 - (t - tf) / 0.12) * 0.85; fr = (fr * (1 - a_) + 255 * a_).astype(np.uint8)
        if gdec:
            gb = gdec.stdout.read(GW * GH * 3)
            if len(gb) == GW * GH * 3: glast = np.frombuffer(gb, np.uint8).reshape(GH, GW, 3)
        md = mode_at(t)
        if LAND: pan = md in ("split", "full"); fr = landscape(fr, glast, pan); md = "land" if pan else "land_face"
        elif md == "full": fr = glast.copy()
        elif md == "split":                                                  # графика сверху, лицо — в нижней части
            # крупность плана тут не нужна (лицо и так обрезано вдвое) — только толчки склеек/акцентов
            fh = H - SPLIT; zs = z / zb; cws, chs = W / zs, H / zs
            xs = min(max(0, W / 2 + dx - cws / 2), W - cws); ys = min(max(0, FACE_Y + dy - chs / 2), H - chs)
            ff = cv2.warpAffine(last, np.float32([[zs, 0, -xs * zs], [0, zs, -ys * zs]]), (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            yo = int(min(max(0, (FACE_Y - ys) * zs - FACE_POS * fh), H - fh))
            fr = np.concatenate([glast[:SPLIT], ff[yo:yo + fh]], axis=0)
        for ts, d, img, sx, sy, inst in STICK:
            if 0 <= t - ts < d:
                q = (t - ts) / 0.14
                blend(fr, img, sx, sy, 1.0 if inst or q >= 1.5 else 0.4 + 0.75 * ease(q) - 0.15 * ease((q - 1) * 2))
        for ci, c in enumerate(chunks):
            if c["s"] <= t < c["e"]:
                act = max([wi for wi, w in enumerate(c["ws"]) if t >= w["s"] - CAP["lead"]] or [0])
                q = (t - c["s"]) / 0.1; blend(fr, caption_img(ci, act), OW / 2, CAPY.get(md, CAP["y"]), 1 + CAP["pop"] * (1 - ease(q)) if q < 1 else 1.0)
                break
        if BAR: fr[0:(8 if LAND else 12), : int(OW * (fi + 1) / NF)] = rgb(BAR)
        enc.stdin.write(fr.tobytes()); fi += 1
    dec.stdout.close(); dec.wait()
    print(f"план {k:02d} готов ({fi}/{NF})", flush=True)
enc.stdin.close(); enc.wait()
if gdec: gdec.stdout.close(); gdec.wait()
print("→", WD / "video.mp4", WD / "sfx.wav")
