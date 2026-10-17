# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "soundfile", "pillow", "librosa"]
# ///
"""sound_check.py <workdir> <short.mp4> — проверка звука по ГОТОВОМУ MP4 (не по WAV) перед сдачей.

Я не слышу звук (пост автора 2026-10-17: «всё измеряй… не утверждай, что звук получился хорошим»), поэтому:
  1. Громкость экспорта: ebur128 по MP4 — интегральная (цель −14 LUFS), true peak (≤ −1 dBTP), и то же в МОНО
     (динамик телефона): потеря громкости в моно > 1.5 дБ или участки с отрицательной корреляцией L/R — противофаза.
  2. Доли (если был music_bed.py --sync → beats.json): где на сетке стоят входы графики и переходы (Δ до ближайшей доли),
     и проверка сетки по самому экспорту — сдвиг, при котором атаки ниже 120 Гц ложатся на доли (должен быть ≈ 0).
  3. Лист «кадр до · кадр после · волна ±0.6 с» на каждый звук/серию звуков → qa/sfx_sheet.jpg (открыть и посмотреть,
     что звук стоит на событии в кадре, а не мимо).
  4. Пять таймкодов для проверки в наушниках — где риск больше всего (громкий звук поверх речи, хуже всего попавший в долю
     переход, противофаза, старт, концовка). При сдаче автору — этот список, а не «звук хороший».
Пишет <workdir>/qa/sound.md, печатает его."""
import json, re, subprocess, sys, tempfile
from pathlib import Path
import numpy as np, soundfile as sf
from PIL import Image, ImageDraw, ImageFont

WD, MP4 = Path(sys.argv[1]), Path(sys.argv[2]); OUT = WD / "qa"; OUT.mkdir(exist_ok=True)
FD = Path.home() / ".cache/content-factory/fonts/Inter.ttf"
def fnt(sz): return ImageFont.truetype(str(FD), sz) if FD.exists() else ImageFont.load_default()
def mmss(t): return f"{int(t // 60)}:{t % 60:04.1f}"

def ebur(args):
    o = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(MP4)] + args + ["-f", "null", "-"], capture_output=True, text=True).stderr
    I = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", o)[-1]); TP = re.findall(r"Peak:\s+(-?[\d.inf]+) dBFS", o)
    return I, (float(TP[-1]) if TP and TP[-1] not in ("-inf",) else -99.0)
I_st, TP_st = ebur(["-af", "ebur128=peak=true"])
I_mo, TP_mo = ebur(["-af", "pan=mono|c0=0.5*c0+0.5*c1,ebur128=peak=true"])
with tempfile.NamedTemporaryFile(suffix=".wav") as tf:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(MP4), "-vn", "-ac", "2", "-ar", "48000", tf.name], check=True)
    x, SR = sf.read(tf.name)
dur = len(x) / SR; mono = x.mean(1)
issues, cands = [], []                     # cands: (риск, t, причина) для «послушай в наушниках»

# ---------- 1. громкость и моно ----------
if abs(I_st + 14) > 1.0: issues.append(f"громкость {I_st:.1f} LUFS — цель −14 ±1")
if TP_st > -1.0: issues.append(f"пик {TP_st:.1f} dBFS — выше −1, после пережатия на телефоне может хрипеть")
# ebur128 складывает мощности каналов: одинаковые L и R в моно (L+R)/2 по определению на 3 дБ тише стерео, некоррелированные — на 6,
# противофаза — проваливаются. Поэтому «потеря в моно» = разница сверх 3 дБ (2026-10-17: первая версия приняла норму 3.2 дБ за противофазу)
MONO_LOSS = (I_st - I_mo) - 3.0
if MONO_LOSS > 1.5: issues.append(f"в моно теряется {MONO_LOSS:.1f} дБ сверх нормы — широкое стерео или противофаза")
win = int(0.5 * SR); bad_corr = []
for k in range(len(x) // win):
    L, R = x[k * win:(k + 1) * win, 0], x[k * win:(k + 1) * win, 1]
    if np.sqrt(np.mean((L + R) ** 2) / 4) < 10 ** (-40 / 20) or L.std() < 1e-6 or R.std() < 1e-6: continue
    c = float(np.corrcoef(L, R)[0, 1])
    if c < 0.0: bad_corr.append((k * 0.5, c))
for t, c in bad_corr[:5]: issues.append(f"{mmss(t)}: корреляция L/R {c:+.2f} — в моно этот звук провалится"); cands.append(("mono", 3.0, t + 0.25, f"противофаза L/R {c:+.2f} — включи телефон в моно / один наушник"))

# ---------- 2. доли ----------
sync_lines = []
if (WD / "beats.json").exists():
    B = json.load(open(WD / "beats.json")); bt = np.array(B["beats"]); dn = np.array(B["downbeats"])
    evs = []
    if (WD / "layout.json").exists():
        for m in json.load(open(WD / "layout.json")).get("modes", []): evs += [(m["s"], f"вход {m['mode']}"), (m["e"], f"выход {m['mode']}")]
    if (WD / "transitions.json").exists():           # переход проверяем по его «ключевому» моменту (вход — начало, выход — конец)
        trs = {round(x_.get("key", x_["t"]), 2): x_["kind"] for x_ in json.load(open(WD / "transitions.json"))}
        evs = [(t, nm + (f" ({trs[round(t, 2)]})" if round(t, 2) in trs else "")) for t, nm in evs] + [(t, f"переход {k}") for t, k in trs.items() if all(abs(t - e[0]) > 0.02 for e in evs)]
    on_beat = 0; worst = None
    for t, nm in sorted(set(evs)):
        if not (0.1 < t < dur - 0.1) or not len(bt): continue
        d = float(bt[np.argmin(np.abs(bt - t))] - t); onb = abs(d) <= 0.03; on_beat += onb
        sync_lines.append(f"{mmss(t)}  {nm}: до доли {d:+.3f} с" + ("" if onb else "  (на слове — доля дальше окна подтяжки)"))
        if not onb and (worst is None or abs(d) > abs(worst[0])): worst = (d, t, nm)
    if worst: cands.append(("beat", 1.0, worst[1], f"{worst[2]} не на доле ({worst[0]:+.2f} с) — не звучит «мимо ритма»?"))
    sync_lines.insert(0, f"на долях {on_beat} из {len(sync_lines)} событий графики (остальные оставлены на словах)")
    # сетка по музыкальной дорожке во времени ролика (music.wav): в миксе ниже 120 Гц доминирует голос, а не бочка
    # (первая версия мерила по миксу и показала «сдвиг 141 мс»). Атаки бочки — ударная часть (HPSS) ниже 120 Гц.
    import scipy.signal as ss, librosa
    mw, msr = librosa.load(str(WD / "music.wav"), sr=22050, mono=True) if (WD / "music.wav").exists() else (mono, SR)
    low = ss.sosfiltfilt(ss.butter(4, 120, "lowpass", fs=msr, output="sos"), librosa.effects.percussive(mw, margin=3.0) if (WD / "music.wav").exists() else mw); hop = 128
    env = librosa.feature.rms(y=low, frame_length=1024, hop_length=hop)[0]; on = np.maximum(0, np.diff(env, prepend=env[0])); ft = np.arange(len(on)) * hop / msr
    P = 60 / B["bpm"]; shifts = np.arange(-P / 2, P / 2, 0.005)
    sc = [float(np.interp(bt + s, ft, on).sum()) for s in shifts]; best = float(shifts[int(np.argmax(sc))])
    sync_lines.insert(0, f"сетка {B['bpm']} BPM, трек «{B['track']}» с {B['offset']:.2f} с; в музыкальной дорожке ролика удары бочки ложатся на доли со сдвигом {best * 1000:+.0f} мс")
    if abs(best) > 0.03: issues.append(f"в дорожке музыки сетка долей уехала на {best * 1000:+.0f} мс — проверь beats_check.png и offset трека")

# ---------- 3. лист «кадр до · после · волна» на каждый звук ----------
S = sorted(json.load(open(WD / "sfx_list.json"))["sounds"], key=lambda s: s["t"]) if (WD / "sfx_list.json").exists() else []
groups = []
for s in S:
    if groups and s["t"] < max(g["t"] + min(g.get("dur", 0.3), 1.0) for g in groups[-1]): groups[-1].append(s)
    else: groups.append([s])
voice = sf.read(WD / "voice.wav")[0] if (WD / "voice.wav").exists() else None
if voice is not None and voice.ndim > 1: voice = voice.mean(1)
words = json.load(open(WD / "words_out.json")) if (WD / "words_out.json").exists() else []
SFXW = sf.read(WD / "sfx.wav")[0] if (WD / "sfx.wav").exists() else None
if SFXW is not None and SFXW.ndim > 1: SFXW = SFXW.mean(1)
def rms_db(a): return 20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-9) if len(a) else -120
def frame(t, w=180):
    r = subprocess.run(["ffmpeg", "-v", "quiet", "-ss", f"{max(0, t):.3f}", "-i", str(MP4), "-frames:v", "1", "-vf", f"scale={w}:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    try:
        import io; return Image.open(io.BytesIO(r.stdout)).convert("RGB")
    except Exception: return Image.new("RGB", (w, 320), (40, 0, 0))
tiles = []
for g in groups[:16]:
    t = g[0]["t"]; names = ", ".join(sorted({str(s.get("spec")) for s in g}))
    a, b = int(max(0, t - 0.6) * SR), int(min(dur, t + 0.6) * SR); seg = mono[a:b]
    tile = Image.new("RGB", (760, 340), (20, 20, 24)); d = ImageDraw.Draw(tile)
    tile.paste(frame(t - 0.1), (8, 8)); tile.paste(frame(t + 0.12), (196, 8))
    W_, H_, x0, y0 = 360, 240, 392, 40; d.rectangle([x0, y0, x0 + W_, y0 + H_], fill=(30, 30, 38))
    if len(seg):
        cols = np.array_split(seg, W_)
        for k, c in enumerate(cols):
            v = min(1, np.abs(c).max() * 1.2) if len(c) else 0; d.line([x0 + k, y0 + H_ / 2 - v * H_ / 2, x0 + k, y0 + H_ / 2 + v * H_ / 2], fill=(90, 190, 255))
    if (WD / "beats.json").exists():
        for bb in json.load(open(WD / "beats.json"))["beats"]:
            if t - 0.6 <= bb <= t + 0.6: xx = x0 + (bb - (t - 0.6)) / 1.2 * W_; d.line([xx, y0, xx, y0 + H_], fill=(60, 200, 110), width=1)
    xc = x0 + W_ * 0.5; d.line([xc, y0 - 4, xc, y0 + H_ + 4], fill=(255, 70, 70), width=3)
    d.text((8, 300), f"{mmss(t)}  {names}", font=fnt(20), fill=(255, 255, 255)); d.text((x0, 10), "−0.6 с … +0.6 с, красная — звук, зелёные — доли", font=fnt(14), fill=(160, 160, 170))
    d.text((8, 322), "кадр за 0.1 с до · через 0.12 с после", font=fnt(13), fill=(150, 150, 160))
    tiles.append(tile)
    # риск для «послушай»: громкость звука к речи рядом и звук поверх слова
    if voice is not None:
        # уровень звука — из sfx.wav, той же стадии, что voice.wav (до мастеринга); микс MP4 с голосом на −24 сравнивать нельзя
        vs = len(voice) / dur; sp = rms_db(voice[int(max(0, t - 1) * vs):int(min(dur, t + 1) * vs)])
        sfx_db = rms_db(SFXW[int(t * vs):int(min(dur, t + 0.3) * vs)]) if SFXW is not None else -120
        on_word = next((w["w"].strip() for w in words if w["s"] - 0.05 <= t <= w["e"]), None)
        if on_word: cands.append(("word", sfx_db - sp, t, f"звук «{names}» поверх слова «{on_word}» ({sfx_db - sp:+.0f} дБ к речи) — слово разборчиво?"))
        if any("Meme" in s.get("file", "") for s in g): cands.append(("meme", sfx_db - sp, t, f"мем «{Path(g[0]['file']).stem}» ({sfx_db - sp:+.0f} дБ к речи) — не громче голоса?"))
if tiles:
    sh = Image.new("RGB", (2 * 768, ((len(tiles) + 1) // 2) * 348), (0, 0, 0))
    for k, im in enumerate(tiles): sh.paste(im, ((k % 2) * 768, (k // 2) * 348))
    sh.save(OUT / "sfx_sheet.jpg", quality=85)

# ---------- 4. пять мест для наушников ----------
# пять РАЗНЫХ рисков: старт, концовка, самый громкий звук на слове, худший промах по доле / противофаза, самый громкий мем
cands += [("start", 9, 0.0, "старт: первые 2 с — громкость, хук, звук на кадре 0"), ("end", 9, max(0, dur - 3), "концовка: звук концовки и затухание музыки")]
pick = []
for cat in ("start", "end", "mono", "word", "beat", "meme", "word"):
    for c in sorted([c for c in cands if c[0] == cat], key=lambda c: -c[1]):
        if len(pick) < 5 and all(abs(c[2] - p[2]) > 2.0 for p in pick): pick.append(c); break
for c in sorted(cands, key=lambda c: -c[1]):            # кандидаты рядом друг с другом отсеялись — добрать до 5 с шагом ≥ 1 с
    if len(pick) < 5 and all(abs(c[2] - p[2]) > 1.0 for p in pick): pick.append(c)
pick.sort(key=lambda p: p[2])

md = [f"# Звук: {MP4.name}", "", "Звук я не слышу — ниже замеры по экспортированному MP4 и места, которые надо послушать.", "",
      f"- Громкость: **{I_st:.1f} LUFS**, true peak {TP_st:.1f} dBFS (цель −14 LUFS, пик ≤ −1).",
      f"- В моно (динамик телефона): {I_mo:.1f} LUFS, пик {TP_mo:.1f}; потеря сверх нормальных 3 дБ — {MONO_LOSS:+.1f} дБ" + (" (ок)" if MONO_LOSS <= 1.5 else " ← широкое стерео/противофаза") + ".",
      f"- Участков с противофазой L/R: {len(bad_corr)}.", ""]
if sync_lines: md += ["## Доли и графика"] + [f"- {l}" for l in sync_lines] + [""]
md += [f"## Лист звуков: `qa/sfx_sheet.jpg` ({len(tiles)} шт.)", "", "## Проверь в наушниках — 5 мест"] + [f"{i + 1}. **{mmss(t)}** — {why}" for i, (c_, r, t, why) in enumerate(pick)]
md += ["", "## Замечания — " + (str(len(issues)) if issues else "нет")] + [f"- {x}" for x in issues]
(OUT / "sound.md").write_text("\n".join(md) + "\n"); print("\n".join(md)); print("→", OUT / "sound.md")
