#!/usr/bin/env bash
# Build the wireless stability test for the custom ESP32-C3 board.
# CDCOnBoot stays at its default (off): Serial goes to UART0, i.e. the J1
# TX/RX pins and the FTDI adapter, not the chip's native USB.
set -euo pipefail
cd "$(dirname "$0")"
[ -f wireless_test/wifi_secrets.h ] || { echo "missing wireless_test/wifi_secrets.h (copy the .example.h)"; exit 1; }
./bin/arduino-cli compile --fqbn esp32:esp32:esp32c3 --build-path build_wtest wireless_test/wireless_test.ino
