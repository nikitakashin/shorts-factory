# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "librosa", "soundfile", "matplotlib"]
# ///
"""beats.py <трек> [--from S] [--dur D] [--png out.png] [--json out.json] — сетка долей трека с проверкой по бочке.

Я не слышу звук, поэтому доли меряются и проверяются картинкой (пост автора 2026-10-17: «librosa ошибочно
синхронизировалась со слабыми долями, сетка уехала на 0.22 с — увидел, только наложив сетку на волну ниже 120 Гц»):
  1. темп: из имени трека («134bpm») — у трэпа librosa часто находит половинный; без подсказки — librosa;
  2. темп (±1.5 BPM от подсказки) и фаза подбираются так, чтобы на доли попало больше всего атак бочки — ударной части
     ниже 120 Гц (808-бас отделён HPSS); grid_shift — насколько сетка librosa мимо этой (None — у librosa неверный темп);
  3. сильная доля (раз в такте 4/4) — фаза, где бочка сильнее всего;
  4. PNG: волна ниже 120 Гц на 4 такта крупно + сетка librosa (красный пунктир) + исправленная (зелёная), сильные
     доли жирные; снизу — обзор всей длины. Этот PNG надо ОТКРЫТЬ и посмотреть: удары бочки должны стоять на зелёных линиях.
Как модуль: analyze(path, t0, dur) → dict(bpm, beats, downbeats, grid_shift, …) — его зовёт music_bed.py --sync."""
import json, re, sys
from pathlib import Path
import numpy as np

def bpm_hint(name):
    m = re.search(r"(\d{2,3})\s*bpm", name, re.I)
    return float(m.group(1)) if m else None

def analyze(path, t0=0.0, dur=None, sr=22050):
    import librosa, scipy.signal as ss
    y, sr = librosa.load(str(path), sr=sr, mono=True, offset=t0, duration=dur)
    hop = 128; T = len(y) / sr
    # В трэпе ниже 120 Гц звучит и бочка, и 808-бас: бас тянется и часто стоит мимо долей. Поэтому атаки ищем в
    # УДАРНОЙ части (HPSS: бочка — удар, 808 — тянущаяся нота) ниже 120 Гц; на графике видно обе
    perc = librosa.effects.percussive(y, margin=3.0)
    lp = ss.butter(4, 120, "lowpass", fs=sr, output="sos")
    low = ss.sosfiltfilt(lp, y); lowp = ss.sosfiltfilt(lp, perc)
    env = librosa.feature.rms(y=lowp, frame_length=1024, hop_length=hop)[0]
    on_low = np.maximum(0, np.diff(env, prepend=env[0])); on_low /= on_low.max() + 1e-9          # атаки бочки
    on_all = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop); on_all /= on_all.max() + 1e-9
    ft = np.arange(len(env)) * hop / sr
    hint = bpm_hint(Path(path).name)
    tempo, lb = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop, start_bpm=hint or 120, units="time")
    tempo = float(np.atleast_1d(tempo)[0])
    # Темп и фаза подбираются вместе по атакам бочки на всей длине: темп из имени бывает округлён (у «lovely» 163 —
    # сетка за 10 с уезжала с ударов), а librosa у трэпа ловит 2/3 или половину темпа («angel»: 89 вместо 134)
    base = hint or tempo
    cands = np.arange(base - 1.5, base + 1.5001, 0.02)
    best = (-1, base, 0.0)
    for bp in cands:
        P_ = 60.0 / bp; phs = np.arange(0, P_, 0.004)
        g = phs[:, None] + np.arange(int(T / P_) + 1)[None, :] * P_; g = np.where(g < T, g, np.nan)
        sc_ = np.nansum(np.interp(np.nan_to_num(g, nan=T + 1), ft, on_low, right=0) + 0.25 * np.interp(np.nan_to_num(g, nan=T + 1), ft, on_all, right=0), axis=1)
        i = int(np.argmax(sc_))
        if sc_[i] > best[0]: best = (float(sc_[i]), float(bp), float(phs[i]))
    _, bpm, ph_best = best; P = 60.0 / bpm
    # насколько сетка librosa расходится с исправленной (если темп librosa тот же; иначе её фаза не имеет смысла)
    same = abs(tempo - bpm) < 3
    off = [((b - ph_best) + P / 2) % P - P / 2 for b in lb] if len(lb) else [0.0]
    shift = -float(np.median(off)) if same else float("nan")
    ph_lib = float(np.median([(b % P) for b in lb])) if len(lb) else 0.0
    ph = ph_best
    beats = np.arange(ph, T, P)
    bar = [float(np.interp(beats[m::4], ft, on_low).sum()) for m in range(4)]; m0 = int(np.argmax(bar))
    downs = beats[m0::4]
    kicks = ft[(on_low > 0.35) & (np.r_[0, np.diff(np.sign(np.diff(on_low))), 0] < 0)]
    return dict(path=str(path), t0=t0, dur=T, bpm=round(bpm, 2), librosa_bpm=round(tempo, 2), hint_bpm=hint, period=P,
                phase_librosa=round(ph_lib, 4), phase_kick=round(ph_best, 4), grid_shift=None if shift != shift else round(shift, 4), librosa_tempo_ok=same,
                beats=[round(float(b), 4) for b in beats], downbeats=[round(float(b), 4) for b in downs],
                lib_beats=[round(float(b), 4) for b in lb], kicks=[round(float(k), 4) for k in kicks[:400]],
                _low=low, _lowp=lowp, _sr=sr, _env=env, _ft=ft, _on=on_low)

def plot(R, png, zoom_from=None, bars=4, title=""):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    low, sr, P = R["_low"], R["_sr"], R["period"]
    e = R["_env"]; first = float(R["_ft"][int(np.argmax(e > 0.3 * e.max()))])          # увеличиваем там, где бит уже играет
    d0 = next((d for d in R["downbeats"] if d >= (zoom_from if zoom_from is not None else max(2.0, first))), R["downbeats"][0] if R["downbeats"] else 0.0)
    a, b = max(0.0, d0 - P * 0.5), min(R["dur"], d0 + P * 4 * bars + P * 0.2)
    fig, ax = plt.subplots(2, 1, figsize=(16, 7), gridspec_kw={"height_ratios": [2.2, 1]})
    i0, i1 = int(a * sr), int(b * sr); t = np.arange(i0, i1) / sr
    ax[0].plot(t, low[i0:i1], color="#bcd2ea", lw=0.6, label="всё < 120 Гц (бочка + 808)")
    ax[0].plot(t, R["_lowp"][i0:i1] * (np.abs(low[i0:i1]).max() / (np.abs(R["_lowp"][i0:i1]).max() + 1e-9)), color="#1a365d", lw=0.8, label="ударная часть < 120 Гц (бочка)")
    ax[0].legend(loc="upper right", fontsize=8)
    for x in R["lib_beats"]:
        if a <= x <= b: ax[0].axvline(x, color="#e53e3e", ls="--", lw=1.0, alpha=0.8)
    for x in R["beats"]:
        if a <= x <= b: ax[0].axvline(x, color="#2f855a", lw=1.2, alpha=0.9)
    for x in R["downbeats"]:
        if a <= x <= b: ax[0].axvline(x, color="#22543d", lw=3)
    ax[0].set_xlim(a, b); ax[0].set_title(f"{title}  волна < 120 Гц, {bars} такта крупно · красный пунктир — librosa, зелёный — исправленная сетка, жирный — сильная доля · "
                                          f"BPM {R['bpm']} (librosa {R['librosa_bpm']}, имя {R['hint_bpm']}) · " + (f"librosa мимо на {R['grid_shift']:+.3f} с" if R['grid_shift'] is not None else "темп librosa неверный — её сетка не годится"), fontsize=10)
    ax[1].plot(R["_ft"], R["_env"], color="#2b6cb0", lw=0.6)
    for x in R["downbeats"]: ax[1].axvline(x, color="#2f855a", lw=0.6, alpha=0.6)
    ax[1].axvspan(a, b, color="#f6e05e", alpha=0.25); ax[1].set_xlim(0, R["dur"]); ax[1].set_title("огибающая < 120 Гц по всей длине, зелёные — сильные доли; жёлтым — увеличенный кусок", fontsize=9)
    plt.tight_layout(); plt.savefig(png, dpi=80); plt.close(fig)

def public(R): return {k: v for k, v in R.items() if not k.startswith("_")}

if __name__ == "__main__":
    a = sys.argv[1:]; path = a[0]
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    R = analyze(path, float(opt("--from", 0)), float(opt("--dur")) if opt("--dur") else None)
    png = opt("--png", str(Path(path).with_suffix("")) + "_beats.png"); plot(R, png, title=Path(path).name)
    if opt("--json"): json.dump(public(R), open(opt("--json"), "w"), ensure_ascii=False)
    gs = f"librosa мимо на {R['grid_shift']:+.3f} с" if R["grid_shift"] is not None else "темп librosa неверный — её сетка не годится"
    print(f"BPM {R['bpm']} (librosa {R['librosa_bpm']}, из имени {R['hint_bpm']}); фаза по бочке {R['phase_kick']:.3f} с; {gs}; "
          f"долей {len(R['beats'])}, сильных {len(R['downbeats'])}\nграфик для проверки → {png}")
