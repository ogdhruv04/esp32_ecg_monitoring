# Sourced by the build and flash scripts: sets CLI to arduino-cli.
# bin/ is gitignored, so a git worktree (fw, algo, app) has no copy of it; fall
# back to the main checkout's. ARDUINO_CLI overrides both.
CLI="${ARDUINO_CLI:-./bin/arduino-cli}"
if [ ! -x "$CLI" ]; then
  CLI="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/bin/arduino-cli"
fi
[ -x "$CLI" ] || { echo "arduino-cli not found (looked in ./bin and the main checkout; set ARDUINO_CLI)" >&2; exit 1; }
