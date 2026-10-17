#!/usr/bin/env bash
# master.sh <workdir> <out.mp4> [out_audio.wav] — голос+SFX → двухпроходный loudnorm −14 LUFS → лимитер → мукс → проверка.
# Внимание (zsh/bash): переменную перед двоеточием пиши как ${II}, а не $II: — в zsh `$II:l` это модификатор lowercase.
# alimiter обязательно с level=disabled, иначе он сам поднимает уровень до 0 dBFS.
set -euo pipefail
WD="$1"; OUT="$2"; AUDIO_OUT="${3:-}"
IN=(-i "$WD/voice.wav" -i "$WD/sfx.wav")
MIX="[0][1]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11"
# фоновая музыка (music_bed.py → music.wav): приглушается за голосом (sidechain), NO_MUSIC=1 — без неё (2026-10-14)
if [ -f "$WD/music.wav" ] && [ -z "${NO_MUSIC:-}" ]; then
  IN+=(-i "$WD/music.wav")
  MIX="[0]asplit=2[v][sc];[2][sc]sidechaincompress=threshold=0.03:ratio=2.5:attack=20:release=400[m];[v][1][m]amix=inputs=3:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11"
  echo "музыка: $(python3 -c "import json;print(json.load(open('$WD/music.json'))['track'])" 2>/dev/null || echo music.wav)"
fi
J=$(ffmpeg -hide_banner "${IN[@]}" -filter_complex "${MIX}:print_format=json" -f null - 2>&1 | sed -n '/{/,/}/p')
II=$(echo "$J" | python3 -c "import json,sys;d=json.load(sys.stdin);print(f\"measured_I={d['input_i']}:measured_TP={d['input_tp']}:measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}:offset={d['target_offset']}\")")
ffmpeg -v error -y "${IN[@]}" -filter_complex "${MIX}:${II}:linear=true,alimiter=limit=0.7:level=disabled[a]" -map "[a]" -ar 48000 "$WD/mix.wav"
ffmpeg -v error -y -i "$WD/video.mp4" -i "$WD/mix.wav" -map 0:v -map 1:a -c:v copy -c:a aac -b:a 256k -shortest -movflags +faststart "$OUT"
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate -of compact "$OUT"
ffmpeg -hide_banner -i "$OUT" -af ebur128=peak=true -f null - 2>&1 | grep -E "^\s+(I:|Peak:)"
ffmpeg -v error -y -i "$OUT" -vf "fps=1,scale=216:-1,tile=10x6" -frames:v 1 "$WD/out_sheet.jpg"
echo "лист кадров результата (1 кадр/сек): $WD/out_sheet.jpg"
[ -n "$AUDIO_OUT" ] && cp "$WD/mix.wav" "$AUDIO_OUT" && echo "звук отдельно: $AUDIO_OUT"; true
