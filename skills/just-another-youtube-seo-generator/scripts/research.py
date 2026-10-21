# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""research.py "<запрос>" ["<ещё запрос>" ...] [--out DIR] [--lang ru] [--region RU] [--format shorts|long]
                [--top 20] [--deep] [--no-api] [--key-file FILE] [--min-views N]

Собирает ФАКТЫ из поиска YouTube, чтобы название, описание, теги и хештеги писались по данным, а не из головы.

1. Подсказки поиска YouTube (автодополнение, без ключа): что люди реально набирают.
2. Конкуренты — верх выдачи по запросу:
     • есть ключ YouTube Data API (переменная YOUTUBE_API_KEY или --key-file) → API: просмотры, лайки, подписчики канала,
       теги, описания (≈ 205 единиц квоты за запуск из 10 000 в сутки);
     • ключа нет → yt-dlp (поиск и метаданные без ключа; подписчики только если yt-dlp отдал).
3. Разбор: какие слова стоят в названиях, какие теги и хештеги реально используют ролики из топа (и сколько просмотров у
   тех, кто их использует), длины названий и описаний, главы, ссылки.

Пишет в --out (по умолчанию ./seo): seo_research.json (машинный, нужен validate.py) и seo_research.md (для чтения).
Ключ API нигде не печатается и не сохраняется. Это наблюдения о том, что используют ролики в топе, а не доказательство
причины их успеха."""
import argparse, json, os, re, statistics, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ytseo_text import tokens, stems, stem, flat, hashtags_in, is_meaningful, ngrams, STOP

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("queries", nargs="+", help="основной запрос и, по желанию, соседние формулировки темы")
ap.add_argument("--out", default="seo")
ap.add_argument("--lang", default="ru", help="язык интерфейса и выдачи (hl / relevanceLanguage)")
ap.add_argument("--region", default="RU", help="страна (gl / regionCode)")
ap.add_argument("--format", choices=["shorts", "long"], default="shorts")
ap.add_argument("--top", type=int, default=20, help="сколько конкурентов разбирать на запрос")
ap.add_argument("--deep", action="store_true", help="расширить подсказки по алфавиту (больше запросов, дольше)")
ap.add_argument("--no-api", action="store_true", help="не использовать ключ, даже если он есть")
ap.add_argument("--key-file", help="файл с ключом YouTube Data API (одна строка)")
ap.add_argument("--cookies-from-browser", help="для yt-dlp без ключа: взять cookies из браузера (chrome, safari…), если YouTube просит войти")
ap.add_argument("--vidiq-keywords", help="JSON с результатами vidIQ keyword_research (см. SKILL.md): объём и конкуренция по фразам")
ap.add_argument("--min-views", type=int, default=0, help="отбросить конкурентов с меньшим числом просмотров")
A = ap.parse_args()
OUT = Path(A.out); OUT.mkdir(parents=True, exist_ok=True)
SHORT_MAX = 180   # Shorts — до 3 минут


def log(*a): print(*a, file=sys.stderr, flush=True)


# ───────────────────────── ключ ─────────────────────────
def load_key():
    if A.no_api: return None
    k = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not k and A.key_file:
        p = Path(A.key_file).expanduser()
        k = p.read_text().strip() if p.exists() else ""
    return k or None
KEY = load_key()


class ApiError(Exception): pass


def api(path, **params):
    params["key"] = KEY
    url = f"{os.environ.get('YTSEO_API_BASE', 'https://www.googleapis.com/youtube/v3')}/{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=25) as r: return json.load(r)
    except urllib.error.HTTPError as e:           # URL с ключом не печатаем
        try: msg = json.load(e)["error"]["message"]
        except Exception: msg = e.reason
        raise ApiError(f"HTTP {e.code}: {msg}") from None
    except Exception as e:
        raise ApiError(type(e).__name__) from None


# ───────────────────────── vidIQ (необязательно) ─────────────────────────
def load_vidiq(path):
    """Файл, который агент собрал из ответов vidIQ MCP: список {phrase, volume, competition, score}. Названия полей терпимые."""
    raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    items = raw.get("keywords", raw) if isinstance(raw, dict) else raw
    pick = lambda d, ks: next((d[k] for k in ks if k in d and d[k] is not None), None)
    out = []
    for d in items:
        if not isinstance(d, dict): continue
        ph = pick(d, ("phrase", "keyword", "query", "term", "text"))
        if ph: out.append(dict(phrase=str(ph).strip().lower(), volume=pick(d, ("volume", "search_volume", "searchVolume")),
                               competition=pick(d, ("competition", "competition_score", "competitionScore")),
                               score=pick(d, ("overall", "overall_score", "overallScore", "score"))))
    return out

VIDIQ = load_vidiq(A.vidiq_keywords) if A.vidiq_keywords else []


# ───────────────────────── подсказки ─────────────────────────
def suggest(q):
    url = "https://suggestqueries.google.com/complete/search?" + urllib.parse.urlencode(
        {"client": "firefox", "ds": "yt", "hl": A.lang, "gl": A.region, "q": q})
    try:
        with urllib.request.urlopen(url, timeout=15) as r: return json.loads(r.read().decode("utf-8", "replace"))[1]
    except Exception: return []


PREFIX = {"ru": ["как", "что", "почему", "где", "какой", "лучший"], "en": ["how", "what", "why", "best", "is"]}
ALPHA = {"ru": "абвгдежзиклмнопрстуфхцчшэюя", "en": "abcdefghijklmnopqrstuvwxyz"}


def collect_suggestions(queries):
    seen = {}                      # фраза → {"rank": лучший ранг, "n": в скольких запросах}
    probes = []
    for q in queries:
        probes += [q] + [f"{p} {q}" for p in PREFIX.get(A.lang, PREFIX["en"])]
        if A.deep: probes += [f"{q} {c}" for c in ALPHA.get(A.lang, ALPHA["en"])]
    for p in probes:
        for rank, s in enumerate(suggest(p), 1):
            s = s.strip().lower()
            if not s: continue
            e = seen.setdefault(s, {"rank": rank, "n": 0}); e["rank"] = min(e["rank"], rank); e["n"] += 1
        time.sleep(0.12)
    return [{"phrase": k, **v} for k, v in sorted(seen.items(), key=lambda kv: (-kv[1]["n"], kv[1]["rank"]))]


# ───────────────────────── конкуренты: API ─────────────────────────
def iso_dur(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m: return 0
    d, h, mi, se = (int(x or 0) for x in m.groups()); return d * 86400 + h * 3600 + mi * 60 + se


def api_candidates(q, n):
    ids = []
    base = dict(part="snippet", type="video", q=q, maxResults=min(50, n * 2), regionCode=A.region, relevanceLanguage=A.lang)
    if A.format == "shorts": base["videoDuration"] = "short"
    for extra in ({"order": "relevance"},
                  {"order": "viewCount", "publishedAfter": (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")}):
        for it in api("search", **base, **extra).get("items", []):
            v = it["id"].get("videoId")
            if v and v not in ids: ids.append(v)
    return ids


def api_details(ids):
    vids, chans = {}, {}
    for i in range(0, len(ids), 50):
        for it in api("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])).get("items", []):
            vids[it["id"]] = it
    ch_ids = sorted({v["snippet"]["channelId"] for v in vids.values()})
    for i in range(0, len(ch_ids), 50):
        for it in api("channels", part="statistics", id=",".join(ch_ids[i:i + 50])).get("items", []):
            st = it.get("statistics", {}); chans[it["id"]] = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0))
    out = {}
    for vid, it in vids.items():
        sn, st = it["snippet"], it.get("statistics", {})
        out[vid] = dict(id=vid, title=sn.get("title", ""), channel=sn.get("channelTitle", ""), subs=chans.get(sn["channelId"]),
                        views=int(st.get("viewCount", 0)), likes=int(st["likeCount"]) if "likeCount" in st else None,
                        comments=int(st["commentCount"]) if "commentCount" in st else None,
                        published=sn.get("publishedAt", "")[:10], duration=iso_dur(it["contentDetails"].get("duration")),
                        tags=sn.get("tags", []), description=sn.get("description", ""), source="api")
    return out


# ───────────────────────── конкуренты: yt-dlp ─────────────────────────
COOKIES = ["--cookies-from-browser", A.cookies_from_browser] if A.cookies_from_browser else []
BOT = {"n": 0}


def ytdlp_flat(q, n):
    """Поиск без заходов на страницы роликов: id, название, канал, просмотры, длительность."""
    r = subprocess.run(["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", *COOKIES, f"ytsearch{n}:{q}"], capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        try: d = json.loads(line)
        except Exception: continue
        out.append(dict(id=d["id"], title=d.get("title", ""), channel=d.get("channel") or d.get("uploader") or "",
                        views=int(d.get("view_count") or 0), duration=int(d.get("duration") or 0)))
    return out


def ytdlp_one(vid):
    if BOT["n"] >= 3: return None
    r = subprocess.run(["yt-dlp", "--skip-download", "--no-playlist", "--dump-json", "--no-warnings", *COOKIES, f"https://www.youtube.com/watch?v={vid}"],
                       capture_output=True, text=True)
    if "Sign in to confirm" in r.stderr:
        BOT["n"] += 1
        if BOT["n"] == 3: log("YouTube просит войти (защита от ботов): теги и описания не получены. Нужен ключ API или --cookies-from-browser chrome")
        return None
    try: d = json.loads(r.stdout.splitlines()[-1])
    except Exception: return None
    time.sleep(0.4)
    up = d.get("upload_date") or ""
    return dict(id=vid, title=d.get("title", ""), channel=d.get("channel") or d.get("uploader") or "", subs=d.get("channel_follower_count"),
                views=int(d.get("view_count") or 0), likes=d.get("like_count"), comments=d.get("comment_count"),
                published=f"{up[:4]}-{up[4:6]}-{up[6:8]}" if len(up) == 8 else "", duration=int(d.get("duration") or 0),
                tags=d.get("tags") or [], description=d.get("description") or "", source="yt-dlp",
                vertical=(d.get("height") or 0) > (d.get("width") or 0) if d.get("width") else None)


def ytdlp_details(ids):
    with ThreadPoolExecutor(2) as ex: res = list(ex.map(ytdlp_one, ids))
    return {r["id"]: r for r in res if r}


def format_ok(duration, vertical=None):
    if A.format == "shorts": return 0 < duration <= SHORT_MAX and vertical is not False
    return duration > SHORT_MAX


# ───────────────────────── сбор ─────────────────────────
def gather_api(queries):
    cand = []
    for q in queries:
        for i in api_candidates(q, A.top):
            if i not in cand: cand.append(i)
    det = api_details(cand)
    recs = [dict(det[i], detail=True) for i in cand if i in det]
    return [r for r in recs if format_ok(r["duration"])], len(recs)


def gather_ytdlp(queries):
    flat = {}
    for q in queries:
        for e in ytdlp_flat(q, A.top * 3): flat.setdefault(e["id"], e)
        if A.format == "shorts":
            for e in ytdlp_flat(f"{q} shorts", A.top * 3): flat.setdefault(e["id"], e)
    pick = [e for e in flat.values() if format_ok(e["duration"]) and e["views"] >= A.min_views][: A.top * len(queries)]
    det = ytdlp_details([e["id"] for e in pick])
    recs = []
    for e in pick:
        if e["id"] in det and format_ok(det[e["id"]]["duration"], det[e["id"]].get("vertical")): recs.append(dict(det[e["id"]], detail=True))
        elif e["id"] not in det:
            recs.append(dict(e, subs=None, likes=None, comments=None, published="", tags=[], description="", source="yt-dlp-flat", detail=False))
    return recs, len(flat)


def gather(queries):
    if KEY:
        try:
            recs, seen = gather_api(queries); source = "api"
            return [r for r in recs if r["views"] >= A.min_views][: A.top * len(queries)], source, seen
        except ApiError as e: log(f"API недоступен ({e}); перехожу на yt-dlp")
    recs, seen = gather_ytdlp(queries)
    return recs, "yt-dlp", seen


# ───────────────────────── анализ ─────────────────────────
def med(xs):
    xs = [x for x in xs if x is not None]
    return int(statistics.median(xs)) if xs else None


def pct(a, b): return round(100 * a / b) if b else 0


def analyze(recs, sugg):
    today = date.today(); N = len(recs)
    for r in recs:
        try: days = max(1, (today - date.fromisoformat(r["published"])).days)
        except Exception: days = None
        r["age_days"] = days
        r["views_per_day"] = round(r["views"] / days) if days else None
        r["hashtags"] = list(dict.fromkeys(hashtags_in(r["description"]) + hashtags_in(r["title"])))
        r["title_stems"] = stems(r["title"])
    D = [r for r in recs if r.get("detail")]; ND = len(D)
    min_df = 2 if N >= 8 else 1; min_df_d = 2 if ND >= 8 else 1

    # термины в названиях: 1–4-граммы по числу роликов, где они встречаются
    grp = defaultdict(lambda: {"vids": set(), "forms": Counter()})
    for i, r in enumerate(recs):
        tk = tokens(r["title"])
        for n in (1, 2, 3, 4):
            for g in ngrams(tk, n):
                if not is_meaningful(g): continue
                k = tuple(stem(t) for t in g); grp[k]["vids"].add(i); grp[k]["forms"][" ".join(g)] += 1
    title_terms = sorted(({"term": v["forms"].most_common(1)[0][0], "df": len(v["vids"]), "median_views": med([recs[i]["views"] for i in v["vids"]])}
                          for v in grp.values() if len(v["vids"]) >= min_df), key=lambda x: (-x["df"], -len(x["term"].split()), x["term"]))[:60]

    kept = []
    for t in title_terms:                         # короткая часть длинной фразы с тем же числом роликов — шум
        tt = t["term"].split()
        if any(k["df"] == t["df"] and len(k["term"].split()) > len(tt) and " ".join(tt) in k["term"] for k in kept): continue
        kept.append(t)
    title_terms = kept

    def tally(getter):
        g = defaultdict(lambda: {"vids": set(), "forms": Counter()})
        for i, r in enumerate(recs):
            if not r.get("detail"): continue
            for t in set(getter(r)):
                k = flat(t)
                if k: g[k]["vids"].add(i); g[k]["forms"][t.lower()] += 1
        return sorted(({"term": v["forms"].most_common(1)[0][0], "df": len(v["vids"]), "median_views": med([recs[i]["views"] for i in v["vids"]])}
                       for v in g.values() if len(v["vids"]) >= min_df_d), key=lambda x: (-x["df"], x["term"]))[:40]
    tags = tally(lambda r: r["tags"])
    hashtags = tally(lambda r: r["hashtags"])
    in_title = Counter(h for r in recs for h in hashtags_in(r["title"]))

    # кандидаты в главный ключ: подсказки, которые покрывают названия конкурентов
    cands = []
    for s in sugg[:80]:
        need = {t for t in stems(s["phrase"]) if t not in STOP}
        if not need: continue
        cov = sum(1 for r in recs if need <= set(r["title_stems"]))
        cands.append({"phrase": s["phrase"], "rank": s["rank"], "asked_in": s["n"], "titles_with_all_words": cov})
    vq = {flat(v["phrase"]): v for v in VIDIQ}
    for c in cands:
        v = vq.get(flat(c["phrase"]))
        if v: c.update(vidiq_volume=v["volume"], vidiq_competition=v["competition"], vidiq_score=v["score"])
    cands.sort(key=lambda c: (-(c["titles_with_all_words"] > 0), -c["asked_in"], c["rank"], -c["titles_with_all_words"]))

    lens = [len(r["title"]) for r in recs]
    def pd(cond): return pct(sum(bool(cond(r)) for r in D), ND) if ND else None
    stats = dict(videos=N, videos_with_details=ND, min_df=min_df,
                 title_len={"median": med(lens), "p25": int(statistics.quantiles(lens, n=4)[0]) if N >= 4 else None,
                            "p75": int(statistics.quantiles(lens, n=4)[2]) if N >= 4 else None},
                 title_with_digit_pct=pct(sum(bool(re.search(r"\d", r["title"])) for r in recs), N),
                 title_with_brackets_pct=pct(sum(bool(re.search(r"[(\[]", r["title"])) for r in recs), N),
                 title_with_question_pct=pct(sum("?" in r["title"] for r in recs), N),
                 title_with_hashtag_pct=pd(lambda r: hashtags_in(r["title"])),
                 videos_with_tags_pct=pd(lambda r: r["tags"]),
                 videos_with_hashtags_pct=pd(lambda r: r["hashtags"]),
                 hashtags_per_video_median=med([len(r["hashtags"]) for r in D]),
                 tags_per_video_median=med([len(r["tags"]) for r in D if r["tags"]]),
                 description_len_median=med([len(r["description"]) for r in D]),
                 description_with_chapters_pct=pd(lambda r: len(re.findall(r"(?m)^\s*\d{1,2}:\d{2}", r["description"])) >= 3),
                 description_with_links_pct=pd(lambda r: "http" in r["description"]),
                 views_median=med([r["views"] for r in recs]), views_per_day_median=med([r["views_per_day"] for r in recs]),
                 subs_known=sum(r["subs"] is not None for r in recs), detail_pct=pct(ND, N),
                 shorts_tag_pct=pd(lambda r: "#shorts" in r["hashtags"]))
    return dict(stats=stats, title_terms=title_terms, tags=tags, hashtags=hashtags, hashtags_in_title=dict(in_title.most_common(10)),
                keyword_candidates=cands[:25])


def outliers(recs):
    """Ролики, которые набрали намного больше, чем обычно у такого канала: смотреть, чем они упакованы."""
    out = []
    for r in recs:
        if r["subs"]: out.append((r["views"] / max(r["subs"], 1000), r))
    out.sort(key=lambda x: -x[0])
    return [dict(id=r["id"], title=r["title"], channel=r["channel"], views=r["views"], subs=r["subs"], ratio=round(x, 1)) for x, r in out[:5]]


# ───────────────────────── отчёт ─────────────────────────
def fmt(n): return "—" if n is None else f"{n:,}".replace(",", " ")
def esc(x): return str(x).replace("|", "¦")
def pc(x): return "—" if x is None else f"{x}%"


def write_md(data, path):
    s = data["stats"]; L = []
    L += [f"# SEO-исследование: {', '.join(data['queries'])}", "",
          f"Формат: **{data['format']}** · язык `{data['lang']}` · страна `{data['region']}` · источник конкурентов: **{data['source']}** · {data['date']}",
          f"Разобрано роликов: **{s['videos']}** (с деталями: {s['videos_with_details']}; из {data['candidates_seen']} найденных). "
          + ("Данных мало: пороги «встречается минимум в 2 роликах» не применялись, выводы слабые." if s["min_df"] == 1 else ""),
          ("⚠ **Теги, описания и даты получены только у %d%% роликов** (YouTube не отдаёт их без входа). Теги и хештеги ниже неполные: нужен ключ YouTube Data API или `--cookies-from-browser chrome`." % s["detail_pct"]) if s["detail_pct"] < 60 else "", "",
          "> Это наблюдения: что используют ролики из топа выдачи. Причину успеха они не доказывают. "
          "Берём только то, что подтверждено данными. Если термина здесь нет, его нет и в пакете.", ""]
    L += ["## Что люди набирают (подсказки YouTube)", "", "| Фраза | Ранг | Запросов | Названий конкурентов со всеми словами |", "|---|---|---|---|"]
    for c in data["keyword_candidates"][:15]:
        L.append(f"| {c['phrase']} | {c['rank']} | {c['asked_in']} | {c['titles_with_all_words']} |")
    if data["vidiq"]:
        L += ["", "## vidIQ: ключевые слова", "", "Данные из vidIQ MCP (методика оценок на странице vidIQ не раскрыта; это оценки сервиса, не факт).", "",
              "| Фраза | Объём | Конкуренция | Оценка |", "|---|---|---|---|"]
        L += [f"| {esc(v['phrase'])} | {fmt(v['volume']) if isinstance(v['volume'], int) else (v['volume'] if v['volume'] is not None else '—')} | {v['competition'] if v['competition'] is not None else '—'} | {v['score'] if v['score'] is not None else '—'} |" for v in data["vidiq"][:30]]
    L += ["", "## Названия конкурентов", "",
          f"- Длина: медиана **{s['title_len']['median']}**, середина выборки {s['title_len']['p25']}–{s['title_len']['p75']} символов",
          f"- С цифрой: {s['title_with_digit_pct']}% · со скобками: {s['title_with_brackets_pct']}% · с вопросом: {s['title_with_question_pct']}% · с хештегом: {pc(s['title_with_hashtag_pct'])}", "",
          "| Слова в названиях | Роликов | Медиана просмотров |", "|---|---|---|"]
    for t in data["title_terms"][:25]: L.append(f"| {t['term']} | {t['df']} | {fmt(t['median_views'])} |")
    L += ["", "## Теги", "", f"Теги есть у {pc(s['videos_with_tags_pct'])} роликов (медиана {s['tags_per_video_median']}).", ""]
    if data["tags"]:
        L += ["| Тег | Роликов | Медиана просмотров |", "|---|---|---|"] + [f"| {t['term']} | {t['df']} | {fmt(t['median_views'])} |" for t in data["tags"][:25]]
    else: L.append("Повторяющихся тегов не нашлось (теги часто скрыты или не заданы).")
    L += ["", "## Хештеги", "", f"Хештеги есть у {pc(s['videos_with_hashtags_pct'])} роликов (медиана {s['hashtags_per_video_median']}); `#shorts` — у {pc(s['shorts_tag_pct'])}.", ""]
    if data["hashtags"]:
        L += ["| Хештег | Роликов | Медиана просмотров |", "|---|---|---|"] + [f"| {t['term']} | {t['df']} | {fmt(t['median_views'])} |" for t in data["hashtags"][:25]]
    else: L.append("Повторяющихся хештегов не нашлось.")
    L += ["", "## Описания", "",
          f"- Длина: медиана **{fmt(s['description_len_median'])}** символов", f"- С главами (≥ 3 таймкода): {pc(s['description_with_chapters_pct'])} · со ссылками: {pc(s['description_with_links_pct'])}", "",
          "## Конкуренты", "", "| Название | Канал | Просмотры | Подписчики | В день | Теги |", "|---|---|---|---|---|---|"]
    for r in data["competitors"]:
        L.append(f"| {esc(r['title'][:70])} | {esc(r['channel'][:24])} | {fmt(r['views'])} | {fmt(r['subs'])} | {fmt(r['views_per_day'])} | {len(r['tags'])} |")
    if data["outliers"]:
        L += ["", "## Выбивающиеся (просмотров намного больше, чем подписчиков)", "", "| Название | Просмотры | Подписчики | Во сколько раз |", "|---|---|---|---|"]
        L += [f"| {esc(o['title'][:70])} | {fmt(o['views'])} | {fmt(o['subs'])} | ×{o['ratio']} |" for o in data["outliers"]]
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    log(f"режим: {'API (ключ найден)' if KEY else 'yt-dlp (ключа нет, это нормально)'}")
    sugg = collect_suggestions(A.queries); log(f"подсказок: {len(sugg)}")
    recs, source, seen = gather(A.queries)
    if len(recs) < 5: log(f"⚠ подходящих конкурентов всего {len(recs)}: выводы будут слабыми (попробуй другой запрос, --format long или --min-views 0)")
    an = analyze(recs, sugg)
    comp = [{k: r[k] for k in ("id", "title", "channel", "subs", "views", "likes", "comments", "published", "duration", "age_days", "views_per_day", "tags", "hashtags")} for r in recs]
    data = dict(queries=A.queries, format=A.format, lang=A.lang, region=A.region, source=source, date=date.today().isoformat(),
                candidates_seen=seen, vidiq=VIDIQ, suggestions=sugg, competitors=comp, outliers=outliers(recs), **an)
    (OUT / "seo_research.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_md(data, OUT / "seo_research.md")
    print(f"готово: {OUT/'seo_research.md'}  ·  {OUT/'seo_research.json'}  ·  конкурентов {len(recs)}, источник {source}")


main()
