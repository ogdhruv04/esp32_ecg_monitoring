#!/usr/bin/env bash
# Build the SAME sketch.ino for the reference device (ESP32-WROOM-32).
# Board-conditional #ifdefs pick the pins; the signal path is identical to the
# ring build, which is the entire point of the comparison.
set -euo pipefail
cd "$(dirname "$0")"
. ./arduino_cli.sh
# INPUT_DEFAULT=e builds the variant that boots in the 'e' input configuration
# (-DINPUT_DEFAULT_E, see sketch.ino) into its own directories, so the default
# image is never overwritten by it. Not the default: docs/amplitude_investigation.md.
SUF=""; DEFS=""
case "${INPUT_DEFAULT:-}" in
  "") ;;
  e)  SUF=_e; DEFS="-DINPUT_DEFAULT_E" ;;
  *)  echo "INPUT_DEFAULT must be unset or 'e', not '${INPUT_DEFAULT}'" >&2; exit 1 ;;
esac
mkdir -p "src_build_ref$SUF" "build_ref$SUF"
cp sketch.ino "src_build_ref$SUF/src_build_ref$SUF.ino"
"$CLI" compile --jobs "${BUILD_JOBS:-2}" \
  --fqbn esp32:esp32:esp32:FlashSize=8M,PartitionScheme=default_8MB \
  --build-path "build_ref$SUF" \
  ${DEFS:+--build-property "compiler.cpp.extra_flags=$DEFS"} "src_build_ref$SUF/src_build_ref$SUF.ino"
