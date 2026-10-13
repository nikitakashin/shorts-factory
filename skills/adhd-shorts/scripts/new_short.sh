#!/usr/bin/env bash
# new_short.sh <video> <slug> — папка ролика ~/Movies/Shorts/<YYYY-MM-DD>-<slug>/ и осмотр исходника.
# На виду только результат (short.mp4, audio.wav, youtube.md, thumbnail-prompt.md, thumb-frames/),
# всё промежуточное — в скрытой .work/ (можно удалить после публикации).
set -euo pipefail
SRC="$1"; SLUG="$2"; ROOT="${SHORTS_ROOT:-$HOME/Movies/Shorts}"
D="$ROOT/$(date +%F)-$SLUG"; WD="$D/.work"
mkdir -p "$WD" "$D/thumb-frames"
echo "$SRC" > "$WD/source.txt"
# Исходник — жёсткой ссылкой внутрь проекта: место не занимает (тот же том), а переименование/удаление
# оригинала в Загрузках («… готов.mp4») её не ломает. Если другой том — копия. В edl.json src = этот путь.
EXT="${SRC##*.}"; LOCAL="$WD/source.$EXT"
[ -e "$LOCAL" ] || ln "$SRC" "$LOCAL" 2>/dev/null || cp "$SRC" "$LOCAL"
echo "ИСХОДНИК: $LOCAL"
bash "$(dirname "$0")/probe.sh" "$LOCAL" "$WD" 4
echo "ПАПКА: $D"; echo "WD: $WD"
