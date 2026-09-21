#!/usr/bin/env bash
# Build the SAME sketch.ino for the reference device (ESP32-WROOM-32).
# Board-conditional #ifdefs pick the pins; the signal path is identical to the
# ring build, which is the entire point of the comparison.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p src_build_ref build_ref
cp sketch.ino src_build_ref/src_build_ref.ino
./bin/arduino-cli compile \
  --fqbn esp32:esp32:esp32:FlashSize=8M,PartitionScheme=default_8MB \
  --build-path build_ref src_build_ref/src_build_ref.ino
