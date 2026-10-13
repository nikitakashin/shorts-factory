# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""build_voice.py <workdir> — собирает голосовую дорожку по <workdir>/edl.json.

Перед нарезкой края планов выравниваются по реальной энергии голоса (snap), потому что концы
слов у Whisper и «на глаз» почти всегда раньше настоящих: тихие окончания русских слов («-то»,
«-ла», безударные гласные) затухают дольше. Так «за 3500 на авито» превращалось в «на ави…»
(2026-10-07: 6 из 14 внешних склеек резали речь). Правила:
  конец плана — дотянуть вперёд до первой тишины ≥150 мс (смыкание перед «т/к/п» внутри слова короче), не дальше
    +1.2 с; хвосты длиннее 0.4 с помечаются «⚠ длинный хвост»; если речь идёт
    сплошняком (намеренный разрез посреди фразы), резать в самой тихой точке около b и пометить «⚠ проверь»;
  начало плана — отступить назад до тишины, но не дальше −0.25 с; иначе — в самую тихую точку;
  внутренние склейки (b == a следующего, джамп-зум без разрыва звука) не трогаются; "snap": false у плана — тоже.
Тишина = ниже шумового пола +8 дБ (начала) / +11 дБ (концы) по окнам 10 мс. Исходные границы сохраняются в edl_out.json как a0/b0.

Дальше каждый план режется из исходника, ускоряется atempo (тон не меняется), обрезается ровно
под целое число кадров (иначе за 20 склеек звук уплывает от картинки), края — микрофейды 8/15 мс.
b-roll (broll: true) идёт без звука. "voice_fx": "anull" — без обработки (голос чистят Adobe и цепочка).
Пишет voice.wav и edl_out.json (+ n кадров и f0 у каждого плана)."""
import json, os, subprocess, sys
import numpy as np, soundfile as sf

WD = sys.argv[1]
E = json.load(open(f"{WD}/edl.json")); FPS = E.get("fps", 60); SP = E.get("speed", 1.15)
os.makedirs(f"{WD}/aseg", exist_ok=True)

# --- энергия голоса исходника (16 кГц моно из probe.sh; если нет — извлечь) ---
A16 = f"{WD}/audio.wav"
if not os.path.exists(A16):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", E["src"], "-vn", "-ac", "1", "-ar", "16000", A16], check=True)
x, sr = sf.read(A16)
if x.ndim > 1: x = x.mean(1)
hop = sr // 100; nfr = len(x) // hop
db = 20 * np.log10(np.sqrt((x[: nfr * hop].reshape(nfr, hop) ** 2).mean(1)) + 1e-9)
FLOOR = np.percentile(db, 10)
quiet = db < FLOOR + 8          # для начал: всё, что громче пола на 8 дБ, — уже звук
quiet_end = db < FLOOR + 11     # для концов: фон комнаты/ноутбука держится на +8…+10 дБ и иначе «тянет» хвост
                                # (2026-10-09: после «видео» +0.65 с шума и щелчков); тихое «о» в «авито» ≈ +15 дБ
# окна по 10 мс. Конец слова — тишина ≥150 мс: смыкание перед «т/к/п» внутри слова даёт тишину до ~110 мс
# («ави|то»: 33.75–33.82 тишина, потом хлопок «т» и тихое «о» до 34.6). Вперёд ≤1.2 с, назад ≤0.25 с (тишина ≥70 мс).
SIL_END, SIL_START, EXT_END, EXT_START, LONG_TAIL = 15, 7, 120, 25, 0.40

def snap_end(b):
    k = int(round(b * 100))
    for j in range(k, min(nfr - SIL_END, k + EXT_END)):
        if quiet_end[j:j + SIL_END].all(): return (j + 3) / 100, False  # +30 мс воздуха после хвоста
    lo, hi = max(0, k - 8), min(nfr, k + 12)
    return (lo + int(np.argmin(db[lo:hi]))) / 100, True                  # сплошная речь: самая тихая точка

def snap_start(a):
    k = int(round(a * 100))
    for j in range(k, max(SIL_START, k - EXT_START), -1):
        if quiet[j - SIL_START:j].all(): return max(0, (j - 3) / 100), False
    lo, hi = max(0, k - 12), min(nfr, k + 8)
    return (lo + int(np.argmin(db[lo:hi]))) / 100, True

segs = E["segs"]; report = []
for s in segs: s.setdefault("a0", s["a"]); s.setdefault("b0", s["b"])
for i, s in enumerate(segs):
    if s.get("broll") or s.get("snap") is False: continue
    prev = segs[i - 1] if i else None; nxt = segs[i + 1] if i + 1 < len(segs) else None
    if not (prev and not prev.get("broll") and abs(prev["b0"] - s["a0"]) < 0.02):
        a, warn = snap_start(s["a0"])
        if abs(a - s["a0"]) >= 0.01: report.append(f"  #{i:02d} начало {s['a0']:7.2f} → {a:7.2f}{'  ⚠ резали посреди речи — проверь' if warn else ''}")
        s["a"] = a
    if not (nxt and not nxt.get("broll") and abs(nxt["a0"] - s["b0"]) < 0.02):
        b, warn = snap_end(s["b0"])
        if nxt and not nxt.get("broll") and b > nxt["a0"] - 0.02 and nxt["a0"] > s["b0"]:
            b = min(b, nxt["a0"] - 0.02)   # не залезать в следующий план, если он идёт сразу за этим в исходнике
        if abs(b - s["b0"]) >= 0.01:
            note = "  ⚠ резали посреди речи — проверь" if warn else ("  ⚠ длинный хвост — проверь, нет ли «э-э»/вдоха" if b - s["b0"] > LONG_TAIL else "")
            report.append(f"  #{i:02d} конец  {s['b0']:7.2f} → {b:7.2f}  ({b - s['b0']:+.2f} с){note}")
        s["b"] = b
if report: print("Склейки выровнены по голосу:\n" + "\n".join(report))

total = 0; lst = []
def atempo(sp):  # atempo принимает 0.5..2 — длинные множители раскладываем в цепочку
    parts = []
    while sp > 2: parts.append(2.0); sp /= 2
    parts.append(sp); return ",".join(f"atempo={p:.4f}" for p in parts)
for i, s in enumerate(segs):
    sp = s.get("sp", SP); n = round((s["b"] - s["a"]) / sp * FPS); out = n / FPS
    s.update(n=n, f0=total, sp_eff=sp)
    f = f"{WD}/aseg/{i:02d}.wav"
    if s.get("broll") and not s.get("keep_audio"):
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{out}", f]
    else:
        vol = f",volume={s['vol']}" if "vol" in s else ""
        af = f"{atempo(sp)},apad,atrim=0:{out},afade=t=in:d=0.008,afade=t=out:st={max(0, out-0.015)}:d=0.015{vol}"
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{s['a']}", "-t", f"{s['b']-s['a']+0.05}", "-i", E["src"],
               "-vn", "-af", af, "-ar", "48000", "-ac", "2", f]
    subprocess.run(cmd, check=True)
    lst.append(f"file '{os.path.abspath(f)}'"); total += n
open(f"{WD}/aseg/list.txt", "w").write("\n".join(lst))
chain = E.get("voice_fx", "highpass=f=80,afftdn=nf=-30,acompressor=threshold=-22dB:ratio=3:attack=5:release=90:makeup=2")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{WD}/aseg/list.txt", "-af", chain, f"{WD}/voice.wav"], check=True)
E["frames"] = total; E["fps"] = FPS
json.dump(E, open(f"{WD}/edl_out.json", "w"), indent=1, ensure_ascii=False)
print(f"{len(segs)} планов, {total} кадров = {total/FPS:.2f} сек")
for i, s in enumerate(segs):
    print(f"  #{i:02d} src {s['a']:7.2f}-{s['b']:7.2f} → out {s['f0']/FPS:6.2f}s  z={s.get('z',1)}{'  B-ROLL x'+str(s['sp_eff']) if s.get('broll') else ''}")
