# /// script
# requires-python = ">=3.11"
# dependencies = ["google-api-python-client", "google-auth-oauthlib"]
# ///
"""yt.py <команда> … — доступ к своему YouTube-каналу: ролики, правка SEO, аналитика.

  auth                         вход через Google в браузере (один раз; токен в ~/.config/yt-seo/token-<профиль>.json)
  whoami                       какой канал подключён
  videos [--since 2026-10-01] [--status all|public|private|scheduled|unlisted] [--grep текст] [--shorts|--long] [--limit 50]
                               свои ролики, включая приватные и отложенные (с датой выхода)
  show <id|ссылка>             название, описание, теги, статус, дата выхода
  plan <папка ролика>           найти загруженный ролик по черновому названию = имени папки (файл <папка>.mp4) и взять её youtube.md
  plan <id|ссылка> <youtube.md> [--out plan.json]      план правки по готовому youtube.md (название, описание, теги)
  plan --batch <правки.json> [--out plan.json]         массовая правка: [{"id": …, "title"?: …, "description"?: …, "tags"?: […]}]
  apply <plan.json> --yes      применить план (только после «да» автора; перед записью сверяет, что ролик не меняли)
  thumb <id|ссылка> <обложка.jpg> --yes                поставить обложку
  analytics [--preset videos|daily|traffic|countries|devices|subscribed|shorts]
            [--metrics …] [--dimensions …] [--filters …] [--sort=-views] [--max 50]
            [--start 2026-09-01] [--end 2026-10-22] [--out отчёт.csv]
  probe-metrics [--start …]    какие метрики (в т.ч. для Shorts) API реально отдаёт по этому каналу

Общие флаги: --profile <канал> — несколько каналов, свой вход на каждый (токен token-<канал>.json); по умолчанию $YT_PROFILE
или ai-native. Профиль = имя папки канала в ~/Movies/Shorts (ai-native, syamych…): plan <папка ролика> берёт его сам.
--client <client_secret.json>.
Правка перезаписывает блок snippet целиком, поэтому план собирается из текущих данных ролика: меняются только
название, описание и теги, категория и язык остаются. Дату выхода и статус правка не трогает (part=snippet)."""
import argparse, csv, datetime as dt, json, os, re, sys
from pathlib import Path

CFG = Path.home() / ".config/yt-seo"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl", "https://www.googleapis.com/auth/yt-analytics.readonly"]

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
ap.add_argument("cmd")
ap.add_argument("args", nargs="*")
ap.add_argument("--profile")
ap.add_argument("--client", default=str(CFG / "client_secret.json"))
ap.add_argument("--since"); ap.add_argument("--status", default="all"); ap.add_argument("--grep")
ap.add_argument("--shorts", action="store_true"); ap.add_argument("--long", action="store_true")
ap.add_argument("--limit", type=int, default=50)
ap.add_argument("--out"); ap.add_argument("--batch"); ap.add_argument("--yes", action="store_true")
ap.add_argument("--preset"); ap.add_argument("--metrics"); ap.add_argument("--dimensions"); ap.add_argument("--filters")
ap.add_argument("--sort"); ap.add_argument("--max", type=int, default=50)
ap.add_argument("--start"); ap.add_argument("--end")
A = ap.parse_args()
PROFILE = A.profile or os.environ.get("YT_PROFILE") or "ai-native"
TOKEN = CFG / f"token-{PROFILE}.json"


# ───────────────────────── вход ─────────────────────────
def creds(interactive=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    c = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if c and c.expired and c.refresh_token:
        try: c.refresh(Request())
        except Exception as e:
            # приложение в тестовом режиме Google: токен живёт 7 дней
            sys.exit(f"вход истёк ({type(e).__name__}): запусти `yt.py auth --profile {TOKEN.stem.removeprefix('token-')}` заново")
    if not c or not c.valid:
        if not interactive: sys.exit(f"канал «{TOKEN.stem.removeprefix('token-')}» не подключён: сначала `yt.py auth --profile {TOKEN.stem.removeprefix('token-')}` (SKILL.md, «Настройка»)")
        if not Path(A.client).exists(): sys.exit(f"нет {A.client}: скачай OAuth-клиент «Desktop app» из Google Cloud (SKILL.md, «Настройка»)")
        from google_auth_oauthlib.flow import InstalledAppFlow
        c = InstalledAppFlow.from_client_secrets_file(A.client, SCOPES).run_local_server(port=0, open_browser=True)
    CFG.mkdir(parents=True, exist_ok=True); TOKEN.write_text(c.to_json()); TOKEN.chmod(0o600)
    return c


def yt():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds(), cache_discovery=False)


def yta():
    from googleapiclient.discovery import build
    return build("youtubeAnalytics", "v2", credentials=creds(), cache_discovery=False)


def call(req):
    from googleapiclient.errors import HttpError
    try: return req.execute()
    except HttpError as e:
        try: msg = json.loads(e.content)["error"]["message"]
        except Exception: msg = str(e)
        sys.exit(f"YouTube API {e.resp.status}: {msg}")


# ───────────────────────── ролики ─────────────────────────
def vid_id(s):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|/video/)([\w-]{11})", s)
    return m.group(1) if m else s


def iso_dur(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m: return 0
    d, h, mi, se = (int(x or 0) for x in m.groups()); return d * 86400 + h * 3600 + mi * 60 + se


def my_channel(Y):
    it = call(Y.channels().list(part="snippet,contentDetails,statistics", mine=True)).get("items", [])
    if not it: sys.exit("у этого аккаунта нет канала YouTube (или при входе выбран не тот аккаунт/бренд-канал)")
    return it[0]


def get_videos(Y, ids, parts="snippet,status,contentDetails,statistics"):
    out = {}
    for i in range(0, len(ids), 50):
        for v in call(Y.videos().list(part=parts, id=",".join(ids[i:i + 50]))).get("items", []): out[v["id"]] = v
    return out


def status_of(v):
    st = v["status"]
    if st.get("privacyStatus") == "private" and st.get("publishAt"): return "scheduled"
    return st.get("privacyStatus", "?")


def upload_ids(Y, n):
    """Последние n загрузок канала, включая приватные и отложенные (плейлист загрузок видит только владелец)."""
    up = my_channel(Y)["contentDetails"]["relatedPlaylists"]["uploads"]; ids, tok = [], None
    while len(ids) < n:
        r = call(Y.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50, pageToken=tok))
        ids += [x["contentDetails"]["videoId"] for x in r.get("items", [])]
        tok = r.get("nextPageToken")
        if not tok: break
    return ids


def find_by_draft_title(Y, name):
    """Ролик, загруженный файлом <папка>.mp4: YouTube ставит имя файла черновым названием (2026-10-22)."""
    V = get_videos(Y, upload_ids(Y, 100), parts="snippet,status")
    norm = lambda s: re.sub(r"\.(mp4|mov)$", "", s.strip().lower())
    hit = [v for v in V.values() if norm(v["snippet"]["title"]) == norm(name)]
    if len(hit) == 1: return hit[0]["id"]
    if len(hit) > 1: sys.exit(f"роликов с названием «{name}» несколько: {', '.join(v['id'] for v in hit)} — укажи id")
    sys.exit(f"ролик с черновым названием «{name}» не найден среди 100 последних загрузок: он загружен? название в Студии уже меняли? Тогда plan <id> <youtube.md>")


def cmd_videos():
    Y = yt(); ids = upload_ids(Y, max(A.limit * 4, 200))   # с запасом: фильтры ниже отсекают часть
    V = get_videos(Y, ids); rows = []
    for i in ids:
        v = V.get(i)
        if not v: continue
        s, st = v["snippet"], status_of(v); dur = iso_dur(v["contentDetails"]["duration"])
        when = v["status"].get("publishAt") or s.get("publishedAt", "")
        if A.since and when[:10] < A.since: continue
        if A.status != "all" and st != A.status: continue
        if A.grep and A.grep.lower() not in s["title"].lower(): continue
        if (A.shorts and dur > 180) or (A.long and dur <= 180): continue
        rows.append(dict(id=i, status=st, date=when[:16].replace("T", " "), dur=dur, views=int(v.get("statistics", {}).get("viewCount", 0)), title=s["title"]))
        if len(rows) >= A.limit: break
    rows.sort(key=lambda r: r["date"], reverse=True)   # плейлист загрузок идёт не по дате выхода: отложенные вперемешку
    for r in rows: print(f"{r['id']}  {r['status']:9}  {r['date']}  {r['dur']:>5}s  {r['views']:>8}  {r['title']}")
    if A.out: Path(A.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1)); print(f"→ {A.out}")


def cmd_show():
    Y = yt(); i = vid_id(A.args[0]); v = get_videos(Y, [i]).get(i)
    if not v: sys.exit(f"ролик {i} не найден на подключённом канале")
    s = v["snippet"]
    print(f"{i} · {status_of(v)} · выход {v['status'].get('publishAt') or s.get('publishedAt')} · {iso_dur(v['contentDetails']['duration'])} с")
    print(f"\nНазвание ({len(s['title'])}/100): {s['title']}\n\nОписание:\n{s.get('description', '')}\n\nТеги: {', '.join(s.get('tags', []))}")


# ───────────────────────── SEO: план и применение ─────────────────────────
def parse_youtube_md(path):
    """youtube.md в формате adhd-shorts/references/package.md: «# Название (N/100)», «## Описание», «## Теги YouTube», «## Закреплённый комментарий»."""
    md = Path(path).read_text(encoding="utf-8")
    sec = lambda name: (m.group(1).strip() if (m := re.search(rf"^## {name}[^\n]*\n(.*?)(?=^## |\Z)", md, flags=re.M | re.S)) else "")
    m = re.search(r"^# (.+)$", md, flags=re.M)
    if not m: sys.exit(f"{path}: нет строки «# Название»")
    title = re.sub(r"\s*\(\d+/100\)\s*$", "", m.group(1)).strip()
    tags = [t.strip() for t in re.split(r"[,\n]", sec("Теги YouTube")) if t.strip()]
    return dict(title=title, description=sec("Описание"), tags=tags), sec("Закреплённый комментарий")


def check(after):
    """Ограничения YouTube: иначе videos.update падает с невнятной ошибкой или молча режет."""
    errs = []
    t, d, tags = after["title"], after.get("description", ""), after.get("tags", [])
    if not t: errs.append("пустое название")
    if len(t) > 100: errs.append(f"название {len(t)} символов (лимит 100)")
    if len(d.encode()) > 5000: errs.append(f"описание {len(d.encode())} байт (лимит 5000)")
    if re.search(r"[<>]", t + d): errs.append("в названии или описании есть < или >: YouTube их не принимает")
    tl = sum(len(x) + (2 if " " in x else 0) for x in tags) + max(0, len(tags) - 1)
    if tl > 500: errs.append(f"теги ≈ {tl} символов (лимит 500)")
    if any(re.search(r"[<>,]", x) for x in tags): errs.append("в теге запятая или < >")
    return errs


MUTABLE = ("title", "description", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")


def cmd_plan():
    global TOKEN
    if not A.batch and len(A.args) == 1 and Path(A.args[0]).expanduser().is_dir() and not A.profile:
        d0 = Path(A.args[0]).expanduser().resolve()
        ch = d0.parent.parent.name if d0.parent.name == "Archive" else d0.parent.name   # ~/Movies/Shorts/<канал>/[Archive/]<ролик>
        if (CFG / f"token-{ch}.json").exists(): TOKEN = CFG / f"token-{ch}.json"; print(f"канал по папке: {ch}")
    Y = yt()
    folder = None
    if A.batch: wants = json.loads(Path(A.batch).read_text(encoding="utf-8")); pin = ""
    elif len(A.args) == 1 and Path(A.args[0]).expanduser().is_dir():   # папка ролика из adhd-shorts
        d = Path(A.args[0]).expanduser().resolve(); folder = str(d)
        if not (d / "youtube.md").is_file(): sys.exit(f"в {d} нет youtube.md")
        vids = [f for f in d.glob("*.mp4") if f.stem != "short"]   # видео названо как папка или «<ролик>-<часть>» у серий
        draft = vids[0].stem if len(vids) == 1 else d.name
        i = find_by_draft_title(Y, draft); print(f"нашёл ролик {i} с черновым названием «{draft}»")
        want, pin = parse_youtube_md(d / "youtube.md"); wants = [dict(want, id=i)]
        if not A.out: A.out = str(d / ".work/yt_plan.json") if (d / ".work").is_dir() else str(d / "yt_plan.json")
        covers = sorted(d.glob("cover_*.jpg"))
        if covers: print(f"обложки в папке: {', '.join(c.name for c in covers)} — поставить: yt.py thumb {i} <файл> --yes (после «да»)")
    else:
        if len(A.args) < 2: sys.exit("plan <папка ролика>  |  plan <id|ссылка> <youtube.md>  |  plan --batch правки.json")
        want, pin = parse_youtube_md(A.args[1]); wants = [dict(want, id=vid_id(A.args[0]))]
    V = get_videos(Y, [vid_id(w["id"]) for w in wants], parts="snippet,status")
    changes, bad = [], 0
    for w in wants:
        i = vid_id(w["id"]); v = V.get(i)
        if not v: print(f"✗ {i}: не найден на подключённом канале"); bad += 1; continue
        before = {k: v["snippet"][k] for k in MUTABLE if k in v["snippet"]}
        after = dict(before, **{k: w[k] for k in ("title", "description", "tags") if k in w})
        # ссылки (телега, GitHub) из старого описания не теряем: нет в новом — дописываем в конец (2026-10-22)
        lost = [u for u in re.findall(r"https?://\S+", before.get("description", "")) if u not in after.get("description", "")]
        if lost:
            after["description"] = after.get("description", "").rstrip() + "\n\n" + "\n".join(dict.fromkeys(lost))
            print(f"! {i}: в новом описании не было ссылок из старого — дописал: {', '.join(dict.fromkeys(lost))}")
        errs = check(after)
        for e in errs: print(f"✗ {i}: {e}")
        if errs: bad += 1; continue
        diff = [k for k in ("title", "description", "tags") if before.get(k) != after.get(k)]
        if not diff: print(f"= {i}: менять нечего"); continue
        changes.append(dict(id=i, status=status_of(v), before=before, after=after))
        print(f"\n── {i} ({status_of(v)}) — меняется: {', '.join(diff)}")
        for k in diff:
            b, a = before.get(k, ""), after.get(k, "")
            if k == "tags": b, a = ", ".join(b or []), ", ".join(a or [])
            print(f"  {k}:\n    было:  {b[:300]}{'…' if len(b) > 300 else ''}\n    стало: {a[:300]}{'…' if len(a) > 300 else ''}")
    out = Path(A.out or "yt_plan.json")
    out.write_text(json.dumps(dict(created=dt.datetime.now().isoformat(timespec="seconds"), folder=folder, changes=changes), ensure_ascii=False, indent=1))
    print(f"\nплан: {len(changes)} роликов{f', с ошибками {bad}' if bad else ''} → {out}")
    print("Применить: yt.py apply " + str(out) + " --yes  (только после «да» автора)")
    if pin: print(f"\nЗакреп (API закрепить не умеет — вставь и закрепи в Студии):\n{pin}")
    if bad: sys.exit(1)


def cmd_apply():
    if not A.yes: sys.exit("apply меняет опубликованные данные: нужен флаг --yes (ставится только после «да» автора)")
    plan = json.loads(Path(A.args[0]).read_text(encoding="utf-8")); Y = yt()
    V = get_videos(Y, [c["id"] for c in plan["changes"]], parts="snippet")
    ok = 0
    for c in plan["changes"]:
        v = V.get(c["id"])
        now = {k: v["snippet"][k] for k in MUTABLE if k in v["snippet"]} if v else None
        if now != c["before"]:
            print(f"✗ {c['id']}: ролик изменили после plan — пропускаю, пересобери план"); continue
        call(Y.videos().update(part="snippet", body={"id": c["id"], "snippet": c["after"]}))
        print(f"✓ {c['id']}: {c['after']['title']}"); ok += 1
    print(f"применено {ok} из {len(plan['changes'])} (≈ {50 * ok} единиц квоты)")
    # ролик из папки adhd-shorts загружен и получил SEO → статус «выгружен», папка уезжает в Archive/ (status.py, 2026-10-22)
    st = Path(__file__).resolve().parents[2] / "adhd-shorts/scripts/status.py"
    if ok and plan.get("folder") and Path(plan["folder"]).is_dir() and st.is_file():
        import subprocess
        subprocess.run([sys.executable, str(st), "set", plan["folder"], "uploaded", "--note", f"SEO через API, ролик {plan['changes'][0]['id']}"])


def cmd_thumb():
    if not A.yes: sys.exit("thumb меняет обложку: нужен флаг --yes (только после «да» автора)")
    from googleapiclient.http import MediaFileUpload
    i, f = vid_id(A.args[0]), Path(A.args[1])
    if f.stat().st_size > 2 * 1024 * 1024: sys.exit(f"{f.name}: {f.stat().st_size // 1024} КБ — YouTube принимает обложку до 2 МБ (бери .jpg из cover_gen.py)")
    call(yt().thumbnails().set(videoId=i, media_body=MediaFileUpload(str(f))))
    print(f"✓ обложка {f.name} → {i}")


# ───────────────────────── аналитика ─────────────────────────
BASE = "views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,shares,comments,subscribersGained,subscribersLost"
PRESETS = {
    "videos": dict(dimensions="video", metrics=BASE, sort="-views"),
    "daily": dict(dimensions="day", metrics=BASE, sort="day"),
    "traffic": dict(dimensions="insightTrafficSourceType", metrics="views,estimatedMinutesWatched", sort="-views"),
    "countries": dict(dimensions="country", metrics="views,estimatedMinutesWatched,averageViewDuration", sort="-views"),
    "devices": dict(dimensions="deviceType", metrics="views,estimatedMinutesWatched", sort="-views"),
    "subscribed": dict(dimensions="subscribedStatus", metrics="views,estimatedMinutesWatched,averageViewPercentage"),
    "shorts": dict(dimensions="creatorContentType", metrics=BASE),
}


def cmd_analytics():
    p = dict(PRESETS.get(A.preset or "videos", {}))
    if A.preset and A.preset not in PRESETS: sys.exit(f"нет пресета {A.preset}: {', '.join(PRESETS)}")
    for k in ("metrics", "dimensions", "filters", "sort"):
        if getattr(A, k): p[k] = getattr(A, k)
    end = A.end or dt.date.today().isoformat(); start = A.start or (dt.date.fromisoformat(end) - dt.timedelta(days=28)).isoformat()
    q = dict(ids="channel==MINE", startDate=start, endDate=end, metrics=p["metrics"])
    for k in ("dimensions", "filters", "sort"):
        if p.get(k): q[k] = p[k]
    dims = p.get("dimensions") or ""
    if "video" in dims: q["maxResults"] = min(A.max, 200)
    if "insightTrafficSourceDetail" in dims: q["maxResults"] = min(A.max, 25)   # без лимита ≤ 25 API отвечает «query is not supported»
    r = call(yta().reports().query(**q))
    head = [h["name"] for h in r.get("columnHeaders", [])]; rows = r.get("rows", [])
    if "video" in head and rows:                       # подписать ролики названиями
        k = head.index("video"); T = get_videos(yt(), [x[k] for x in rows], parts="snippet")
        head.insert(k + 1, "title"); rows = [x[:k + 1] + [T.get(x[k], {}).get("snippet", {}).get("title", "")] + x[k + 1:] for x in rows]
    if "views" in head and "engagedViews" in head:      # «Продолжили смотреть» из Студии = engagedViews / views (сверено 2026-10-22: ±0–3 п.)
        a, b = head.index("engagedViews"), head.index("views")
        head.append("stayedPct"); rows = [x + [round(100 * x[a] / x[b], 1) if x[b] else 0] for x in rows]
    print(f"{start} … {end} · {len(rows)} строк · данные YouTube идут с задержкой ~2–3 дня")
    w = [max([len(str(h))] + [min(len(str(x[j])), 60) for x in rows]) for j, h in enumerate(head)]
    print("  ".join(str(h).ljust(w[j]) for j, h in enumerate(head)))
    for x in rows: print("  ".join(str(v)[:60].ljust(w[j]) for j, v in enumerate(x)))
    if A.out:
        with open(A.out, "w", newline="", encoding="utf-8") as f: csv.writer(f).writerows([head] + rows)
        print(f"→ {A.out}")


PROBE = ["views", "engagedViews", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "likes", "shares",
         "comments", "subscribersGained", "videoThumbnailImpressions", "videoThumbnailImpressionsClickRate", "cardClickRate",
         "redViews", "playlistStarts"]


def cmd_probe():
    """Какие метрики канал реально отдаёт: проверяем по одной, ошибки собираем (2026-10-22: «продолжили смотреть» в API не подтверждено)."""
    from googleapiclient.errors import HttpError
    end = A.end or dt.date.today().isoformat(); start = A.start or (dt.date.fromisoformat(end) - dt.timedelta(days=28)).isoformat()
    Q = yta()
    for m in PROBE:
        try:
            r = Q.reports().query(ids="channel==MINE", startDate=start, endDate=end, metrics=m).execute()
            print(f"✓ {m:38} {r.get('rows', [[None]])[0][0]}")
        except HttpError as e:
            try: msg = json.loads(e.content)["error"]["message"]
            except Exception: msg = str(e)
            print(f"✗ {m:38} {msg[:90]}")


def cmd_whoami():
    c = my_channel(yt()); s = c["statistics"]
    print(f"{c['snippet']['title']} ({c['snippet'].get('customUrl', '')}) · id {c['id']} · подписчиков {s.get('subscriberCount')} · роликов {s.get('videoCount')}")


CMDS = dict(auth=lambda: (TOKEN.unlink(missing_ok=True), creds(interactive=True), cmd_whoami()), whoami=cmd_whoami, videos=cmd_videos, show=cmd_show, plan=cmd_plan,
            apply=cmd_apply, thumb=cmd_thumb, analytics=cmd_analytics, **{"probe-metrics": cmd_probe})
if A.cmd not in CMDS: sys.exit(f"нет команды {A.cmd}: {', '.join(CMDS)}")
CMDS[A.cmd]()
