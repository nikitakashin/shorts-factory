"""retime_panels.py <workdir> <old_edl_out.json> — после перемонтажа (tighten.py и т.п.) пересчитывает
времена в panels.json и fx.json: числа и пороги «СЛОВО>N» переводятся старый выход → исходник → новый выход.
Если старое время попало в вырезанную паузу — берётся начало следующего плана. Старые файлы → *.bak.json."""
import json, re, shutil, sys
from pathlib import Path

WD = Path(sys.argv[1]); O = json.load(open(sys.argv[2])); N = json.load(open(WD / "edl_out.json"))
fps = N["fps"]; SP = N.get("speed", 1.15)
def to_src(t):
    for s in O["segs"]:
        t0, t1 = s["f0"] / fps, (s["f0"] + s["n"]) / fps
        if t0 <= t <= t1: return s["a"] + (t - t0) * s.get("sp_eff", SP)
    return None
def to_new(src):
    best = None
    for s in N["segs"]:
        if s["a"] - 0.001 <= src <= s["b"] + 0.001: return s["f0"] / fps + (src - s["a"]) / s.get("sp_eff", SP)
        if s["a"] > src and (best is None or s["a"] < best["a"]): best = s
    return best["f0"] / fps if best else N["frames"] / fps
def m(t):
    src = to_src(t)
    return round(to_new(src), 2) if src is not None else t
def conv(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool): return m(v)
    if isinstance(v, str):
        mm = re.match(r"^(end:)?([^>]+)>([\d.]+)(.*)$", v)
        if mm: return f"{mm.group(1) or ''}{mm.group(2)}>{m(float(mm.group(3)))}{mm.group(4)}"
    return v
KEYS = {"at", "until", "select_at", "hl_at", "on_at", "strike_at", "after"}
def walk(o):
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if k in KEYS: o[k] = conv(v)
            else: walk(v)
    elif isinstance(o, list):
        for v in o: walk(v)
for name in ("panels.json", "fx.json"):
    f = WD / name
    if not f.exists(): continue
    shutil.copy(f, WD / name.replace(".json", ".bak.json"))
    d = json.load(open(f)); walk(d)
    json.dump(d, open(f, "w"), ensure_ascii=False, indent=1); print(f"{name}: времена пересчитаны")
