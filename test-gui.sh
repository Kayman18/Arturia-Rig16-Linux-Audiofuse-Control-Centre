#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$script_dir/gui_smoke.py" --report "$script_dir/AF16Rig-GUI-check.json" "$@"
