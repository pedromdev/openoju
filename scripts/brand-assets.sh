#!/usr/bin/env bash
# Gera os assets de marca do OpenOju a partir dos SVGs-fonte.
# Requisitos: ImageMagick 6 (`convert`) e a fonte Inter instalada.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRAND="$ROOT/docs/assets/brand"
PUBLIC="$ROOT/frontend/public"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

INK="#0B1220"
SLATE="#1E293B"
EMERALD="#34D399"
AMBER="#FBBF24"
MIST="#E2E8F0"
MUTED="#94A3B8"

render() { # render <svg> <size> <out>
  convert -background none -density 768 "$1" -resize "${2}x${2}" "$3"
}

mkdir -p "$PUBLIC"

# Ícones do aplicativo (fundo navy arredondado)
render "$BRAND/logo-app.svg" 16  "$TMP/16.png"
render "$BRAND/logo-app.svg" 32  "$TMP/32.png"
render "$BRAND/logo-app.svg" 48  "$TMP/48.png"
render "$BRAND/logo-app.svg" 180 "$TMP/180.png"
render "$BRAND/logo-app.svg" 192 "$TMP/192.png"
render "$BRAND/logo-app.svg" 512 "$TMP/512.png"

cp "$TMP/16.png"  "$PUBLIC/favicon-16x16.png"
cp "$TMP/32.png"  "$PUBLIC/favicon-32x32.png"
cp "$TMP/180.png" "$PUBLIC/apple-touch-icon.png"
cp "$TMP/192.png" "$PUBLIC/icon-192.png"
cp "$TMP/512.png" "$PUBLIC/icon-512.png"
convert "$TMP/16.png" "$TMP/32.png" "$TMP/48.png" "$PUBLIC/favicon.ico"

# Maskable: fundo navy de borda a borda, símbolo dentro de 80% centrais
cat > "$TMP/maskable.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" fill="#0B1220"/>
  <g transform="translate(6.4 6.4) scale(0.8)">
    <path d="M46.98 31.21A15 15 0 1 1 32.79 17.02" fill="none" stroke="#34D399" stroke-width="6" stroke-linecap="round"/>
    <circle cx="43.67" cy="20.33" r="4" fill="#FBBF24"/>
  </g>
</svg>
SVG
render "$TMP/maskable.svg" 512 "$PUBLIC/icon-maskable-512.png"

# Safari pinned tab
cp "$BRAND/mask-icon.svg" "$PUBLIC/mask-icon.svg"

# Lockups em PNG (texto composto com Inter, sem depender do renderizador SVG)
render "$BRAND/logo-app.svg" 176 "$TMP/mark176.png"
convert -size 960x240 xc:none \
  "$TMP/mark176.png" -geometry +0+32 -composite \
  -stroke none -font Inter-SemiBold -pointsize 86 -fill "$MIST" -gravity northwest -annotate +200+38 "OpenOju" \
  -font Inter-Regular -pointsize 30 -fill "$MUTED" -gravity northwest -annotate +202+168 "Olhos abertos para o que a câmera viu" \
  "$BRAND/logo-lockup.png"

render "$BRAND/logo-app.svg" 240 "$TMP/mark240.png"
convert -size 800x560 xc:none \
  "$TMP/mark240.png" -gravity north -geometry +0+40 -composite \
  -stroke none -font Inter-SemiBold -pointsize 112 -fill "$MIST" -gravity north -annotate +0+300 "OpenOju" \
  -font Inter-Regular -pointsize 32 -fill "$MUTED" -gravity north -annotate +0+470 "Open eyes on what the camera saw" \
  "$BRAND/logo-lockup-stacked.png"

# Card do README (fundo navy, funciona em tema claro e escuro)
render "$BRAND/logo-app.svg" 64 "$TMP/mark64.png"
convert -size 680x168 xc:none \
  -fill "$INK" -stroke "$SLATE" -strokewidth 2 -draw "roundrectangle 1,1 679,167 32,32" \
  "$TMP/mark64.png" -geometry +28+28 -composite \
  -stroke none -font Inter-SemiBold -pointsize 56 -fill "$MIST" -gravity northwest -annotate +168+36 "OpenOju" \
  -font Inter-Regular -pointsize 21 -fill "$MUTED" -gravity northwest -annotate +170+112 "Olhos abertos para o que a câmera viu" \
  "$BRAND/logo-lockup-card.png"

# Open Graph 1200x630
convert "$BRAND/logo-lockup-stacked.png" -resize 420x "$TMP/stack420.png"
convert -size 1200x630 "xc:$INK" \
  -stroke "$SLATE" -strokewidth 1 -fill none \
  -draw "path 'M 0,48 L 1200,48 M 0,96 L 1200,96 M 0,144 L 1200,144 M 0,192 L 1200,192 M 0,240 L 1200,240 M 0,288 L 1200,288 M 0,336 L 1200,336 M 0,384 L 1200,384 M 0,432 L 1200,432 M 0,480 L 1200,480 M 0,528 L 1200,528 M 0,576 L 1200,576'" \
  "$TMP/stack420.png" -gravity north -geometry +0+70 -composite \
  -font Inter-Regular -pointsize 26 -fill "$MUTED" -gravity north -annotate +0+500 "github.com/pedromdev/openoju" \
  -pointsize 20 -annotate +0+548 "open-source  ·  self-hosted  ·  Apache-2.0" \
  "$PUBLIC/og-image.png"

# Social preview do GitHub 1280x640
convert -size 1280x640 "xc:$INK" \
  "$TMP/stack420.png" -gravity center -geometry +0-40 -composite \
  -font Inter-Regular -pointsize 24 -fill "$MUTED" -gravity center -annotate +0+210 "github.com/pedromdev/openoju" \
  "$BRAND/social-preview.png"

identify "$PUBLIC/favicon.ico" "$PUBLIC/favicon-16x16.png" "$PUBLIC/icon-maskable-512.png" \
  "$PUBLIC/og-image.png" "$BRAND/social-preview.png" "$BRAND/logo-lockup.png"
