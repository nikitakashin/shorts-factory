#!/usr/bin/env bash
# render_gfx.sh <workdir> [--snap t1,t2,...] — panels.json → panels.js/layout.json → gfx.mp4 (1080×1920, или 1312×1080 при "canvas": "landscape"; без звука).
#   --snap  вместо рендера — кадры в моменты t (секунды выхода) и лист <workdir>/gfx_snaps/sheet.jpg
# Env: FPS (60 — как у шортса; 30 — вдвое быстрее), TOTAL (длина, если нет edl_out.json), GFX_HOME (движок).
set -euo pipefail
S="$(cd "$(dirname "$0")" && pwd)"
WD="$(cd "$1" && pwd)"; shift
GFX="$(bash "$S/engine.sh" | tail -1)"
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
npx hyperframes render . -o "$WD/gfx.mp4" -f "${FPS:-60}" --quiet
ffprobe -v error -show_entries stream=width,height,r_frame_rate:format=duration -of compact "$WD/gfx.mp4"
echo "→ $WD/gfx.mp4"
