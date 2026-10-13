# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""conform_voice.py <ref.wav> <in.wav> <out.wav> — привести обработанный голос к оригиналу.
Любая внешняя обработка (Adobe Enhance, цепочка плагинов, рендер из FL) может дать другую частоту,
моно, сдвиг на несколько мс (задержка плагинов) и другую длину. Скрипт:
  ресемпл в 48 кГц стерео (ffmpeg, filter_size=64; soxr в brew-ffmpeg нет) →
  сдвиг по кросс-корреляции огибающих (1 мс) относительно ref → длина ровно как у ref → 24 бит.
Печатает найденный сдвиг и сходство; сходство < 0.4 — вероятно, прислали не тот файл."""
import subprocess, sys
import numpy as np, soundfile as sf
ref, inp, out = sys.argv[1:4]
SR = 48000
def load48(f):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-af", "aresample=48000:filter_size=64", "-ac", "2", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)
r, x = load48(ref), load48(inp)
def env(a): h = SR // 1000; n = len(a) // h; return np.abs(a.mean(1)[: n * h]).reshape(n, h).mean(1)
er, ex = env(r), env(x); L = min(len(er), len(ex), 20000)          # первые 20 с
a, b = er[:L] - er[:L].mean(), ex[:L] - ex[:L].mean()
M = 200; c = np.correlate(b, a[M:-M], "valid"); lag = int(c.argmax()) - M   # мс; +lag — вход опаздывает
sim = c.max() / np.sqrt((a[M:-M] ** 2).sum() * (b ** 2).sum() + 1e-12)
k = lag * SR // 1000
x = x[k:] if k > 0 else np.pad(x, ((-k, 0), (0, 0)))
x = np.pad(x, ((0, max(0, len(r) - len(x))), (0, 0)))[: len(r)]
sf.write(out, x, SR, subtype="PCM_24")
print(f"сдвиг {lag:+d} мс (исправлен), сходство {sim:.2f}, длина {len(r)/SR:.3f} с → {out}")
if sim < 0.4: print("ВНИМАНИЕ: сходство низкое — проверь, тот ли это файл")
