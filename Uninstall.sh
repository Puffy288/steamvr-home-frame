#!/bin/bash
set -euo pipefail
install_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ! -t 1 && -z "${FRAME_HOME_INSTALL_TERMINAL:-}" ]] && command -v konsole >/dev/null 2>&1; then
    export FRAME_HOME_INSTALL_TERMINAL=1
    exec konsole --hold -e /bin/bash "$install_dir/Uninstall.sh"
fi
exec python3 "$install_dir/src/install.py" --install-dir "$install_dir" --uninstall
