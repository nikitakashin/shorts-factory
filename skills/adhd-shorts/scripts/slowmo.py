# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile"]
# ///
"""slowmo.py <workdir> --word <СЛОВО> [--after <сек>] [--k 0.7] [--ramp 1.2] [--pad 0.05] [--pad-out -0.01] [--zoom 0.15]
Замедление времени к акцентному слову (трендовый эффект, идея автора 2026-10-14).

Как надо (автор): не «одно слово медленно», а «секунды за две до слова всё начинает ПЛАВНО замедляться»:
скорость падает от 1 до k (плавно, ease-in-out) за --ramp секунд перед словом, на самом слове держится k, сразу
после слова — обратно 1. Высота тона НЕ сохраняется: голос тянется вниз, как тормозящая пластинка («хуя-а-акать»);
картинка тормозит вместе со звуком и плавно наезжает (--zoom). Особенно хорошо на мате, в развязке; 1–2 раза на ролик.

Как сделано: на старом таймлайне участок [слово − ramp, конец слова] деформируется непрерывной кривой скорости r(t).
  - voice.wav / voice_raw.wav — пересэмплированы по этой кривой (переменная скорость → тон плавно уходит вниз);
  - edl_out.json — участок порезан на куски по ~0.1 с с постоянной скоростью каждый (кусочно-линейное приближение той
    же кривой, с границами на кадрах и на старых склейках); куски медленнее исходного темпа помечены "slowmo" —
    render.py дорисует им промежуточные кадры (minterpolate);
  - words_out.json — время слов внутри участка по той же кривой, после — со сдвигом.
Работает на готовом голосе (Adobe + цепочка), повторная обработка не нужна. Запускать после subcut.py / reslice_voice.py
и ДО panels.json с числовыми временами (якоря-слова — можно). Повторный запуск — от копий *_before_slowmo.*."""
import argparse, json, re, shutil
from pathlib import Path
import numpy as np, soundfile as sf

ap = argparse.ArgumentParser(); ap.add_argument("wd"); ap.add_argument("--word", required=True); ap.add_argument("--after", type=float, default=0.0)
ap.add_argument("--k", type=float, default=0.7); ap.add_argument("--ramp", type=float, default=1.2)   # автор: 0.5 и 2 с — «слишком рано и слишком сильно»
ap.add_argument("--pad", type=float, default=0.05); ap.add_argument("--pad-out", type=float, default=-0.01)   # хвост: Whisper ставит конец слова впритык к следующему
ap.add_argument("--zoom", type=float, default=0.15)
A = ap.parse_args(); WD = Path(A.wd)
FILES = ["edl_out.json", "words_out.json", "voice.wav", "voice_raw.wav"]
for f in FILES:                                           # первый запуск — запомнить исходник; повторный — начать с него
    p, b = WD / f, WD / f.replace(".", "_before_slowmo.", 1)
    if p.exists() and not b.exists(): shutil.copy(p, b)
    elif b.exists(): shutil.copy(b, p)
E = json.load(open(WD / "edl_out.json")); fps = E["fps"]; W = json.load(open(WD / "words_out.json")); SP0 = E.get("speed", 1.15)
norm = lambda s: re.sub(r"[^\wё]", "", s.lower())
w = next((x for x in sorted(W, key=lambda x: x["s"]) if x["s"] >= A.after and norm(A.word) in norm(x["w"])), None)
if not w: raise SystemExit(f"слово «{A.word}» не найдено после {A.after} с")

# ---------- кривая скорости на СТАРОМ таймлайне ----------
fr = lambda t: round(t * fps) / fps
Tw0, Tw1 = fr(w["s"] - A.pad), fr(w["e"] + A.pad_out); Ta = fr(max(0.0, Tw0 - A.ramp))
def rate(t):
    if t >= Tw0: return A.k
    u = (t - Ta) / max(1e-9, Tw0 - Ta); e = 0.5 - 0.5 * np.cos(np.pi * u)      # ease-in-out
    return 1 - (1 - A.k) * e
dt = 1e-4; tg = np.arange(Ta, Tw1 + dt / 2, dt)                                   # старое время → новое (τ)
tau = np.concatenate([[0.0], np.cumsum(dt / np.array([rate(t) for t in tg[:-1]]))])
D_old, D_new = Tw1 - Ta, tau[-1]
n_new = round(D_new * fps); tau *= (n_new / fps) / D_new; D_new = n_new / fps        # новая длина — целые кадры
t_of = lambda x: np.interp(x, tau, tg)                                           # новое → старое
tau_of = lambda t: np.interp(t, tg, tau)                                         # старое → новое
print(f"«{w['w']}» {w['s']:.2f}–{w['e']:.2f} с: торможение с {Ta:.2f} с, слово ×{1 / A.k:.1f}; участок {D_old:.2f} → {D_new:.2f} с (+{D_new - D_old:.2f})")

# ---------- куски для картинки: ~0.1 с, границы на кадрах и на старых склейках ----------
def seg_at(t):
    return next(i for i, s in enumerate(E["segs"]) if s["f0"] / fps - 1e-6 <= t < (s["f0"] + s["n"]) / fps + 1e-6)
cuts_old = sorted({s["f0"] / fps for s in E["segs"] if Ta < s["f0"] / fps < Tw1})
bnd = set(range(0, n_new + 1, 6)) | {n_new} | {round(tau_of(c) * fps) for c in cuts_old} | {round(tau_of(Tw0) * fps)}
bnd = sorted(b for b in bnd if 0 <= b <= n_new)
i_a, i_b = seg_at(Ta), seg_at(Tw1 - 1e-6)
pieces = []
for j0, j1 in zip(bnd, bnd[1:]):
    if j1 <= j0: continue
    t0 = Ta if j0 == 0 else float(t_of(j0 / fps)); t1 = Tw1 if j1 == n_new else float(t_of(j1 / fps))
    k_ = seg_at((t0 + t1) / 2); s = E["segs"][k_]; s0 = s["f0"] / fps; sp = s.get("sp_eff", SP0)
    a = s["a"] + (max(t0, s0) - s0) * sp; b = s["a"] + (min(t1, s0 + s["n"] / fps) - s0) * sp
    n = j1 - j0; spe = (b - a) / (n / fps); prog0, prog1 = j0 / n_new, j1 / n_new
    z = s.get("z", 1.0); d = {kk: v for kk, v in s.items() if kk not in ("a", "b", "n", "f0", "sp", "sp_eff", "a0", "b0", "z2", "slowmo", "snap")}
    d.update(a=round(a, 4), b=round(b, 4), n=n, sp_eff=spe, sp=spe, z=round(z * (1 + A.zoom * prog0), 4), z2=round(z * (1 + A.zoom * prog1), 4), snap=False)
    if spe < sp * 0.97: d["slowmo"] = round(spe / sp, 3)
    pieces.append(d)
# что остаётся от крайних старых планов
sA, sB = E["segs"][i_a], E["segs"][i_b]
before = E["segs"][:i_a]; after = E["segs"][i_b + 1:]
ja = round((Ta - sA["f0"] / fps) * fps)
if ja > 0: before = before + [dict(sA, b=round(sA["a"] + ja / fps * sA.get("sp_eff", SP0), 4), n=ja)]
jb = round((Tw1 - sB["f0"] / fps) * fps)
if jb < sB["n"]: after = [dict(sB, a=round(sB["a"] + jb / fps * sB.get("sp_eff", SP0), 4), n=sB["n"] - jb)] + after
for d in (before[-1:] + after[:1]): d.pop("z2", None)
segs = before + pieces + after
f = 0
for x in segs: x["f0"] = f; f += x["n"]
E["segs"] = segs; E["frames"] = f; json.dump(E, open(WD / "edl_out.json", "w"), ensure_ascii=False, indent=1)

# ---------- звук: пересэмплирование по кривой (тон уходит вниз вместе со скоростью) ----------
delta = D_new - D_old
for f_ in ("voice.wav", "voice_raw.wav"):
    p = WD / f_
    if not p.exists(): continue
    v, sr = sf.read(p, always_2d=True); x0, x1 = round(Ta * sr), round(Tw1 * sr); L = round(D_new * sr)
    t_new = np.arange(L) / sr; t_old = t_of(t_new) - Ta                       # секунды внутри старого куска
    pos = np.clip(t_old * sr, 0, x1 - x0 - 1); src = v[x0:x1]
    mid = np.stack([np.interp(pos, np.arange(len(src)), src[:, c]) for c in range(v.shape[1])], 1)
    sf.write(p, np.concatenate([v[:x0], mid, v[x1:]]), sr, subtype="PCM_24")
for x in W:
    for key in ("s", "e"):
        t = x[key]
        if t >= Tw1: x[key] = round(t + delta, 3)
        elif t > Ta: x[key] = round(Ta + float(tau_of(t)), 3)
json.dump(W, open(WD / "words_out.json", "w"), ensure_ascii=False, indent=1)
print(f"готово: {len(pieces)} кусков, ролик длиннее на {delta:.2f} с")
