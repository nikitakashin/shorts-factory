#!/usr/bin/env python3
"""tools/sync_skills.py [--from <папка со скиллами>] [--check] — обновить skills/ из рабочих скиллов.

Рабочие скиллы живут у автора в проекте (по умолчанию ~/Desktop/life/.claude/skills) и пишутся под его машину:
личные пути к библиотекам звуков, папке канала, шаблону CapCut. Скрипт копирует adhd-shorts и ui-panels сюда
(rsync --delete, без node_modules, шрифтов, движка HyperFrames и медиа — см. .gitignore), заменяет личные пути на
общие (~/Samples, ~/youtube, --template <папка>) и в конце ищет оставшиеся: если найдёт — выходит с ошибкой.
--check — только поиск личных путей, без копирования."""
import argparse, re, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = ("adhd-shorts", "ui-panels")
EXCLUDE = ["node_modules/", "__pycache__/", ".DS_Store", "*.pyc", "renders/", "scratch/",
           "engine/assets/js/", "engine/assets/fonts/", "engine/assets/media/", "engine/assets/panels.js", "assets/fonts/"]
TEXT = {".md", ".py", ".js", ".json", ".sh", ".css", ".html", ".txt", ".mjs"}
SUBS = [   # (было, стало) — порядок важен: сначала длинные пути
    ("/Users/nikitakashin/", "~/"),
    ("$HOME/Desktop/life/Samples", "$HOME/Samples"),
    ("~/Desktop/life/Samples", "~/Samples"),
    ("Desktop/life/youtube/", "youtube/"),
    ("~/Desktop/life/.claude/skills/", "~/.claude/skills/"),
    ("~/Desktop/life/.adobe-upload/", "<рабочая папка Claude Code>/.adobe-upload/"),
    ("~/Desktop/life/motion design examples/", "<папка с референсами>/"),
    ("~/Desktop/Music/Presets/", "~/Music/Presets/"),
    ("~/youtube/Ресерч/", "<разборы референсов у автора, в репозиторий не входят>/"),
    # CapCut: у автора шаблон — его черновик «1012»; в репозитории — обязательный --template
    ('ap.add_argument("--template", default=str(ROOT / "1012"))',
     'ap.add_argument("--template", required=True, help="папка черновика-шаблона в ROOT, сделанного руками (см. README)")'),
    ("TPL = Path(A.template)\n",
     "TPL = Path(A.template).expanduser()\nif not TPL.is_absolute(): TPL = ROOT / TPL          # можно передать просто имя черновика-шаблона\n"),
    ("`~/Movies/CapCut/User Data/Projects/com.lveditor.draft/1012`",
     "`--template <папка черновика-шаблона>` в `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/`"),
]
LEFTOVER = [r"/Users/[A-Za-z]", r"Desktop/life", r"lveditor\.draft/1012", r"honor4x", r"@gmail"]

def leftovers():
    bad = []
    for sk in SKILLS:
        for f in (REPO / "skills" / sk).rglob("*"):
            if f.is_file() and f.suffix in TEXT:
                for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                    if any(re.search(p, line) for p in LEFTOVER): bad.append(f"{f.relative_to(REPO)}:{i}: {line.strip()[:120]}")
    return bad

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--from", dest="src", default=str(Path.home() / "Desktop/life/.claude/skills")); ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not a.check:
        for sk in SKILLS:
            src = Path(a.src).expanduser() / sk
            if not src.is_dir(): sys.exit(f"нет {src}")
            cmd = ["rsync", "-a", "--delete"] + sum((["--exclude", e] for e in EXCLUDE), []) + [f"{src}/", f"{REPO / 'skills' / sk}/"]
            subprocess.run(cmd, check=True)
            n = 0
            for f in (REPO / "skills" / sk).rglob("*"):
                if f.is_file() and f.suffix in TEXT:
                    t = f.read_text(errors="ignore"); t2 = t
                    for old, new in SUBS: t2 = t2.replace(old, new)
                    if t2 != t: f.write_text(t2); n += 1
            print(f"{sk}: скопирован, личные пути заменены в {n} файлах")
    bad = leftovers()
    if bad:
        print("Остались личные пути — добавь замену в SUBS:\n" + "\n".join(bad)); sys.exit(1)
    print("личных путей не осталось")

if __name__ == "__main__":
    main()
