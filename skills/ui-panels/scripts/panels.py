#!/usr/bin/env python3
"""panels.py <workdir> [--total S] — panels.json → panels.js (для движка) + layout.json (для render.py).

Якоря времени — как в fx.json adhd-shorts. Любой ключ `at`, `until` или `*_at` может быть:
  12.5            секунды выходного ролика
  "ТОКЕНОВ"       начало первого слова субтитров, содержащего подстроку (регистр не важен)
  "ТОКЕНОВ>20"    то же, но ищем после 20-й секунды
  "end:ТОКЕНОВ"   конец этого слова
  "seg:7"         начало плана 7 из edl_out.json
  "+0.3" в конце  сдвиг: "ТОКЕНОВ+0.3", "end:ГОДА-0.1", "seg:7+0.2"
Слова берутся из words_out.json с исправлениями fixes/replace из fx.json — так же, как строит субтитры
render.py, поэтому якоря пиши по captions.txt. Без words_out.json работают только числа (режим без лица).

layout.json: {"split": 930, "modes": [{"s","e","mode"}], "sounds": [{"t","sound","gain_db"?}]} —
по нему render.py кладёт графику сверху (split) или на весь кадр (full) и ставит звуки."""
import json, re, sys
from pathlib import Path

WD = Path(sys.argv[1])
SPEC = json.load(open(WD / "panels.json"))
FX = json.load(open(WD / "fx.json")) if (WD / "fx.json").exists() else {}
E = json.load(open(WD / "edl_out.json")) if (WD / "edl_out.json").exists() else None
TOTAL = float(sys.argv[sys.argv.index("--total") + 1]) if "--total" in sys.argv else \
    (E["frames"] / E["fps"] if E else float(SPEC.get("total", 0)))
if not TOTAL: raise SystemExit("panels.py: не знаю длину ролика — нужен edl_out.json, --total или \"total\" в panels.json")
SPLIT = int(SPEC.get("split", 930))

# ---------- слова → токены (как в adhd-shorts/render.py) ----------
def norm(w): return re.sub(r"[^\wёЁ.\-₽]", "", w.lower()).strip(".")
toks = []
if (WD / "words_out.json").exists():
    raw = json.load(open(WD / "words_out.json"))
    fixes = {norm(k): v for k, v in FX.get("fixes", {}).items()}
    seqs = [([norm(x) for x in r["seq"]], r["to"]) for r in FX.get("replace", [])]
    i = 0
    while i < len(raw):
        w = raw[i]; s, e = w["s"], w["e"]; txt = re.sub(r"[,?!…]|\.+$", "", w["w"])
        hit = next(((L, to) for L, to in seqs if [norm(x["w"]) for x in raw[i:i + len(L)]] == L), None)
        if hit:
            L, to = hit; txt = to; e = raw[i + len(L) - 1]["e"]; i += len(L) - 1
        else:
            while i + 1 < len(raw) and re.match(r"^[-.]\w", raw[i + 1]["w"]):
                i += 1; txt += re.sub(r"[,?!…]|\.+$", "", raw[i]["w"]); e = raw[i]["e"]
            k = norm(txt)
            if k in fixes: txt = fixes[k]
        if txt: toks.append(dict(t=txt.upper(), s=s, e=e))
        i += 1
seg_t = [s["f0"] / E["fps"] for s in E["segs"]] if E else []

ANCHOR = re.compile(r"^(end:)?(.+?)(?:>(\d+(?:\.\d+)?))?([+-]\d+(?:\.\d+)?)?$")
def resolve(v, where):
    if isinstance(v, (int, float)): return float(v)
    m = ANCHOR.match(str(v).strip())
    if not m: raise SystemExit(f"panels.json {where}: не понимаю якорь «{v}»")
    end, word, after, off = m.group(1), m.group(2), float(m.group(3) or 0), float(m.group(4) or 0)
    if word.startswith("seg:"): return seg_t[int(word[4:])] + off
    return _word(word, after, end, where) + off      # строка — всегда слово («26» — это сказанное «26»); секунды пиши числом
def _word(word, after, end, where):
    for t in toks:
        if t["s"] >= after - 1e-6 and word.upper() in t["t"]: return t["e"] if end else t["s"]
    raise SystemExit(f"panels.json {where}: слово «{word}» после {after}s не найдено (см. captions.txt)")

def walk(o, where):
    if isinstance(o, dict):
        for k in list(o):
            if k in ("at", "until") or k.endswith("_at"):
                if isinstance(o[k], list):        # word_at: [..], click_at: [..] — якорь на каждый элемент
                    o[k] = [None if v is None else round(resolve(v, f"{where}.{k}[{j}]"), 3) for j, v in enumerate(o[k])]
                elif o[k] is not None: o[k] = round(resolve(o[k], f"{where}.{k}"), 3)
            else: walk(o[k], f"{where}.{k}")
    elif isinstance(o, list):
        for i, x in enumerate(o): walk(x, f"{where}[{i}]")

def media(o):
    """пути "media/…" (папка $WD/media) → "assets/media/…" внутри движка"""
    if isinstance(o, dict): return {k: media(v) for k, v in o.items()}
    if isinstance(o, list): return [media(x) for x in o]
    if isinstance(o, str) and o.startswith("media/"): return "assets/" + o
    return o

panels = SPEC["panels"]
for i, p in enumerate(panels):
    walk(p, f"panels[{i}]")
for i, p in enumerate(panels):
    if p.get("until") is None:
        p["until"] = panels[i + 1]["at"] if i + 1 < len(panels) else min(TOTAL, p["at"] + 2.5)
    p["until"] = min(p["until"], TOTAL)
    if p["until"] <= p["at"]: raise SystemExit(f"panels[{i}]: until {p['until']} ≤ at {p['at']}")
    if i and p["at"] < panels[i - 1]["until"] - 1e-3:
        raise SystemExit(f"panels[{i}] (at {p['at']}) налезает на panels[{i-1}] (до {panels[i-1]['until']})")
    if p.get("mode", "split") not in ("split", "full", "pip"): raise SystemExit(f"panels[{i}]: mode — split, full или pip")
    if E:
        for k, s in enumerate(E["segs"]):
            a, b = s["f0"] / E["fps"], (s["f0"] + s["n"]) / E["fps"]
            if s.get("broll") and a < p["until"] - 0.02 and p["at"] < b - 0.02:
                print(f"! panels[{i}] {p['at']:.2f}–{p['until']:.2f} перекрывает b-roll плана {k} ({a:.2f}–{b:.2f})")

# ---------- подтяжка к долям музыки (beats.json от music_bed.py --sync, 2026-10-17) ----------
# Вход/выход панели (и с ним переход и вжух) встаёт на ближайшую долю, если она в −0.15…+0.06 с от слова-якоря:
# картинка чуть раньше слова — нормально (референсы «Editing is Storytelling»), заметно позже — нет. "snap_beats": false — выключить.
if (WD / "beats.json").exists() and SPEC.get("snap_beats", True):
    BTS = json.load(open(WD / "beats.json"))["beats"]; moved = []
    def snap(t, lo=-0.15, hi=0.06):
        c = [b for b in BTS if lo <= b - t <= hi]
        return min(c, key=lambda b: abs(b - t)) if c else t
    for i, p in enumerate(panels):
        a0, u0 = p["at"], p["until"]; p["at"] = round(snap(a0), 3)
        if p["until"] < TOTAL - 0.05: p["until"] = round(snap(u0, -0.12, 0.06), 3)
        if i and p["at"] < panels[i - 1]["until"]: p["at"] = panels[i - 1]["until"]
        if p["until"] <= p["at"] + 0.3: p["until"] = u0
        if abs(p["at"] - a0) > 1e-3 or abs(p["until"] - u0) > 1e-3: moved.append(f"{a0:.2f}→{p['at']:.2f} / {u0:.2f}→{p['until']:.2f}")
    if moved: print("к долям: " + "; ".join(moved))

# ---------- звуки ----------
DEF = SPEC.get("sounds", {})      # переопределение ролей по умолчанию: {"panel": "whoosh", "step": "pop", "alert": "error"}
R = dict(panel="whoosh", step="pop", alert="error") | DEF
sounds = []
def snd(t, role, gain=None):
    if role: sounds.append(dict(t=round(t, 3), sound=role, **({"gain_db": gain} if gain is not None else {})))
for p in panels:
    snd(p["at"], p.get("sound", R["panel"]), p.get("gain_db"))
    for b in p.get("blocks", []):
        bt = b.get("at", p["at"]); typ = b.get("type")
        if "sound" in b: snd(b.get("sound_at", bt), b["sound"], b.get("gain_db"))
        if typ == "counter":
            for s in b.get("steps", [])[1:]: snd(s["at"], s.get("sound", R["step"]))
        elif typ == "toggle": snd(b.get("on_at", bt + 0.6), b.get("toggle_sound", R["step"]))
        elif typ == "grid":
            for s in b.get("steps", []): snd(s["at"], s.get("sound", R["alert"] if s.get("state") == "fail" else R["step"]))
        elif typ == "pipeline":
            for s in b.get("steps", []): snd(s["at"], s.get("sound", R["step"]))
        elif typ == "terminal":
            lim = b.get("limit") or {}
            for s in lim.get("steps", []):
                if s.get("v", 0) >= lim.get("warn", 95): snd(s["at"], s.get("sound", R["alert"]))
            for L in b.get("lines", []):
                if "sound" in L: snd(L["at"], L["sound"])
        for s in b.get("steps", []) if typ not in ("counter", "grid", "pipeline") else []:
            if "sound" in s: snd(s["at"], s["sound"])
sounds.sort(key=lambda x: x["t"])

# in/out — переход при входе в панель и при выходе (render.py adhd-shorts, transitions.py); pip — карточка с лицом
modes = []
for p in panels:
    m = dict(s=p["at"], e=p["until"], mode=p.get("mode", "split"), **{k: p[k] for k in ("in", "out", "pip", "dir", "tr", "tr_sound") if k in p})
    fo = p.get("face_off_at")                 # pip: с этого момента лицо уходит, графика остаётся на весь кадр (концовка без камеры)
    if fo and m["mode"] == "pip" and m["s"] < fo < m["e"]:
        modes += [dict(m, e=fo), dict(s=fo, e=m["e"], mode="full", **{"in": p.get("face_off_in", "morph"), "tr_sound": p.get("face_off_sound", False)})]
    else: modes.append(m)
LAND = SPEC.get("canvas") == "landscape"   # горизонтальный ролик: холст 1312×1080 (левые 2/3 кадра 1920×1080)
GW, GH = (1312, 1080) if LAND else (1080, 1920)
out = dict(total=round(TOTAL, 4), split=SPLIT, panels=media(panels), canvas="landscape" if LAND else "portrait")
(WD / "panels.js").write_text("window.PANELS = " + json.dumps(out, ensure_ascii=False, indent=1) + ";\n")
json.dump(dict(split=SPLIT, total=round(TOTAL, 4), face_pos=SPEC.get("face_pos", 0.5), modes=modes, sounds=sounds, caption_y=SPEC.get("caption_y", {}),
               transitions=SPEC.get("transitions"),
               canvas="landscape" if LAND else "portrait", gfx_w=GW, gfx_h=GH),
          open(WD / "layout.json", "w"), ensure_ascii=False, indent=1)
for p in panels:
    kinds = ", ".join(b.get("type", "?") for b in p.get("blocks", []))
    print(f"{p['at']:6.2f}–{p['until']:6.2f}  {p.get('mode','split'):5s} {p.get('theme','dark'):5s}  {kinds}")
print(f"{len(panels)} панелей, {len(sounds)} звуков → panels.js, layout.json (длина {TOTAL:.2f} с)")
