#!/usr/bin/env bash
# Build flex_bringup/flex_bringup.ino for the HEALTH_FLEX_C3 ring board and copy
# the images into flex_bringup/firmware/ (committed, so the kit can be flashed
# with esptool alone). CDCOnBoot off: Serial is UART0, the RX1/TX1 pads.
# DIO: the safe flash mode for the C3's in-package flash, as on the test board.
set -euo pipefail
cd "$(dirname "$0")"
. ./arduino_cli.sh
B=build_flex_bringup
FQBN=esp32:esp32:esp32c3:CDCOnBoot=default,FlashMode=dio,FlashSize=4M
O=flex_bringup/firmware
mkdir -p "$O" "$B"
"$CLI" compile --jobs "${BUILD_JOBS:-2}" --warnings all --fqbn "$FQBN" \
  --build-path "$B" flex_bringup/flex_bringup.ino 2>&1 | tee "$B/compile.log"
cp "$B/flex_bringup.ino.bootloader.bin" "$B/flex_bringup.ino.partitions.bin" \
   "$B/flex_bringup.ino.bin" "$O/"
cp ~/.arduino15/packages/esp32/hardware/esp32/*/tools/partitions/boot_app0.bin "$O/"
( cd "$O" && sha256sum *.bin > SHA256SUMS )
{ echo "flex_bringup build, $(date -u +%Y-%m-%dT%H:%MZ), commit $(git rev-parse --short HEAD) (sketch may be newer if uncommitted)"
  echo "FQBN $FQBN"
  "$CLI" core list | grep esp32:esp32
  grep -E "Sketch uses|Global variables" "$B/compile.log"
  echo "warnings: $(grep -ci warning "$B/compile.log" || true)"
} > "$O/BUILD.txt"
ls -l "$O"
