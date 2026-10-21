"""Install a private Home runtime and add its Steam library shortcut."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

from common import INSTALL, VERSION, DEPOTS, find_steam, library_paths, live_process, write_json
from depot import ensure_depot, ensure_fex
from libraries import install_libraries
from shortcut import add_shortcut, remove_shortcut
from steamui import SteamUI
from artwork import apply_official_artwork
from vr_application import register
from quality import configure_quality
from stock_manifest import merge_verified

SOURCE = Path(__file__).resolve().parents[1]
ROOTFS = Path('/usr/share/guestos/fex-mesa')
VR = Path('/opt/steamvr')


def merge_assets(source, destination, manifest):
    return merge_verified(source, manifest, destination)


def find_manifest(steam, depot):
    for root in library_paths(steam):
        path = root / 'depotcache' / f'{depot}_{DEPOTS[depot]}.manifest'
        if path.is_file():
            return path
    raise RuntimeError(f'Pinned Steam manifest {depot}/{DEPOTS[depot]} is missing. '
                       'Download this Home depot through Steam before retrying.')


def require_fresh_destination(destination):
    if os.path.lexists(destination):
        raise RuntimeError('This release requires a fresh installation. Close Home and run the '
                           'existing installation\'s Uninstall.sh first. Its settings are kept '
                           'in a separate .uninstalled folder; no files were overwritten.')


def validate(runtime, fex):
    game = runtime / 'game'
    paths = [game / 'bin/linuxsteamrt64', game / 'steamtours/bin/linuxsteamrt64']
    libraries = ':'.join(map(str, [runtime / 'lib'] + paths + [VR / 'bin/linux64']))
    env = os.environ.copy()
    env.pop('LD_LIBRARY_PATH', None)
    env.pop('LD_PRELOAD', None)
    env['FEX_ROOTFS'] = str(ROOTFS)
    modules = [p for d in paths for p in d.glob('*.so')]
    modules += [game / 'bin/linuxsteamrt64/steamtours', VR / 'bin/linux64/vrclient.so']
    for module in modules:
        result = subprocess.run([str(fex), '/lib64/ld-linux-x86-64.so.2', '--library-path',
                                 libraries, '--list', str(module)], env=env, cwd=game,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        if result.returncode or 'not found' in result.stdout:
            raise RuntimeError('Dependency validation failed for ' + module.name + ':\n' + result.stdout[-2000:])
    # SDL loads PulseAudio dynamically, so it needs an explicit check too.
    result = subprocess.run([str(fex), '/lib64/ld-linux-x86-64.so.2', '--library-path', libraries,
                             '--list', str(runtime / 'lib/libpulse.so.0')], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
    if result.returncode or 'not found' in result.stdout:
        raise RuntimeError('Audio dependency validation failed:\n' + result.stdout[-2000:])
    print(f'Validated {len(modules)} game/VR modules and the audio loader.', flush=True)


def check_platform():
    if os.geteuid() == 0:
        raise RuntimeError('Run as the normal Steam user, without sudo.')
    if platform.system() != 'Linux' or platform.machine() not in ['aarch64', 'arm64']:
        raise RuntimeError('This installer requires Steam Frame ARM64 Linux.')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines()
                   if '=' in line and not line.startswith('#'))
    release = {key: value.strip("\"'") for key, value in release.items()}
    if release.get('ID') != 'steamos' or release.get('VARIANT_ID') != 'vr':
        raise RuntimeError('This version supports SteamOS VR on Steam Frame only.')
    for path in [ROOTFS, VR / 'bin/linux64/vrclient.so']:
        if not path.exists():
            raise RuntimeError('The required Frame runtime is missing: ' + str(path))


def install(destination):
    require_fresh_destination(destination)
    check_platform()
    if destination.is_symlink():
        raise RuntimeError('Install directory must not be a symlink.')
    steam = find_steam()
    cache = Path.home() / '.cache/steamvr-home-frame'
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / 'installer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another installer is already running.')
        require_fresh_destination(destination)
        with SteamUI() as ui:
            # Fail early if the Steam build removed required APIs.
            ready = ui.evaluate('''["AddShortcut","SetShortcutName","SetShortcutExe",
                "SetShortcutStartDir","SetShortcutLaunchOptions","SetShortcutIsVR",
                "SpecifyCompatTool","RegisterForAppDetails"].every(
                key=>typeof SteamClient.Apps[key]==="function") &&
                typeof SteamClient.Console.ExecCommand==="function" &&
                typeof SteamClient.Console.RegisterForSpewOutput==="function"''')
            if not ready:
                raise RuntimeError('This Steam client lacks required installer functions. Update Steam and try again; no runtime was installed.')
            fex = ensure_fex(ui, steam)
            assets = ensure_depot(ui, steam, 250830)
            binary = ensure_depot(ui, steam, 250832)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(destination.parent).free < 256 * 1024 * 1024:
                raise RuntimeError('At least 256 MB free space is needed for the private runtime.')
            with tempfile.TemporaryDirectory(prefix='.frame-home-install-', dir=destination.parent) as name:
                stage = Path(name) / 'runtime'
                stage.mkdir()
                install_libraries(SOURCE / 'packages.lock.json', stage, cache / 'packages')
                prefix = fex.parent.parent
                guest_vulkan = prefix / 'share/fex-emu/GuestThunks/libvulkan-guest.so'
                host_vulkan = prefix / 'lib/aarch64-linux-gnu/fex-emu/HostThunks/libvulkan-host.so'
                if guest_vulkan.is_file() and host_vulkan.is_file():
                    (stage / 'vulkan').mkdir()
                    (stage / 'vulkan/libvulkan.so.1').symlink_to(guest_vulkan)
                    print('Using Valve\'s bundled native Vulkan forwarding libraries.', flush=True)
                else:
                    print('Native Vulkan forwarding is unavailable; using the emulated driver.', flush=True)
                print('Preparing the private Home game directory...', flush=True)
                verified_assets = merge_assets(assets, stage / 'game', find_manifest(steam, 250830))
                verified_binary = merge_assets(binary, stage / 'game', find_manifest(steam, 250832))
                configure_quality(SOURCE, stage / 'game')
                for name in ['src', 'coverage', 'docs', 'README.md', 'START-HERE.md', 'SYSTEM-CHANGES.md', 'LICENSE', 'Launch.sh',
                             'Uninstall.sh', 'packages.lock.json']:
                    source = SOURCE / name
                    target = stage / name
                    if source.is_dir():
                        shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                    else:
                        shutil.copy2(source, target)
                for script in ['Launch.sh', 'Uninstall.sh']:
                    (stage / script).chmod(0o755)
                validate(stage, fex)
                receipt = {'project': 'steamvr-home-frame', 'version': VERSION,
                           'steam': str(steam), 'fex': str(fex), 'rootfs': str(ROOTFS),
                           'vr': str(VR), 'assets': str(assets), 'binary': str(binary),
                           'requested_manifests_for_new_downloads': DEPOTS,
                           'verified_valve_files': len(verified_assets) + len(verified_binary),
                           'shortcut_id': None}
                write_json(stage / 'installation.json', receipt)
                require_fresh_destination(destination)
                stage.rename(destination)
            # If Steam registration fails, this receipt allows safe uninstall.
            # Fresh setup never replaces a previous runtime or imports its saves.
            print('Adding SteamVR Home (Frame - Unofficial) to the library...', flush=True)
            receipt['shortcut_id'] = add_shortcut(ui, destination)
            write_json(destination / 'installation.json', receipt)
            try:
                applied = apply_official_artwork(ui, cache / 'artwork', destination, receipt['shortcut_id'])
                if applied:
                    print('Added Home artwork: ' + ', '.join(applied) + '.', flush=True)
            except (RuntimeError, OSError, ValueError) as exc:
                # Artwork must never turn a working installation into a failure.
                print('Optional Home artwork skipped: ' + str(exc), flush=True)
            register(destination, receipt['shortcut_id'], VR)
        print('\nInstalled. Open Steam Library → Non-Steam → SteamVR Home (Frame - Unofficial) → Play.', flush=True)
        print('Private files:', destination, flush=True)
        print('Download cache:', cache, flush=True)
        print('If you need to uninstall: bash "' + str(destination / 'Uninstall.sh') + '"', flush=True)
        print('Workshop subscriptions and download settings were not changed.', flush=True)


def uninstall(destination):
    config_path = destination / 'installation.json'
    config = json.loads(config_path.read_text())
    if destination.is_symlink() or config.get('project') != 'steamvr-home-frame':
        raise RuntimeError('Not a recognized Home installation.')
    if live_process(destination / 'process.json'):
        raise RuntimeError('Close SteamVR Home before uninstalling.')
    saved = destination.with_name(destination.name + '.uninstalled')
    if saved.exists():
        raise RuntimeError('An earlier uninstall backup exists: ' + str(saved))
    if config.get('shortcut_id'):
        register(destination, config['shortcut_id'], config['vr'], remove=True)
        with SteamUI() as ui:
            remove_shortcut(ui, destination, config['shortcut_id'])
    # Keep saved settings/logs recoverable rather than silently deleting them.
    destination.rename(saved)
    print('Removed the Steam shortcut. Settings and files were preserved at:', saved)
    print('Valve depots, FEX, Workshop content, and other Steam entries were preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', type=Path, default=INSTALL)
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    destination = args.install_dir.expanduser().absolute()
    if any(c in str(destination) for c in ['"', '\n', '\r']):
        raise RuntimeError('The install path cannot contain quotes or newlines.')
    if args.uninstall:
        uninstall(destination)
    else:
        install(destination)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('\nINSTALLER STOPPED:', exc, file=sys.stderr)
        sys.exit(1)
