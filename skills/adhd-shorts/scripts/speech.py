# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy","soundfile"]
# ///
"""speech.py <audio.wav> [--db 14] — где реально звучит голос (по энергии, окно 10 мс).
Whisper растягивает слова на соседние паузы (слово «даже» может «длиться» 5 сек),
поэтому точки реза берём отсюда, а слова — из расшифровки."""
import argparse, numpy as np, soundfile as sf
ap = argparse.ArgumentParser(); ap.add_argument("wav"); ap.add_argument("--db", type=float, default=14)
ap.add_argument("--gap", type=float, default=0.25); ap.add_argument("--min", type=float, default=0.12)
a = ap.parse_args()
x, sr = sf.read(a.wav)
if x.ndim > 1: x = x.mean(1)
hop = sr // 100; n = len(x) // hop
db = 20 * np.log10(np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
floor = np.percentile(db, 10); on = db > floor + a.db
print(f"шумовой пол ≈ {floor:.1f} dB, порог {floor + a.db:.1f} dB")
regs = []; i = 0
while i < n:
    if on[i]:
        j = i
        while j < n and on[j]: j += 1
        if regs and i - regs[-1][1] < a.gap * 100: regs[-1][1] = j
        else: regs.append([i, j])
        i = j
    else: i += 1
for s, e in regs:
    if (e - s) / 100 >= a.min: print(f"{s/100:8.2f} - {e/100:8.2f}")
