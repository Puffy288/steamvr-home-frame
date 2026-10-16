#!/usr/bin/env python3
"""Build source-only release files from an explicit allowlist."""
import base64
import hashlib
from pathlib import Path
import zipfile
import io
import os

ROOT = Path(__file__).resolve().parent
TOP = ['Install.sh', 'Launch.sh', 'Uninstall.sh', 'README.md', 'START-HERE.md', 'SYSTEM-CHANGES.md',
       'LICENSE', 'packages.lock.json', 'frame-fidelity.csv',
       'build_release.py', '.gitignore']
MEDIA = ['docs/screenshots/ilias-retreat.jpg', 'docs/screenshots/ilias-retreat-menu.jpg',
         'docs/screenshots/mount-rainier.jpg', 'docs/screenshots/konsole-on-frame.jpg']
FILES = TOP + MEDIA + [str(p.relative_to(ROOT)) for directory in ['src', 'tests']
               for p in sorted((ROOT / directory).glob('*.py'))]


def source_zip():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in FILES:
            path = ROOT / name
            if path.is_symlink():
                raise RuntimeError('Release sources must not be symlinks: ' + name)
            info = zipfile.ZipInfo('steamvr-home-frame/' + name, date_time=(2026, 10, 15, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return stream.getvalue()


def main():
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    payload = source_zip()
    checksum = hashlib.sha256(payload).hexdigest()
    zip_path = dist / 'steamvr-home-frame-source.zip'
    zip_path.write_bytes(payload)
    # The bootstrap validates its embedded payload before extracting it. It does
    # not download or execute a script from a mutable remote URL.
    prefix = '''#!/bin/bash
set -euo pipefail
self=$(readlink -f -- "$0")
if [[ ! -t 1 && -z "${FRAME_HOME_INSTALL_TERMINAL:-}" ]] && command -v konsole >/dev/null 2>&1; then
    export FRAME_HOME_INSTALL_TERMINAL=1
    exec konsole --hold -e /bin/bash "$self" "$@"
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required. Run this on Steam Frame's SteamOS."
    exit 1
fi
python3 - "$self" "$@" <<'FRAME_HOME_BOOTSTRAP'
import base64, hashlib, io, os, pathlib, subprocess, sys, tempfile, zipfile
source = pathlib.Path(sys.argv[1]).read_bytes()
data = base64.b64decode(source.split(b'\\n__FRAME_HOME_PAYLOAD__\\n', 1)[1], validate=False)
if hashlib.sha256(data).hexdigest() != 'CHECKSUM':
    raise SystemExit('Installer payload checksum mismatch; download it again.')
with tempfile.TemporaryDirectory(prefix='frame-home-setup-') as folder:
    root = pathlib.Path(folder)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            path = pathlib.PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise SystemExit('Unsafe installer archive.')
            target = root.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))
            target.chmod(0o755 if path.suffix == '.sh' else 0o644)
    if '--extract-only' in sys.argv[2:]:
        # Used by release verification; does not install or contact Steam.
        print('Embedded source verified:', len(archive.infolist()), 'files')
        result = 0
    else:
        result = subprocess.call(['/bin/bash', str(root/'steamvr-home-frame/Install.sh')] + sys.argv[2:])
    raise SystemExit(result)
FRAME_HOME_BOOTSTRAP
exit $?
__FRAME_HOME_PAYLOAD__
'''.replace('CHECKSUM', checksum)
    run_path = dist / 'SteamVR-Home-Frame-Install.run'
    run_path.write_bytes(prefix.encode() + base64.encodebytes(payload))
    run_path.chmod(0o755)
    (dist / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                                          for p in [run_path, zip_path]))
    print('Built:', run_path)
    print('Built:', zip_path)
    print('Source files:', len(FILES), 'Installer bytes:', run_path.stat().st_size)


if __name__ == '__main__':
    main()
