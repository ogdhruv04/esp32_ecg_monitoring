#!/usr/bin/env bash
# Build sketch.ino for the custom ESP32-C3 test board (BOARD_TEST_C3 config:
# INTB on GPIO3). CDCOnBoot stays off, so Serial goes to UART0 and the FTDI.
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
mkdir -p "src_build_test$SUF"
cp sketch.ino "src_build_test$SUF/src_build_test$SUF.ino"
"$CLI" compile --jobs "${BUILD_JOBS:-2}" --fqbn esp32:esp32:esp32c3 --build-path "build_test$SUF" \
  --build-property "compiler.cpp.extra_flags=-DBOARD_TEST_C3${DEFS:+ $DEFS}" "src_build_test$SUF/src_build_test$SUF.ino"
