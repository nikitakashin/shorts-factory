# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""reslice_voice.py <workdir> <old_edl_out.json> <old_voice.wav> [<edl_out2.json> <voice2.wav> ...] <new_voice.wav>

После tighten.py (или любой правки, которая только вырезает куски внутри старых планов) переносит уже
обработанный голос (Adobe + цепочка) на новый монтаж без повторной загрузки в Adobe: каждый новый план
вырезается из старой готовой дорожки по времени (src → старый выход), длина — ровно n кадров нового плана,
края — микрофейды 8/15 мс. План должен лежать внутри одного старого плана.
Несколько пар «edl_out + голос»: правка вернула куски, которых не было в старом монтаже, — их отдельно прогоняют
через Adobe и цепочку (маленький «патч», 2026-10-14), и план берётся из той пары, где он целиком помещается."""
import json, sys
from pathlib import Path
import numpy as np, soundfile as sf

WD = Path(sys.argv[1]); NEW = json.load(open(WD / "edl_out.json")); fps = NEW["fps"]
PAIRS = []
for k in range(2, len(sys.argv) - 1, 2):
    v, sr = sf.read(sys.argv[k + 1], always_2d=True); PAIRS.append((json.load(open(sys.argv[k])), v, sr))
sr = PAIRS[0][2]; ch = PAIRS[0][1].shape[1]
out = []
for s in NEW["segs"]:
    n = int(round(s["n"] / fps * sr))
    # старый план ищем по исходнику: "parent" от tighten.py — номер в edl_out ДО нарезки, а старым сюда часто
    # передают уже нарезанный edl_out (2026-10-14, «Гайды умерли»: после 30 с голос брался не из тех кусков)
    hit = None
    for OLD, v, _ in PAIRS:
        p = next((o for o in OLD["segs"] if o["a"] - 0.01 <= s["a"] and s["b"] <= o["b"] + 0.01), None)
        if p: hit = (OLD, v, p); break
    if hit is None: sys.exit(f"план {s['a']:.2f}–{s['b']:.2f} не лежит ни в одном обработанном плане — прогони его через Adobe отдельно")
    OLD, v, p = hit
    t0 = p["f0"] / fps + (s["a"] - p["a"]) / p.get("sp_eff", OLD.get("speed", 1.15))
    k = int(round(t0 * sr)); seg = v[k:k + n, :ch].copy()
    if len(seg) < n: seg = np.vstack([seg, np.zeros((n - len(seg), ch))])
    fi, fo = int(0.008 * sr), int(0.015 * sr)
    seg[:fi] *= np.linspace(0, 1, fi)[:, None]; seg[-fo:] *= np.linspace(1, 0, fo)[:, None]
    out.append(seg)
sf.write(sys.argv[-1], np.vstack(out), sr, subtype="PCM_24")
print(f"{len(out)} планов, {sum(len(o) for o in out) / sr:.2f} с → {sys.argv[-1]}")
