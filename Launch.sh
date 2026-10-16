#!/bin/bash
set -euo pipefail
install_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Native ARM64 bash/Python starts the guest binary explicitly through Valve's FEX.
unset LD_PRELOAD LD_LIBRARY_PATH
case "${1:-}" in
    start|stop|status) ;;
    *) set -- start "$@" ;;
esac
exec python3 "$install_dir/src/launch.py" --install-dir "$install_dir" "$@"
