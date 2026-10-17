# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""tighten.py <workdir> [--gap 0.22] [--exclude a-b,a-b] — жёсткая нарезка «в упор» по словам.

Зачем: build_voice дотягивает края до настоящей тишины (чтобы не съедать окончания), но на краях и внутри
планов остаются вдохи, «э», паузы на дочитывание. В кадре это выглядит как взгляд мимо камеры
(2026-10-11, автор: «почти каждый фрагмент вырезан не в упор… пустот вообще не должно быть»).

Как: речь = слова из words.json (расшифровка ИСХОДНИКА), лежащие внутри планов edl_out.json. Края каждого
слова уточняются по громкости (окна 10 мс, пол = 10-й перцентиль):
  начало — первая «гласная» (> пол+25 дБ) минус ≤0.10 с назад, пока громче пол+12 (согласная); если гласных
    нет (тихое слово) — первое окно громче пол+12. Так вдох перед словом (+8…+22 дБ) отрезается;
  конец — последняя гласная плюс ≤0.30 с вперёд, пока громче пол+12 (тихие окончания «-то», «-ла»), +40 мс.
Слова с паузой между ними < --gap склеиваются в один план, паузы длиннее вырезаются.
Только по громкости резать нельзя: первая версия (порог +25 дБ) выкинула тихие слова («комп», «языков»).
--exclude — диапазоны исходника, которые выкинуть целиком (оговорки: «ско… скорость»).
Новые планы: "snap": false, зум родителя (каждый второй кусок ×1.08 — джамп-зум), "parent" — номер плана
в старом edl_out.json. Пишет edl.json (старый → edl_before_tighten.json).
Дальше: build_voice.py → reslice_voice.py (голос уже прошёл Adobe и цепочку) → transcribe → render."""
import argparse, json, shutil
from pathlib import Path
import numpy as np, soundfile as sf

ap = argparse.ArgumentParser(); ap.add_argument("wd"); ap.add_argument("--gap", type=float, default=0.22)
ap.add_argument("--exclude", default="")
a = ap.parse_args(); WD = Path(a.wd)
E = json.load(open(WD / "edl_out.json")); W = json.load(open(WD / "words.json"))
x, sr = sf.read(WD / "audio.wav")
if x.ndim > 1: x = x.mean(1)
hop = sr // 100; nfr = len(x) // hop
db = 20 * np.log10(np.sqrt((x[: nfr * hop].reshape(nfr, hop) ** 2).mean(1)) + 1e-9)
F = np.percentile(db, 10); CORE, EDGE = F + 25, F + 12
EXC = [tuple(map(float, r.split("-"))) for r in a.exclude.split(",") if r]
def excluded(t): return any(e0 <= t < e1 for e0, e1 in EXC)

def word_span(ws, we, lo, hi):
    k0, k1 = max(int(lo * 100), int((ws - 0.10) * 100)), min(int(hi * 100), int((we + 0.15) * 100))
    core = [k for k in range(k0, k1) if db[k] > CORE and not excluded(k / 100)]
    loud = [k for k in range(k0, k1) if db[k] > EDGE and not excluded(k / 100)]
    if not loud: return None
    if core:
        st = core[0]
        while st > max(int(lo * 100), core[0] - 10) and db[st - 1] > EDGE and not excluded((st - 1) / 100): st -= 1
        en = core[-1]
        while en < min(int(hi * 100) - 1, core[-1] + 30) and db[en + 1] > EDGE and not excluded((en + 1) / 100): en += 1
    else:
        st, en = loud[0], loud[-1]
    return max(lo, st / 100 - 0.02), min(hi, (en + 1) / 100 + 0.04)

shutil.copy(WD / "edl.json", WD / "edl_before_tighten.json")
new = []; cut = 0.0
for i, s in enumerate(E["segs"]):
    if s.get("broll") or s.get("endcard"):
        d = {k: v for k, v in s.items() if k not in ("n", "f0", "sp_eff")}; d["parent"] = i; new.append(d); continue
    spans = []
    for w in W:
        c = (w["s"] + w["e"]) / 2
        if not (s["a"] - 0.05 <= c <= s["b"] + 0.05) or excluded(c): continue
        sp = word_span(w["s"], w["e"], s["a"], s["b"])
        if sp: spans.append(list(sp))
    spans.sort(); merged = []
    for p in spans:
        if merged and p[0] - merged[-1][1] < a.gap: merged[-1][1] = max(merged[-1][1], p[1])
        else: merged.append(p)
    # пауза ВНУТРИ слова по Whisper: он растягивает слово на паузу («будет… [1.3 с] …довольно», 2026-10-14) —
    # тихие участки (< пол+20 дБ) длиннее 0.4 с внутри куска тоже вырезаем
    split = []
    for p0, p1 in merged:
        k0, k1, cur, run = int(p0 * 100), int(p1 * 100), p0, None
        for k in range(k0, k1):
            q = db[k] < F + 20
            if q and run is None: run = k
            if (not q or k == k1 - 1) and run is not None:
                if (k - run) >= 40 and run > k0 + 5 and k < k1 - 5:
                    split.append([cur, run / 100 + 0.06]); cur = k / 100 - 0.04
                run = None
        split.append([cur, p1])
    merged = [p for p in split if p[1] - p[0] >= 0.12]
    cut += (s["b"] - s["a"]) - sum(p1 - p0 for p0, p1 in merged)
    for j, (p0, p1) in enumerate(merged):
        z = s.get("z", 1.0) if j % 2 == 0 else round(s.get("z", 1.0) * 1.08, 3)
        d = {"a": round(p0, 3), "b": round(p1, 3), "z": z, "snap": False, "parent": i}
        if "z2" in s and len(merged) == 1: d["z2"] = s["z2"]
        for k in ("sp", "vol", "cx", "cy"):
            if k in s: d[k] = s[k]
        new.append(d)
E2 = {k: v for k, v in json.load(open(WD / "edl.json")).items() if k != "segs"}; E2["segs"] = new
json.dump(E2, open(WD / "edl.json", "w"), ensure_ascii=False, indent=1)
print(f"{len(E['segs'])} планов → {len(new)}; вырезано пауз/вдохов {cut:.1f} с исходника (~{cut / E.get('speed', 1.15):.1f} с ролика)")
