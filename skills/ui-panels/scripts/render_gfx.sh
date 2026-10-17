#!/usr/bin/env bash
# render_gfx.sh <workdir> [--snap t1,t2,...] — panels.json → panels.js/layout.json → gfx.mp4 (1080×1920, или 1312×1080 при "canvas": "landscape"; без звука).
#   --snap  вместо рендера — кадры в моменты t (секунды выхода) и лист <workdir>/gfx_snaps/sheet.jpg
# Env: FPS (60 — как у шортса; 30 — вдвое быстрее), TOTAL (длина, если нет edl_out.json), GFX_HOME (движок).
set -euo pipefail
S="$(cd "$(dirname "$0")" && pwd)"
WD="$(cd "$1" && pwd)"; shift
GFX="$(bash "$S/engine.sh" | tail -1)"
# движок общий (~/Movies/Shorts/_gfx): два рендера сразу подменяют друг другу panels.js посреди рендера —
# 2026-10-14 в графику полного видео попали терминалы из соседней главы. Поэтому — по очереди.
until mkdir "$GFX/.render.lock" 2>/dev/null; do
  if [ -f "$GFX/.render.lock/pid" ] && ! kill -0 "$(cat "$GFX/.render.lock/pid")" 2>/dev/null; then rm -rf "$GFX/.render.lock"; continue; fi
  sleep 5
done
echo $$ > "$GFX/.render.lock/pid"; trap 'rm -rf "$GFX/.render.lock"' EXIT
python3 "$S/panels.py" "$WD" ${TOTAL:+--total "$TOTAL"}
cp "$WD/panels.js" "$GFX/assets/panels.js"
# горизонтальный холст: размер композиции задаётся в index.html (движок копируется из скилла заново при каждом запуске)
if grep -q '"canvas": "landscape"' "$WD/panels.js"; then
  sed -i '' 's/width=1080, height=1920/width=1312, height=1080/; s/data-width="1080" data-height="1920"/data-width="1312" data-height="1080"/' "$GFX/index.html"
fi
mkdir -p "$GFX/assets/media"
if [ -d "$WD/media" ]; then rsync -a --delete "$WD/media/" "$GFX/assets/media/"; else find "$GFX/assets/media" -mindepth 1 -delete; fi
cd "$GFX"
node tools/probe.mjs --comp index.html --sync-duration | grep -v "^data-duration" || true
if [ "${1:-}" = "--snap" ]; then
  node tools/snap.mjs --comp index.html --at "$2" --out "$WD/gfx_snaps" --cols "${COLS:-6}" --w "${SNAP_W:-300}"
  exit 0
fi
export DO_NOT_TRACK=1 HYPERFRAMES_SKIP_SKILLS=1
npx hyperframes render . -o "$WD/gfx.mp4" -f "${FPS:-60}" --crf "${GFX_CRF:-10}" --quiet   # crf 10: графика потом пережимается ещё 2–4 раза
ffprobe -v error -show_entries stream=width,height,r_frame_rate:format=duration -of compact "$WD/gfx.mp4"
echo "→ $WD/gfx.mp4"
