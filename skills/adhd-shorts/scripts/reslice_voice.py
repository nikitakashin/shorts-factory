# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""reslice_voice.py <workdir> <old_edl_out.json> <old_voice.wav> <new_voice.wav>

После tighten.py (или любой правки, которая только вырезает куски внутри старых планов) переносит уже
обработанный голос (Adobe + цепочка) на новый монтаж без повторной загрузки в Adobe: каждый новый план
вырезается из старой готовой дорожки по времени (src → старый выход), длина — ровно n кадров нового плана,
края — микрофейды 8/15 мс. План должен лежать внутри одного старого плана (у tighten.py это "parent")."""
import json, sys
from pathlib import Path
import numpy as np, soundfile as sf

WD = Path(sys.argv[1]); OLD = json.load(open(sys.argv[2])); NEW = json.load(open(WD / "edl_out.json"))
v, sr = sf.read(sys.argv[3], always_2d=True); fps = NEW["fps"]
out = []
for s in NEW["segs"]:
    n = int(round(s["n"] / fps * sr))
    p = OLD["segs"][s["parent"]] if "parent" in s else next(o for o in OLD["segs"] if o["a"] - 0.01 <= s["a"] <= o["b"] + 0.01)
    t0 = p["f0"] / fps + (s["a"] - p["a"]) / p.get("sp_eff", OLD.get("speed", 1.15))
    k = int(round(t0 * sr)); seg = v[k:k + n].copy()
    if len(seg) < n: seg = np.vstack([seg, np.zeros((n - len(seg), v.shape[1]))])
    fi, fo = int(0.008 * sr), int(0.015 * sr)
    seg[:fi] *= np.linspace(0, 1, fi)[:, None]; seg[-fo:] *= np.linspace(1, 0, fo)[:, None]
    out.append(seg)
sf.write(sys.argv[4], np.vstack(out), sr, subtype="PCM_24")
print(f"{len(out)} планов, {sum(len(o) for o in out) / sr:.2f} с → {sys.argv[4]}")
