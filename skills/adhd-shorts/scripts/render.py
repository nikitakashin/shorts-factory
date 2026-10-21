# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy","opencv-python-headless<4.13","pillow","soundfile",
#   "pyobjc-framework-Vision; sys_platform == 'darwin'", "pyobjc-framework-Quartz; sys_platform == 'darwin'"]
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
# "look" — творческие решения ролика из брифа (SKILL.md, шаг 1.5): accent/accent2 — цвета свечения и хука,
# stickers — plate/glow, transitions — палитра переходов, format/experiment — для истории (look.py)
LOOK = FX.get("look", {})
FPS = E["fps"]; W, H = 1080, 1920; NF = E["frames"]; SRC = E["src"]
# Горизонтальный ролик из вертикальной съёмки ("canvas": "landscape" в fx.json): выход 1920×1080,
# вертикальный кадр (со всеми зумами/тряской) — столбик 608×1080 поверх размытого фона; при UI-панели
# графика занимает левые 1312 px, лицо — справа. Субтитры фразами внизу, стикеры/хук — в координатах 1920×1080.
LAND = FX.get("canvas") == "landscape"
OW, OH = (1920, 1080) if LAND else (W, H)
COLW = round(OH * W / H)            # ширина столбика лица в горизонтали (608)
if not Path(SRC).is_file():   # иначе декодер молча отдаёт ноль кадров и весь ролик выходит чёрным
    raise SystemExit(f"Исходник не найден: {SRC}\nЕго переименовали/удалили? Укажи новый путь в edl.json и edl_out.json.")
# Субтитры. style "glow" (по умолчанию с 2026-10-17): зрители массово писали «шрифт хуйня» — капс Montserrat с толстой
# чёрной обводкой. Взяли приёмы из рилса-референса автора (marina_movie): широкий шрифт Unbounded, строчные, мягкое
# свечение вместо обводки, контраст веса — активное слово жирное (w_act), остальные тонкие (w_reg).
# style "stroke" — старый вид (капс, жёлтое активное слово, обводка stroke).
_CAPF = FX.get("caption", {})
if _CAPF.get("style", "glow") == "glow":
    CAP = dict(style="glow", y=1380, size=96, max_words=2, max_chars=14, gap=0.3, hold=0.35, lead=0.04, color="#FFFFFF",
               active="#FFFFFF", glow=LOOK.get("accent", "#50C8FF"), w_reg=400, w_act=900, shadow=0.7, case="smart", font=None,
               acc_scale=1.15, rise=0.16, glow_all=False, accents=[]) | _CAPF
else:
    CAP = dict(style="stroke", y=1380, size=118, max_words=2, max_chars=13, gap=0.3, hold=0.35, lead=0.04,
               color="#FFFFFF", active="#FFE500", stroke=12, pop=0.22, font=None, case="upper") | _CAPF

LAY = json.load(open(WD / "layout.json")) if (WD / "layout.json").exists() and (WD / "gfx.mp4").exists() else None
if (WD / "panels.json").exists() and LAY is None and "--sfx-only" not in sys.argv:
    # 2026-10-09: рендер графики прервался («render_cancelled_parent_exited»), gfx.mp4 не появился —
    # и ролик молча собрался без панелей. Лучше упасть.
    raise SystemExit("Есть panels.json, но нет gfx.mp4/layout.json — сначала render_gfx.sh (и дождись его конца)")
if LAY and "total" in LAY and "--sfx-only" not in sys.argv:
    # 2026-10-14 («Гайды умерли»): после перемонтажа взялся старый gfx.mp4 на 64.8 с при ролике 63.9 —
    # панели к концу разъехались с речью. После любой правки edl — retime_panels.py и заново render_gfx.sh
    _E = json.load(open(WD / "edl_out.json")); _tot = _E["frames"] / _E["fps"]
    if abs(LAY["total"] - _tot) > 0.1:
        raise SystemExit(f"gfx.mp4 устарел: графика на {LAY['total']:.2f} с, ролик {_tot:.2f} с — перезапусти render_gfx.sh")
SPLIT = int(LAY["split"]) if LAY else 0
def mode_at(t):
    for m in (LAY or {}).get("modes", []):
        if m["s"] <= t < m["e"]: return m["mode"]
    return "face"
CAPY = {"face": CAP["y"], "split": SPLIT, "full": CAP["y"], "pip": CAP["y"]} | (LAY or {}).get("caption_y", {})
if LAY: print(f"UI-панели: {len(LAY['modes'])} шт., стык на {SPLIT}px")

def rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
_FD = Path.home() / ".cache/content-factory/fonts"     # Unbounded, Marck Script — Google Fonts (OFL), скачаны 2026-10-17
FONT_CANDIDATES = [CAP["font"]] + ([str(_FD / "Unbounded.ttf")] if CAP["style"] == "glow" else []) + [
                   str(Path(__file__).resolve().parent.parent / "assets/fonts/Montserrat.ttf"), str(_FD / "Montserrat.ttf"),
                   "/System/Library/Fonts/Supplemental/Arial Black.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
FONT = next(f for f in FONT_CANDIDATES if f and Path(f).is_file())
def font(sz, wt=900, path=None):
    f = ImageFont.truetype(path or FONT, int(sz))
    try: f.set_variation_by_axes([wt])
    except Exception: pass
    return f

# ---------- слова → токены субтитров ----------
raw = json.load(open(WD / "words_out.json"))
def norm(w): return re.sub(r"[^\wёЁ.\-₽]", "", w.lower()).strip(".")
fixes = {norm(k): v for k, v in FX.get("fixes", {}).items()}
seqs = [([norm(x) for x in r["seq"]], r["to"]) for r in FX.get("replace", [])]
def case(txt):
    """upper — капс; lower — всё строчными; smart — строчные, но аббревиатуры (ИИ, GPT, WebMCP: ≥2 заглавных)
    и латинские названия с заглавной (Claude, Google) остаются как есть; asis — как написано."""
    c = "upper" if CAP.get("upper") is True else CAP.get("case", "upper")
    if c == "upper": return txt.upper()
    if c == "lower": return txt.lower()
    if c == "asis": return txt
    return " ".join(w if sum(ch.isupper() for ch in w) >= 2 or re.match(r"^[A-Z][a-z]", w) else w.lower() for w in txt.split(" "))
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
        toks.append(dict(t=case(txt), s=s, e=e, end=bool(re.search(r"[.?!,…]$", last))))
    i += 1
chunks = []; cur = []
# границы глав длинного видео (fx.json "caption_breaks", сек выхода): фраза субтитров не переходит через стык,
# иначе на заставке/в начале главы висит последнее слово прошлой («БЛ*ТЬ ОТКУДА БЕРУТСЯ ЗВУКИ», 2026-10-14)
BRK = sorted(FX.get("caption_breaks", []))
crosses = lambda a, b: any(a < x <= b for x in BRK)
for t in toks:
    if cur and (len(cur) >= CAP["max_words"] or len(" ".join(x["t"] for x in cur + [t])) > CAP["max_chars"]
                or t["s"] - cur[-1]["e"] > CAP["gap"] or crosses(cur[-1]["s"], t["s"])):
        chunks.append(cur); cur = []
    cur.append(t)
    if t["end"]: chunks.append(cur); cur = []
if cur: chunks.append(cur)
for j, c in enumerate(chunks):
    nxt = chunks[j + 1][0]["s"] - CAP["lead"] if j + 1 < len(chunks) else NF / FPS
    e_ = min(nxt, c[-1]["e"] + CAP["hold"]); e_ = min([e_] + [x for x in BRK if c[-1]["s"] < x])   # не держать фразу за стыком главы
    chunks[j] = dict(ws=c, s=max(c[0]["s"] - CAP["lead"], max([0.0] + [x for x in BRK if x <= c[0]["s"]])), e=e_)
(WD / "captions.txt").write_text("\n".join(f'{c["s"]:6.2f}-{c["e"]:6.2f}  ' + " ".join(w["t"] for w in c["ws"]) for c in chunks))
print(f"{len(toks)} слов, {len(chunks)} фраз субтитров → captions.txt")

seg_t = [s["f0"] / FPS for s in E["segs"]]
def at(spec, after=0.0):
    """число → секунды выхода; "seg:N" → начало плана N; "СЛОВО" → первое слово, содержащее его, после `after` сек."""
    if isinstance(spec, (int, float)): return float(spec)
    if spec.startswith("seg:"): return seg_t[int(spec[4:])]
    m = re.match(r"^(.+?)>(\d+(?:\.\d+)?)$", spec)          # «СЛОВО>28» — как в panels.json (2026-10-16 упал на этом)
    if m: spec, after = m.group(1), max(after, float(m.group(2)))
    for t in toks:
        if t["s"] >= after and spec.upper() in t["t"].upper(): return t["s"]
    raise SystemExit(f"fx.json: слово «{spec}» после {after}s не найдено в субтитрах (см. captions.txt)")
def T(d): return at(d["at"], d.get("after", 0.0))
# ---------- раскладки кадра и переходы между ними (transitions.py, 2026-10-17) ----------
# Состояния: face / split / full / pip (лицо в карточке поверх графики). На каждой смене — переход: panels.json
# "in"/"out" у панели, иначе выбирается сам из палитры ролика (fx.json "look": {"transitions": [...]} или
# panels.json "transitions") с учётом пары состояний; "cut" — без перехода. fx.json "cuts": [{"at", "kind", "dir"}] —
# переход на обычной склейке лицо→лицо (смена темы): старый план замирает и уезжает, новый въезжает.
import zlib
sys.path.insert(0, str(Path(__file__).resolve().parent)); import transitions as TRX
SEED = FX.get("seed", zlib.crc32(str(WD.resolve()).encode()) % 1000)
LOOK = FX.get("look", {})
PAL = LOOK.get("transitions") or (LAY or {}).get("transitions")
AUTO = {("face", "split"): ["morph", "slide", "whip"], ("split", "face"): ["morph", "whip"],
        ("face", "full"): ["whip", "zoom", "slide", "glitch", "iris"], ("full", "face"): ["whip", "zoom", "glitch", "iris", "blur"],
        ("face", "pip"): ["morph"], ("pip", "face"): ["morph", "iris"], "panel": ["morph", "glitch", "whip", "flash"]}
def pick_kind(a, b, k):
    pool = AUTO.get((a, b)) or AUTO["panel"]
    if PAL: pool = [x for x in pool if x in PAL] or [x for x in PAL if x in TRX.DUR] or pool
    return pool[(SEED + k) % len(pool)]
TLN, TRS = [], []
if LAY and not LAND:
    _t = 0.0
    for m in sorted(LAY.get("modes", []), key=lambda m: m["s"]):
        if m["s"] - _t > 1e-3: TLN.append(dict(s=_t, e=m["s"], mode="face"))
        TLN.append(dict(m)); _t = m["e"]
    if NF / FPS - _t > 1e-3: TLN.append(dict(s=_t, e=NF / FPS, mode="face"))
    k = 1
    while k < len(TLN):
        a, b = TLN[k - 1], TLN[k]; tb = b["s"]; nxt = TLN[k + 1] if k + 1 < len(TLN) else None
        # лицо мелькает между двумя панелями меньше 0.5 с — не «выход-лицо-вход», а один переход панель→панель через паузу
        if b["mode"] == "face" and a["mode"] != "face" and nxt and nxt["mode"] != "face" and b["e"] - b["s"] < 0.5:
            kind = nxt.get("in") or a.get("out") or pick_kind(a["mode"], nxt["mode"], k)
            if kind in TRX.DUR:
                D = max(TRX.DUR[kind], b["e"] - b["s"] + 0.16); mid = (b["s"] + b["e"]) / 2
                TRS.append(dict(t0=mid - D / 2, t1=mid + D / 2, a=a, b=nxt, kind=kind, opt=nxt.get("tr") or a.get("tr") or {}, dir=nxt.get("dir") or a.get("dir") or ("up" if (SEED + k) % 3 else "left")))
            k += 2; continue
        k += 1
        if a["mode"] == b["mode"] and not b.get("in"): continue      # та же раскладка: смену панели делает сама графика
        kind = (b.get("in") if b["mode"] != "face" else None) or (a.get("out") if a["mode"] != "face" else None) or pick_kind(a["mode"], b["mode"], k)
        if kind == "cut" or kind not in TRX.DUR: continue
        if a["mode"] == "face": D = min(TRX.DUR[kind], 0.45 * (b["e"] - b["s"])); t0, t1 = tb, tb + D       # вход: лицо до слова-якоря, переход уже на графике
        elif b["mode"] == "face": D = min(TRX.DUR[kind], 0.45 * (a["e"] - a["s"])); t0, t1 = tb - D, tb    # выход: к следующей фразе уже лицо
        else: D = min(TRX.DUR[kind], 0.9 * (a["e"] - a["s"]), 0.9 * (b["e"] - b["s"])); t0, t1 = tb - D / 2, tb + D / 2
        if D < 0.08: continue
        TRS.append(dict(t0=t0, t1=t1, a=a, b=b, kind=kind, opt=(b.get("tr") if b["mode"] != "face" else a.get("tr")) or {}, dir=b.get("dir") or a.get("dir") or ("up" if (SEED + k) % 3 else "left")))
CUTTR = []
for c in FX.get("cuts", []):
    _w = at(c["at"], c.get("after", 0.0)); _tb = min(seg_t[1:] or [_w], key=lambda x: abs(x - _w))   # точно на склейку
    _k = c.get("kind", "whip"); _t1 = _tb + TRX.DUR.get(_k, 0.3)
    if abs(_tb - _w) > 0.3: print(f"! cuts «{c['at']}»: рядом ({_w:.2f} с) нет склейки — ближайшая {_tb:.2f}, пропускаю"); continue
    if any(x["t0"] < _t1 and _tb < x["t1"] for x in TRS): print(f"! cuts «{c['at']}» ({_tb:.2f}) совпал с переходом раскладки — пропускаю"); continue
    CUTTR.append(dict(t0=_tb, t1=_t1, kind=_k, dir=c.get("dir", "left"), opt={k_: v for k_, v in c.items() if k_ in ("ring", "center", "dx")}))
# key — момент, который должен стоять на доле: вход в панель — начало перехода, выход — конец, панель→панель и склейка — середина
_key = lambda x: x["t0"] if x.get("a", {}).get("mode", "face") == "face" and x.get("b", {}).get("mode", "face") != "face" else \
    x["t1"] if x.get("b", {}).get("mode", "face") == "face" and x.get("a", {}).get("mode", "face") != "face" else (x["t0"] + x["t1"]) / 2
json.dump([dict(t=round(x["t0"], 3), key=round(_key(x), 3), kind=x["kind"], a=x.get("a", {}).get("mode", "face"), b=x.get("b", {}).get("mode", "face"))
           for x in sorted(TRS + CUTTR, key=lambda x: x["t0"])], open(WD / "transitions.json", "w"), ensure_ascii=False)   # для look.py log
if TRS or CUTTR:
    print("переходы: " + ", ".join(f"{x['t0']:.2f} {x.get('a', {}).get('mode', 'face')}→{x.get('b', {}).get('mode', 'face')} {x['kind']}" for x in sorted(TRS + CUTTR, key=lambda x: x["t0"])))

# Акцентные слова субтитров (glow): якоря стикеров/punch/shake/flash/boom + caption.accents (["СЛОВО", "СЛОВО>12"]).
# Рисуются рукописным со свечением, остальные слова свечения не получают — так акцент виден (ресерч 2026-10-17).
if CAP["style"] == "glow":
    _acc = [T(d) for k_ in ("stickers", "punch", "shake", "flash", "boom") for d in FX.get(k_, [])
            if isinstance(d.get("at"), str) and not d["at"].startswith("seg:") and not d.get("no_accent")]
    _acc += [at(a_) for a_ in CAP.get("accents", [])]
    for t_ in toks:
        if any(abs(t_["s"] - x) < 1e-6 for x in _acc): t_["acc"] = True

# ---------- отрисовка ----------
def glow_img(runs, w, h, glow, size, shadow=0.55, anchor="la"):
    """runs: [(x, y, текст, шрифт, цвет)] → RGBA: тёмная мягкая тень (читается и на светлом экране), под ней
    цветное свечение вместо обводки (приём из рилса marina_movie, 2026-10-17), сверху сам текст."""
    m = Image.new("L", (w, h), 0); dm = ImageDraw.Draw(m)
    t = Image.new("RGBA", (w, h), (0, 0, 0, 0)); dt = ImageDraw.Draw(t)
    for x, y, s_, f, fill in runs:
        dm.text((x, y), s_, font=f, fill=255, stroke_width=max(2, int(size / 34)), stroke_fill=255, anchor=anchor)
        dt.text((x, y), s_, font=f, fill=rgb(fill) + (255,), anchor=anchor)
    M = np.asarray(m, np.float32) / 255
    sh = np.clip(cv2.GaussianBlur(np.roll(M, int(size * 0.06), 0), (0, 0), size * 0.14) * 1.6, 0, 1) * shadow
    gl = np.clip(cv2.GaussianBlur(M, (0, 0), size * 0.2) * 1.5 + cv2.GaussianBlur(M, (0, 0), size * 0.055) * 0.9, 0, 1) if glow else np.zeros_like(M)
    A = gl + sh * (1 - gl); C = np.array(rgb(glow or "#000000"), np.float32) * (gl / np.maximum(A, 1e-6))[..., None]   # свечение поверх чёрной тени
    T = np.asarray(t, np.float32); at = T[..., 3] / 255
    A2 = at + A * (1 - at); C2 = (T[..., :3] * at[..., None] + C * (A * (1 - at))[..., None]) / np.maximum(A2, 1e-6)[..., None]
    return np.dstack([np.clip(C2, 0, 255), np.clip(A2 * 255, 0, 255)]).astype(np.uint8)

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

def acc_kind(w):
    """Как рисовать акцент: script — рукописный (только строчная кириллица); bold — жирный со свечением.
    Рукописные заглавные и латиница не читаются: «ИИ-агент» OCR прочитал как «All-агент» (qa.py, 2026-10-17)."""
    if not w.get("acc"): return None
    return "bold" if re.search(r"[A-Za-zА-ЯЁ0-9]", w["t"]) else "script"
def cap_fonts(sz):
    return dict(reg=font(sz, CAP["w_reg"]), act=font(sz, CAP["w_act"]),
                acc=font(int(sz * CAP["acc_scale"]), 400, str(_FD / "MarckScript.ttf")))
_lay = {}
def cap_layout(ci):
    """Размер шрифта фразы и слоты слов (x от центра строки, ширина). Слот — по самому широкому начертанию слова:
    когда активное слово становится жирным, а следующее всплывает, зазоры между словами не прыгают."""
    if ci in _lay: return _lay[ci]
    ws = chunks[ci]["ws"]; sz = CAP["size"]; maxw = CAP.get("max_w", OW - 100 if LAND else W - 100)
    while True:
        F = cap_fonts(sz); sp = int(sz * 0.32)
        wid = [(F["acc"].getlength(w["t"]),) * 2 if acc_kind(w) == "script" else (F["reg"].getlength(w["t"]), F["act"].getlength(w["t"])) for w in ws]
        slot = [max(a) for a in wid]; tot = sum(slot) + sp * (len(ws) - 1)
        if tot <= maxw or sz < 40: break
        sz -= 4
    xs = []; x = -tot / 2
    for k in range(len(ws)): xs.append((x, slot[k])); x += slot[k] + sp
    _lay[ci] = (sz, xs); return _lay[ci]

_wimg = {}
def word_img(ci, k, state, blur=False):
    """Одно слово фразы → (RGBA, ширина текста). Все слова фразы на холсте одной высоты с общей базовой линией.
    Акцент — рукописный со свечением; обычные слова — без свечения, только мягкая тень (state act — жирное)."""
    key = (ci, k, state, blur)
    if key in _wimg: return _wimg[key]
    sz, _ = cap_layout(ci); F = cap_fonts(sz); w = chunks[ci]["ws"][k]
    if acc_kind(w) == "script": f, gl, col = F["acc"], CAP["glow"], CAP["color"]
    elif acc_kind(w) == "bold": f, gl, col = F["act"], CAP["glow"], CAP["active"]     # акцент-аббревиатура: жирный всегда
    else: f, gl, col = (F["act"], None, CAP["active"]) if state == "act" else (F["reg"], None, CAP["color"])
    if CAP.get("glow_all"): gl = CAP["glow"]
    wk = f.getlength(w["t"]); pad = int(sz * 0.7)
    im = glow_img([(pad, pad + int(sz * 1.05), w["t"], f, col)], int(wk + 2 * pad), int(sz * 1.45 + 2 * pad), gl, sz, CAP["shadow"], anchor="ls")
    if blur:                                          # размытие с предумножением альфы, иначе по краям чёрная кайма
        a = im[..., 3:4].astype(np.float32) / 255; P = cv2.GaussianBlur(im[..., :3].astype(np.float32) * a, (0, 0), sz * 0.06)
        A = cv2.GaussianBlur(a[..., 0], (0, 0), sz * 0.06)[..., None]
        im = np.dstack([np.clip(P / np.maximum(A, 1e-4), 0, 255), np.clip(A * 255, 0, 255)]).astype(np.uint8)
    _wimg[key] = (im, wk); return _wimg[key]

def draw_caption(fr, ci, t, cy):
    """Слова появляются по мере речи: всплывают снизу с проявлением и лёгким размытием (CAP rise, 0.16 с);
    сказанные — тонкие, текущее — жирное, ещё не сказанные не видны (визуальный гайд Joseph, ресерч 2026-10-17)."""
    c = chunks[ci]; ws = c["ws"]; n = len(ws); sz, xs = cap_layout(ci)
    act = max([wi for wi, w in enumerate(ws) if t >= w["s"] - CAP["lead"]] or [0])
    for k in range(act + 1):
        ap = max(c["s"], ws[k]["s"] - CAP["lead"])
        q = (t - ap) / min(CAP["rise"], 0.4 * max(0.05, c["e"] - ap))   # короткое слово: анимация не съедает показ
        im, wk = word_img(ci, k, "act" if k == act else "past", blur=q < 0.5)
        x0, slot = xs[k]
        left = x0 + (slot - wk if (k == 0 and n > 1) else 0 if (k == n - 1 and n > 1) else (slot - wk) / 2)
        e_ = ease(q) if q < 1 else 1.0
        blend(fr, im, OW / 2 + left + wk / 2, cy + (1 - e_) * sz * 0.35, alpha=0.15 + 0.85 * e_ if q < 1 else 1.0)

def hook_img(text, lines=None, size=130, glow="#50C8FF", accent="#FF3CAA", **_):
    """Хук из рилса-референса: строки разными шрифтами в столбик. Стили строк: bold — Unbounded Black с розовым
    свечением, thin — Unbounded ExtraLight капсом, script — рукописный Marck Script. По умолчанию: 1 строка — bold;
    2 — bold + script; 3+ — bold, thin…, script. Регистр — как написан в fx.json (thin — всегда капс)."""
    L = text.split("\n"); n = len(L)
    st = lines or (["bold"] if n == 1 else ["bold", "script"] if n == 2 else ["bold"] + ["thin"] * (n - 2) + ["script"])
    spec = dict(bold=(1.0, 900, None, accent), thin=(0.62, 200, None, glow), script=(1.05, None, str(_FD / "MarckScript.ttf"), glow))
    parts = []
    for ln, sty in zip(L, st):
        k, wt, path, gc = spec[sty]; sz = int(size * k)
        if sty == "thin": ln = ln.upper()
        while True:
            f = font(sz, wt or 400, path); wl = f.getlength(ln)
            if wl <= OW - 120 or sz < 30: break
            sz -= 4
        pad = int(sz * 0.6); b = f.getbbox(ln)
        parts.append(glow_img([(pad, pad - b[1], ln, f, "#FFFFFF")], int(wl + 2 * pad), int(b[3] - b[1] + 2 * pad), gc, sz))
    gap = -int(size * 0.55)                                    # поля свечения перекрываются — строки плотно
    Wt = max(p_.shape[1] for p_ in parts); Ht = sum(p_.shape[0] for p_ in parts) + gap * (len(parts) - 1)
    out = np.zeros((Ht, Wt, 4), np.float32); y = 0
    for p_ in parts:
        x = (Wt - p_.shape[1]) // 2; a = p_[..., 3:4].astype(np.float32) / 255; roi = out[y:y + p_.shape[0], x:x + p_.shape[1]]
        A = a + roi[..., 3:4] * (1 - a); roi[..., :3] = (p_[..., :3] * a + roi[..., :3] * roi[..., 3:4] * (1 - a)) / np.maximum(A, 1e-6); roi[..., 3:4] = A
        y += p_.shape[0] + gap
    out[..., 3] *= 255; return out.astype(np.uint8)

def sticker(text, bg="#E61E28", fg="#FFFFFF", size=100, rot=-6, style=None, **_):
    if (style or LOOK.get("stickers", "plate")) == "glow":      # без плашки: жирный текст со свечением цвета bg
        f = font(size, 900); L = text.split("\n"); pad = int(size * 0.7); lh = int(size * 1.12)
        wl = max(f.getlength(x) for x in L)
        while wl + 2 * pad > OW - 60 and size > 40: size -= 4; f = font(size, 900); wl = max(f.getlength(x) for x in L); lh = int(size * 1.12)
        im = glow_img([(pad + (wl - f.getlength(x)) / 2, pad + i * lh, x, f, "#FFFFFF" if fg in ("#000000", "#282828") else fg) for i, x in enumerate(L)],
                      int(wl + 2 * pad), int(lh * len(L) + 2 * pad), bg if bg not in ("#282828", "#000000") else LOOK.get("accent", "#50C8FF"), size)
        return np.array(Image.fromarray(im).rotate(rot, expand=True, resample=Image.BICUBIC))
    while True:                                    # не шире кадра с полями 40 px с учётом наклона — иначе шрифт мельче
        f = font(size); sp = int(size * 0.18)      # "\n" в тексте — несколько строк (для хука)
        bb = ImageDraw.Draw(Image.new("RGBA", (1, 1))).multiline_textbbox((0, 0), text, font=f, spacing=sp, align="center")
        pw, ph = int(round(bb[2])) + 60, int(round(bb[3])) + 50
        a = math.radians(abs(rot))
        if pw * math.cos(a) + ph * math.sin(a) <= OW - 80 or size <= 40: break
        size -= 2
    im = Image.new("RGBA", (pw, ph), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=26, fill=rgb(bg) + (255,), outline=(0, 0, 0, 255), width=8)
    d.multiline_text((30, 18), text, font=f, fill=rgb(fg) + (255,), spacing=sp, align="center")
    return np.array(im.rotate(rot, expand=True, resample=Image.BICUBIC))

def blend(fr, img, cx, cy, scale=1.0, alpha=1.0):
    if scale != 1.0: img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    FH_, FW_ = fr.shape[:2]
    h, w = img.shape[:2]; x0, y0 = int(cx - w / 2), int(cy - h / 2)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(FW_, x0 + w), min(FH_, y0 + h)
    if xa >= xb or ya >= yb: return
    sub = img[ya - y0:yb - y0, xa - x0:xb - x0]; al = sub[..., 3:4].astype(np.float32) / 255 * alpha
    roi = fr[ya:yb, xa:xb]; roi[:] = (roi * (1 - al) + sub[..., :3] * al).astype(np.uint8)

def ease(p): return 1 - (1 - min(1, max(0, p))) ** 3

STICK = [(T(s), s.get("dur", 1.3), sticker(**s), s.get("x", 540), s.get("y", 340), s.get("instant", False), s.get("behind", False))
         for s in FX.get("stickers", [])]
# Хук: плашка с главной мыслью видна ЦЕЛИКОМ с первого кадра (без анимации появления). Половина ленты решает
# листать за ~1 с, а субтитры по 1–2 слова собирают мысль за 3 с (первый шортс: «продолжили смотреть» 49.6%).
HOOK = FX.get("hook"); _HOOKF = dict(HOOK or {})
if HOOK:
    HOOK = dict(dict(at=0.0, dur=2.6, bg="#FFE500", fg="#000000", size=92, rot=-3, y=300, instant=True, sound="pop",
                     style="mix" if CAP["style"] == "glow" else "plate", glow=LOOK.get("accent", "#50C8FF"), accent=LOOK.get("accent2", "#FF3CAA")), **HOOK)
    if HOOK["style"] == "mix": HOOK = dict(HOOK, size=_HOOKF.get("size", 130), y=_HOOKF.get("y", 330))
    STICK.insert(0, (0.0, HOOK["dur"], hook_img(**HOOK) if HOOK["style"] == "mix" else sticker(**HOOK), HOOK.get("x", 540), HOOK["y"], True, HOOK.get("behind", False)))
# для черновика CapCut (capcut_draft.py): субтитры по словам и плашки с уже посчитанными временами
_stk = ([dict(HOOK, t=0.0)] if HOOK else []) + [dict(dict(dur=1.3, x=540, y=340, bg="#E61E28", fg="#FFFFFF", size=100, rot=-6), **s, t=T(s)) for s in FX.get("stickers", [])]
(WD / "stickers").mkdir(exist_ok=True)
for _i, _d in enumerate(_stk):        # плашки картинками — в CapCut текст с подложкой из файла не встаёт
    Image.fromarray(hook_img(**_d) if _d.get("style") == "mix" else sticker(**_d)).save(WD / "stickers" / f"{_i:02d}.png"); _d["png"] = str(WD / "stickers" / f"{_i:02d}.png")
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
        if (E["segs"][k].get("z", 1) != E["segs"][k - 1].get("z", 1) or E["segs"][k].get("broll") or E["segs"][k - 1].get("broll"))
        and not E["segs"][k].get("tail")       # tail — хвост после речи под графикой: без вжуха и тиканья
        and not E["segs"][k].get("no_whoosh")]  # ответ в скетче-пинг-понге падает «всухую», без вжуха
brolls = [(seg_t[k], s["n"] / FPS) for k, s in enumerate(E["segs"]) if s.get("broll") and not s.get("endcard") and not s.get("tail")]

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
    # seed по папке проекта: с общим seed=7 во всех шортсах выпадали одни и те же звуки (концовка — всегда «Стогнии»,
    # автор 2026-10-14: «разнообразие давай»). fx.json "seed" — зафиксировать вручную.
    import zlib
    _dec, _peak, _pools, krng = {}, {}, {}, random.Random(FX.get("seed", zlib.crc32(str(WD.resolve().parent if WD.name == ".work" else WD.resolve()).encode())))
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
            if spec == "end":    # концовка не повторяет те, что уже стоят в других роликах (автор: «разнообразие давай»)
                used = {}                                   # сколько роликов уже кончаются этим звуком
                for f_ in Path.home().glob("Movies/Shorts/*/.work/sfx_list.json"):
                    if f_.resolve().parent == WD.resolve(): continue
                    try:
                        for n_ in {Path(x["file"]).name for x in json.load(open(f_))["sounds"] if x.get("spec") == "end"}: used[n_] = used.get(n_, 0) + 1
                    except Exception: pass
                krng.shuffle(files)                         # все уже были — самый редкий, а не случайный (2026-10-15: повтор)
                files = sorted(files, key=lambda f_: used.get(Path(f_).name, 0))
            else: krng.shuffle(files)
            _pools[spec] = [files, 0]
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
    for x in TRS + CUTTR:                     # звук перехода; вход в панель уже со вжухом из panels.py — второй не нужен
        role = TRX.SOUND.get(x["kind"]); entering = x.get("a", {}).get("mode", "face") == "face" and x.get("b", {}).get("mode", "face") != "face"
        if x.get("b", {}).get("tr_sound") is False: continue          # переход без звука (концовка рядом с мемом)
        if role and not (entering and role == "whoosh") and role in KIT["roles"]:
            # звуки переходов — служебные: тише kit-уровня (2026-10-17: boom на pulse вышел +9 дБ к речи по qa.py)
            tg = {"boom": 0.4, "punch": 0.5, "rise": 0.6}.get(role, 0.7)
            place(role, (x["t0"] + x["t1"]) / 2 if role == "rise" else x["t0"], mult=M.get(role, 1.0) * tg)
    # звук концовки — на начало заставки «смотри полное видео», если она есть: голосовой мем на последней фразе
    # перекрывал речь («Вот это поворот» поверх «есть на моём гитхабе», 2026-10-14)
    _ec = [seg_t[k] for k, s in enumerate(E["segs"]) if s.get("endcard")]
    if FX.get("end_pop", True) and chunks: place("end", _ec[0] + 0.15 if _ec else chunks[-1]["s"], mult=M.get("end_pop", 1.0))
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
    "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(FX.get("crf", 15)), "-pix_fmt", "yuv420p", str(WD / "video.mp4")],
    stdin=subprocess.PIPE)
BAR = FX.get("progress_bar", LOOK.get("accent", "#FFE500")); FACE_Y = FX.get("face_y", 800); fi = 0
# Финальная заставка (план с "endcard": true): обложка полного видео + призыв. В Shorts ссылка «Связанное
# видео» стоит внизу экрана — поэтому «ССЫЛКА ВНИЗУ». Только для вертикали.
EC = FX.get("endcard") or {}
EC_BG = EC_IMG = EC_ST = None
if EC.get("image") and not LAND:
    _ip = Path(EC["image"]).expanduser(); _ip = _ip if _ip.is_absolute() else WD / _ip     # относительный путь — от папки проекта
    if not _ip.exists(): raise SystemExit(f"endcard: нет картинки {_ip}")
    _ci = cv2.cvtColor(cv2.imread(str(_ip)), cv2.COLOR_BGR2RGB)
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
# ---------- запись экрана на весь кадр (fx.json "screen") ----------
# Recordly с его зумами — поверх всего кадра (лицо прячется), субтитры и плашки рисуются сверху (2026-10-14).
# Записи: {"file", "from": сек экрана, и либо "a"/"b" — сек ИСХОДНИКА (картинка идёт вместе с речью, режется
# вместе с планами; "to" — конец куска экрана, иначе 1:1), либо "t"/"dur" — сек выхода (свободная перебивка)}.
SCR = []
for c in FX.get("screen", []):
    f = str(Path(c["file"]).expanduser() if Path(c["file"]).expanduser().is_absolute() else WD / c["file"])
    if "a" in c:
        rate = (c["to"] - c["from"]) / (c["b"] - c["a"]) if "to" in c else 1.0
        for s_ in E["segs"]:
            o0, o1 = max(c["a"], s_["a"]), min(c["b"], s_["b"])
            if o1 - o0 < 0.05: continue
            sp_ = s_.get("sp_eff", E.get("speed", 1.15))
            SCR.append(dict(file=f, t=s_["f0"] / FPS + (o0 - s_["a"]) / sp_, dur=(o1 - o0) / sp_, src=c["from"] + (o0 - c["a"]) * rate, speed=sp_ * rate))
    else:
        SCR.append(dict(file=f, t=c["t"], dur=c["dur"], src=c["from"], speed=c.get("speed", 1.0)))
SCR.sort(key=lambda x: x["t"])
_sdec = {}
def screen_frame(t):
    for i, c in enumerate(SCR):
        if c["t"] - 1e-6 <= t < c["t"] + c["dur"]:
            if i not in _sdec:
                _sdec[i] = [subprocess.Popen(["ffmpeg", "-v", "quiet", "-ss", f"{c['src']:.3f}", "-t", f"{c['dur'] * c['speed'] + 0.2:.3f}", "-i", c["file"], "-an",
                    "-vf", f"setpts=(PTS-STARTPTS)/{c['speed']},fps={FPS}," + (f"scale={OW}:{OH}:force_original_aspect_ratio=decrease,pad={OW}:{OH}:(ow-iw)/2:(oh-ih)/2,format=rgb24" if LAND else
                           f"split[a][b];[a]scale={OW}:{OH}:force_original_aspect_ratio=increase,crop={OW}:{OH},boxblur=30:2,eq=brightness=-0.28[bg];"
                           f"[b]crop='min(iw,ih*1.1)':ih,scale={OW}:-2[fg];[bg][fg]overlay=0:(H-h)*0.42,format=rgb24"),   # середина кадра почти квадратом — крупнее, чем вся ширина
                    "-f", "rawvideo", "-"], stdout=subprocess.PIPE), None]
            p_, last_ = _sdec[i]; b_ = p_.stdout.read(OW * OH * 3) if p_ else b""
            if len(b_) == OW * OH * 3: _sdec[i][1] = last_ = np.frombuffer(b_, np.uint8).reshape(OH, OW, 3)
            return last_
        if c["t"] + c["dur"] <= t and i in _sdec and _sdec[i][0]:      # кусок кончился — декодер закрываем
            _sdec[i][0].stdout.close(); _sdec[i][0].kill(); _sdec[i][0] = None
    return None
BEH_DEC = {}
if SCR: print(f"запись экрана на весь кадр: {len(SCR)} кусков, {sum(c['dur'] for c in SCR):.1f} с")

# ---------- фон за человеком: размытие (fx.json "bg") ----------
# 2026-10-17: зрители жаловались на фон (обои с цветами). Автор выбрал вариант C: маска человека через Apple Vision
# (VNGeneratePersonSegmentationRequest, accurate, ~32 мс/кадр на 540×960), фон — тот же кадр, сильно размытый
# и затемнённый, плюс виньетка. Полная замена фона не годится: цветы у уха попадают в маску, у волос кайма.
# "bg": false — выключить; {"blur": 40, "dim": 0.55, "vignette": 0.55, "smooth": 0.6} — параметры.
BG = FX.get("bg", {}) if FX.get("bg", {}) is not False else None
BEHIND = any(x[6] for x in STICK); VISION = BG is not None or BEHIND
if VISION:
    try:
        import objc, Vision, Quartz
        from Foundation import NSData
    except Exception as e_:
        print(f"Apple Vision недоступен ({e_}) — фон как есть, «за головой» выключено"); BG = None; BEHIND = VISION = False
if VISION:
    def person_mask(rgb_):
        with objc.autorelease_pool():
            ok_, buf_ = cv2.imencode(".bmp", cv2.resize(rgb_, (540, 960), interpolation=cv2.INTER_AREA)[..., ::-1])
            req = Vision.VNGeneratePersonSegmentationRequest.alloc().initWithCompletionHandler_(None)
            req.setQualityLevel_(0); req.setOutputPixelFormat_(0x4C303038)       # accurate, OneComponent8
            hnd = Vision.VNImageRequestHandler.alloc().initWithData_options_(NSData.dataWithBytes_length_(buf_.tobytes(), len(buf_)), None)
            ok_, _ = hnd.performRequests_error_([req], None); res = req.results()
            if not ok_ or not res: return None
            pb = res[0].pixelBuffer(); Quartz.CVPixelBufferLockBaseAddress(pb, 1)
            mw, mh, bpr = Quartz.CVPixelBufferGetWidth(pb), Quartz.CVPixelBufferGetHeight(pb), Quartz.CVPixelBufferGetBytesPerRow(pb)
            a_ = np.frombuffer(Quartz.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * mh), np.uint8).reshape(mh, bpr)[:, :mw].astype(np.float32) / 255
            Quartz.CVPixelBufferUnlockBaseAddress(pb, 1)
        return a_
    def out_mask(m_src, last_, Maff):
        """Маска человека в координатах готового кадра (тот же зум/сдвиг, что у картинки)."""
        if m_src is None: m_src = person_mask(last_)          # без размытия фона маску считаем только здесь
        if m_src is None: return None
        m_ = cv2.warpAffine(cv2.resize(m_src, (W, H), interpolation=cv2.INTER_LINEAR), Maff, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return cv2.GaussianBlur(m_, (0, 0), 1.5)[..., None]
if BG is not None:
    BG = dict(blur=40, dim=0.55, vignette=0.55, smooth=0.6) | BG
    _yy, _xx = np.mgrid[0:H, 0:W].astype(np.float32)
    _r = np.sqrt(((_xx - W / 2) / (W / 2)) ** 2 + ((_yy - H / 2) / (H / 2)) ** 2)
    VIG = np.clip(1 - BG["vignette"] * (_r - 0.4), 0.35, 1).astype(np.float32)[..., None]; del _yy, _xx, _r
    def bg_blur(rgb_, prev):
        """→ (кадр с размытым фоном, маска для сглаживания следующего кадра)."""
        m = person_mask(rgb_)
        if m is None: return rgb_, prev
        if prev is not None and prev.shape == m.shape: m = BG["smooth"] * m + (1 - BG["smooth"]) * prev   # край не дрожит
        q = 4; sm = cv2.resize(rgb_, (W // q, H // q), interpolation=cv2.INTER_AREA).astype(np.float32)
        wb = 1 - cv2.resize(m, (W // q, H // q), interpolation=cv2.INTER_AREA); sig = BG["blur"] / q
        # нормированное размытие: человек не растекается ореолом по фону
        bgs = cv2.GaussianBlur(sm * wb[..., None], (0, 0), sig) / np.maximum(cv2.GaussianBlur(wb, (0, 0), sig), 1e-3)[..., None]
        bg_ = cv2.resize(bgs, (W, H), interpolation=cv2.INTER_LINEAR) * BG["dim"]
        mf = cv2.GaussianBlur(cv2.resize(m, (W, H), interpolation=cv2.INTER_LINEAR), (0, 0), 2)[..., None]
        out = (rgb_.astype(np.float32) * mf + bg_ * (1 - mf)) * VIG
        return np.clip(out, 0, 255).astype(np.uint8), m
    print("фон: размытие за человеком (Apple Vision)")

# ---------- геометрия раскладок для переходов (transitions.py) ----------
PIPDEF = dict(pos="tr", w=340, h=430, rad=44, y=190)
def pip_rect(st):
    p_ = PIPDEF | (st.get("pip") or {})
    if p_.get("shape") == "round": p_["w"] = p_["h"] = p_.get("size", 380); p_["rad"] = p_["w"] / 2
    return (W - 44 - p_["w"] if p_["pos"] == "tr" else 44, p_["y"], p_["w"], p_["h"]), p_["rad"]
def split_aff(c):
    fh = H - SPLIT; zs = c["z"] / c["zb"]; cws, chs = W / zs, H / zs
    xs = min(max(0, W / 2 + c["dx"] - cws / 2), W - cws); ys = min(max(0, FACE_Y + c["dy"] - chs / 2), H - chs)
    yo = int(min(max(0, (FACE_Y - ys) * zs - FACE_POS * fh), H - fh))
    return (zs, -xs * zs, -ys * zs - yo + SPLIT)
def face_part(st, c):
    """→ (аффин лица, прямоугольник, скругление, карточка) или None для full (там лицо зависит от соседа)."""
    m = st["mode"]
    if m == "face": return (c["Maff"][0, 0], c["Maff"][0, 2], c["Maff"][1, 2]), (0, 0, W, H), 0, 0
    if m == "split": return split_aff(c), (0, SPLIT, W, H - SPLIT), 0, 0
    if m == "pip":
        (x, y, w, h), rad = pip_rect(st); k = h / (0.62 * H) * c["z"] / c["zb"]
        return (k, x + w / 2 - k * (W / 2 + c["dx"]), y + h / 2 - k * (FACE_Y + c["dy"])), (x, y, w, h), rad, 1.0
    return None
def state_geo(st, other, c):
    m = st["mode"]; f = face_part(st, c)
    if m == "full":
        o = face_part(other, c) if other else None
        if o is None: f = ((1, 0, 0), (0, H, W, 0), 0, 0)
        elif other["mode"] == "pip": x, y, w, h = o[1]; f = (o[0], (x + w / 2, y + h / 2, 0, 0), o[2], 1.0)   # карточка растёт из точки
        else: k_, tx, ty = o[0]; x, y, w, h = o[1]; f = ((k_, tx, ty + (H - y)), (x, H, w, h), o[2], o[3])  # лицо уезжает вниз
    if m == "face":
        if other and other["mode"] == "pip": gr, gs = (0, 0, W, H), 0      # графика уже за лицом: лицо сжимается в карточку
        else: gh = SPLIT if other and other["mode"] == "split" else H; gr, gs = (0, -gh, W, gh), -gh   # графика въезжает сверху
    elif m == "split": gr, gs = (0, 0, W, SPLIT), 0
    else: gr, gs = (0, 0, W, H), 0
    return TRX.geo(f[0], f[1], gr, gs, f[2], f[3])
def sub_ps(x, t):
    """Прогресс перехода на 5 подкадрах внутри кадра (выдержка 180°) — для размытия движения."""
    L = x["t1"] - x["t0"]; p = (t - x["t0"]) / L; dp = 0.5 / (FPS * L)
    n = 11 if x["kind"] == "zoom" else 7                 # зуму больше подкадров: масштаб за кадр меняется сильно
    return [TRX.clip01(p + dp * (i / (n - 1) - 0.5)) for i in range(n)], p
def layout_transition(x, t, last, glast, c):
    ps, p = sub_ps(x, t); a, b = x["a"], x["b"]
    ga, gb = state_geo(a, b, c), state_geo(b, a, c)
    if x["kind"] == "morph":
        ez = (lambda q: TRX.out_back(q, 1.2)) if "pip" in (a["mode"], b["mode"]) else TRX.inout_expo
        acc = np.zeros((H, W, 3), np.float32)
        for q in ps: acc += TRX.compose(TRX.lerp(ga, gb, ez(q)), last, glast, W, H)
        out = (acc / len(ps)).astype(np.uint8); e = ez(p)
    else:
        A = TRX.compose(ga, last, glast, W, H); B = TRX.compose(gb, last, glast, W, H)
        out = TRX.mix(x["kind"], A, B, ps, dict(dict(dir=x["dir"], seed=SEED, center=(W / 2 + c["dx"], FACE_Y)), **x.get("opt", {})))
        e = TRX.inout_cubic(p)
    ya, yb = CAPY.get(a["mode"], CAP["y"]), CAPY.get(b["mode"], CAP["y"])
    return out, ya + (yb - ya) * TRX.clip01(e), (b if p >= 0.5 else a)["mode"]
def tl_entry(t): return next((x for x in TLN if x["s"] <= t < x["e"]), {"mode": "face"})
prev_out = held = held_for = None
# цветокоррекция лица (grade.py → $WD/grade.cube, 3D-LUT): на декодере планов лица, b-roll и записи экрана не трогает.
# "grade": false в fx.json — без неё (2026-10-17, автор: «можно норм отцветокорить моё видео?»)
GRADE_VF = None
if (WD / "grade.cube").exists() and FX.get("grade", True) is not False:
    GRADE_VF = "lut3d=file=" + str(WD / "grade.cube").replace(":", "\\:") + ":interp=tetrahedral,"
    print("цвет: " + (json.load(open(WD / "grade.json")).get("look", "?") if (WD / "grade.json").exists() else "grade.cube"))

for k, s in enumerate(E["segs"]):
    dec = subprocess.Popen(["ffmpeg", "-v", "quiet", "-ss", f"{s['a']}", "-t", f"{s['b'] - s['a'] + 0.1}", "-i", s.get("src", SRC), "-an",   # "src" у плана — склейка из разных съёмок (merge_wd.py)
        "-vf", f"setpts=(PTS-STARTPTS)/{s['sp_eff']}," + (f"minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1," if s.get("slowmo") else "")   # slowmo.py: плавное замедление
               + f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
               + (GRADE_VF if GRADE_VF and not s.get("broll") else "") + "format=rgb24",
        "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    last = np.zeros((H, W, 3), np.uint8)
    # Стоп-кадр в начале (резкий кадр с лицом держится, пока камера «доезжает») выключен по умолчанию: автор,
    # 2026-10-17: «убери эту штуку, когда в начале видео с камеры не идёт, а зависло на первом кадре». Смазанное
    # начало режь в edl.json (первый план — с момента, где лицо уже резкое). "first_frame_sharp": true — вернуть.
    pre = []; pre_m = []
    if k == 0 and FX.get("first_frame_sharp", False):
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
            best = int(np.argmax(score)); pre = [pre[max(i_, best)] for i_ in range(len(pre))]; pre_m = [None] * len(pre)
            if BG is not None and not s.get("broll"):                # стоп-кадр — один и тот же кадр, считаем раз
                _bp = {}; _m = None
                for i_, f_ in enumerate(pre):
                    if id(f_) not in _bp: _bp[id(f_)] = bg_blur(f_, _m); _m = _bp[id(f_)][1]
                    pre[i_], pre_m[i_] = _bp[id(f_)]
            if best: print(f"первый кадр: держу резкий кадр с лицом ({best / FPS:.2f} с стоп-кадра)")
    got = len(pre); bgm = cur_m = None; use_bg = BG is not None and not s.get("broll") and not s.get("endcard") and s.get("bg", True) is not False
    if s.get("endcard") and EC_BG is not None:
        for j in range(s["n"]):
            fr = endcard_frame(j / max(1, s["n"] - 1))
            if BAR: fr[0:12, : int(W * (fi + 1) / NF)] = rgb(BAR)
            enc.stdin.write(fr.tobytes()); fi += 1
        dec.stdout.close(); dec.wait(); print(f"план {k:02d} — заставка ({fi}/{NF})", flush=True); continue
    for j in range(s["n"]):
        if j < len(pre): last = pre[j]; cur_m = pre_m[j]
        else:
            buf = dec.stdout.read(W * H * 3)
            if len(buf) == W * H * 3:
                last = np.frombuffer(buf, np.uint8).reshape(H, W, 3); got += 1; cur_m = None
                if use_bg: last, bgm = bg_blur(last, bgm); cur_m = bgm
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
        Maff = np.float32([[z, 0, -x0 * z], [0, z, -y0 * z]])
        fr = cv2.warpAffine(last, Maff, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        for tf in FLASH:
            if 0 <= t - tf < 0.12: a_ = (1 - (t - tf) / 0.12) * 0.85; fr = (fr * (1 - a_) + 255 * a_).astype(np.uint8)
        if gdec:
            gb = gdec.stdout.read(GW * GH * 3)
            if len(gb) == GW * GH * 3: glast = np.frombuffer(gb, np.uint8).reshape(GH, GW, 3)
        md = mode_at(t); cap_y = None
        ctx = dict(Maff=Maff, z=z, zb=zb, dx=dx, dy=dy)
        tr = None if LAND else next((x for x in TRS if x["t0"] <= t < x["t1"]), None)
        if tr: fr, cap_y, md = layout_transition(tr, t, last, glast, ctx)
        elif LAND: pan = md in ("split", "full"); fr = landscape(fr, glast, pan); md = "land" if pan else "land_face"
        elif md == "full": fr = glast.copy()
        elif md == "pip": fr = TRX.compose(state_geo(tl_entry(t), None, ctx), last, glast, W, H)
        elif md == "split":                                                  # графика сверху, лицо — в нижней части
            # крупность плана тут не нужна (лицо и так обрезано вдвое) — только толчки склеек/акцентов
            fh = H - SPLIT; zs = z / zb; cws, chs = W / zs, H / zs
            xs = min(max(0, W / 2 + dx - cws / 2), W - cws); ys = min(max(0, FACE_Y + dy - chs / 2), H - chs)
            ff = cv2.warpAffine(last, np.float32([[zs, 0, -xs * zs], [0, zs, -ys * zs]]), (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            yo = int(min(max(0, (FACE_Y - ys) * zs - FACE_POS * fh), H - fh))
            fr = np.concatenate([glast[:SPLIT], ff[yo:yo + fh]], axis=0)
        # запись экрана — после выбора раскладки (2026-10-14: стояла внутри if/elif и в вертикали съела все панели)
        if SCR:
            sf_ = screen_frame(t)
            if sf_ is not None: fr = sf_.copy(); md = "land" if LAND else "full"
        ct = next((x for x in CUTTR if x["t0"] <= t < x["t1"]), None)
        if ct:                                    # переход на склейке лицо→лицо: последний кадр старого плана уезжает
            if held_for is not ct: held, held_for = prev_out, ct
            if held is not None: fr = TRX.mix(ct["kind"], held, fr, sub_ps(ct, t)[0], dict(dict(dir=ct["dir"], seed=SEED + int(ct["t0"] * 10), center=(W / 2, FACE_Y)), **ct["opt"]))
        prev_out = fr.copy()
        mo = None
        for si, (ts, d, img, sx, sy, inst, beh) in enumerate(STICK):
            if 0 <= t - ts < d:
                q = (t - ts) / 0.14; sc = 1.0 if inst or q >= 1.5 else 0.4 + 0.75 * ease(q) - 0.15 * ease((q - 1) * 2)
                if beh and BEHIND and md == "face":
                    # «текст за головой»: рисуем надпись, потом возвращаем поверх пиксели человека по маске.
                    # Решение — один раз на первом кадре надписи: если голова закрывает > 1-behind_min текста,
                    # ставим спереди (в селфи-кадре голова часто закрывает всю строку — читать нечего).
                    if mo is None: mo = out_mask(cur_m, last, Maff)
                    if mo is not None and si not in BEH_DEC:
                        A_ = np.zeros((H, W), np.float32); a_img = img.copy(); a_img[..., :3] = 255
                        _tmp = np.zeros((H, W, 3), np.uint8); blend(_tmp, a_img, sx, sy, sc); A_ = _tmp[..., 0].astype(np.float32) / 255
                        vis = float((A_ * (1 - mo[..., 0])).sum() / max(A_.sum(), 1)); BEH_DEC[si] = vis >= FX.get("behind_min", 0.8)
                        print(f"за головой: надпись {si} видна на {vis:.0%} → {'за головой' if BEH_DEC[si] else 'спереди'}")
                    if mo is not None and BEH_DEC.get(si):
                        fr0 = fr.copy(); blend(fr, img, sx, sy, sc); fr[:] = (fr * (1 - mo) + fr0 * mo).astype(np.uint8); continue
                blend(fr, img, sx, sy, sc)
        for ci, c in enumerate(chunks):
            if c["s"] <= t < c["e"]:
                if CAP["style"] == "glow": draw_caption(fr, ci, t, cap_y if cap_y is not None else CAPY.get(md, CAP["y"])); break
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
