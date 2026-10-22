#!/usr/bin/env python3
"""vidiq_cache.py — кэш ответов vidIQ keyword_research и учёт кредитов.

  vidiq_cache.py get "<ключ>" [--out $WD/seo/vidiq.json] [--days 30]   есть свежий ответ → кладёт в --out, код 0; нет → код 1
  vidiq_cache.py put "<ключ>" <ответ.json|.txt> [--out $WD/seo/vidiq.json]  сохранить ответ MCP (JSON или весь текст ответа)
  vidiq_cache.py usage                                                  сколько вызовов в текущем цикле кредитов

Бесплатный тариф — 150 кредитов в месяц, keyword_research стоит 5: ровно 30 вызовов, один на ролик при ролике в день
(2026-10-22). Поэтому перед вызовом — `get`: темы повторяются, и повторный ключ из кэша кредитов не тратит.
Ответ переводится в формат research.py --vidiq-keywords: [{phrase, volume (запросов в месяц), volume_display, competition,
score, growth_pct, country_volume}]. volume 0 у vidIQ значит «меньше 750 в месяц», а не ноль — volume_display это сохраняет.
Кэш: ~/.cache/yt-seo/vidiq/<ключ>.json."""
import argparse, datetime as dt, json, re, sys
from pathlib import Path

CACHE = Path.home() / ".cache/yt-seo/vidiq"


def flat(s): return re.sub(r"[^0-9a-zа-яё]+", "-", s.lower().replace("ё", "е")).strip("-")


def parse(raw):
    """Ответ MCP: чистый JSON или текст с блоком «Keyword data (JSON):»."""
    raw = raw.strip()
    try: return json.loads(raw)
    except Exception: pass
    i = raw.find("{")
    if i < 0: sys.exit("в ответе vidIQ нет JSON")
    return json.JSONDecoder().raw_decode(raw[i:])[0]


def normalize(d):
    rows = ([d["seedKeyword"]] if d.get("seedKeyword") else []) + list(d.get("relatedKeywords") or []) \
        + list(d.get("matchingTerms") or []) + list(d.get("questions") or [])
    out = []
    for r in rows:
        ph = (r.get("keyword") or "").strip().lower()
        if not ph: continue
        out.append(dict(phrase=ph, volume=r.get("estimatedMonthlySearch"), volume_display=r.get("monthlySearchesDisplay"),
                        competition=r.get("competition"), score=round(r["overall"], 1) if r.get("overall") is not None else None,
                        growth_pct=round(r["searchDemandGrowthPct"]) if r.get("searchDemandGrowthPct") is not None else None,
                        country_volume=r.get("countryVolume")))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["get", "put", "usage"]); ap.add_argument("args", nargs="*")
    ap.add_argument("--out"); ap.add_argument("--days", type=int, default=30)
    A = ap.parse_args(); CACHE.mkdir(parents=True, exist_ok=True)
    if A.cmd == "usage":
        items = [json.loads(p.read_text(encoding="utf-8")) for p in CACHE.glob("*.json")]
        since = dt.date.today() - dt.timedelta(days=30)
        recent = sorted((i for i in items if dt.date.fromisoformat(i["date"]) >= since), key=lambda i: i["date"])
        for i in recent: print(f"{i['date']}  {i['keyword']}")
        print(f"вызовов за 30 дней: {len(recent)} из ~30 (по 5 кредитов; точный остаток — vidiq_balance, бесплатно)"); return
    if not A.args: sys.exit("нужен ключ")
    kw = A.args[0].strip().lower(); f = CACHE / f"{flat(kw)}.json"
    if A.cmd == "get":
        if not f.is_file(): print(f"нет в кэше: «{kw}» — нужен вызов vidiq_keyword_research (5 кредитов)"); sys.exit(1)
        c = json.loads(f.read_text(encoding="utf-8")); age = (dt.date.today() - dt.date.fromisoformat(c["date"])).days
        if age > A.days: print(f"в кэше от {c['date']} ({age} дн.) — устарел, нужен новый вызов"); sys.exit(1)
        if A.out: Path(A.out).parent.mkdir(parents=True, exist_ok=True); Path(A.out).write_text(json.dumps(c["rows"], ensure_ascii=False, indent=1))
        print(f"из кэша от {c['date']}: «{kw}», фраз {len(c['rows'])}" + (f" → {A.out}" if A.out else "")); return
    if len(A.args) < 2: sys.exit("put \"<ключ>\" <ответ.json|.txt>")
    d = parse(Path(A.args[1]).read_text(encoding="utf-8")); rows = normalize(d)
    if not rows: sys.exit("в ответе нет ни одной фразы")
    f.write_text(json.dumps(dict(keyword=kw, date=dt.date.today().isoformat(), country=d.get("country"), mode=d.get("mode"), rows=rows, raw=d),
                            ensure_ascii=False, indent=1))
    if A.out: Path(A.out).parent.mkdir(parents=True, exist_ok=True); Path(A.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"сохранено: «{kw}», фраз {len(rows)}" + (f" → {A.out}" if A.out else ""))


if __name__ == "__main__":
    main()
