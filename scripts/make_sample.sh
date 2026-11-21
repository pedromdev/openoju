#!/usr/bin/env bash
# Gera um vídeo de teste.
#   ./scripts/make_sample.sh [saida] [duracao_s] [resolucao] [bitrate]
#
# Sem bitrate: cena estática com um quadrado em movimento (arquivo pequeno).
# Com bitrate: padrão testsrc2 animado (arquivo grande, para multipart no S3).
set -euo pipefail

OUT="${1:-/tmp/opencode/openoju/moving.mp4}"
DURATION="${2:-20}"
SIZE="${3:-640x360}"
BITRATE="${4:-}"
mkdir -p "$(dirname "$OUT")"

if [[ -n "$BITRATE" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    -f lavfi -i "testsrc2=s=${SIZE}:r=10:d=${DURATION}" \
    -c:v libx264 -preset ultrafast -b:v "$BITRATE" -pix_fmt yuv420p "$OUT"
else
  ffmpeg -y -hide_banner -loglevel error \
    -f lavfi -i "color=c=0x202020:s=${SIZE}:r=10:d=${DURATION}" \
    -f lavfi -i "color=c=white:s=80x80:r=10:d=${DURATION}" \
    -filter_complex "[0:v][1:v]overlay=x='mod(t*120,400)':y=150:shortest=1" \
    -c:v libx264 -preset ultrafast -pix_fmt yuv420p "$OUT"
fi

echo "$OUT"
