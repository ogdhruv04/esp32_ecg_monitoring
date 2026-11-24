#!/usr/bin/env bash
# README.md -> flex_bringup_kit.pdf (A4). pandoc makes a self-contained HTML page;
# Microsoft Edge on the Windows side prints it (WSL has no Linux browser here).
set -euo pipefail
cd "$(dirname "$0")"
EDGE="/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
WIN=/mnt/c/Users/dhruv/flex_bringup_export
pandoc README.md -f markdown -t html5 --standalone --embed-resources --css kit.css \
  --metadata pagetitle="HEALTH_FLEX_C3 bring-up" -o .kit.html
mkdir -p "$WIN"; cp .kit.html "$WIN/kit.html"
"$EDGE" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf='C:\Users\dhruv\flex_bringup_export\kit.pdf' \
  'C:\Users\dhruv\flex_bringup_export\kit.html' >/dev/null 2>&1 || true
cp "$WIN/kit.pdf" flex_bringup_kit.pdf
rm -rf "$WIN" .kit.html
pdfinfo flex_bringup_kit.pdf | grep -E "Pages|Page size"
