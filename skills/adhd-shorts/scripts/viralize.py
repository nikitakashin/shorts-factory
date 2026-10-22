# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""viralize.py — «завиралить»: необязательный последний этап. Видеомодель дорисовывает в кадр с лицом что-нибудь
абсурдное на 1–3 секунды (очки, Фредди Крюгер за спиной, лицо плавится на слоумо), чтобы оживить видеоряд и удержать.

  viralize.py models                                         видеомодели OpenRouter: режим, длительности, цена 2-с вставки
  viralize.py plan   <WD> [--every 5] [--min 1.2] [--max 3]   отрезки «только лицо» → viral/plan.json + viral/plan_sheet.jpg
  viralize.py show   <WD>                                     список: таймкод, фраза, варианты на вставку
  viralize.py pick   <WD> 1=3 2=5 3=0                         выбор автора (0 — без вставки)
  viralize.py gen    <WD> [--model <id>] [--res 720p] [--ids 1,3] [--max-usd 3] [--yes]
                         [--video-base-url https://… --serve-dir <папка>]          генерация вставок → viral/<модель>/
  viralize.py render <WD> [--model <id>] [--fit speed|trim]     render.py с вставками + master.sh → <папка>/<папка>-viral-<модель>.mp4
  viralize.py compare <WD> [--base <финал.mp4>]               все варианты бок о бок → <папка>/viral-compare.mp4

Идея автора (2026-10-22): «разнообразить и оживить видеоряд… в константе концентрация вмешательств, например 5 — примерно
каждые 5 секунд что-то дорисовать… идей-заготовок нет, они подбираются из контекста или на рандоме».
Порядок: обычный монтаж готов → `render.py <WD> --plate` (чистый видеоряд без субтитров и стикеров + plate.json — где в кадре
только лицо) → plan → агент пишет каждой вставке 4 варианта ("ideas": [{note, prompt}]) по контексту реплики, заготовок нет →
автор выбирает в карточках вопросов (4 варианта + свой; автор, 2026-10-22) → pick →
gen → render → compare.

Режимы моделей:
- «кадр → видео» (frame_images): первый кадр отрезка из plate.mp4, у моделей с last_frame — и последний (вставка
  возвращается к исходному кадру, склейка незаметна). Губы в эти 1–3 с с речью не совпадают — бери моменты, где это не важно.
- «правка видео» (FLUX Video Edit, Runway Aleph): кусок plate.mp4 → та же сцена с правкой, губы и движения сохраняются. Видео
  OpenRouter берёт только по публичной HTTPS-ссылке: --serve-dir — папка, которую автор сам отдаёт наружу (например
  cloudflared tunnel), --video-base-url — её адрес. Сам скрипт туннели не поднимает.
Каждый вызов платный: gen без --yes только считает смету; фактическая цена берётся из ответа OpenRouter (usage.cost).
Ключ OPENROUTER_API_KEY — из окружения или ближайшего .env (как у cover_gen.py); не печатается."""
import argparse, base64, concurrent.futures as cf, json, math, os, re, secrets, shutil, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1"
S = Path(__file__).resolve().parent
CACHE = Path.home() / ".cache/viralize"
# принимают исходное видео (input_references video_url). Seedance 2.5 — «video editing» в описании и цена video_tokens_with_video_input,
# формат правки на странице модели не описан (2026-10-22) — проверяем тем же input_references, что у FLUX
EDIT = {"black-forest-labs/flux-video-edit", "runway/aleph-2", "bytedance/seedance-2.5"}
# По умолчанию — FLUX Video Edit (автор после двух тестов, 2026-10-22): губы и мимика остаются родными, ~3¢/с
DEFAULT_MODEL = "black-forest-labs/flux-video-edit"
# Обёртка промпта: модели «кадр → видео» охотно меняют человека, ракурс и добавляют надписи
WRAP = ("Vertical 9:16 selfie video of the same man. Keep his face, identity, clothes, the room, camera position, framing and "
        "lighting exactly as in the input. No text, no captions, no subtitles, no logos. ")
RETURN = " At the very end everything is back to exactly the original shot."
WRAP_EDIT = ("Edit the input video. Keep the same man, his face, lip movements, head motion, the room, camera and framing exactly as in "
             "the input video, no text or captions. Only this change: ")
SIZES = {"480p": (480, 854), "720p": (720, 1280), "768p": (768, 1366), "1080p": (1080, 1920)}


def sh(*a, **k): return subprocess.run([str(x) for x in a], check=True, **k)
def probe_dur(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True).stdout.strip() or 0)
def slug(m): return re.sub(r"[^a-z0-9.]+", "-", m.lower()).strip("-")


def key(env_file=None):
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if k: return k
    cands = [Path(env_file).expanduser()] if env_file else []
    d = Path.cwd()
    while True:
        cands.append(d / ".env")
        if d == Path.home() or d.parent == d: break
        d = d.parent
    for f in cands:
        if f.is_file():
            for line in f.read_text().splitlines():
                m = re.match(r"\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*)", line)
                if m: return m.group(1).strip().strip("'\"")
    sys.exit("нет ключа OpenRouter: строка OPENROUTER_API_KEY=… в .env или переменная окружения")


def http(url, body=None, k=None, raw=False, timeout=120):
    h = {"Authorization": f"Bearer {k}"} if k else {}
    if body is not None: h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h,
                               method="POST" if body is not None else "GET")
    for att in range(4):
        try:
            with urllib.request.urlopen(r, timeout=timeout) as x:
                b = x.read(); return b if raw else json.loads(b)
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and att < 3: time.sleep(3 * (att + 1)); continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError:
            if att < 3: time.sleep(3 * (att + 1)); continue
            raise


def models():
    f = CACHE / "models.json"
    if f.is_file() and time.time() - f.stat().st_mtime < 86400: return json.loads(f.read_text())
    d = http(f"{API}/videos/models"); d = d.get("data", d)
    CACHE.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d, ensure_ascii=False)); return d


def meta(mid):
    m = next((x for x in models() if x["id"] == mid), None)
    if not m: sys.exit(f"нет такой видеомодели: {mid} (список — viralize.py models)")
    return m


def pick_res(m, want):
    rs = m.get("supported_resolutions") or []
    if not rs or want in rs: return want if rs else None
    order = ["480p", "720p", "768p", "1080p", "2K", "4K"]
    up = [r for r in order if r in rs and order.index(r) >= order.index(want)] if want in order else []
    return (up or rs)[0]


def pick_dur(m, d):
    ds = sorted(m.get("supported_durations") or [])
    if not ds: return None
    return next((x for x in ds if x >= d - 0.05), ds[-1])


def estimate(m, res, dur, n_img=0, video_in=False):
    """Смета в $ по pricing_skus — ключи у провайдеров разные, это оценка; правда — usage.cost в ответе."""
    p = {k: float(v) for k, v in (m.get("pricing_skus") or {}).items()}
    usd = lambda k: p[k] / 100 if k.startswith("cents") or "cents" in k else p[k]
    per_sec = [k for k in p if "second" in k and "reference" not in k and "continuation" not in k and "megapixel" not in k
               and "with_audio" not in k and "text_to_video" not in k]
    best = ([k for k in per_sec if res and res.lower() in k.lower() and "image_to_video" in k] or
            [k for k in per_sec if res and res.lower() in k.lower()] or
            [k for k in per_sec if "without_audio" in k and not re.search(r"_\d+[pk]$", k)] or
            [k for k in per_sec if not re.search(r"\d+p|\dk", k.lower())] or per_sec)
    cost = None
    if best: cost = usd(best[0]) * (dur or 0)
    elif "video_tokens" in p or "video_tokens_without_audio" in p:      # Seedance: токены = w·h·fps·сек / 1024
        w, h = SIZES.get(res or "720p", (720, 1280))
        rate = p.get("video_tokens_with_video_input") if video_in and "video_tokens_with_video_input" in p else p.get("video_tokens_without_audio", p.get("video_tokens"))
        cost = w * h * 24 * (dur or 0) / 1024 * rate
    if cost is None: return None
    for k in p:
        if "image_input" in k or k == "reference_input_images": cost += usd(k) * n_img
    if "minimum_cents_per_generation" in p: cost = max(cost, p["minimum_cents_per_generation"] / 100)
    return cost


# ───────────────────────── models ─────────────────────────
def cmd_models(A):
    rows = []
    for m in models():
        mode = "правка видео" if m["id"] in EDIT else ("кадр→видео" if m.get("supported_frame_images") else "текст→видео")
        if "upscale" in m["id"] or "avatar" in m["id"]: continue
        res = pick_res(m, A.res); dur = pick_dur(m, 2.0) or 2
        c = estimate(m, res, dur, 1 + ("last_frame" in (m.get("supported_frame_images") or [])))
        rows.append((c if c is not None else 99, m["id"], mode, res, dur, ",".join(m.get("supported_frame_images") or []), c))
    print(f"{'модель':42s} {'режим':13s} {'разр.':6s} {'сек':>3s} {'кадры':22s} 2-с вставка")
    for _, i, mode, res, dur, fr, c in sorted(rows):
        print(f"{i:42s} {mode:13s} {str(res):6s} {dur:>3} {fr:22s} " + (f"~${c:.3f}" if c is not None else "?"))


# ───────────────────────── plan ─────────────────────────
def cmd_plan(A):
    wd = Path(A.wd).expanduser(); pj = wd / "plate.json"
    if not pj.is_file() or not (wd / "plate.mp4").is_file():
        sys.exit(f"нет plate.mp4/plate.json — сначала: uv run --script {S}/render.py {wd} --plate")
    P = json.load(open(pj)); E = json.load(open(wd / "edl_out.json")); fps = E["fps"]; tot = P["frames"] / fps
    words = json.load(open(wd / "words_out.json")) if (wd / "words_out.json").is_file() else []
    fx = json.load(open(wd / "fx.json")) if (wd / "fx.json").is_file() else {}
    # кадры с одним лицом, с отступом от смены раскладки (там переходы) и от начала ролика (первый кадр — узнаваемый)
    face = []
    for r in P["runs"]:
        if r["mode"] != "face": continue
        s_, e_ = r["s"] + (A.margin if r["s"] > 0.01 else A.skip_start), r["e"] - (A.margin if r["e"] < tot - 0.01 else A.skip_end)
        if e_ - s_ >= A.min: face.append((s_, e_))
    face_total = sum(e - s for s, e in face)
    # планы → «кадры» камеры: подряд идущие планы с непрерывным исходником (замедление режет план на куски по 0.1 с) — один кадр
    shots, t = [], 0.0
    for s in E["segs"]:
        d = s["n"] / fps; cont = shots and abs(shots[-1]["b"] - s["a"]) < 0.05 and shots[-1]["src"] == s.get("src")
        if cont: shots[-1].update(e=t + d, b=s["b"], slowmo=shots[-1]["slowmo"] or bool(s.get("slowmo")))
        else: shots.append(dict(s=t, e=t + d, b=s["b"], src=s.get("src"), slowmo=bool(s.get("slowmo"))))
        t += d
    accents = [w["s"] for w in words if re.search(r"[A-ZА-ЯЁ]{3,}|!", w.get("w", ""))]
    for k in ("punch", "shake", "flash"):
        for x in fx.get(k, []):
            m_ = next((w for w in words if isinstance(x.get("at"), str) and re.sub(r"\W", "", w["w"].lower()) == re.sub(r"\W", "", x["at"].lower())), None)
            if m_: accents.append(m_["s"])
    cands = []
    # --cross-cuts: отрезок может идти через склейки (для «правки видео» стык внутри куска не мешает; у Seedance минимум 4 с,
    # а в рваном монтаже кадров по 4 с без склейки почти нет — «Haiku», 2026-10-22)
    bounds = [x["s"] for x in shots] + [shots[-1]["e"]] if shots else []
    spans = ([dict(s=fs, e=fe, slowmo=any(x["slowmo"] and x["s"] < fe and x["e"] > fs for x in shots)) for fs, fe in face]
             if A.cross_cuts else shots)
    for sh_ in spans:
        for fs, fe in face:
            a, b = max(sh_["s"], fs), min(sh_["e"], fe)
            st = a
            while b - st >= A.min:
                L = min(A.max, b - st)
                if b - (st + L) < A.min * 0.6 and b - st <= A.max * 1.25: L = b - st      # не оставлять обрубок
                t0, t1 = st, st + L
                cs, ce = (any(abs(t0 - x) < 0.06 for x in bounds), any(abs(t1 - x) < 0.06 for x in bounds)) if A.cross_cuts else \
                         (abs(t0 - sh_["s"]) < 0.06, abs(t1 - sh_["e"]) < 0.06)
                score = 1.0 * sh_["slowmo"] + 0.6 * any(t0 <= x < t1 for x in accents) + 0.3 * cs + 0.3 * ce
                cands.append(dict(t0=round(t0, 3), t1=round(t1, 3), cut_start=cs, cut_end=ce, slowmo=sh_["slowmo"], score=score))
                st += 1.0 if A.cross_cuts else L      # через склейки — кандидаты с шагом 1 с, разнос даёт отбор
    n = max(1, round(face_total / A.every)) if A.count is None else A.count
    pick = []
    for c in sorted(cands, key=lambda c: -c["score"]):
        if len(pick) >= n: break
        if all(c["t1"] + A.every * 0.6 <= p["t0"] or c["t0"] >= p["t1"] + A.every * 0.6 for p in pick): pick.append(c)
    pick.sort(key=lambda c: c["t0"])
    text = lambda a, b: " ".join(w["w"] for w in words if a <= w["s"] < b)
    vd = wd / "viral"; (vd / "frames").mkdir(parents=True, exist_ok=True)
    old = {(round(x["t0"], 2), round(x["t1"], 2)): x for x in (json.load(open(vd / "plan.json"))["items"] if (vd / "plan.json").is_file() else [])}
    items = []
    for i, c in enumerate(pick, 1):
        c = dict(id=i, **c, dur=round(c["t1"] - c["t0"], 3), says=text(c["t0"], c["t1"]),
                 context=text(c["t0"] - 5, c["t1"] + 3), first=f"frames/{i:02d}_first.jpg", last=f"frames/{i:02d}_last.jpg",
                 ideas=[], pick=None)
        prev = old.get((round(c["t0"], 2), round(c["t1"], 2)))
        if prev: c.update(ideas=prev.get("ideas", []), pick=prev.get("pick"))      # написанные идеи и выбор не теряем
        for name, at in (("first", c["t0"] + 0.5 / fps), ("last", c["t1"] - 1.5 / fps)):
            sh("ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", wd / "plate.mp4", "-frames:v", "1", "-q:v", "2", vd / c[name])
        items.append(c)
    plan = dict(wd=str(wd), total=round(tot, 2), face_total=round(face_total, 2), every=A.every,
                transcript=" ".join(w["w"] for w in words), items=items)
    json.dump(plan, open(vd / "plan.json", "w"), ensure_ascii=False, indent=1)
    sheet(vd, items)
    print(f"ролик {tot:.1f} с, только лицо {face_total:.1f} с, кандидатов {len(cands)}, вставок {len(items)} (раз в ~{A.every} с)")
    for c in items:
        tags = ("слоумо " if c["slowmo"] else "") + ("[склейка" if c["cut_start"] else "[") + "…" + ("склейка]" if c["cut_end"] else "]")
        print(f"  {c['id']}. {c['t0']:5.2f}–{c['t1']:5.2f} ({c['dur']:.1f} с) {tags:22s} «{c['says']}»")
    print(f"→ {vd / 'plan.json'}  {vd / 'plan_sheet.jpg'}\nДальше: впиши каждой вставке \"ideas\" — 4 варианта {{\"note\": по-русски для автора, \"prompt\": англ.}}, потом show → выбор автора → pick")


def sheet(vd, items):
    from PIL import Image, ImageDraw, ImageFont
    tw, th = 270, 480; im = Image.new("RGB", (tw * 2 * len(items) + 12 * len(items), th + 70), (20, 20, 24)); d = ImageDraw.Draw(im)
    try: f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 20)
    except Exception: f = ImageFont.load_default()
    x = 0
    for c in items:
        for k in ("first", "last"):
            im.paste(Image.open(vd / c[k]).convert("RGB").resize((tw, th)), (x, 0)); x += tw
        d.text((x - 2 * tw + 6, th + 6), f"{c['id']}. {c['t0']:.1f}-{c['t1']:.1f}s" + (" slowmo" if c["slowmo"] else ""), fill="white", font=f)
        d.text((x - 2 * tw + 6, th + 36), c["says"][:42], fill=(180, 180, 190), font=f); x += 12
    im.save(vd / "plan_sheet.jpg", quality=85)


def chosen(c):
    """Выбранный автором вариант вставки или None (не выбран / 0 — без вставки)."""
    k = c.get("pick")
    return c["ideas"][k - 1] if k and 0 < k <= len(c.get("ideas", [])) else None


def cmd_show(A):
    plan = json.load(open(Path(A.wd).expanduser() / "viral/plan.json"))
    for c in plan["items"]:
        m, sec = divmod(c["t0"], 60)
        print(f"\n{c['id']}. {int(m)}:{sec:04.1f} ({c['dur']:.1f} с{', слоумо' if c['slowmo'] else ''}) — «{c['says'] or '…молчу…'}»")
        for i, x in enumerate(c.get("ideas", []), 1): print(f"   {i}) {x['note']}" + ("   ← выбрано" if c.get("pick") == i else ""))
        if not c.get("ideas"): print("   (вариантов ещё нет)")


def cmd_pick(A):
    f = Path(A.wd).expanduser() / "viral/plan.json"; plan = json.load(open(f)); items = {c["id"]: c for c in plan["items"]}
    for a in A.choices:
        i, k = (int(x) for x in a.split("="))
        if i not in items: sys.exit(f"нет вставки {i}")
        if k and not 0 < k <= len(items[i].get("ideas", [])): sys.exit(f"у вставки {i} нет варианта {k}")
        items[i]["pick"] = k or 0
    json.dump(plan, open(f, "w"), ensure_ascii=False, indent=1)
    for c in plan["items"]: print(f"{c['id']}. " + ((chosen(c) or {}).get("note") or ("без вставки" if c.get("pick") == 0 else "не выбрано")))


# ───────────────────────── gen ─────────────────────────
def data_url(p): return "data:image/jpeg;base64," + base64.b64encode(Path(p).read_bytes()).decode()


def cmd_gen(A):
    wd = Path(A.wd).expanduser(); vd = wd / "viral"; plan = json.load(open(vd / "plan.json"))
    m = meta(A.model); od = vd / slug(A.model); od.mkdir(parents=True, exist_ok=True)
    ids = {int(x) for x in A.ids.split(",")} if A.ids else None
    items = [c for c in plan["items"] if (ids is None or c["id"] in ids) and c.get("pick") != 0]
    if not all(chosen(c) for c in items): sys.exit("не у всех вставок выбран вариант — show → выбор автора → pick")
    edit = A.model in EDIT; frames = m.get("supported_frame_images") or []
    if edit and not (A.video_base_url and A.serve_dir):
        sys.exit("модель правит видео: нужен --serve-dir (папка, которую ты сам отдаёшь наружу, напр. cloudflared) и --video-base-url")
    if not edit and "first_frame" not in frames: sys.exit(f"{A.model} не берёт первый кадр — для вставки в ролик не годится")
    res = pick_res(m, A.res); jobs = []; total = 0.0
    for c in items:
        ret = not edit and not c["cut_end"] and "last_frame" in frames and not A.no_return
        dur = pick_dur(m, c["dur"])                                    # у FLUX Edit длительностей нет → None, длина = исходник
        idea = chosen(c)
        body = dict(model=A.model, prompt=(WRAP_EDIT + idea["prompt"] if edit else WRAP + idea["prompt"] + (RETURN if ret else "")))
        if edit and dur:                                               # Seedance: длительность и формат задаются и при правке
            body.update(duration=dur, aspect_ratio="9:16", generate_audio=False)
            if res: body["resolution"] = res
        if not edit:
            body.update(duration=dur, aspect_ratio="9:16")
            if res: body["resolution"] = res
            body["frame_images"] = [dict(type="image_url", image_url=dict(url=data_url(vd / c["first"])), frame_type="first_frame")]
            if ret: body["frame_images"].append(dict(type="image_url", image_url=dict(url=data_url(vd / c["last"])), frame_type="last_frame"))
            if m.get("generate_audio") is not None: body["generate_audio"] = False
        est = estimate(m, res, dur if dur else c["dur"], len(body.get("frame_images", [])), video_in=edit)
        total += est or 0
        jobs.append((c, body, ret, dur, est))
        print(f"  {c['id']}. {c['dur']:.1f} с → {('правка' + (f' {dur} с {res}' if dur else '') if edit else f'{dur} с {res}')}{' +последний кадр' if ret else ''}  ~${(est or 0):.3f}  {idea['note']}")
    print(f"{A.model}: {len(jobs)} вставок, смета ~${total:.2f} (лимит --max-usd {A.max_usd})")
    if total > A.max_usd: sys.exit("смета выше лимита — подними --max-usd или возьми модель дешевле")
    if not A.yes: print("это только смета; генерация — с --yes"); return
    K = key(A.env_file)

    def run(job):
        c, body, ret, dur, est = job; t0 = time.time()
        if edit:
            name = secrets.token_hex(12) + ".mp4"; clip = Path(A.serve_dir).expanduser() / name
            sh("ffmpeg", "-v", "error", "-y", "-ss", f"{c['t0']:.3f}", "-t", f"{c['dur']:.3f}", "-i", wd / "plate.mp4", "-an",
               "-vf", "scale=720:1280", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", clip)
            body["input_references"] = [dict(type="video_url", video_url=dict(url=A.video_base_url.rstrip("/") + "/" + name))]
        try:
            j = http(f"{API}/videos", body, K)
            pu = j.get("polling_url") or f"{API}/videos/{j['id']}"
            while j.get("status") not in ("completed", "failed", "cancelled", "expired"):
                time.sleep(5); j = http(pu, k=K)
                if time.time() - t0 > A.timeout: return dict(id=c["id"], ok=False, error="таймаут", sec=round(time.time() - t0))
            if j["status"] != "completed": return dict(id=c["id"], ok=False, error=str(j.get("error") or j["status"])[:300], sec=round(time.time() - t0))
            out = od / f"{c['id']:02d}.mp4"; out.write_bytes(http(j["unsigned_urls"][0], k=K, raw=True, timeout=300))
            return dict(id=c["id"], ok=True, file=str(out), cost=(j.get("usage") or {}).get("cost"), est=est, sec=round(time.time() - t0),
                        dur=probe_dur(out), gen_dur=dur, res=res, last_frame=ret, pick=c["pick"], prompt=body["prompt"], job=j.get("id"))
        except Exception as e:
            return dict(id=c["id"], ok=False, error=str(e)[:300], sec=round(time.time() - t0))
        finally:
            if edit: clip.unlink(missing_ok=True)

    with cf.ThreadPoolExecutor(4) as ex: rs = list(ex.map(run, jobs))
    rf = od / "results.json"; prev = {r["id"]: r for r in (json.load(open(rf))["results"] if rf.is_file() else [])}
    for r in rs:
        if r["ok"] or not prev.get(r["id"], {}).get("ok"): prev[r["id"]] = r      # новая ошибка заменяет старую, удачу не затирает
    spent = sum(r.get("cost") or 0 for r in rs if r["ok"])
    json.dump(dict(model=A.model, results=sorted(prev.values(), key=lambda r: r["id"])), open(rf, "w"), ensure_ascii=False, indent=1)
    for r in rs: print(f"  {r['id']}. " + (f"✓ {r['sec']} с, ${r['cost']}" if r["ok"] else f"✗ {r['error']}"))
    print(f"потрачено ${spent:.3f} → {od}")


# ───────────────────────── render / compare ─────────────────────────
def cmd_render(A):
    wd = Path(A.wd).expanduser(); vd = wd / "viral"; plan = json.load(open(vd / "plan.json")); sl = slug(A.model)
    rs = {r["id"]: r for r in json.load(open(vd / sl / "results.json"))["results"] if r["ok"]}
    clips = []
    for c in plan["items"]:
        r = rs.get(c["id"])
        if not r or r.get("pick") != c.get("pick"): continue          # вставка под другой, уже не выбранный вариант
        # «кадр → видео» с последним кадром — вся вставка сжимается в отрезок (заканчивается на исходном кадре); правка видео
        # той же длины; без последнего кадра — тоже сжатие: суть шутки может быть в конце сгенерированного куска
        clips.append(dict(t0=c["t0"], t1=c["t1"], file=r["file"], dur=r["dur"], fit=A.fit,
                          xfade=0.0 if c["cut_end"] or r.get("last_frame") else 0.12))
    if not clips: sys.exit("нет готовых вставок для этой модели")
    vj = vd / sl / "viral.json"; json.dump(dict(model=A.model, clips=clips), open(vj, "w"), indent=1)
    vid = wd / f"video_viral-{sl}.mp4"
    sh("uv", "run", "--script", S / "render.py", wd, "--viral", vj, "--out", vid.name, stdout=subprocess.DEVNULL)
    folder = wd.parent if wd.name == ".work" else wd
    out = folder / f"{folder.name}-viral-{sl}.mp4"
    sh("bash", S / "master.sh", wd, out, env=dict(os.environ, VIDEO=str(vid)), stdout=subprocess.DEVNULL)
    print(f"{len(clips)} вставок → {out}")


def cmd_compare(A):
    wd = Path(A.wd).expanduser(); folder = wd.parent if wd.name == ".work" else wd
    vs = sorted(folder.glob(f"{folder.name}-viral-*.mp4"))
    base = Path(A.base).expanduser() if A.base else next((p for p in (folder / f"{folder.name}.mp4", folder / "short.mp4") if p.is_file()), None)
    files = ([base] if base else []) + vs
    if len(files) < 2: sys.exit("сравнивать нечего: нужен исходник (--base) и хотя бы один вариант")
    from PIL import Image, ImageDraw, ImageFont
    try: f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 26)
    except Exception: f = ImageFont.load_default()
    tmp = wd / "viral" / "labels"; tmp.mkdir(parents=True, exist_ok=True); args, fl = [], []
    for i, p in enumerate(files):
        lab = "исходник" if p == base else p.stem.split("-viral-")[-1]
        im = Image.new("RGBA", (360, 44), (0, 0, 0, 160)); ImageDraw.Draw(im).text((10, 8), lab, fill="white", font=f)
        im.save(tmp / f"{i}.png"); args += ["-i", p, "-i", tmp / f"{i}.png"]
        fl.append(f"[{2 * i}:v]scale=360:640,setsar=1[v{i}];[v{i}][{2 * i + 1}:v]overlay=0:0[o{i}]")
    fl.append("".join(f"[o{i}]" for i in range(len(files))) + f"hstack=inputs={len(files)}[v]")
    out = folder / "viral-compare.mp4"
    sh("ffmpeg", "-v", "error", "-y", *args, "-filter_complex", ";".join(fl), "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
       "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out)
    print(f"{len(files)} вариантов бок о бок → {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0]); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("models"); p.add_argument("--res", default="720p")
    p = sp.add_parser("plan"); p.add_argument("wd")
    p.add_argument("--every", type=float, default=5.0, help="одна вставка на столько секунд «только лицо»")
    p.add_argument("--count", type=int); p.add_argument("--min", type=float, default=1.2); p.add_argument("--max", type=float, default=3.0)
    p.add_argument("--margin", type=float, default=0.35); p.add_argument("--skip-start", type=float, default=0.0)
    p.add_argument("--skip-end", type=float, default=0.5)
    p.add_argument("--cross-cuts", action="store_true", help="отрезок может идти через склейки (для моделей правки видео)")
    p = sp.add_parser("show"); p.add_argument("wd")
    p = sp.add_parser("pick"); p.add_argument("wd"); p.add_argument("choices", nargs="+", help="вставка=вариант, 0 — без вставки")
    p = sp.add_parser("gen"); p.add_argument("wd"); p.add_argument("--model", default=DEFAULT_MODEL); p.add_argument("--res", default="720p")
    p.add_argument("--ids"); p.add_argument("--max-usd", type=float, default=3.0); p.add_argument("--yes", action="store_true")
    p.add_argument("--no-return", action="store_true", help="не передавать последний кадр (вставка не возвращается к исходнику)")
    p.add_argument("--video-base-url"); p.add_argument("--serve-dir"); p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--env-file")
    p = sp.add_parser("render"); p.add_argument("wd"); p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--fit", default="speed", choices=["speed", "trim"])
    p = sp.add_parser("compare"); p.add_argument("wd"); p.add_argument("--base")
    A = ap.parse_args()
    dict(models=cmd_models, plan=cmd_plan, show=cmd_show, pick=cmd_pick, gen=cmd_gen, render=cmd_render, compare=cmd_compare)[A.cmd](A)


if __name__ == "__main__":
    main()
