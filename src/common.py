"""Shared paths and conservative process identification."""
import json
import os
from pathlib import Path
import re
import tempfile

APP_NAME = 'SteamVR Home (Frame - Unofficial)'
VERSION = '0.1.0'
INSTALL = Path.home() / '.local/share/steamvr-home-frame'
DEPOTS = {250830: '1874458903680892192', 250832: '3112697343985428860'}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def find_steam():
    for path in [Path.home() / '.local/share/Steam', Path.home() / '.steam/steam']:
        if (path / 'steamapps').is_dir():
            return path.resolve()
    raise RuntimeError('Steam was not found. Start Steam on the Frame and sign in first.')


def library_paths(steam):
    paths = [steam, steam / 'steamrtarm64']
    vdf = steam / 'steamapps/libraryfolders.vdf'
    if vdf.exists():
        for match in re.finditer(r'"path"\s*"((?:[^"\\]|\\.)*)"', vdf.read_text()):
            value = match[1].replace('\\\\', '\\').replace('\\"', '"')
            path = Path(value)
            if path.is_absolute() and path not in paths:
                paths.append(path)
    return paths


def find_fex(steam):
    for root in library_paths(steam):
        path = root / 'steamapps/common/FEX-Emu/usr/bin/FEX'
        if path.is_file():
            return path.resolve()
    return None


def find_depot(steam, depot):
    for root in library_paths(steam):
        path = root / f'steamapps/content/app_250820/depot_{depot}/tools/steamvr_environments/game'
        marker = 'bin/linuxsteamrt64/steamtours' if depot == 250832 else 'steamtours/gameinfo.gi'
        if (path / marker).is_file():
            return path
    return None


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError):
        return None


def live_process(state_path):
    try:
        state = json.loads(Path(state_path).read_text())
        if state.get('start_ticks') and identity(int(state['pid'])) == state['start_ticks']:
            return state
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def other_home_process():
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            args = (path / 'cmdline').read_bytes().split(b'\0')
            if any(arg.endswith(b'/bin/linuxsteamrt64/steamtours') for arg in args):
                return int(path.name)
        except OSError:
            continue
    return None
