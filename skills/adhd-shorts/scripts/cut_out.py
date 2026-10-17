# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""cut_out.py <workdir> <t0> <t1> — вырезать кусок готового монтажа (сек ВЫХОДА) без повторной обработки голоса.

Для правок «на 29-й секунде остался неудачный дубль»: кусок должен лежать внутри одного плана edl_out.json
(у начала плана — подрезается начало, у конца — конец, в середине — план делится на два). Границы округляются до кадров.
Правит: edl_out.json, voice.wav / voice_raw.wav, words_out.json (слова внутри куска удаляются, после — сдвигаются),
числовые времена в fx.json ("screen": t; "at" числом) и копии *_before_slowmo.* (если кусок раньше замедления).
После: render_gfx.sh (если есть panels.json), music_bed.py (длина изменилась), render.py, master.sh."""
import json, sys
from pathlib import Path
import numpy as np, soundfile as sf

WD = Path(sys.argv[1]); t0, t1 = float(sys.argv[2]), float(sys.argv[3])

def cut(edl_p, words_p, voices, fx_p=None):
    E = json.load(open(edl_p)); fps = E["fps"]
    j0, j1 = round(t0 * fps), round(t1 * fps); d = j1 - j0
    k = next(i for i, s in enumerate(E["segs"]) if s["f0"] <= j0 < s["f0"] + s["n"])
    s = E["segs"][k]
    if j1 > s["f0"] + s["n"]: raise SystemExit(f"кусок {t0}–{t1} выходит за план {k} ({s['f0'] / fps:.2f}–{(s['f0'] + s['n']) / fps:.2f})")
    sp = s.get("sp_eff", E.get("speed", 1.15)); a_cut = s["a"] + (j0 - s["f0"]) / fps * sp; b_cut = s["a"] + (j1 - s["f0"]) / fps * sp
    parts = []
    if j0 > s["f0"]: parts.append(dict(s, b=round(a_cut, 4), n=j0 - s["f0"]))
    if j1 < s["f0"] + s["n"]: parts.append(dict(s, a=round(b_cut, 4), n=s["f0"] + s["n"] - j1))
    for p in parts: p.pop("z2", None) if len(parts) > 1 else None
    E["segs"] = E["segs"][:k] + parts + E["segs"][k + 1:]
    f = 0
    for x in E["segs"]: x["f0"] = f; f += x["n"]
    E["frames"] = f; json.dump(E, open(edl_p, "w"), ensure_ascii=False, indent=1)
    T0, T1, D = j0 / fps, j1 / fps, d / fps
    for vp in voices:
        if not vp.exists(): continue
        v, sr = sf.read(vp, always_2d=True); x0, x1 = round(T0 * sr), round(T1 * sr); fd = int(0.008 * sr)
        a, b = v[:x0].copy(), v[x1:].copy(); a[-fd:] *= np.linspace(1, 0, fd)[:, None]; b[:fd] *= np.linspace(0, 1, fd)[:, None]
        sf.write(vp, np.concatenate([a, b]), sr, subtype="PCM_24")
    W = json.load(open(words_p)); out = []
    for w in W:
        c = (w["s"] + w["e"]) / 2
        if T0 <= c < T1: continue
        if w["s"] >= T1 - 1e-6: w = dict(w, s=round(w["s"] - D, 3), e=round(w["e"] - D, 3))
        out.append(w)
    json.dump(out, open(words_p, "w"), ensure_ascii=False, indent=1)
    if fx_p and fx_p.exists():
        fx = json.load(open(fx_p))
        for c in fx.get("screen", []):
            if "t" in c and c["t"] >= T1: c["t"] = round(c["t"] - D, 3)
        for key in ("stickers", "sounds", "punch", "shake", "flash", "boom"):
            for e in fx.get(key, []):
                if isinstance(e.get("at"), (int, float)) and e["at"] >= T1: e["at"] = round(e["at"] - D, 3)
        json.dump(fx, open(fx_p, "w"), ensure_ascii=False, indent=1)
    return k, T0, T1, D, len(W) - len(out)

k, T0, T1, D, nw = cut(WD / "edl_out.json", WD / "words_out.json", [WD / "voice.wav", WD / "voice_raw.wav"], WD / "fx.json")
print(f"вырезано {T0:.2f}–{T1:.2f} с (план {k}, {D:.2f} с), слов убрано: {nw}")
if (WD / "edl_out_before_slowmo.json").exists():
    Eb = json.load(open(WD / "edl_out_before_slowmo.json")); E = json.load(open(WD / "edl_out.json"))
    sm = [s for s in E["segs"] if s.get("slowmo")]
    if sm and sm[0]["f0"] / E["fps"] > T0:     # замедление позже — та же правка в копиях до замедления
        cut(WD / "edl_out_before_slowmo.json", WD / "words_out_before_slowmo.json", [WD / "voice_before_slowmo.wav", WD / "voice_raw_before_slowmo.wav"])
        print("копии до замедления поправлены тоже")
