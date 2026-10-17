# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "soundfile", "scipy", "librosa", "matplotlib"]
# ///
"""music_bed.py <workdir> [--track <начало имени>] [--from <сек трека>] [--rel -4 | --bed <LUFS>] [--dir <папка>] [--seed N]
Фоновая музыка для шортса: трек из библиотеки автора (по умолчанию ~/Samples/Background Music,
трэп-биты @ttooxxiinn) → $WD/music.wav той же длины, что voice.wav, на --rel дБ ниже голоса (−4 — как в полном видео, которое автор одобрил 2026-10-14; --bed — абсолютный уровень),
вход 0.3 с, выход 1.2 с. master.sh сам подмешает music.wav и приглушит его за голосом (sidechain).
Без --track — случайный трек (seed — чтобы перезапуск дал тот же). Автор попросил шортсы с фоновой музыкой 2026-10-14.
--sync (2026-10-17): трек начинается с такого такта, чтобы доли совпали с событиями графики (входы/выходы панелей из
layout.json — сначала `python3 <ui-panels>/scripts/panels.py $WD`). Сетка долей — beats.py (темп и фаза по бочке ниже
120 Гц, проверочный PNG $WD/beats_check.png — ОТКРОЙ и убедись, что удары стоят на зелёных линиях). Пишет $WD/beats.json
(доли в времени ролика) — по нему panels.py подтягивает входы панелей к долям (−0.15…+0.06 с от слова)."""
import argparse, json, random, subprocess, sys
from pathlib import Path
import numpy as np, soundfile as sf

ap = argparse.ArgumentParser(); ap.add_argument("wd"); ap.add_argument("--track"); ap.add_argument("--from", dest="t0", type=float, default=0.0)
ap.add_argument("--bed", type=float, default=None); ap.add_argument("--rel", type=float, default=-4.0); ap.add_argument("--dir", default="~/Samples/Background Music"); ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--sync", action="store_true")
A = ap.parse_args(); WD = Path(A.wd); SR = 48000
tracks = sorted(p for p in Path(A.dir).expanduser().iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".flac"))
if not tracks: raise SystemExit(f"нет треков в {A.dir}")
p = next((t for t in tracks if t.name.lower().startswith(A.track.lower())), None) if A.track else random.Random(A.seed).choice(tracks)
if p is None: raise SystemExit(f"нет трека «{A.track}»")
n = sf.info(WD / "voice.wav").frames * SR // sf.info(WD / "voice.wav").samplerate
SNAP = (-0.15, 0.06)                     # окно подтяжки события к доле: картинка чуть раньше слова — хорошо, позже — чуть-чуть
if A.sync:
    sys.path.insert(0, str(Path(__file__).resolve().parent)); import beats as BT
    R = BT.analyze(p); L = n / SR
    ev = []
    if (WD / "layout.json").exists():
        for m in json.load(open(WD / "layout.json")).get("modes", []):
            ev += [(m["s"], 2.0, f"вход {m['mode']}"), (m["e"], 1.0, f"выход {m['mode']}")]
    ev = [e for e in ev if 0.2 < e[0] < L - 0.2]
    # «энергичный» кусок — средняя плотность ударов бочки не ниже 60 % средней по треку (медиана редких ударов ≈ 0,
    # первая версия по медиане отбросила все варианты и всегда брала начало трека)
    env, ft = R["_env"], R["_ft"]; med = float(env.mean())
    def score(o):
        bt = np.array(R["beats"]) - o; dn = np.array(R["downbeats"]) - o; sc = 0.0
        for t, w, _ in ev:
            d = bt - t; ok = d[(d >= SNAP[0]) & (d <= SNAP[1])]
            if len(ok): sc += w * (1.3 if np.any(np.abs(dn - (t + ok[np.argmin(np.abs(ok))])) < 0.01) else 1.0)
            sc += 0.3 * w * float(np.exp(-(np.min(np.abs(d)) / 0.05) ** 2))
        return sc
    # Старт с ровной сильной доли не меняет фазу сетки в ролике (сдвиг на целые такты), поэтому трек стартует на долю
    # секунды раньше сильной доли: φ ∈ [0, P) — доли ролика встают на k·P + φ (вход фейдом 0.3 с, сдвига не слышно)
    P = 60 / R["bpm"]
    bars = [d for d in R["downbeats"] if d - P >= 0 and d + L <= R["dur"] - 0.3 and env[(ft >= d) & (ft <= d + L)].mean() >= 0.6 * med]
    if not bars: bars = [R["downbeats"][0] + 0.0]
    cands = [max(0.0, d - ph) for d in bars[:24] for ph in np.arange(0, P, 0.005)]
    A.t0 = max(cands, key=lambda o: (round(score(o), 3), -o))
    bt = [round(b - A.t0, 4) for b in R["beats"] if 0 <= b - A.t0 <= L]; dn = [round(b - A.t0, 4) for b in R["downbeats"] if 0 <= b - A.t0 <= L]
    BT.plot(R, str(WD / "beats_check.png"), zoom_from=A.t0, title=f"{p.name} с {A.t0:.2f} с")
    rep_ = [dict(t=round(t, 3), what=nm, d_beat=round(min((b - t for b in bt), key=abs), 3) if bt else None,
                 d_snap=round(min((b - t for b in bt if SNAP[0] <= b - t <= SNAP[1]), key=abs, default=float("nan")), 3)) for t, w, nm in ev]
    json.dump(dict(track=p.name, offset=round(A.t0, 4), bpm=R["bpm"], librosa_bpm=R["librosa_bpm"], grid_shift=R["grid_shift"],
                   beats=bt, downbeats=dn, events=rep_, check_png=str(WD / "beats_check.png")), open(WD / "beats.json", "w"), ensure_ascii=False, indent=1)
    inwin = sum(1 for e in rep_ if e["d_snap"] == e["d_snap"])
    print(f"доли: {R['bpm']} BPM (librosa {R['librosa_bpm']}), трек с {A.t0:.2f} с; событий графики {len(rep_)}, "
          f"в окне подтяжки {inwin}; проверь глазами {WD / 'beats_check.png'}")
raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(A.t0), "-i", str(p), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
x = np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)
while len(x) < n:                                                         # трек короче ролика — повтор с перехлёстом 1 с
    xf = SR; x = np.concatenate([x[:-xf], x[-xf:] * np.linspace(1, 0, xf)[:, None] + x[:xf] * np.linspace(0, 1, xf)[:, None], x[xf:]])
x = x[:n].copy()
tmp = WD / "_music_tmp.wav"; sf.write(tmp, x, SR)
o = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(tmp), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
L = float([l for l in o.splitlines() if l.strip().startswith("I:")][-1].split()[1]); tmp.unlink()
# уровень — ОТНОСИТЕЛЬНО голоса: в полном видео подложка стояла на 4 дБ ниже сведённого голоса (−18 при −14), а в шортсе
# голос до мастеринга ~−24 LUFS — абсолютные −18 выходили громче голоса (2026-10-14: «громче, чем договаривались»)
def lufs_of(f):
    o = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float([l for l in o.splitlines() if l.strip().startswith("I:")][-1].split()[1])
target = A.bed if A.bed is not None else lufs_of(WD / "voice.wav") + A.rel
x *= 10 ** ((target - L) / 20)
fi, fo = int(.3 * SR), int(1.2 * SR); x[:fi] *= np.linspace(0, 1, fi)[:, None]; x[-fo:] *= np.linspace(1, 0, fo)[:, None]
sf.write(WD / "music.wav", x, SR)
json.dump({"track": p.name, "from": A.t0, "bed_lufs": round(target, 1), "sync": A.sync}, open(WD / "music.json", "w"), ensure_ascii=False)
print(f"музыка: {p.name} с {A.t0:.1f} с, {target:.1f} LUFS (голос {target - A.rel if A.bed is None else 0:.1f}) → {WD / 'music.wav'}")
