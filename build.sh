#!/usr/bin/env bash
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
mkdir -p "src_build$SUF"
cp sketch.ino "src_build$SUF/src_build$SUF.ino"
"$CLI" compile --jobs "${BUILD_JOBS:-2}" --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc --build-path "build$SUF" \
  ${DEFS:+--build-property "compiler.cpp.extra_flags=$DEFS"} "src_build$SUF/src_build$SUF.ino"
