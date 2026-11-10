#!/usr/bin/env bash
# Build sketch.ino for the custom ESP32-C3 test board (BOARD_TEST_C3 config:
# INTB on GPIO3). CDCOnBoot stays off, so Serial goes to UART0 and the FTDI.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p src_build_test
cp sketch.ino src_build_test/src_build_test.ino
./bin/arduino-cli compile --fqbn esp32:esp32:esp32c3 --build-path build_test \
  --build-property "compiler.cpp.extra_flags=-DBOARD_TEST_C3" src_build_test/src_build_test.ino
