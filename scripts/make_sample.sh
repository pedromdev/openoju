#!/usr/bin/env bash
set -euo pipefail

OUT="${1:-/tmp/opencode/openoju/moving.mp4}"
mkdir -p "$(dirname "$OUT")"

ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "color=c=0x202020:s=640x360:r=10:d=20" \
  -f lavfi -i "color=c=white:s=80x80:r=10:d=20" \
  -filter_complex "[0:v][1:v]overlay=x='mod(t*120,400)':y=150:shortest=1" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p "$OUT"

echo "$OUT"
