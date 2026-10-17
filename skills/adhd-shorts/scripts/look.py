#!/usr/bin/env python3
"""look.py — история творческих решений по шортсам, чтобы ролики не были одинаковыми.

  look.py history [N]   последние N записей (по умолчанию 6) и сводка: какие переходы, цвета, хуки, раскладки
                        брались чаще — и что давно не брали (подсказка для брифа нового ролика)
  look.py log <WD>      дописать запись о готовом ролике: формат и эксперимент из fx.json "look", доли раскладок
                        из layout.json, переходы из transitions.json (пишет render.py), цвет, хук, темп (склейки/мин)

Файл истории: ~/Movies/Shorts/_looks.jsonl (одна строка JSON на ролик).
Автор, 2026-10-17: «больше самостоятельности… меньше захардкоженных решений… решения в моменте, дабы разнообразить контент»."""
import json, re, sys, collections
from datetime import date
from pathlib import Path

HIST = Path.home() / "Movies/Shorts/_looks.jsonl"
OPTIONS = {   # что можно варьировать (подробно — references/style.md, «Палитры»)
    "transitions": ["morph", "whip", "zoom", "glitch", "iris", "flash", "blur", "slide", "leak", "flicker", "defocus", "slit", "invert", "pulse"],
    "themes": ["dark", "light", "noir", "black", "poster", "blueprint", "neon", "violet", "aurora", "charcoal", "studio", "grid", "void"],
    "accent": ["#50C8FF", "#B8FF3C", "#FF8A3D", "#C77DFF", "#FFD23F", "#FF4D6D"],
    "hook": ["mix", "plate", "behind"],
    "stickers": ["plate", "glow"],
    "layout": ["face", "split", "full", "pip"],
    "grade": ["natural", "cine", "warm", "tech"],
}

def load():
    if not HIST.exists(): return []
    return [json.loads(x) for x in HIST.read_text().splitlines() if x.strip()]

def history(n=6):
    H = load()
    if not H: print("История пуста — первый ролик по новой схеме: выбирай свободно."); return
    for r in H[-n:]:
        lay = ", ".join(f"{k} {v:.0%}" for k, v in r.get("layout", {}).items())
        print(f"{r.get('date')}  {r.get('folder')}\n   формат: {r.get('format', '—')} | хук: {r.get('hook', '—')} | цвет: {r.get('accent', '—')} | "
              f"стикеры: {r.get('stickers', '—')} | склейки/мин: {r.get('cuts_min', '—')}\n   раскладка: {lay or '—'} | переходы: {', '.join(r.get('transitions', [])) or '—'}"
              + (f"\n   эксперимент: {r['experiment']}" if r.get("experiment") else ""))
    recent = H[-n:]
    print("\nЧастота за последние", len(recent), "роликов:")
    for key in ("transitions", "accent", "hook", "stickers", "grade"):
        c = collections.Counter(x for r in recent for x in (r.get(key) if isinstance(r.get(key), list) else [r.get(key)]) if x)
        unused = [o for o in OPTIONS[key] if c.get(o, 0) == 0]
        print(f"  {key}: " + (", ".join(f"{k}×{v}" for k, v in c.most_common()) or "—") + (f"   | давно не брали: {', '.join(unused)}" if unused else ""))
    last = H[-1]
    print(f"\nНе повторяй подряд с прошлым роликом: цвет {last.get('accent')}, хук {last.get('hook')}, "
          f"набор переходов {sorted(set(last.get('transitions', [])))}.")

def log(wd):
    wd = Path(wd); wd = wd if wd.name.startswith(".") else wd / ".work"
    fx = json.loads((wd / "fx.json").read_text()) if (wd / "fx.json").exists() else {}
    look = fx.get("look", {}); E = json.loads((wd / "edl_out.json").read_text()); dur = E["frames"] / E["fps"]
    lay = json.loads((wd / "layout.json").read_text()) if (wd / "layout.json").exists() and (wd / "gfx.mp4").exists() else {}
    share = collections.Counter()
    for m in lay.get("modes", []): share[m["mode"]] += m["e"] - m["s"]
    share["face"] = max(0.0, dur - sum(share.values()))
    trs = [x["kind"] for x in json.loads((wd / "transitions.json").read_text())] if (wd / "transitions.json").exists() else []
    segs = E["segs"]
    real = sum(1 for i in range(1, len(segs)) if not (abs(segs[i - 1]["b"] - segs[i]["a"]) < 0.02 and segs[i - 1].get("src") == segs[i].get("src")))
    rec = dict(date=str(date.today()), folder=wd.parent.name, format=look.get("format"), experiment=look.get("experiment"),
               accent=look.get("accent") or fx.get("caption", {}).get("glow", "#50C8FF"),
               hook=("behind" if (fx.get("hook") or {}).get("behind") else (fx.get("hook") or {}).get("style", "mix")),
               stickers=look.get("stickers", "plate"), transitions=trs,
               grade=(json.loads((wd / "grade.json").read_text()).get("look") if (wd / "grade.json").exists() else None),
               layout={k: round(v / dur, 3) for k, v in share.items() if v > 0}, cuts_min=round(real / dur * 60, 1), dur=round(dur, 1))
    with HIST.open("a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("записал:", json.dumps(rec, ensure_ascii=False))

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "history": history(int(a[1]) if len(a) > 1 else 6)
    elif a[0] == "log": log(a[1])
    else: print(__doc__)
