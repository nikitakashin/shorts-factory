# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""cover_gen.py <папка ролика> [--prompt-file thumbnail-prompt.md] [--variant A|B|all] [--frame <кадр>]
                [--model openai/gpt-image-2.5-sunburst] [--quality high] [--env-file .env]

Обложка без ручной нейросети: кадр автора + промпт из thumbnail-prompt.md → OpenRouter Image API → cover_A.png, cover_B.png
в папке ролика, затем cover_check.py (лист обрезок 2:3 / 4:5 / 1:1 / 3:2).

- Кадр — первый путь `thumb-frames/…` из раздела «## Кадр» (или --frame). Промпты — разделы «## Промпт — вариант A/B»,
  к каждому дописывается «## Негатив». Формат берётся из первой строки файла: «16:9» → горизонталь, иначе 9:16.
- Модель по умолчанию — GPT Image 2.5 Sunburst: версия серии для точного редактирования, она держит лицо и правит
  кадр, а не рисует нового человека. Наши промпты и так написаны как «отредактируй этот кадр».
- Ключ: переменная OPENROUTER_API_KEY, --env-file или ближайший .env от текущей папки вверх до домашней. Не печатается.
- Каждый вызов — платный: скрипт печатает стоимость из ответа OpenRouter."""
import argparse, base64, io, json, os, re, subprocess, sys, urllib.error, urllib.request
from pathlib import Path
from PIL import Image

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("folder")
ap.add_argument("--prompt-file", default="thumbnail-prompt.md")
ap.add_argument("--variant", default="all", help="A, B или all")
ap.add_argument("--frame")
ap.add_argument("--model", default="openai/gpt-image-2.5-sunburst")
ap.add_argument("--quality", default="high", choices=["auto", "low", "medium", "high"])
ap.add_argument("--env-file")
A = ap.parse_args()
DIR = Path(A.folder).expanduser(); PF = DIR / A.prompt_file
if not PF.is_file(): sys.exit(f"нет {PF}: сначала напиши промпт обложки (references/package.md)")
MD = PF.read_text(encoding="utf-8")


def env_key():
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if k: return k
    cands = [Path(A.env_file).expanduser()] if A.env_file else []
    d = Path.cwd()
    while True:
        cands.append(d / ".env")
        if d == Path.home() or d == d.parent: break
        d = d.parent
    for p in cands:
        if not p.is_file(): continue
        for line in p.read_text(errors="ignore").splitlines():
            m = re.match(r"\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*)", line)
            v = m.group(1).split(" #")[0].strip().strip("\"'") if m else ""
            if v: return v
    sys.exit("нет ключа OpenRouter: строка OPENROUTER_API_KEY=… в .env или переменная окружения")


def section(title_re):
    """Текст раздела «## …» до следующего «## »."""
    m = re.search(rf"^## {title_re}[^\n]*\n(.*?)(?=^## |\Z)", MD, flags=re.M | re.S)
    return m.group(1).strip() if m else ""


frame = Path(A.frame).expanduser() if A.frame else None
if frame is None:
    m = re.search(r"`(thumb-frames/[^`]+)`", section("Кадр"))
    if not m: sys.exit("в разделе «## Кадр» нет пути `thumb-frames/…`: передай --frame")
    frame = DIR / m.group(1)
if not frame.is_file(): sys.exit(f"кадр не найден: {frame}")
first = MD.splitlines()[0] if MD else ""
ASPECT = "16:9" if "16:9" in first else "9:16"
NEG = section("Негатив")
variants = sorted(set(re.findall(r"^## Промпт — вариант ([A-ZА-Я])", MD, flags=re.M)))
want = variants if A.variant == "all" else [A.variant.upper()]
if not set(want) <= set(variants): sys.exit(f"в {PF.name} нет варианта {A.variant}; есть: {', '.join(variants) or '—'}")

# кадр — JPEG до 1536 px по длинной стороне: этого модели хватает, а запрос не раздувается
img = Image.open(frame).convert("RGB"); img.thumbnail((1536, 1536))
buf = io.BytesIO(); img.save(buf, "JPEG", quality=92)
ref = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
KEY = env_key()

total = 0.0; out_files = []
for v in want:
    prompt = section(f"Промпт — вариант {v}")
    if NEG: prompt += "\n\nAvoid: " + " ".join(NEG.split())
    body = dict(model=A.model, prompt=prompt, aspect_ratio=ASPECT, quality=A.quality, output_format="png", n=1,
                input_references=[{"type": "image_url", "image_url": {"url": ref}}])
    req = urllib.request.Request("https://openrouter.ai/api/v1/images", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    print(f"вариант {v}: {A.model}, {ASPECT}, кадр {frame.name} …", flush=True)
    try:
        with urllib.request.urlopen(req, timeout=300) as r: res = json.load(r)
    except urllib.error.HTTPError as e:
        try: msg = json.load(e).get("error", {}).get("message", "")
        except Exception: msg = e.reason
        sys.exit(f"OpenRouter HTTP {e.code}: {msg}")
    items = res.get("data") or []
    if not items: sys.exit(f"OpenRouter не вернул картинку: {json.dumps(res, ensure_ascii=False)[:300]}")
    out = DIR / f"cover_{v}.png"
    im = Image.open(io.BytesIO(base64.b64decode(items[0]["b64_json"]))).convert("RGB")
    raw_size = im.size
    # модель отдаёт 864×1536; YouTube ждёт 1080×1920 (16:9 — 1280×720), а файл обложки — до 2 МБ: PNG — мастер, JPEG — загружать
    target = (1080, 1920) if ASPECT == "9:16" else (1280, 720)
    if abs(im.width / im.height - target[0] / target[1]) < 0.01: im = im.resize(target, Image.LANCZOS)
    im.save(out); im.save(out.with_suffix(".jpg"), "JPEG", quality=90)
    cost = float((res.get("usage") or {}).get("cost") or 0); total += cost
    print(f"  → {out.name} (+ .jpg для загрузки)  модель {raw_size[0]}×{raw_size[1]} → {im.width}×{im.height}  ${cost:.3f}")
    out_files.append(out)

print(f"итого ${total:.3f}")
check = Path(__file__).with_name("cover_check.py")
if check.is_file() and ASPECT == "9:16":
    subprocess.run(["uv", "run", "--script", str(check), *map(str, out_files)])
