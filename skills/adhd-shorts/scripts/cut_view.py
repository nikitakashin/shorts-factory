# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile", "pillow"]
# ///
"""cut_view.py <workdir> [--all] — картинки склеек голоса, чтобы посмотреть спорные места ДО рендера.

Идея из video-use (timeline_view, ресерч 2026-10-17): модель не слышит звук, но видит волну, слова и кадры.
Для каждой настоящей склейки (не внутренний джамп-зум, где звук идёт без разрыва) рисует PNG ±1 с вокруг стыка
в готовом голосе (voice.wav, после build_voice/tighten): волна, слова из words_out.json, линия склейки и 4 кадра
исходника (до стыка −0.3 с, последний кадр плана, первый кадр следующего, +0.3 с).
Спорная склейка: в ИСХОДНИКЕ сразу за концом плана (или перед началом следующего) ещё звучит речь — значит, режем
посреди слова (так ловятся обрезанные тихие окончания: «на ави…», 2026-10-07); стык внутри слова по words_out;
пауза на стыке > 0.18 с (автор: монтаж впритык, без пауз). По умолчанию картинки только для спорных; --all — все.
Пишет <workdir>/cuts/NN.png, cuts/_sheet.jpg (спорные одной картинкой) и cuts/cuts.txt."""
import json, subprocess, sys, tempfile
from pathlib import Path
import numpy as np, soundfile as sf
from PIL import Image, ImageDraw, ImageFont

WD = Path(sys.argv[1]); ALL = "--all" in sys.argv
E = json.load(open(WD / "edl_out.json")); FPS = E["fps"]; SRC = E["src"]; segs = E["segs"]
voice, SR = sf.read(WD / "voice.wav"); voice = voice.mean(1) if voice.ndim > 1 else voice
words = json.load(open(WD / "words_out.json")) if (WD / "words_out.json").exists() else []
OUT = WD / "cuts"; OUT.mkdir(exist_ok=True)
for f in OUT.glob("*.png"): f.unlink()
FD = Path.home() / ".cache/content-factory/fonts"
def fnt(sz, wt=500):
    f = ImageFont.truetype(str(FD / "Inter.ttf"), sz)
    try: f.set_variation_by_axes([wt])
    except Exception: pass
    return f

# шумовой пол голоса: 10-й перцентиль RMS по окнам 10 мс
win = int(SR * 0.01); nwin = len(voice) // win
rms = np.sqrt((voice[: nwin * win].reshape(nwin, win) ** 2).mean(1) + 1e-12); db = 20 * np.log10(rms)
FLOOR = float(np.percentile(db, 10))
dbm = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(db, 2, mode="edge"), 5), axis=1)   # щелчок в 10–20 мс паузу не рвёт
def db_at(t0, t1, x=None, sr=None):
    x = voice if x is None else x; sr = sr or SR
    a, b = max(0, int(t0 * sr)), min(len(x), int(t1 * sr))
    return 20 * np.log10(np.sqrt((x[a:b] ** 2).mean() + 1e-12)) if b > a else -120.0
def quiet_run(tc, direction):
    """Длина тишины (ниже пола +8 дБ), примыкающей к стыку с одной стороны, в готовом голосе."""
    k = int(tc / 0.01); n = 0
    while 0 <= k + (n if direction > 0 else -n - 1) < len(dbm) and dbm[k + (n if direction > 0 else -n - 1)] < FLOOR + 8: n += 1
    return n * 0.01
# исходный звук (16 кГц из probe.sh): по нему видно, шла ли речь дальше за точкой разреза
SRCA = None
if not (WD / "audio.wav").exists() and Path(SRC).exists():          # как в build_voice.py
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", SRC, "-vn", "-ac", "1", "-ar", "16000", str(WD / "audio.wav")])
if (WD / "audio.wav").exists():
    SRCA, SRSR = sf.read(WD / "audio.wav"); SRCA = SRCA.mean(1) if SRCA.ndim > 1 else SRCA
    _w = int(SRSR * 0.01); _n = len(SRCA) // _w
    SFLOOR = float(np.percentile(20 * np.log10(np.sqrt((SRCA[: _n * _w].reshape(_n, _w) ** 2).mean(1) + 1e-12)), 10))

cuts = []
for i in range(1, len(segs)):
    p_, n_ = segs[i - 1], segs[i]
    if p_.get("endcard") or n_.get("endcard"): continue
    if not p_.get("broll") and not n_.get("broll") and abs(p_["b"] - n_["a"]) < 0.02 and p_.get("src") == n_.get("src"):
        continue                                    # внутренняя склейка: звук без разрыва, только смена крупности
    tc = n_["f0"] / FPS
    inside = next((w for w in words if w["s"] < tc - 0.03 and w["e"] > tc + 0.03), None)
    why = []
    if SRCA is not None and not p_.get("broll") and p_.get("src", SRC) == SRC:
        e_ = db_at(p_["b"], p_["b"] + 0.06, SRCA, SRSR)
        if e_ > SFLOOR + 14: why.append(f"за концом плана в исходнике сразу речь ({e_ - SFLOOR:+.0f} дБ) — не съедено ли окончание")
    if SRCA is not None and not n_.get("broll") and n_.get("src", SRC) == SRC:
        e_ = db_at(n_["a"] - 0.06, n_["a"], SRCA, SRSR)
        if e_ > SFLOOR + 14: why.append(f"перед началом плана в исходнике речь ({e_ - SFLOOR:+.0f} дБ) — не съедено ли начало слова")
    if inside: why.append(f"стык внутри слова «{inside['w'].strip()}»")
    pz = quiet_run(tc, -1) + quiet_run(tc, +1)
    if pz > 0.18 and not p_.get("broll") and not n_.get("broll"): why.append(f"пауза на стыке {pz:.2f} с")
    cuts.append(dict(i=i, tc=tc, prev=p_, next=n_, why=why))

def frame(src, t, w=150, h=266):
    with tempfile.NamedTemporaryFile(suffix=".png") as tf:
        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", f"{max(0, t):.3f}", "-i", src, "-frames:v", "1",
                        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}", tf.name])
        try: return Image.open(tf.name).convert("RGB")
        except Exception: return Image.new("RGB", (w, h), (40, 0, 0))

def draw(c):
    Wd, Hd = 1200, 560; im = Image.new("RGB", (Wd, Hd), (18, 18, 22)); d = ImageDraw.Draw(im)
    p_, n_, tc = c["prev"], c["next"], c["tc"]
    hdr = f"#{c['i']:02d}  план {c['i'] - 1}→{c['i']}   выход {tc:.2f} с   исходник {p_['b']:.2f} → {n_['a']:.2f}"
    d.text((16, 12), hdr, font=fnt(22, 600), fill=(255, 255, 255))
    d.text((16, 42), ("⚠ " + "; ".join(c["why"])) if c["why"] else "ок", font=fnt(19, 500), fill=(255, 120, 90) if c["why"] else (120, 220, 140))
    # волна ±1 с
    x0, y0, ww, hh = 16, 80, Wd - 32, 170; t0 = tc - 1.0
    a, b = max(0, int(t0 * SR)), min(len(voice), int((tc + 1.0) * SR)); seg = voice[a:b]
    d.rectangle([x0, y0, x0 + ww, y0 + hh], fill=(28, 28, 34))
    if len(seg):
        cols = np.array_split(seg, ww)
        for k, col in enumerate(cols):
            if len(col) == 0: continue
            v = min(1, np.abs(col).max() * 3); d.line([x0 + k, y0 + hh / 2 - v * hh / 2, x0 + k, y0 + hh / 2 + v * hh / 2], fill=(90, 190, 255))
    for k in range(-10, 11):                      # деления по 0.1 с
        x = x0 + (k + 10) / 20 * ww; d.line([x, y0 + hh, x, y0 + hh + (8 if k % 5 == 0 else 4)], fill=(120, 120, 130))
        if k % 5 == 0: d.text((x - 14, y0 + hh + 10), f"{k / 10:+.1f}", font=fnt(14), fill=(150, 150, 160))
    xc = x0 + ww / 2; d.line([xc, y0 - 6, xc, y0 + hh + 6], fill=(255, 70, 70), width=3)
    # слова
    for w in words:
        if w["e"] < t0 or w["s"] > tc + 1.0: continue
        xa = x0 + max(0, (w["s"] - t0) / 2.0) * ww; xb = x0 + min(1, (w["e"] - t0) / 2.0) * ww
        d.rectangle([xa, y0 + hh + 34, xb, y0 + hh + 66], outline=(255, 210, 90), width=2)
        d.text((xa + 4, y0 + hh + 38), w["w"].strip(), font=fnt(18, 600), fill=(255, 230, 150))
    # кадры исходника
    fy = y0 + hh + 82; xs = 16
    shots = [(p_.get("src", SRC), p_["b"] - 0.3, "−0.3 с"), (p_.get("src", SRC), p_["b"] - 1 / FPS, "конец плана"),
             (n_.get("src", SRC), n_["a"], "начало след."), (n_.get("src", SRC), n_["a"] + 0.3, "+0.3 с")]
    for k, (src, t, lab) in enumerate(shots):
        fr = frame(src, t, 150, 200); im.paste(fr, (xs, fy)); d.text((xs, fy + 202), lab, font=fnt(14), fill=(170, 170, 180))
        xs += 162 + (40 if k == 1 else 0)
    d.text((xs + 20, fy + 10), "Что проверить:\n• не съедено ли окончание слова\n• нет ли вдоха / «э-э» на хвосте\n• лицо не дёргается на стыке",
           font=fnt(17), fill=(200, 200, 210), spacing=8)
    return im

risky = [c for c in cuts if c["why"]]
lines = [f"{len(cuts)} склеек, спорных {len(risky)} (шумовой пол голоса {FLOOR:.0f} дБ)"]
imgs = []
for c in cuts:
    lines.append(f"#{c['i']:02d}  {c['tc']:6.2f} с  " + ("⚠ " + "; ".join(c["why"]) if c["why"] else "ок"))
    if c["why"] or ALL:
        im = draw(c); im.save(OUT / f"{c['i']:02d}.png")
        if c["why"]: imgs.append(im)
(OUT / "cuts.txt").write_text("\n".join(lines) + "\n")
if imgs:
    sh = Image.new("RGB", (1200, 560 * len(imgs)), (0, 0, 0))
    for k, im in enumerate(imgs): sh.paste(im, (0, 560 * k))
    sh.thumbnail((1200, 560 * 8)); sh.save(OUT / "_sheet.jpg", quality=85)
print("\n".join(lines)); print("→", OUT)
