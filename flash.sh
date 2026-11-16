#!/usr/bin/env bash
PORT=${1:-/dev/ttyACM1}
BAUD=${2:-57600}

echo "Building project..."
./build.sh

if [ ! -w "$PORT" ]; then
    echo "Requesting sudo to set USB port permissions..."
    sudo chmod 666 $PORT
fi

echo "Flashing to $PORT..."
. ./arduino_cli.sh
SUF=""; [ "${INPUT_DEFAULT:-}" = e ] && SUF=_e   # the variant build.sh just made, if asked for
"$CLI" upload -p $PORT --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc --build-path "build$SUF" "src_build$SUF/src_build$SUF.ino"

echo "Flash complete!"
python3 ./serial_monitor.py $PORT $BAUD
