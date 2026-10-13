# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "opencv-python-headless<4.13"]
# ///
"""thumb_frames.py <WD> <out_dir> [--n 8] — кандидаты в кадр для обложки (лицо автора, без субтитров).
Берёт моменты акцентов из fx.json (стикеры, punch, shake, boom) и начала планов с крупностью z>1
(обычно лицо крупно), переводит время ролика во время исходника через edl_out.json и вытаскивает
из ИСХОДНИКА самый резкий кадр в окне ±0.35 с (дисперсия лапласиана). Кадры без лица (экран) отбрасываются\n(Haar-каскад OpenCV); акценты идут вперёд, потом самые крупные лица. Пишет NN_<метка>.jpg (1080×1920)
и _sheet.jpg — лист для выбора. Эмоция на акценте обычно ярче всего: удивление, ухмылка, крик."""
import json, re, subprocess, sys
from pathlib import Path
import cv2, numpy as np
WD, OUT = Path(sys.argv[1]), Path(sys.argv[2]); N = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 8
OUT.mkdir(parents=True, exist_ok=True)
E = json.load(open(WD / "edl_out.json")); FX = json.load(open(WD / "fx.json")); FPS = E["fps"]
words = json.load(open(WD / "words_out.json"))
def at(spec, after=0.0):
    if isinstance(spec, (int, float)): return float(spec)
    if spec.startswith("seg:"): return E["segs"][int(spec[4:])]["f0"] / FPS
    for w in words:
        if w["s"] >= after and spec.upper() in w["w"].upper(): return w["s"]
    return None
def to_src(t):
    for s in E["segs"]:
        t0 = s["f0"] / FPS; t1 = t0 + s["n"] / FPS
        if t0 <= t < t1: return None if s.get("broll") else s["a"] + (t - t0) * s["sp_eff"]
    return None
cands = []
for key in ("stickers", "punch", "shake", "boom"):
    for e in FX.get(key, []):
        t = at(e["at"], e.get("after", 0.0))
        if t is not None: cands.append((t + 0.15, re.sub(r"[^\wА-Яа-яЁё]+", "_", e.get("text", e["at"] if isinstance(e["at"], str) else key))[:20]))
for s in E["segs"]:                     # плюс кадр каждые 2.5 с по всем планам — выбор по всему ролику
    if s.get("broll"): continue
    t0, t1 = s["f0"] / FPS, (s["f0"] + s["n"]) / FPS; t = t0 + 0.3
    while t < t1 - 0.2: cands.append((t, f"t{t:05.1f}s")); t += 2.5
seen, picks = [], []
for t, label in sorted(cands, key=lambda c: (c[1].startswith("t"), c[0])):   # акценты не вытесняются периодикой
    src = to_src(t)
    if src is None or any(abs(src - x) < 1.0 for x in seen): continue
    seen.append(src); picks.append((src, label))
FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
def face_area(f):
    g = cv2.cvtColor(cv2.resize(f, (540, 960)), cv2.COLOR_BGR2GRAY)
    fs = FACE.detectMultiScale(g, 1.1, 4, minSize=(70, 70))
    return max((w * h for x, y, w, h in fs), default=0)
def grab(t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t - 0.35):.3f}", "-t", "0.7", "-i", E["src"],
                          "-vf", "fps=20,scale=1080:1920", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8)[: len(raw) // (1080 * 1920 * 3) * 1080 * 1920 * 3].reshape(-1, 1920, 1080, 3)
    if not len(fr): return None
    sharp = [cv2.Laplacian(cv2.cvtColor(f[300:1300], cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() for f in fr]
    return fr[int(np.argmax(sharp))]
# все кандидаты по ролику → только кадры с лицом → акценты (стикеры/punch…) вперёд, потом крупные лица
good = []
for src, label in picks:
    f = grab(src)
    if f is None: continue
    fa = face_area(f)
    if fa: good.append((not label.startswith("t"), fa, src, label, f))
good = sorted(sorted(good, key=lambda g: (g[0], g[1]), reverse=True)[:N], key=lambda g: g[2])
thumbs = []
for i, (_, _, src, label, f) in enumerate(good, 1):
    p = OUT / f"{i:02d}_{label}.jpg"; cv2.imwrite(str(p), f, [cv2.IMWRITE_JPEG_QUALITY, 92])
    th = cv2.resize(f, (270, 480)); cv2.putText(th, f"{i:02d}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 229, 255), 3)
    thumbs.append(th); print(f"{p.name}  src {src:6.2f}s")
if thumbs:
    rows = [np.hstack(thumbs[i:i + 4] + [np.zeros_like(thumbs[0])] * (4 - len(thumbs[i:i + 4]))) for i in range(0, len(thumbs), 4)]
    cv2.imwrite(str(OUT / "_sheet.jpg"), np.vstack(rows)); print("лист:", OUT / "_sheet.jpg")
