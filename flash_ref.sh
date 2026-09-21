#!/usr/bin/env bash
# Flash the reference device. Note the port: the WROOM board goes through a
# USB-UART bridge, so it enumerates as /dev/ttyUSB*, not the /dev/ttyACM* the
# C3's native USB gives us.
set -euo pipefail
cd "$(dirname "$0")"
PORT=${1:-/dev/ttyUSB0}
./build_ref.sh
[ -w "$PORT" ] || sudo chmod 666 "$PORT"
./bin/arduino-cli upload -p "$PORT" \
  --fqbn esp32:esp32:esp32:FlashSize=8M,PartitionScheme=default_8MB \
  --build-path build_ref src_build_ref/src_build_ref.ino
