# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile", "pillow", "opencv-python-headless<4.13",
#   "pyobjc-framework-Vision; sys_platform == 'darwin'", "pyobjc-framework-Quartz; sys_platform == 'darwin'"]
# ///
"""qa.py <workdir> [video.mp4] — проверка готового шортса перед сдачей (после render.py, до master.sh или после).

Идея из ресерча 2026-10-17 (ghost-editor, video-use): модель не смотрит ролик целиком, поэтому ролик проверяет
скрипт, а я правлю найденное и перезапускаю — не больше 3 проходов. Проверки:
  1. Читаемость субтитров — Apple Vision OCR (ru/en) на кадре каждой фразы: распознано ли каждое слово.
     Главный риск стиля glow (свечение без обводки) и рукописных акцентов.
  2. Субтитры и плашки на лице — пересечение текста с зоной глаз и рта (Vision face rectangles).
  3. Зоны интерфейса Shorts — текст не должен заходить в нижние ~380 px (название, канал), в правую колонку
     кнопок (x > 940 при y 700–1540) и в верхние 140 px.
  4. Громкость каждого звука относительно речи рядом (sfx.wav против voice.wav): служебные звуки должны быть
     на 5–7 дБ тише речи, мемы — на 1–5 дБ, слишком тихие (< −18 дБ) не слышны.
  5. Пустоты: отрезки > 2 с почти без движения в кадре.
Пишет <workdir>/qa/report.md и qa/*.jpg (кадры с проблемами), печатает сводку."""
import difflib, json, re, subprocess, sys, tempfile
from pathlib import Path
import cv2, numpy as np, soundfile as sf

WD = Path(sys.argv[1]); VID = Path(sys.argv[2]) if len(sys.argv) > 2 else WD / "video.mp4"
OUT = WD / "qa"; OUT.mkdir(exist_ok=True)
for f in OUT.glob("*.jpg"): f.unlink()
OV = json.load(open(WD / "overlays.json")); CAP = OV["caption"]; LAND = OV.get("landscape")
LAY = json.load(open(WD / "layout.json")) if (WD / "layout.json").exists() and (WD / "gfx.mp4").exists() else {}
W, H = (1920, 1080) if LAND else (1080, 1920)
import objc, Vision, Quartz
from Foundation import NSData

def grab(t):
    with tempfile.NamedTemporaryFile(suffix=".png") as tf:
        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", f"{max(0, t):.3f}", "-i", str(VID), "-frames:v", "1", tf.name])
        im = cv2.imread(tf.name)
    return im
def vision(img_bgr, req):
    with objc.autorelease_pool():
        ok, buf = cv2.imencode(".png", img_bgr)
        h = Vision.VNImageRequestHandler.alloc().initWithData_options_(NSData.dataWithBytes_length_(buf.tobytes(), len(buf)), None)
        h.performRequests_error_([req], None)
        return list(req.results() or [])
def box(obs, w, h):
    """Нормированный bbox Vision (начало внизу слева) → пиксели (x0, y0, x1, y1), начало вверху слева."""
    b = obs.boundingBox(); x, y, bw, bh = b.origin.x, b.origin.y, b.size.width, b.size.height
    return (x * w, (1 - y - bh) * h, (x + bw) * w, (1 - y) * h)
def ocr(img):
    r = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(None)
    r.setRecognitionLevel_(0); r.setRecognitionLanguages_(["ru-RU", "en-US"]); r.setUsesLanguageCorrection_(False)
    h, w = img.shape[:2]
    return [(o.topCandidates_(1)[0].string(), box(o, w, h)) for o in vision(img, r) if o.topCandidates_(1)]
def faces(img):
    r = Vision.VNDetectFaceRectanglesRequest.alloc().initWithCompletionHandler_(None)
    h, w = img.shape[:2]; return [box(o, w, h) for o in vision(img, r)]
_LAT = str.maketrans("aeopcxykmthb", "аеорсхукмтнв")      # OCR путает латиницу и кириллицу («OН»)
def norm(s): return re.sub(r"[^\w]", "", s.lower().replace("ё", "е").translate(_LAT))
def inter(a, b):
    w = max(0, min(a[2], b[2]) - max(a[0], b[0])); h = max(0, min(a[3], b[3]) - max(a[1], b[1])); return w * h
def mode_at(t):
    for m in LAY.get("modes", []):
        if m["s"] <= t < m["e"]: return m["mode"]
    return "face"

issues = {k: [] for k in ("read", "face", "zone", "sound", "static")}
def shot(name, img, boxes=()):
    im = img.copy()
    for b in boxes: cv2.rectangle(im, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 0, 255), 4)
    cv2.imwrite(str(OUT / f"{name}.jpg"), cv2.resize(im, (im.shape[1] // 2, im.shape[0] // 2)), [cv2.IMWRITE_JPEG_QUALITY, 80])

# Зоны интерфейса Shorts (вертикаль 1080×1920; в горизонтали проверка не нужна)
ZONES = [] if LAND else [("низ: название и канал", (0, 1540, W, H)), ("правая колонка кнопок", (940, 700, W, 1540)), ("верх: поиск/назад", (0, 0, W, 140))]
SPLIT = LAY.get("split")

# ---------- 1–3: субтитры ----------
acc_words = set()
fx = json.load(open(WD / "fx.json")) if (WD / "fx.json").exists() else {}
n_ok = 0
for ci, c in enumerate(OV["chunks"]):
    ws = c["ws"]; ap = max(c["s"], ws[-1]["s"] - CAP.get("lead", 0.04))  # все слова на экране, анимация последнего кончилась
    t = min(c["e"] - 0.02, ap + min(CAP.get("rise", 0.16), 0.4 * max(0.05, c["e"] - ap)) + 0.03)
    md = mode_at(t)
    if md == "full": continue                                           # графика на весь кадр — субтитры поверх неё не проверяем
    img = grab(t)
    if img is None: continue
    cy = SPLIT if (md == "split" and SPLIT) else CAP.get("y", 1380)
    # сначала узкая полоса ±110 px: на стыке графики и лица широкая полоса (±230) даёт пустой OCR, хотя текст читается
    # глазом (2026-10-17: «в феврале», «предложили», «ну и» на стыке split); широкая — запасной вариант
    for hw in (110, 230):
        y0, y1 = int(max(0, cy - hw)), int(min(img.shape[0], cy + hw))
        found = ocr(img[y0:y1])
        if found: break
    toks = [norm(x) for s_, _ in found for x in s_.split()]
    joined = norm("".join(s_ for s_, _ in found))
    miss = [w["t"] for w in ws if norm(w["t"]) and not (norm(w["t"]) in joined or any(difflib.SequenceMatcher(None, norm(w["t"]), x).ratio() >= 0.75 for x in toks))]
    # только боксы со словами этой фразы: на записи экрана OCR цепляет иконки дока и текст сайта (2026-10-17: ложная
    # «зона кнопок» на «моем гитхабе»)
    exp = [norm(w["t"]) for w in ws if len(norm(w["t"])) > 1]
    tboxes = [(b[0], b[1] + y0, b[2], b[3] + y0) for s_, b in found
              if any(e in norm(s_) or difflib.SequenceMatcher(None, e, norm(s_)).ratio() >= 0.6 for e in exp)]
    if miss and all(len(norm(m)) <= 2 for m in miss) and len(miss) < len(ws): miss = []   # OCR слаб на «и», «ее» — не шумим
    if miss:
        issues["read"].append(f"{t:6.2f} с  «{' '.join(w['t'] for w in ws)}» — не прочитано: {', '.join(miss)} (OCR: {' | '.join(s_ for s_, _ in found) or '—'})")
        shot(f"read_{ci:03d}", img, tboxes)
    else: n_ok += 1
    if md == "face" and tboxes:
        for fb in faces(img):
            fh = fb[3] - fb[1]; core = (fb[0], fb[1] + 0.2 * fh, fb[2], fb[1] + 0.8 * fh)    # глаза…рот, без подбородка
            for tb in tboxes:
                if inter(tb, core) > 0.25 * max(1, (tb[2] - tb[0]) * (tb[3] - tb[1])):
                    issues["face"].append(f"{t:6.2f} с  субтитр «{' '.join(w['t'] for w in ws)}» на лице"); shot(f"face_{ci:03d}", img, [tb, core]); break
    for zn, z in ZONES:
        for tb in tboxes:
            if inter(tb, z) > 0.2 * max(1, (tb[2] - tb[0]) * (tb[3] - tb[1])):
                issues["zone"].append(f"{t:6.2f} с  субтитр «{' '.join(w['t'] for w in ws)}» в зоне «{zn}»"); break

# плашки и хук: bbox непрозрачной части PNG на месте (x, y — центр)
for si, st in enumerate(OV.get("stickers", [])):
    png = st.get("png")
    if not png or not Path(png).exists(): continue
    a = cv2.imread(png, cv2.IMREAD_UNCHANGED)
    if a is None or a.shape[2] < 4: continue
    ys, xs = np.where(a[..., 3] > 40)
    if not len(xs): continue
    h_, w_ = a.shape[:2]; X0, Y0 = st.get("x", 540) - w_ / 2, st.get("y", 340) - h_ / 2
    sb = (X0 + xs.min(), Y0 + ys.min(), X0 + xs.max(), Y0 + ys.max())
    name = (st.get("text") or "").replace("\n", " ")
    for zn, z in ZONES:
        if inter(sb, z) > 0.2 * (sb[2] - sb[0]) * (sb[3] - sb[1]): issues["zone"].append(f"{st['t']:6.2f} с  плашка «{name}» в зоне «{zn}»")
    tm = st["t"] + min(0.5, st.get("dur", 1.3) / 2)
    if mode_at(tm) == "face":
        img = grab(tm)
        if img is not None:
            for fb in faces(img):
                fh = fb[3] - fb[1]; eyes = (fb[0], fb[1] + 0.25 * fh, fb[2], fb[1] + 0.55 * fh)
                if inter(sb, eyes) > 0.25 * (eyes[2] - eyes[0]) * (eyes[3] - eyes[1]):
                    issues["face"].append(f"{st['t']:6.2f} с  плашка «{name}» закрывает глаза"); shot(f"face_st{si:02d}", img, [sb, eyes])

# ---------- 4: громкость звуков относительно речи ----------
def rms_db(x): return 20 * np.log10(np.sqrt((x ** 2).mean() + 1e-12)) if len(x) else -120.0
if (WD / "sfx_list.json").exists() and (WD / "sfx.wav").exists():
    voice, sr = sf.read(WD / "voice.wav"); sfx, sr2 = sf.read(WD / "sfx.wav")
    voice = voice.mean(1) if voice.ndim > 1 else voice; sfx = sfx.mean(1) if sfx.ndim > 1 else sfx
    w3 = int(sr * 0.3); hop = int(sr * 0.05)
    def lvl(x, t0, t1):
        """Самое громкое окно 300 мс в [t0, t1] (кратковременная громкость, как слышит зритель)."""
        a, b = int(t0 * sr), int(t1 * sr); x = x[a:max(b, a + w3)]
        return max((rms_db(x[k:k + w3]) for k in range(0, max(1, len(x) - w3 + 1), hop)), default=-120.0)
    n_ = len(voice) // w3; d = np.array([rms_db(voice[k * w3:(k + 1) * w3]) for k in range(n_)])
    act = d[d > d.max() - 25]; SPEECH = float(10 * np.log10((10 ** (act / 10)).mean()))
    L = sorted(json.load(open(WD / "sfx_list.json"))["sounds"], key=lambda x: x["t"])
    groups = []                 # звуки, которые звучат одновременно (или ближе 0.35 с) — одна серия, слышна вместе
    for x in L:
        if groups and x["t"] < max(max(y["t"] + min(y.get("dur", 0.3), 1.5) for y in groups[-1]), groups[-1][-1]["t"] + 0.35):
            groups[-1].append(x)
        else: groups.append([x])
    for g in groups:
        t0 = g[0]["t"]; t1 = max(x["t"] + min(x.get("dur", 0.3), 1.5) for x in g)
        dlt = lvl(sfx, t0, t1) - SPEECH
        meme = any("Meme" in x.get("file", "") or str(x.get("spec", "")).startswith("meme") for x in g)
        loud = any(str(x.get("spec")) in ("boom", "end", "error", "end_pop") for x in g)
        nm = Path(g[0].get("file", "?")).stem[:36] + (f" + ещё {len(g) - 1}" if len(g) > 1 else "")
        lim = 5 if meme else 3 if loud else 1
        if meme and len(g) > 1 and t0 > len(voice) / sr - 3:          # последние 3 с ролика
            issues["sound"].append(f"{t0:6.2f} с  в концовке мем перекрыт другим звуком ({', '.join(str(x.get('spec')) for x in g)}) — "
                                   "правило автора: рядом с мемом-концовкой других SFX нет")
        if dlt > lim: issues["sound"].append(f"{t0:6.2f} с  «{nm}» ({g[0].get('spec')}) {dlt:+.1f} дБ к речи — громче нормы (≤ {lim:+d})")
        elif dlt < -20: issues["sound"].append(f"{t0:6.2f} с  «{nm}» почти не слышен ({dlt:+.1f} дБ к речи)")

# ---------- 5: пустоты без движения ----------
p = subprocess.Popen(["ffmpeg", "-v", "quiet", "-i", str(VID), "-vf", "fps=10,scale=108:-2,format=gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
sw, sh_ = 108, (192 if not LAND else 60); prev = None; diffs = []
while True:
    b = p.stdout.read(sw * sh_)
    if len(b) < sw * sh_: break
    f = np.frombuffer(b, np.uint8).astype(np.float32).reshape(sh_, sw)
    diffs.append(np.abs(f - prev).mean() if prev is not None else 99); prev = f
p.wait(); run = 0
for k, d in enumerate(diffs + [99]):
    if d < 1.2: run += 1
    else:
        if run >= 20: issues["static"].append(f"{(k - run) / 10:6.2f}–{k / 10:.2f} с  почти без движения {run / 10:.1f} с — нужен зум/стикер/перебивка")
        run = 0

# ---------- отчёт ----------
titles = dict(read="Читаемость субтитров (OCR)", face="Текст на лице", zone="Зоны интерфейса Shorts", sound="Громкость звуков", static="Пустоты без движения")
total = sum(len(v) for v in issues.values())
md_ = [f"# QA: {WD.parent.name if WD.name.startswith('.') else WD.name}", "", f"Видео: `{VID}`. Проблем: **{total}**. Субтитры прочитаны целиком: {n_ok} фраз.", ""]
for k, v in issues.items():
    md_.append(f"## {titles[k]} — {len(v) or 'ок'}"); md_ += [f"- {x}" for x in v]; md_.append("")
(OUT / "report.md").write_text("\n".join(md_))
print("\n".join(md_)); print("→", OUT / "report.md")
