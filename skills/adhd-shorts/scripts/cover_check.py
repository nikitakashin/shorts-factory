# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""cover_check.py <обложка.jpg|png> [ещё…] [--out <лист.jpg>] — как обложку шортса обрежут в разных местах YouTube.

Автор, 2026-10-18: «делал превью 9:16 — обрезалось, сделал 2:3 — тоже обрезало». Официальной спецификации нет, источники
спорят: полка Shorts на главной — ~2:3 (замер карточки 249×373), лента — 4:5, по одному источнику местами ~3:2 (горизонтальная
полоса из центра). Поэтому обложка грузится 1080×1920, а лицо и текст держатся в зоне, которая выживает при ВСЕХ обрезках:
центральная полоса 1080×720 (≈ 600–1320 px по высоте). Лист: исходник с рамками обрезок + каждая обрезка отдельно
(центрированная, как делает YouTube). Смотри, не режет ли заголовок и лицо в 3:2."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

A = sys.argv[1:]; out = Path(A[A.index("--out") + 1]) if "--out" in A else None
files = [Path(a) for a in A if a != "--out" and (out is None or Path(a) != out)]
CROPS = [("9:16 видео", 9 / 16, (255, 255, 255)), ("2:3 полка Shorts", 2 / 3, (80, 200, 255)), ("4:5 лента", 4 / 5, (255, 200, 60)),
         ("1:1", 1.0, (180, 120, 255)), ("3:2 полоса", 3 / 2, (255, 70, 70))]
FD = Path.home() / ".cache/content-factory/fonts/Inter.ttf"
fnt = lambda s: ImageFont.truetype(str(FD), s) if FD.exists() else ImageFont.load_default()

def crop(im, r):
    W, H = im.size
    if W / H > r: w = int(H * r); return im.crop(((W - w) // 2, 0, (W - w) // 2 + w, H))
    h = int(W / r); return im.crop((0, (H - h) // 2, W, (H - h) // 2 + h))

rows = []
for f in files:
    im = Image.open(f).convert("RGB"); W, H = im.size
    th = 560; base = im.resize((int(W * th / H), th)); d = ImageDraw.Draw(base); k = th / H
    for name, r, col in CROPS[1:]:
        c = crop(im, r); cw, ch = c.size; x0, y0 = (W - cw) / 2 * k, (H - ch) / 2 * k
        d.rectangle([x0, y0, x0 + cw * k - 1, y0 + ch * k - 1], outline=col, width=3)
    tiles = [base]
    for name, r, col in CROPS[1:]:
        c = crop(im, r); t = c.resize((max(1, int(c.size[0] * 300 / c.size[1])), 300)) if r <= 1 else c.resize((450, int(450 / r)))
        canvas = Image.new("RGB", (t.size[0], 340), (20, 20, 24)); canvas.paste(t, (0, 0)); ImageDraw.Draw(canvas).text((6, 306), name, font=fnt(22), fill=col)
        tiles.append(canvas)
    w = sum(t.size[0] for t in tiles) + 12 * len(tiles); row = Image.new("RGB", (w, 600), (12, 12, 16)); x = 0
    for t in tiles: row.paste(t, (x, 10)); x += t.size[0] + 12
    ImageDraw.Draw(row).text((8, 574), f"{f.name}  {W}×{H}  — рамки: 2:3 голубая, 4:5 жёлтая, 1:1 фиолетовая, 3:2 красная", font=fnt(18), fill=(200, 200, 210))
    rows.append(row)
sheet = Image.new("RGB", (max(r.size[0] for r in rows), sum(r.size[1] for r in rows)), (12, 12, 16)); y = 0
for r in rows: sheet.paste(r, (0, y)); y += r.size[1]
out = out or files[0].with_name(files[0].stem + "_обрезки.jpg"); sheet.save(out, quality=88); print("→", out)
