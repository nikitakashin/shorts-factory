# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow", "opencv-python-headless<4.13", "librosa", "soundfile"]
# ///
"""ref_frames.py <видео…> --out <папка> — материал для покадрового разбора референса моушн-графики.

Модель не смотрит видео и не слышит звук, поэтому видео превращается в то, что можно прочитать:
  sheet_NN.jpg   раскадровка по всей длине (а не только начало): 5 к/с до 20 с, 3 к/с до 40 с, 2 к/с дольше;
                 у каждого кадра подпись времени
  key_TTT.Ts.jpg ключевые кадры в полном размере — на каждой смене сцены и середине длинных сцен (текст, иконки, цвет)
  info.md        длина, размер, fps; смены сцен (детектор ffmpeg); палитра каждого ключевого кадра (k-means, HEX и доля);
                 звук: громкость, темп (BPM), моменты ударов/атак, яркость спектра по секундам — чтобы описать
                 настроение и где стоят SFX (сам звук модель не слышит)
Используется для референсов автора (2026-10-17: «извлечь и изучить кадры на всём протяжении видео…»)."""
import json, re, subprocess, sys
from pathlib import Path
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

args = sys.argv[1:]; OUT = Path(args[args.index("--out") + 1]); vids = [Path(a) for a in args if a != "--out" and Path(a).suffix.lower() in (".mp4", ".mov", ".webm", ".m4v")]
FD = Path.home() / ".cache/content-factory/fonts/Inter.ttf"
def fnt(sz): return ImageFont.truetype(str(FD), sz) if FD.exists() else ImageFont.load_default()

def probe(v):
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(v)], capture_output=True, text=True).stdout)
    vs = next(s for s in j["streams"] if s["codec_type"] == "video"); a = any(s["codec_type"] == "audio" for s in j["streams"])
    n, d = vs["r_frame_rate"].split("/"); return float(j["format"]["duration"]), vs["width"], vs["height"], float(n) / float(d), a

def scenes(v, thr=0.22):
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", str(v), "-vf", f"select='gt(scene,{thr})',showinfo", "-an", "-f", "null", "-"], capture_output=True, text=True).stderr
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", out)]

def frame_at(v, t, w=None):
    vf = f"scale={w}:-2" if w else "null"
    r = subprocess.run(["ffmpeg", "-v", "quiet", "-ss", f"{t:.3f}", "-i", str(v), "-frames:v", "1", "-vf", vf, "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    if not r.stdout: return None                       # за концом ролика ffmpeg ничего не отдаёт
    a = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
    return None if a is None else cv2.cvtColor(a, cv2.COLOR_BGR2RGB)

def palette(img, k=6):
    px = cv2.resize(img, (90, 160)).reshape(-1, 3).astype(np.float32)
    _, lab, cen = cv2.kmeans(px, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    cnt = np.bincount(lab.ravel(), minlength=k) / len(lab)
    return [("#%02X%02X%02X" % tuple(int(c) for c in cen[i]), float(cnt[i])) for i in np.argsort(-cnt)]

def audio(v):
    import librosa, soundfile as sf, tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav") as tf:
        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-i", str(v), "-vn", "-ac", "1", "-ar", "22050", tf.name])
        y, sr = sf.read(tf.name)
    if len(y) < sr * 0.5 or np.abs(y).max() < 1e-4: return "звук: тишина"
    rms = librosa.feature.rms(y=y, hop_length=512)[0]; db = 20 * np.log10(rms + 1e-9)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr); bt = librosa.frames_to_time(beats, sr=sr)
    on = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=False)
    env = librosa.onset.onset_strength(y=y, sr=sr); strong = librosa.frames_to_time(np.where(env > np.percentile(env, 97))[0], sr=sr)
    strong = [t for i, t in enumerate(strong) if i == 0 or t - strong[i - 1] > 0.15]
    cen = librosa.feature.spectral_centroid(y=y, sr=sr)[0]; ct = librosa.frames_to_time(np.arange(len(cen)), sr=sr)
    per_s = []
    for s in range(int(len(y) / sr) + 1):
        m = (ct >= s) & (ct < s + 1)
        if m.any(): per_s.append(f"{s}s: {float(np.mean(db[m[:len(db)]] if m[:len(db)].any() else -90)):.0f} дБ, центроид {float(np.mean(cen[m])):.0f} Гц")
    return (f"звук: пик {db.max():.0f} дБFS, медиана {np.median(db):.0f} дБ; темп ~{float(np.atleast_1d(tempo)[0]):.0f} BPM; "
            f"долей {len(bt)}; атак (onset) {len(on)}\n- сильные удары/атаки (верхние 3%): {', '.join(f'{t:.2f}' for t in strong[:40])}\n"
            f"- доли: {', '.join(f'{t:.2f}' for t in bt[:48])}\n- по секундам: " + "; ".join(per_s))

for v in vids:
    slug = re.sub(r"[^\w\-]+", "_", v.stem).strip("_")[:60]; od = OUT / slug; od.mkdir(parents=True, exist_ok=True)
    for f in od.glob("*.jpg"): f.unlink()
    dur, w, h, fps, has_a = probe(v); sc = scenes(v)
    step = 0.2 if dur <= 20 else 1 / 3 if dur <= 40 else 0.5
    ts = list(np.arange(0, dur - 0.02, step)); thumbs = []
    for t in ts:
        f = frame_at(v, t, 180)
        if f is None: continue
        im = Image.fromarray(f); d = ImageDraw.Draw(im); d.rectangle([0, 0, 64, 20], fill=(0, 0, 0)); d.text((3, 2), f"{t:.1f}s", font=fnt(14), fill=(255, 255, 0))
        thumbs.append(im)
    per = 24; cols = 6
    for i in range(0, len(thumbs), per):
        grp = thumbs[i:i + per]; tw, th = grp[0].size; rows = (len(grp) + cols - 1) // cols
        sh = Image.new("RGB", (cols * (tw + 4), rows * (th + 4)), (30, 30, 30))
        for j, im in enumerate(grp): sh.paste(im, ((j % cols) * (tw + 4), (j // cols) * (th + 4)))
        sh.save(od / f"sheet_{i // per + 1:02d}.jpg", quality=82)
    bounds = [0.0] + sc + [dur]; keys = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a < 0.15: continue
        keys += [a + 0.08] + ([(a + b) / 2] if b - a > 1.2 else [])
    keys = sorted(set(round(k, 2) for k in keys))[:40]
    lines = [f"# {v.name}", "", f"{dur:.2f} с, {w}×{h}, {fps:.2f} fps, звук: {'есть' if has_a else 'нет'}",
             f"Раскадровка: шаг {step:.2f} с, листов {(len(thumbs) + per - 1) // per} (по 24 кадра, 6 в ряд).",
             f"Смены сцен (порог 0.22): {', '.join(f'{t:.2f}' for t in sc) or 'нет (сплошная анимация)'}", "", "## Ключевые кадры и палитра"]
    for t in keys:
        f = frame_at(v, t)
        if f is None: continue
        Image.fromarray(f).save(od / f"key_{t:06.2f}s.jpg", quality=88)
        lines.append(f"- {t:6.2f} с: " + ", ".join(f"{hx} {p:.0%}" for hx, p in palette(f)))
    lines += ["", "## Звук", audio(v) if has_a else "звук: нет дорожки"]
    (od / "info.md").write_text("\n".join(lines) + "\n"); print(f"{v.name}: {len(thumbs)} кадров, {len(keys)} ключевых, сцен {len(sc)} → {od}")
