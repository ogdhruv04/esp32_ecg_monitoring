#!/usr/bin/env bash
PORT=${1:-/dev/ttyACM0}
BAUD=${2:-57600}

python3 ./serial_monitor.py $PORT $BAUD
