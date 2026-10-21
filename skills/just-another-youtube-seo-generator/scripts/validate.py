# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""validate.py seo.json [--research seo/seo_research.json] [--transcript words_out.json|текст.txt] [--md youtube.md]
                       [--title-max 100] [--strict]

Проверяет SEO-пакет, который написал агент, и не пропускает выдумки.

1. Жёсткие лимиты YouTube: название ≤ 100, описание ≤ 5000 байт, теги ≤ 500 символов суммарно,
   хештегов ≤ 15 (если больше, YouTube игнорирует их все).
2. Привязка к данным. Каждый хештег и тег должен найтись в seo_research.json (подсказки поиска, теги и хештеги роликов
   из топа, слова в их названиях) или в расшифровке ролика. Иначе это выдумка, и скрипт возвращает ошибку.
   Главный ключ должен быть в названии и в первых 150 символах описания. Числа и годы тоже должны откуда-то браться.
   Хештеги проверяются все: из списка, из названия и из описания.
3. Правила проекта (adhd-shorts/references/package.md, автор 2026-10-17): название до 100 символов вместе с 2–3 хештегами
   в конце, главный ключ в первых ~40 символах (столько видно в ленте), #shorts только в описании; поисковый вариант
   названия, вопрос в закрепе.

--md пишет youtube.md в формате references/package.md скилла adhd-shorts (счётчик N/100 у названий, хештеги строкой
под описанием) плюс таблицу «Основание» (откуда взят каждый термин).
Код возврата 1, если есть ошибки (предупреждения его не меняют; --strict делает предупреждения ошибками).

seo.json:
{"format": "shorts" | "long", "primary_keyword": "fl studio на mac",
 "title": "...", "title_variants": [{"text": "...", "angle": "search|intrigue|result|emotion"}],
 "description": "...", "hashtags": ["#flstudio"], "tags": ["fl studio mac"],
 "pinned_comment": "...", "notes": ["..."]}"""
import argparse, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ytseo_text import tokens, stems, flat, hashtags_in, ngrams, STOP

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("seo")
ap.add_argument("--research")
ap.add_argument("--transcript")
ap.add_argument("--md")
ap.add_argument("--title-max", type=int)
ap.add_argument("--strict", action="store_true")
A = ap.parse_args()

seo = json.loads(Path(A.seo).read_text(encoding="utf-8"))
fmt = seo.get("format", "shorts")
TITLE_MAX = A.title_max or 100   # правило автора: до 100 символов вместе с хештегами (это и лимит YouTube)
TITLE_FRONT = 40                 # столько символов названия видно в ленте: главный ключ должен быть здесь
R = json.loads(Path(A.research).read_text(encoding="utf-8")) if A.research else None

issues = []           # (уровень, код, сообщение)
def err(c, m): issues.append(("ошибка", c, m))
def warn(c, m): issues.append(("предупреждение", c, m))


# ───────────────────────── источники данных ─────────────────────────
search = {}           # flat → подпись источника
phrases = []          # (подпись, множество основ слов) для частичного совпадения
def add_search(text, label, with_ngrams=False):
    tk = tokens(text)
    if not tk: return
    search.setdefault(flat(text), label)
    phrases.append((label, {t for t in stems(text) if t not in STOP}))
    if with_ngrams:
        for n in (1, 2, 3, 4):
            for g in ngrams(tk, n): search.setdefault(flat(" ".join(g)), label)

if R:
    for s in R["suggestions"]: add_search(s["phrase"], f"подсказка поиска «{s['phrase']}»", True)
    for v in R.get("vidiq", []): add_search(v["phrase"], f"vidIQ «{v['phrase']}» (объём {v['volume']}, конкуренция {v['competition']})", True)
    for c in R["competitors"]:
        for t in c["tags"]: add_search(t, f"тег ролика «{c['title'][:40]}»")
        for h in c["hashtags"]: add_search(h.lstrip("#"), f"хештег ролика «{c['title'][:40]}»")
        add_search(c["title"], f"название «{c['title'][:40]}»", True)
    for group, name in (("tags", "тег"), ("hashtags", "хештег")):
        for t in R[group]: search[flat(t["term"])] = f"{name} в {t['df']} роликах топа (медиана {t['median_views']} просм.)"
    for t in R["title_terms"]: search[flat(t["term"])] = f"слова в {t['df']} названиях топа"

transcript_flat, transcript_tokens, transcript_stems = set(), set(), set()
if A.transcript:
    p = Path(A.transcript); raw = p.read_text(encoding="utf-8")
    try:
        d = json.loads(raw); words = d.get("words", d) if isinstance(d, dict) else d
        text = " ".join(w.get("w", "") if isinstance(w, dict) else str(w) for w in words)
    except Exception: text = raw
    tk = tokens(text); transcript_tokens = set(tk); transcript_stems = set(stems(text))
    for n in (1, 2, 3, 4):
        for g in ngrams(tk, n): transcript_flat.add(flat(" ".join(g)))


def ground(term, allow_partial=False):
    """→ (вердикт, откуда). Вердикты: search / partial / transcript / none."""
    f = flat(term.lstrip("#"))
    if not f: return "none", "пусто"
    if term.lower() == "#shorts" and fmt == "shorts": return "service", "служебный хештег формата (правило проекта)"
    if f in search: return "search", search[f]
    if allow_partial:
        need = {t for t in stems(term) if t not in STOP}
        if need:
            for label, ph in phrases:
                if need <= ph: return "partial", label
    if f in transcript_flat: return "transcript", "сказано в ролике"
    need = {t for t in stems(term) if t not in STOP}
    if len(need) > 1 and need <= transcript_stems:   # «сопроводительное письмо» ← «в сопроводительном письме» (2026-10-22)
        return "transcript", "сказано в ролике (в другой форме)"
    return "none", "нигде не найден"


# ───────────────────────── проверки ─────────────────────────
title = seo.get("title", ""); desc = seo.get("description", "")
tags = [t.strip() for t in seo.get("tags", []) if t.strip()]
tagsH = seo.get("hashtags", [])
kw = seo.get("primary_keyword", "").strip()

if not title: err("title", "нет названия")
if len(title) > 100: err("title_len", f"название {len(title)} символов, лимит YouTube 100 (вместе с хештегами)")
elif len(title) > TITLE_MAX: warn("title_len", f"название {len(title)} символов, задано --title-max {TITLE_MAX}")
title_h = hashtags_in(title)
if not 2 <= len(title_h) <= 3: warn("title_hashtags", f"в названии {len(title_h)} хештегов, правило проекта — 2–3 в конце названия")
if "#shorts" in title_h: warn("title_shorts", "#shorts в названии тратит символы и ничего не говорит о теме: его место в описании")
if len(desc.encode("utf-8")) > 5000: err("desc_len", f"описание {len(desc.encode('utf-8'))} байт, лимит YouTube 5000")
if len(desc) < 150 and fmt == "long": warn("desc_short", "описание длинного видео короче 150 символов: ключи и суть не поместятся")

tag_len = sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)
if tag_len > 500: err("tags_len", f"теги занимают ≈ {tag_len} символов, лимит YouTube 500 (пробел в теге считается с кавычками)")
if len({flat(t) for t in tags}) < len(tags): warn("tags_dup", "в тегах есть повторы")

all_h = list(dict.fromkeys([h.lower() for h in tagsH] + hashtags_in(title) + hashtags_in(desc)))
if len(all_h) > 15: err("hashtags_cnt", f"хештегов {len(all_h)} (в названии, описании и списке вместе): при > 15 YouTube игнорирует все")
for h in tagsH:
    if not re.fullmatch(r"#[\w]+", h, flags=re.UNICODE): err("hashtag_form", f"{h!r}: хештег пишется слитно, начинается с #, без пробелов и знаков")

if not kw: err("keyword", "не задан primary_keyword")
else:
    need = {t for t in stems(kw) if t not in STOP}
    if need and not need <= set(stems(title)): err("keyword_title", f"главный ключ «{kw}» не входит в название")
    elif need and not need <= set(stems(title[:TITLE_FRONT])): warn("keyword_front", f"главный ключ «{kw}» не помещается в первые {TITLE_FRONT} символов названия (видимая часть в ленте)")
    if need and not need <= set(stems(desc[:150])): err("keyword_desc", f"главного ключа «{kw}» нет в первых 150 символах описания (сниппет)")
    if R:
        v, why = ground(kw, allow_partial=False)
        if v == "none": err("keyword_ground", f"главный ключ «{kw}» не найден в подсказках поиска и названиях топа. Возьми фразу из seo_research.md")
        elif v == "transcript": warn("keyword_ground", f"главный ключ «{kw}» есть только в расшифровке, поиск его не подтверждает")

if desc.strip().lower() == title.strip().lower() or desc.strip().lower().startswith(title.strip().lower() + "\n"):
    warn("desc_dup", "первая строка описания повторяет название")

variants = seo.get("title_variants", [])
if variants and not any(v.get("angle") == "search" for v in variants): warn("variants", "нет поискового варианта названия (angle: search): ясного, с ключом в начале")
if seo.get("pinned_comment") and "?" not in seo["pinned_comment"]: warn("pinned", "закреплённый комментарий без вопроса: он должен вызывать ответы")

evidence = []         # для таблицы «Основание»
if R and (R["stats"].get("detail_pct") or 0) < 60:
    warn("thin_data", f"теги и хештеги конкурентов получены только у {R['stats'].get('detail_pct') or 0}% роликов: подтверждение идёт по подсказкам поиска и названиям топа. Для полной картины нужен ключ API или --cookies-from-browser")
if R or A.transcript:
    all_tagsH = list(dict.fromkeys(tagsH + [h for h in hashtags_in(title) + hashtags_in(desc) if h not in {x.lower() for x in tagsH}]))
    for kind, items, partial in (("хештег", all_tagsH, False), ("тег", tags, True)):
        for it in items:
            v, why = ground(it, partial); evidence.append((kind, it, v, why))
            if v == "none": err(f"{kind}_ground", f"{kind} {it!r} нигде не подтверждён: ни в данных поиска, ни в расшифровке. Убери или замени")
            elif v == "transcript": warn(f"{kind}_ground", f"{kind} {it!r} есть только в расшифровке, поиск его не подтверждает")
            elif v == "partial": warn(f"{kind}_ground", f"{kind} {it!r} подтверждён только частично ({why})")
    # числа и годы: не придумывать
    known_nums = set(); nums_src = " ".join([c["title"] for c in R["competitors"]] + [s["phrase"] for s in R["suggestions"]]) if R else ""
    known_nums |= set(re.findall(r"\d+", nums_src)) | {t for t in transcript_tokens if t.isdigit()}
    no_tc = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", title + " " + desc)   # таймкоды глав — не факты
    for m in sorted(set(re.findall(r"\d+", no_tc)) - known_nums):
        if len(m) >= 2: warn("number", f"число {m} из названия или описания не найдено ни в расшифровке, ни в данных поиска")
else:
    warn("no_data", "нет ни --research, ни --transcript: привязка к данным не проверена, проверены только лимиты")

if any((seo.get("extra_hashtags") or {}).values()):
    warn("extra_hashtags", "extra_hashtags (TikTok/Reels) в youtube.md не выводятся: автор публикует только на YouTube")

# ───────────────────────── отчёт ─────────────────────────
errors = [i for i in issues if i[0] == "ошибка"]; warns = [i for i in issues if i[0] != "ошибка"]
for lvl, code, msg in issues: print(f"{'✗' if lvl == 'ошибка' else '!'} [{code}] {msg}")
print(f"\n{len(errors)} ошибок, {len(warns)} предупреждений" + (" — пакет прошёл проверку" if not errors else ""))

VERDICT = {"service": "⚙ служебный", "search": "✅ данные поиска", "partial": "◐ частично", "transcript": "🗣 только расшифровка", "unchecked": "— не проверено", "none": "✗ нет"}
if A.md:
    cnt = lambda s: f"({len(s)}/100)"
    L = [f"# {title}   {cnt(title)}", "", "## Варианты названия (каждый ≤ 100 символов вместе с хештегами)"]
    for i, v in enumerate(variants, 1): L.append(f"{i}. {v['text']}   {cnt(v['text'])}" + (f"   ← {v['angle']}" if v.get("angle") else ""))
    L += ["", "## Описание", desc.strip(), ""]
    if tagsH and not all(h.lower() in hashtags_in(desc) for h in tagsH): L += [" ".join(tagsH), ""]
    L += ["## Теги YouTube (через запятую)", ", ".join(tags), "", "## Закреплённый комментарий", seo.get("pinned_comment", ""), ""]
    if evidence:
        L += ["## Основание", "", f"Главный ключ: **{kw}**. Исследование: {', '.join(R['queries']) + ' · ' + R['source'] + ' · ' + R['date'] if R else 'нет'}", "",
              "| Что | Термин | Вердикт | Откуда |", "|---|---|---|---|"]
        L += [f"| {k} | {t} | {VERDICT[v]} | {str(w).replace('|', '¦')} |" for k, t, v, w in evidence]
        L.append("")
    notes = seo.get("notes", [])
    L += ["## Заметки"] + [f"- {n}" for n in notes] + [""]
    Path(A.md).write_text("\n".join(L), encoding="utf-8"); print(f"записано: {A.md}")

sys.exit(1 if errors or (A.strict and warns) else 0)
