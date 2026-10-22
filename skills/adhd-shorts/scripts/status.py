#!/usr/bin/env python3
"""status.py — статус папки ролика: в работе → готов к выгрузке → выгружен (тогда папка уезжает в <канал>/Archive/).

  status.py set <папка> work|ready|uploaded [--note текст] [--no-move]
  status.py list [--all] [--channel ai-native]   папки со статусами по каналам (--all — и Archive/)
  status.py where <имя папки>     где сейчас папка (в каком канале, в работе или в Archive/)

Раскладка (2026-10-22): ~/Movies/Shorts/<канал>/<дата-тема>/ и ~/Movies/Shorts/<канал>/Archive/<дата-тема>/; служебное
(_cards, _gfx, _presets, _looks.jsonl) — в корне, общее для всех каналов.

Автор, 2026-10-22: «в папках с результатами работы надо писать статус… те что выгружены перемещать в Archive».
Статус — файл status.txt в папке (первая строка — текущий, ниже история с датами) и цветная метка Finder
(жёлтая — в работе, зелёная — готов к выгрузке, синяя — выгружен), чтобы видеть его прямо в списке папок.
Имя папки не трогаем: по нему называется видео (<папка>.mp4), а по черновому названию ролик ищет youtube-channel.
Корень — $SHORTS_ROOT или ~/Movies/Shorts; служебные папки (начинаются с «_») и Archive/ статуса не имеют."""
import argparse, datetime as dt, os, plistlib, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(os.environ.get("SHORTS_ROOT", Path.home() / "Movies/Shorts")).expanduser()
PROJECT = re.compile(r"^(\d{2}(\+\d{2})?_)?\d{4}-\d{2}-\d{2}-")      # 2026-10-21-тема или 01_2026-10-15-тема (серия из полного видео)


def channels():
    """Папки каналов в корне: всё, что не служебное (_…) и не сам ролик."""
    return [p for p in sorted(ROOT.iterdir()) if p.is_dir() and not p.name.startswith(("_", ".")) and not PROJECT.match(p.name) and p.name != "Archive"]
STATES = {"work": ("в работе", "Yellow", 5), "ready": ("готов к выгрузке", "Green", 2), "uploaded": ("выгружен", "Blue", 4)}
LABEL2KEY = {v[0]: k for k, v in STATES.items()}


def read(d):
    f = Path(d) / "status.txt"
    if not f.is_file(): return None, []
    lines = f.read_text(encoding="utf-8").splitlines()
    cur = lines[0].removeprefix("статус:").strip() if lines else None
    return cur, [l for l in lines[1:] if l.strip()]


def finder_tag(d, name, color):
    """Метка Finder через xattr: Finder показывает цвет точкой у папки (и в Spotlight: tag:<имя>)."""
    data = plistlib.dumps([f"{name}\n{color}"], fmt=plistlib.FMT_BINARY)
    subprocess.run(["xattr", "-wx", "com.apple.metadata:_kMDItemUserTags", data.hex(), str(d)], check=False, capture_output=True)


def set_status(d, key, note="", move=True):
    d = Path(d).expanduser().resolve()
    if not d.is_dir(): sys.exit(f"нет папки {d}")
    label, tag, color = STATES[key]
    _, hist = read(d)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    hist = [f"{stamp}  {label}" + (f" — {note}" if note else "")] + hist
    (d / "status.txt").write_text(f"статус: {label}\n" + "\n".join(hist) + "\n", encoding="utf-8")
    finder_tag(d, label.capitalize(), color)
    if key == "uploaded" and move and d.parent.name != "Archive":
        arch = d.parent / "Archive"; arch.mkdir(parents=True, exist_ok=True); dst = arch / d.name
        if dst.exists(): sys.exit(f"{dst} уже есть — переносить некуда, разберись вручную")
        shutil.move(str(d), str(dst)); d = dst
    print(f"{d.name}: {label}" + (f"  → {d}" if key == "uploaded" and move else ""))
    return d


def folders(include_archive=False, channel=None):
    out = [p for p in sorted(ROOT.iterdir()) if p.is_dir() and PROJECT.match(p.name)]   # ещё не разложенные по каналам
    for ch in channels():
        if channel and ch.name != channel: continue
        out += [p for p in sorted(ch.iterdir()) if p.is_dir() and PROJECT.match(p.name)]
        if include_archive and (ch / "Archive").is_dir(): out += sorted(p for p in (ch / "Archive").iterdir() if p.is_dir())
    return out


def find(name):
    for p in [ROOT / name] + [c / name for c in channels()] + [c / "Archive" / name for c in channels()]:
        if p.is_dir(): return p
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["set", "list", "where"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-move", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--channel")
    A = ap.parse_args()
    if A.cmd == "set":
        if len(A.args) != 2 or A.args[1] not in STATES: sys.exit("status.py set <папка> work|ready|uploaded")
        set_status(A.args[0], A.args[1], A.note, not A.no_move)
    elif A.cmd == "where":
        p = find(A.args[0])
        if not p: sys.exit(f"папки {A.args[0]} нет ни в одном канале {ROOT}/<канал>/ (и их Archive/)")
        print(p)
    else:
        for p in folders(A.all, A.channel):
            cur, hist = read(p)
            when = hist[0][:16] if hist else ""
            rel = p.relative_to(ROOT)
            print(f"{(cur or '— нет статуса'):18} {when:16}  {rel}")


if __name__ == "__main__":
    main()
