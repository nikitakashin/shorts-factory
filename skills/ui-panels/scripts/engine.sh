#!/usr/bin/env bash
# engine.sh — разворачивает/обновляет движок UI-панелей в $GFX_HOME (по умолчанию ~/Movies/Shorts/_gfx).
# Код (src/, tools/, index.html) всегда берётся из скилла, node_modules и шрифты ставятся один раз.
# Печатает путь к движку последней строкой.
set -euo pipefail
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
GFX="${GFX_HOME:-$HOME/Movies/Shorts/_gfx}"
mkdir -p "$GFX"
rsync -a --exclude node_modules --exclude 'assets/media' --exclude 'assets/panels.js' --exclude renders --exclude scratch "$SKILL/engine/" "$GFX/"
[ -f "$GFX/assets/panels.js" ] || cp "$SKILL/examples/showcase.panels.js" "$GFX/assets/panels.js" 2>/dev/null || true
bash "$GFX/tools/setup.sh" >&2
echo "$GFX"
