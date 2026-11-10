#!/usr/bin/env bash
cd "$(dirname "$0")"
. ./arduino_cli.sh
mkdir -p src_build
cp sketch.ino src_build/src_build.ino
"$CLI" compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc --build-path build src_build/src_build.ino
