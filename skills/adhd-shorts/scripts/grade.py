# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "opencv-python-headless<4.13", "pillow",
#   "pyobjc-framework-Vision; sys_platform == 'darwin'", "pyobjc-framework-Quartz; sys_platform == 'darwin'"]
# ///
"""grade.py <workdir> [--look natural|cine|warm|tech] [--strength 1.0] [--preview] — цветокоррекция лица в шортсе.

Автор, 2026-10-17: «а можно норм отцветокорить моё видео?». Глаз у меня нет, поэтому цвет меряется:
  1. Замер по 5 кадрам из планов: кожа — центр лица (Apple Vision находит лицо: щёки и нос, без шапки и глаз),
     уровни кадра (перцентили яркости).
  2. Коррекция (одинакова для всех look): баланс белого по коже (к типичной светлой коже G/R≈0.78, B/R≈0.66,
     частично и не больше ±12 %), монотонная тоновая кривая: тени → 0.05, кожа → 0.48, свет → 0.97.
  3. Look поверх: natural — чуть контраста и цвета; cine — плёночная S-кривая, тени в бирюзу, света в тёплый, зелень и
     сирень обоев приглушены; warm — тёплый мягкий; tech — нейтральная кожа, холодные тени, плотный контраст (AI-канал).
     Кожа защищена: насыщенность и сдвиги цвета на тонах кожи ослаблены.
Пишет <workdir>/grade.cube (3D-LUT 33³) + grade.json; render.py применяет его к планам лица (не к b-roll и записям экрана)
через ffmpeg lut3d. --preview — лист «оригинал + 4 look» на 3 кадрах → <workdir>/grade_preview.jpg."""
import json, subprocess, sys, tempfile
from pathlib import Path
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

WD = Path(sys.argv[1]); A = sys.argv[2:]
opt = lambda k, d=None: A[A.index(k) + 1] if k in A else d
LOOK = opt("--look", "natural"); STR = float(opt("--strength", 1.0))
E = json.load(open(WD / "edl_out.json")); SRC = E["src"]
SEGS = [s for s in E["segs"] if not s.get("broll") and not s.get("endcard") and s["b"] - s["a"] > 0.8]
W, H = 1080, 1920

def frame(src, t):
    r = subprocess.run(["ffmpeg", "-v", "quiet", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-vf",
                        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    a = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
    return None if a is None else cv2.cvtColor(a, cv2.COLOR_BGR2RGB)

def face_box(rgb):
    import objc, Vision
    from Foundation import NSData
    with objc.autorelease_pool():
        ok, buf = cv2.imencode(".png", cv2.resize(rgb, (540, 960))[..., ::-1])
        req = Vision.VNDetectFaceRectanglesRequest.alloc().initWithCompletionHandler_(None)
        h = Vision.VNImageRequestHandler.alloc().initWithData_options_(NSData.dataWithBytes_length_(buf.tobytes(), len(buf)), None)
        h.performRequests_error_([req], None); res = list(req.results() or [])
        if not res: return None
        b = max(res, key=lambda o: o.boundingBox().size.width).boundingBox()
        return (b.origin.x * W, (1 - b.origin.y - b.size.height) * H, b.size.width * W, b.size.height * H)

def luma(x): return 0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2]

# ---------- 1. замер ----------
picks = [SEGS[int(i)] for i in np.linspace(0, len(SEGS) - 1, min(5, len(SEGS)))]
frames, skins, lums = [], [], []
for s in picks:
    f = frame(s.get("src", SRC), (s["a"] + s["b"]) / 2)
    if f is None: continue
    frames.append(f); x = f.astype(np.float32) / 255; lums.append(luma(x).ravel()[::7])
    fb = face_box(f)
    if fb:
        fx, fy, fw, fh = fb; patch = x[int(fy + 0.48 * fh):int(fy + 0.78 * fh), int(fx + 0.25 * fw):int(fx + 0.75 * fw)].reshape(-1, 3)
        yv = luma(patch); patch = patch[(yv > 0.15) & (yv < 0.92)]             # без бликов и теней
        if len(patch) > 200: skins.append(np.median(patch, axis=0))
L = np.concatenate(lums); p_lo, p_mid, p_hi = (float(np.percentile(L, q)) for q in (0.5, 50, 99.5))
skin = np.median(np.array(skins), axis=0) if skins else None
stats = dict(frames=len(frames), faces=len(skins), luma_p05=round(p_lo, 3), luma_p50=round(p_mid, 3), luma_p995=round(p_hi, 3),
             skin_rgb=[round(float(v), 3) for v in skin] if skin is not None else None,
             skin_ratio_g_r=round(float(skin[1] / skin[0]), 3) if skin is not None else None,
             skin_ratio_b_r=round(float(skin[2] / skin[0]), 3) if skin is not None else None)

# ---------- 2. коррекция ----------
if skin is not None:
    tgt = np.array([1.0, 0.78, 0.66]) * skin[0]
    gains = 1 + 0.7 * (tgt / np.maximum(skin, 1e-3) - 1)                      # 70 % пути к цели — не «пластиковая» кожа
    gains /= (0.2126 * gains[0] + 0.7152 * gains[1] + 0.0722 * gains[2]); gains = np.clip(gains, 0.88, 1.12)
else: gains = np.ones(3)
# Тоновая кривая — монотонная (Фрич–Карлсон) через точки: самые тёмные 0.5 % → 0.05, кожа → 0.48, светлые 99.5 % → 0.97.
# Первая версия (уровни + гамма к 0.60) только высветлила блёклую картинку: чёрный 0.21 так и остался серым (2026-10-17).
ys_in = float(luma((skin * gains)[None])[0]) if skin is not None else p_mid
pts = sorted({0.0: 0.0, p_lo: 0.05, ys_in: 0.48, min(p_hi, 0.995): 0.97, 1.0: 1.0}.items())
px_, py_ = np.array([a for a, _ in pts]), np.array([b for _, b in pts])
def _mono(xk, yk, xs):
    d = np.diff(yk) / np.diff(xk); m = np.r_[d[0], (d[:-1] + d[1:]) / 2, d[-1]]
    for i in range(len(d)):
        if d[i] == 0: m[i] = m[i + 1] = 0
        else:
            a, b = m[i] / d[i], m[i + 1] / d[i]; t = a * a + b * b
            if t > 9: m[i], m[i + 1] = 3 * a / np.sqrt(t) * d[i], 3 * b / np.sqrt(t) * d[i]
    i = np.clip(np.searchsorted(xk, xs) - 1, 0, len(xk) - 2); h = xk[i + 1] - xk[i]; u = (xs - xk[i]) / h
    return (2 * u**3 - 3 * u**2 + 1) * yk[i] + (u**3 - 2 * u**2 + u) * h * m[i] + (-2 * u**3 + 3 * u**2) * yk[i + 1] + (u**3 - u**2) * h * m[i + 1]
CURVE_X = np.linspace(0, 1, 1025); CURVE_Y = np.clip(_mono(px_, py_, CURVE_X), 0, 1)
def tone(x): return np.interp(np.clip(x, 0, 1), CURVE_X, CURVE_Y)
stats.update(gains=[round(float(g), 3) for g in gains], curve=[[round(float(a), 3), round(float(b), 3)] for a, b in pts])

LOOKS = {   # contrast, saturation, skin_sat, тени (RGB), света (RGB), приглушить зелень/сирень, подъём чёрного, сдвиг ББ
    "natural": dict(c=0.08, sat=1.0, skin_sat=0.96, sh=(0, 0, 0), hi=(0, 0, 0), mute=0.15, lift=0.0, wb=(1, 1, 1)),
    "cine": dict(c=0.22, sat=0.94, skin_sat=0.96, sh=(-0.025, 0.012, 0.04), hi=(0.03, 0.012, -0.03), mute=0.45, lift=0.012, wb=(1, 1, 1)),
    "warm": dict(c=0.1, sat=1.0, skin_sat=0.97, sh=(0.01, 0.004, -0.012), hi=(0.035, 0.015, -0.03), mute=0.25, lift=0.025, wb=(1.03, 1.0, 0.95)),
    "tech": dict(c=0.2, sat=0.88, skin_sat=0.94, sh=(-0.02, 0.0, 0.035), hi=(0.0, 0.006, 0.012), mute=0.4, lift=0.0, wb=(0.985, 1.0, 1.03)),
}

def apply(x, look, strength=1.0):
    """x: (...,3) sRGB 0..1 → грейд. Коррекция всегда целиком, look — со strength."""
    P = LOOKS[look]
    # баланс белого по коже не трогает светлые зоны (потолок, лампа остаются белыми, а не жёлтыми)
    Y0 = luma(x)[..., None]; hw = np.clip((Y0 - 0.7) / 0.3, 0, 1); hw = hw * hw * (3 - 2 * hw)
    g = (gains * np.array(P["wb"]) ** strength - 1) * (1 - hw) + 1; xw = np.clip(x * g, 0, 1)
    # кривая — только по яркости, цвет (соотношения каналов) сохраняется: по каналам она раздувала насыщенность в тенях
    # (футболка и кожа уходили в оранжевый, 2026-10-17)
    Yw = luma(xw)[..., None]; y = xw * (tone(Yw) / np.maximum(Yw, 1e-4))
    # контраст: S-кривая (смесь с smoothstep) + подъём чёрного
    c = P["c"] * strength; s3 = y * y * (3 - 2 * y); y = y + c * (s3 - y); y = P["lift"] * strength + y * (1 - P["lift"] * strength)
    Y = luma(y)[..., None]; ch = y - Y
    # тон и насыщенность входа: кожа (оранжевый ~15–45°) защищена, зелень и сирень обоев приглушаются
    hsv = cv2.cvtColor(np.clip(x, 0, 1).astype(np.float32).reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(x.shape)
    hue, sat = hsv[..., 0], hsv[..., 1]
    skinw = (np.exp(-((hue - 28) / 16) ** 2) * np.clip((sat - 0.08) / 0.15, 0, 1))[..., None]
    mutew = ((np.exp(-((hue - 120) / 35) ** 2) + np.exp(-((hue - 270) / 30) ** 2)) * P["mute"] * strength)[..., None]
    k = (P["sat"] ** strength) * (1 - skinw) + (P["skin_sat"] ** strength) * skinw
    y = Y + ch * k * (1 - mutew)
    # раздельное тонирование теней и светов (на коже вдвое слабее)
    Y = luma(y)[..., None]; tint = (np.array(P["sh"]) * (1 - Y) ** 2 + np.array(P["hi"]) * Y ** 2) * strength * (1 - 0.5 * skinw)
    return np.clip(y + tint, 0, 1)

def write_cube(path, look, strength, n=33):
    g = np.linspace(0, 1, n); b, gg, r = np.meshgrid(g, g, g, indexing="ij")         # в .cube красный меняется быстрее всех
    rgb = np.stack([r, gg, b], -1).reshape(-1, 3)
    out = apply(rgb, look, strength)
    with open(path, "w") as f:
        f.write(f'TITLE "adhd-shorts {look}"\nLUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        f.write("\n".join(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in out)); f.write("\n")

def lut_frame(img, cube):
    with tempfile.TemporaryDirectory() as td:
        Image.fromarray(img).save(f"{td}/i.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"{td}/i.png", "-vf", f"lut3d=file={cube}", f"{td}/o.png"], check=True)
        return np.array(Image.open(f"{td}/o.png").convert("RGB"))

if "--preview" in A:
    looks = list(LOOKS); tw = 270; th = 480; rows = frames[:3]
    sheet = Image.new("RGB", ((len(looks) + 1) * (tw + 6), len(rows) * (th + 6) + 50), (16, 16, 20)); d = ImageDraw.Draw(sheet)
    fnt = ImageFont.truetype(str(Path.home() / ".cache/content-factory/fonts/Inter.ttf"), 24)
    names = {"natural": "натурально", "cine": "кино", "warm": "тёплый", "tech": "tech (холодный)"}
    d.text((10, 12), "оригинал", font=fnt, fill=(255, 255, 255))
    with tempfile.TemporaryDirectory() as td:
        for j, lk in enumerate(looks):
            write_cube(f"{td}/{lk}.cube", lk, STR); d.text(((j + 1) * (tw + 6) + 10, 12), names[lk], font=fnt, fill=(255, 255, 255))
        for i, f in enumerate(rows):
            sheet.paste(Image.fromarray(f).resize((tw, th)), (0, 50 + i * (th + 6)))
            for j, lk in enumerate(looks):
                sheet.paste(Image.fromarray(lut_frame(f, f"{td}/{lk}.cube")).resize((tw, th)), ((j + 1) * (tw + 6), 50 + i * (th + 6)))
    sheet.save(WD / "grade_preview.jpg", quality=88); print("лист →", WD / "grade_preview.jpg")
else:
    write_cube(WD / "grade.cube", LOOK, STR)
    json.dump(dict(stats, look=LOOK, strength=STR), open(WD / "grade.json", "w"), ensure_ascii=False, indent=1)
    print("LUT →", WD / "grade.cube")
print(json.dumps(stats, ensure_ascii=False))
