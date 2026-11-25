#!/usr/bin/env bash
# Package the kit for the person at the bench: the PDF, the sketch (in a folder of
# its own name, as Arduino IDE wants) and the four flash images. Nothing else.
#   ./make_zip.sh [out.zip]     default: ../build_flex_bringup/flex_bringup_kit.zip
set -euo pipefail
cd "$(dirname "$0")"
OUT=$(realpath -m "${1:-../build_flex_bringup/flex_bringup_kit.zip}")
T=$(mktemp -d); K="$T/flex_bringup_kit"
mkdir -p "$K/flex_bringup" "$K/firmware"
cp flex_bringup_kit.pdf "$K/"
cp flex_bringup.ino "$K/flex_bringup/"
cp firmware/flex_bringup.ino.bootloader.bin firmware/flex_bringup.ino.partitions.bin \
   firmware/boot_app0.bin firmware/flex_bringup.ino.bin "$K/firmware/"
mkdir -p "$(dirname "$OUT")"; rm -f "$OUT"
(cd "$T" && zip -qr -X "$OUT" flex_bringup_kit)
rm -rf "$T"
unzip -l "$OUT"
