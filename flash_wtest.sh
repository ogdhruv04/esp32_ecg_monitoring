#!/usr/bin/env bash
# Flash the wireless test onto the custom ESP32-C3 board over the FTDI adapter.
#
# This board has no auto-reset circuit, so put it in download mode FIRST:
#   hold BOOT -> tap EN -> release BOOT
# then run this. Afterwards tap EN once to start the new firmware.
#
# DIO, not the C3 default QIO: if this chip has in-package flash, GPIO12/13
# are flash data lines in QIO mode, and the schematic routes them to header J3.
set -euo pipefail
cd "$(dirname "$0")"
PORT=${1:-/dev/ttyUSB0}
ESPTOOL=~/.arduino15/packages/esp32/tools/esptool_py/5.3.1/esptool
B=build_wtest
./build_wtest.sh
"$ESPTOOL" --chip esp32c3 --port "$PORT" --baud 460800 --before no_reset --after no_reset \
  write_flash -z --flash_mode dio --flash_freq 80m --flash_size detect \
  0x0     $B/wireless_test.ino.bootloader.bin \
  0x8000  $B/wireless_test.ino.partitions.bin \
  0xe000  $B/boot_app0.bin \
  0x10000 $B/wireless_test.ino.bin
echo "Flashed. Tap EN to run it."
