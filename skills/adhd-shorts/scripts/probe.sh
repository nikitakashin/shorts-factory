#!/usr/bin/env bash
# probe.sh <video> <workdir> — параметры исходника, audio.wav (16 кГц моно для Whisper) и контактный лист sheet.jpg (кадр каждые N сек).
set -euo pipefail
SRC="$1"; WD="$2"; STEP="${3:-4}"
mkdir -p "$WD"
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height,r_frame_rate:stream_side_data=rotation -of compact "$SRC"
ffmpeg -v error -y -i "$SRC" -vn -ac 1 -ar 16000 "$WD/audio.wav"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SRC")
N=$(python3 -c "import math;print(math.ceil($DUR/$STEP))"); ROWS=$(( (N + 9) / 10 ))
ffmpeg -v error -y -i "$SRC" -vf "fps=1/$STEP,scale=216:-1,tile=10x$ROWS" -frames:v 1 "$WD/sheet.jpg"
echo "sheet: $WD/sheet.jpg — ячейка i (слева направо, сверху вниз) ≈ ${STEP}*i сек"
