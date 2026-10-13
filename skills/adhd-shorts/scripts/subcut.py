# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""subcut.py <full_WD> <short_WD> <i,j,k-l,...> [--endcard 2.5] — шортс из полного ролика без повторной обработки.

Берёт планы полного монтажа по номерам (из full_WD/edl_out.json, края уже выровнены — snap выключается),
с тем же темпом, поэтому длина каждого плана в кадрах совпадает с полным роликом. Отсюда:
  voice.wav     — нарезка ФИНАЛЬНОГО голоса полного ролика (Adobe + цепочка уже применены) + тишина заставки;
  voice_raw.wav — то же из сырого голоса (если есть);
  words_out.json — слова полного ролика, перенесённые на новое время (расшифровка не нужна);
  edl.json / edl_out.json — для render.py; source.* — жёсткая ссылка на исходник полного ролика.
--endcard N — добавить в конец план-заставку N секунд ("endcard": true; картинку и текст задаёт fx.json "endcard").
После: fx.json (+ panels.json для вертикали) → render.py → master.sh, как обычно."""
import json, os, sys
from pathlib import Path
import numpy as np, soundfile as sf

FULL, SHORT = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
idx = []
for part in sys.argv[3].split(","):
    a, _, b = part.partition("-"); idx += list(range(int(a), int(b) + 1)) if b else [int(a)]
END = float(sys.argv[sys.argv.index("--endcard") + 1]) if "--endcard" in sys.argv else 0
SHORT.mkdir(parents=True, exist_ok=True)
E = json.load(open(FULL / "edl_out.json")); FPS = E["fps"]
src = Path(E["src"]); loc = SHORT / ("source" + src.suffix)
if not loc.exists():
    try: os.link(src, loc)
    except OSError: loc.symlink_to(src)

segs, maps, f0 = [], [], 0
for i in idx:
    s = dict(E["segs"][i]); n = s["n"]
    maps.append((s["f0"], n, f0))
    s = {k: v for k, v in s.items() if k not in ("a0", "b0", "n", "f0", "sp_eff")} | {"snap": False}
    if "sp" not in s and s.get("sp_eff", E.get("speed")) != E.get("speed"): s["sp"] = E["segs"][i]["sp_eff"]
    s.update(n=n, f0=f0, sp_eff=E["segs"][i]["sp_eff"]); segs.append(s); f0 += n
if END:
    n = round(END * FPS); segs.append(dict(a=0.0, b=END, sp=1.0, sp_eff=1.0, broll=True, endcard=True, snap=False, n=n, f0=f0)); f0 += n
out = {k: v for k, v in E.items() if k not in ("segs", "frames")} | {"src": str(loc), "segs": segs, "frames": f0}
json.dump(out, open(SHORT / "edl_out.json", "w"), indent=1, ensure_ascii=False)
json.dump({k: v for k, v in out.items() if k != "frames"} | {"segs": [{k: v for k, v in s.items() if k not in ("n", "f0", "sp_eff")} for s in segs]},
          open(SHORT / "edl.json", "w"), indent=1, ensure_ascii=False)

def cut(name, dst):
    p = FULL / name
    if not p.exists(): return False
    x, sr = sf.read(p, always_2d=True); parts = []
    for ff0, n, _ in maps:
        a = round(ff0 / FPS * sr); b = round((ff0 + n) / FPS * sr)
        seg = x[a:b].copy(); fd = min(len(seg) // 4, int(0.006 * sr))
        if fd: seg[:fd] *= np.linspace(0, 1, fd)[:, None]; seg[-fd:] *= np.linspace(1, 0, fd)[:, None]
        parts.append(seg)
    if END: parts.append(np.zeros((round(round(END * FPS) / FPS * sr), x.shape[1])))
    sf.write(SHORT / dst, np.concatenate(parts), sr, subtype="PCM_24"); return True

got_final = cut("voice.wav", "voice.wav"); cut("voice_raw.wav", "voice_raw.wav")
W = json.load(open(FULL / "words_out.json")); words = []
for w in W:
    for ff0, n, nf0 in maps:
        t0, t1 = ff0 / FPS, (ff0 + n) / FPS
        mid = (w["s"] + w["e"]) / 2
        if t0 <= mid < t1:
            d = nf0 / FPS - t0
            words.append(dict(w=w["w"], s=round(max(w["s"], t0) + d, 3), e=round(min(w["e"], t1) + d, 3))); break
json.dump(words, open(SHORT / "words_out.json", "w"), ensure_ascii=False, indent=0)
print(f"{len(idx)} планов{' + заставка ' + str(END) + ' с' if END else ''} = {f0 / FPS:.2f} с, слов {len(words)}; "
      f"голос: {'финальный' if got_final else 'НЕТ voice.wav в полном ролике'} → {SHORT}")
print(" ".join(w["w"] for w in words))
