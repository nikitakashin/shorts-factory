#!/usr/bin/env bash
# Идемпотентная установка/починка движка: зависимости, шрифты (Inter, JetBrains Mono: latin+cyrillic), GSAP.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d node_modules/hyperframes ] || npm install --no-fund --no-audit --loglevel=error
mkdir -p assets/js assets/fonts assets/media renders scratch
[ -f assets/js/gsap.min.js ] || cp node_modules/gsap/dist/gsap.min.js assets/js/
for w in 400 500 600 700 800; do for s in latin cyrillic; do
  f=inter-$s-$w-normal.woff2; [ -f assets/fonts/$f ] || cp node_modules/@fontsource/inter/files/$f assets/fonts/
done; done
for s in latin cyrillic; do
  f=inter-$s-400-italic.woff2; [ -f assets/fonts/$f ] || cp node_modules/@fontsource/inter/files/$f assets/fonts/
  for w in 400 700; do f=jetbrains-mono-$s-$w-normal.woff2; [ -f assets/fonts/$f ] || cp node_modules/@fontsource/jetbrains-mono/files/$f assets/fonts/; done
done
