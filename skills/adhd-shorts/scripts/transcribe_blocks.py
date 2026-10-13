# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-whisper", "numpy", "soundfile"]
# ///
"""transcribe_blocks.py <audio.wav> <out.json> [--prompt "..."] [--lang ru] [--gap 1.2]
Пословная расшифровка ДЛИННОЙ записи по кускам речи. Whisper на целом файле > ~1 мин с паузами
«зацикливается» (2026-10-09: «Продолжение следует…» 18 раз вместо 3 минут речи) и растягивает слова
через паузы. Здесь: куски речи по энергии (как speech.py), соседние ближе --gap склеиваются, каждый блок
расшифровывается отдельно с condition_on_previous_text=False, тайминги возвращаются в время файла.
out.json: [{w, s, e}] — тот же формат, что transcribe.py. В stdout — блоки с текстом."""
import argparse, json, subprocess, tempfile
import numpy as np, soundfile as sf, mlx_whisper

ap = argparse.ArgumentParser(); ap.add_argument("audio"); ap.add_argument("out")
ap.add_argument("--prompt", default=None); ap.add_argument("--lang", default="ru")
ap.add_argument("--gap", type=float, default=1.2); ap.add_argument("--db", type=float, default=14)
ap.add_argument("--model", default="mlx-community/whisper-large-v3-turbo")
a = ap.parse_args()
x, sr = sf.read(a.audio)
if x.ndim > 1: x = x.mean(1)
hop = sr // 100; n = len(x) // hop
db = 20 * np.log10(np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
on = db > np.percentile(db, 10) + a.db
regs, i = [], 0
while i < n:
    if on[i]:
        j = i
        while j < n and on[j]: j += 1
        if (j - i) >= 12: regs.append([i / 100, j / 100])
        i = j
    else: i += 1
blocks = []
for s, e in regs:
    if blocks and s - blocks[-1][1] < a.gap: blocks[-1][1] = e
    else: blocks.append([s, e])
words = []
tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
for s, e in blocks:
    s0, e0 = max(0, s - 0.3), e + 0.3
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s0}", "-t", f"{e0 - s0}", "-i", a.audio, tmp], check=True)
    r = mlx_whisper.transcribe(tmp, path_or_hf_repo=a.model, language=a.lang, word_timestamps=True,
                               condition_on_previous_text=False, initial_prompt=a.prompt)
    ws = [dict(w=w["word"].strip(), s=round(w["start"] + s0, 2), e=round(w["end"] + s0, 2)) for sg in r["segments"] for w in sg["words"]]
    words += ws
    print(f"[{s:7.2f}-{e:7.2f}] " + " ".join(w["w"] for w in ws))
json.dump(words, open(a.out, "w"), ensure_ascii=False, indent=0)
print(f"{len(blocks)} блоков, {len(words)} слов → {a.out}")
