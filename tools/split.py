#!/usr/bin/env python3
"""
Split Boom One "multi" WAV files into individual samples at silence boundaries.

Each source WAV contains several takes separated by ~1s+ of true digital silence.
Short intra-take gaps (double-hits, click sequences, lulls) stay inside a sample.

Strategy:
  - detect silence with ffmpeg silencedetect (noise=-60dB, min 50ms)
  - a silence region >= SEPARATOR_S seconds (and not leading/trailing padding)
    marks a boundary between samples
  - leading/trailing silence is trimmed
  - cut is done in pure Python on the raw PCM (bit-perfect, no re-encode)
"""
import os, sys, json, subprocess, wave, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "Update 26.03")   # распакованная BOOM ONE (поменяй через --src)
OUT  = os.path.join(HERE, "Split")          # куда класть нарезанные сэмплы (--out)
SUFFIX = "_B00M_ONE"
SEPARATOR_S = 0.86
NOISE_DB = "-60dB"
MIN_SIL = 0.05
EDGE_EPS = 0.02  # seconds from 0/duration to count as leading/trailing

def ffprobe_duration(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1", path],
                       capture_output=True)
    return float(p.stdout.decode().strip())

def silence_regions(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                        "-af", f"silencedetect=noise={NOISE_DB}:d={MIN_SIL}",
                        "-f", "null", "-"], capture_output=True)
    out = p.stderr.decode("utf-8", "replace")
    starts, ends = [], []
    for line in out.splitlines():
        if "silence_start" in line:
            starts.append(float(line.split("silence_start:")[1].split()[0]))
        elif "silence_end" in line:
            ends.append(float(line.split("silence_end:")[1].split()[0]))
    return [(s, e) for s, e in zip(starts, ends)]

def compute_segments(sil, duration):
    """Return list of (start_s, end_s) for each sample."""
    lead = sil[0] if sil and sil[0][0] < EDGE_EPS else None
    trail = sil[-1] if sil and (duration - sil[-1][1]) < EDGE_EPS else None
    seps = [(s, e) for s, e in sil
            if (e - s) >= SEPARATOR_S and (s, e) != lead and (s, e) != trail]

    segs = []
    cursor = lead[1] if lead else 0.0
    for s, e in seps:
        if s > cursor:
            segs.append((cursor, s))
        cursor = e
    end = trail[0] if trail else duration
    if end > cursor:
        segs.append((cursor, end))

    # Drop trailing/leading sub-0.3s artifacts (e.g. a click after a long gap
    # at the end of a take). Only when the neighbour is clearly longer.
    while len(segs) >= 2 and (segs[-1][1] - segs[-1][0]) < 0.3 \
            and (segs[-2][1] - segs[-2][0]) > 0.5:
        segs.pop()
    while len(segs) >= 2 and (segs[0][1] - segs[0][0]) < 0.3 \
            and (segs[1][1] - segs[1][0]) > 0.5:
        segs.pop(0)
    return segs

def all_wavs():
    for dirpath, dirs, files in os.walk(ROOT):
        for f in sorted(files):
            if f.lower().endswith(".wav"):
                yield os.path.join(dirpath, f)

def out_name(rel_dir, base, idx, n):
    if base.endswith(SUFFIX):
        base = base[:-len(SUFFIX)]
    if n > 1:
        return os.path.join(rel_dir, f"{base}_{idx:02d}.wav")
    return os.path.join(rel_dir, f"{base}.wav")

def main():
    global ROOT, OUT
    ap = argparse.ArgumentParser(description="Режет WAV из BOOM ONE (по 5–6 дублей в файле) на отдельные сэмплы по тишине")
    ap.add_argument("--src", default=ROOT, help="папка с WAV BOOM ONE (по умолчанию «Update 26.03» рядом со скриптом)")
    ap.add_argument("--out", default=OUT, help="куда сохранить сэмплы (по умолчанию «Split» рядом со скриптом)")
    ap.add_argument("--dry-run", action="store_true", help="только посчитать и записать manifest.json, без нарезки")
    args = ap.parse_args()
    ROOT, OUT = os.path.abspath(os.path.expanduser(args.src)), os.path.abspath(os.path.expanduser(args.out))

    manifest = []
    total_samples = 0
    multi_files = 0
    single_files = 0

    for path in all_wavs():
        rel = os.path.relpath(path, ROOT)
        rel_dir = os.path.dirname(rel)
        base = os.path.splitext(os.path.basename(rel))[0]
        duration = ffprobe_duration(path)
        sil = silence_regions(path)
        segs = compute_segments(sil, duration)

        entries = []
        for i, (s, e) in enumerate(segs):
            n = len(segs)
            oname = out_name(rel_dir, base, i + 1, n)
            entries.append({"in": s, "out": e, "out": e, "file": oname})

        if len(segs) > 1:
            multi_files += 1
        else:
            single_files += 1
        total_samples += len(segs)
        manifest.append({
            "src": rel, "duration": duration, "n": len(segs),
            "segments": [{"in": s, "out": e} for s, e in segs],
        })

    print(f"files: {len(manifest)}  multi: {multi_files}  single: {single_files}")
    print(f"total samples: {total_samples}")

    if args.dry_run:
        mpath = os.path.join(os.path.dirname(OUT), "manifest.json")
        with open(mpath, "w") as f:
            json.dump(manifest, f, indent=1)
        print(f"manifest -> {mpath}")
        return

    # -- actual split --
    for rec in manifest:
        src = os.path.join(ROOT, rec["src"])
        rel_dir = os.path.dirname(rec["src"])
        base = os.path.splitext(os.path.basename(rec["src"]))[0]
        segs = [(x["in"], x["out"]) for x in rec["segments"]]
        n = len(segs)

        with wave.open(src, "rb") as w:
            params = w.getparams()
            rate = w.getframerate()
            frame_bytes = params.sampwidth * params.nchannels
            raw = w.readframes(w.getnframes())

        for i, (s, e) in enumerate(segs):
            a = round(s * rate)
            b = round(e * rate)
            data = raw[a * frame_bytes: b * frame_bytes]
            oname = out_name(rel_dir, base, i + 1, n)
            full = os.path.join(OUT, oname)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with wave.open(full, "wb") as w:
                w.setparams(params)
                w.writeframes(data)

    print("done")

if __name__ == "__main__":
    main()
