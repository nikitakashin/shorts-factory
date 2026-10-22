#!/usr/bin/env bash
# new_short.sh <video> <slug> [канал] — папка ролика ~/Movies/Shorts/<канал>/<YYYY-MM-DD>-<slug>/ и осмотр исходника.
# Канал — папка канала (ai-native, syamych…): третий аргумент, иначе $SHORTS_CHANNEL, иначе ai-native.
# На виду только результат (<папка>.mp4, audio.wav, youtube.md, thumbnail-prompt.md, thumb-frames/, status.txt),
# всё промежуточное — в скрытой .work/ (можно удалить после публикации).
set -euo pipefail
SRC="$1"; SLUG="$2"; ROOT="${SHORTS_ROOT:-$HOME/Movies/Shorts}"; CHANNEL="${3:-${SHORTS_CHANNEL:-ai-native}}"
D="$ROOT/$CHANNEL/$(date +%F)-$SLUG"; WD="$D/.work"
mkdir -p "$WD" "$D/thumb-frames"
echo "$SRC" > "$WD/source.txt"
# Исходник — жёсткой ссылкой внутрь проекта: место не занимает (тот же том), а переименование/удаление
# оригинала в Загрузках («… готов.mp4») её не ломает. Если другой том — копия. В edl.json src = этот путь.
EXT="${SRC##*.}"; LOCAL="$WD/source.$EXT"
[ -e "$LOCAL" ] || ln "$SRC" "$LOCAL" 2>/dev/null || cp "$SRC" "$LOCAL"
echo "ИСХОДНИК: $LOCAL"
bash "$(dirname "$0")/probe.sh" "$LOCAL" "$WD" 4
python3 "$(dirname "$0")/status.py" set "$D" work >/dev/null   # статус «в работе» + жёлтая метка Finder
echo "ПАПКА: $D"; echo "WD: $WD"
