# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""merge_wd.py <WD_out> <WD1> <WD2> ... — один шортс из кусков разных съёмок.

Каждый WDi — уже нарезанный кусок (обычно subcut.py из своего полного ролика, после cut_out/slowmo), со своим
edl_out.json, voice.wav, voice_raw.wav (если есть) и words_out.json. Склейка встык по порядку:
  edl_out.json / edl.json — планы подряд, у каждого "src" — его исходник (render.py берёт его вместо общего);
  voice.wav, voice_raw.wav — подряд, каждый кусок подогнан ровно под длину своих планов;
  words_out.json — слова со сдвигом; breaks.json — стыки кусков (сек) для fx.json "caption_breaks".
fps у кусков должен совпадать. Заставку (--endcard в subcut) делай только у последнего куска.
После: fx.json (+ panels.json) → render.py → music_bed.py → master.sh, как обычно.
Сделано 2026-10-15 для шортса «части 4+6»: глава полного видео + старый шортс с другой съёмки."""
import json, sys
from pathlib import Path
import numpy as np, soundfile as sf

OUT = Path(sys.argv[1]).expanduser(); WDS = [Path(p).expanduser() for p in sys.argv[2:]]
OUT.mkdir(parents=True, exist_ok=True)
ES = [json.load(open(w / "edl_out.json")) for w in WDS]
FPS = ES[0]["fps"]
if any(E["fps"] != FPS for E in ES): raise SystemExit(f"fps кусков разный: {[E['fps'] for E in ES]}")

segs, words, breaks, f0 = [], [], [], 0
for w, E in zip(WDS, ES):
    src = str(Path(E["src"]).resolve())
    if f0: breaks.append(round(f0 / FPS, 3))
    for s in E["segs"]:
        segs.append(dict(s, src=s.get("src", src), f0=s["f0"] + f0))
    W = json.load(open(w / "words_out.json")); W = W["words"] if isinstance(W, dict) else W
    words += [dict(x, s=round(x["s"] + f0 / FPS, 3), e=round(x["e"] + f0 / FPS, 3)) for x in W]
    f0 += E["frames"]

def cat(name):
    parts, sr0, ch = [], None, None
    for w, E in zip(WDS, ES):
        p = w / name
        if not p.exists(): p = w / "voice.wav"                    # нет сырого — кусок из финального (лишь бы длина)
        x, sr = sf.read(p, always_2d=True)
        sr0 = sr0 or sr; ch = ch or x.shape[1]
        if sr != sr0: raise SystemExit(f"{p}: частота {sr} ≠ {sr0}")
        if x.shape[1] != ch: x = np.repeat(x[:, :1], ch, 1)
        n = round(E["frames"] / FPS * sr)
        x = x[:n] if len(x) >= n else np.concatenate([x, np.zeros((n - len(x), ch))])
        parts.append(x)
    sf.write(OUT / name, np.concatenate(parts), sr0, subtype="PCM_24")

cat("voice.wav"); cat("voice_raw.wav")
base = {k: v for k, v in ES[0].items() if k not in ("segs", "frames")} | {"src": str(Path(ES[0]["src"]).resolve())}
json.dump(base | {"segs": segs, "frames": f0}, open(OUT / "edl_out.json", "w"), indent=1, ensure_ascii=False)
json.dump(base | {"segs": [{k: v for k, v in s.items() if k not in ("n", "f0", "sp_eff")} for s in segs]},
          open(OUT / "edl.json", "w"), indent=1, ensure_ascii=False)
json.dump(words, open(OUT / "words_out.json", "w"), ensure_ascii=False, indent=0)
json.dump(breaks, open(OUT / "breaks.json", "w"))
print(f"{len(WDS)} куска, {len(segs)} планов = {f0 / FPS:.2f} с, слов {len(words)}; стыки {breaks} → {OUT}")
