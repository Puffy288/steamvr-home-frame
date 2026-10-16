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

from common import INSTALL, VERSION, DEPOTS, find_steam, live_process, write_json
from depot import ensure_depot, ensure_fex
from libraries import install_libraries
from shortcut import add_shortcut, remove_shortcut
from steamui import SteamUI
from artwork import apply_official_artwork

SOURCE = Path(__file__).resolve().parents[1]
ROOTFS = Path('/usr/share/guestos/fex-mesa')
VR = Path('/opt/steamvr')


def merge_assets(source, destination):
    """Build real directories with links to immutable depot files, never modifying depots."""
    for root, dirs, files in os.walk(source, followlinks=False):
        relative = Path(root).relative_to(source)
        target_dir = destination / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        # Hand-assembled installations may contain directory links into the assets depot.
        # The assets pass already supplies these; never follow arbitrary directory links.
        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
        for name in files:
            original = Path(root) / name
            target = target_dir / name
            if original.is_symlink():
                continue
            if name in ['console.log', 'vr_fidelity_levels_override.csv'] or name.endswith('.log'):
                continue
            if os.path.lexists(target):
                target.unlink()
            if 'cfg' in relative.parts or (relative == Path('bin/linuxsteamrt64') and name == 'steamtours'):
                # Keep user-writable configuration private, including defaults.
                shutil.copy2(original, target)
            else:
                target.symlink_to(original)


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
        if live_process(destination / 'process.json'):
            raise RuntimeError('Close SteamVR Home before updating it.')
        config_path = destination / 'installation.json'
        if destination.exists() and not config_path.is_file():
            raise RuntimeError('Install folder already exists without an installation receipt. Preserve it and choose another folder.')
        previous = json.loads(config_path.read_text()) if config_path.is_file() else {}
        if previous and previous.get('project') != 'steamvr-home-frame':
            raise RuntimeError('Unrecognized installation receipt; refusing to overwrite.')
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
                merge_assets(assets, stage / 'game')
                merge_assets(binary, stage / 'game')
                # Preserve configurations from previous installations of THIS package.
                old_cfg = destination / 'game/steamtours/cfg'
                if old_cfg.is_dir():
                    shutil.copytree(old_cfg, stage / 'game/steamtours/cfg', dirs_exist_ok=True)
                override = stage / 'game/steamtours/vr_fidelity_levels_override.csv'
                shutil.copy2(SOURCE / 'frame-fidelity.csv', override)
                for name in ['src', 'docs', 'README.md', 'START-HERE.md', 'SYSTEM-CHANGES.md', 'LICENSE', 'Launch.sh',
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
                           'shortcut_id': previous.get('shortcut_id')}
                write_json(stage / 'installation.json', receipt)
                stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                backup = destination.with_name(destination.name + '.previous-' + stamp)
                if backup.exists():
                    raise RuntimeError('A previous installation backup exists at ' + str(backup) + '. Preserve or move it before updating again.')
                if destination.exists():
                    destination.rename(backup)
                try:
                    stage.rename(destination)
                except Exception:
                    if backup.exists():
                        backup.rename(destination)
                    raise
            # An interruption here leaves a complete, repairable runtime. Rerunning
            # will recognize the same target and never duplicate the shortcut.
            print('Adding SteamVR Home (Frame - Unofficial) to the library...', flush=True)
            receipt['shortcut_id'] = add_shortcut(ui, destination, previous.get('shortcut_id'))
            write_json(destination / 'installation.json', receipt)
            try:
                applied = apply_official_artwork(ui, cache / 'artwork', destination, receipt['shortcut_id'])
                if applied:
                    print('Added Valve\'s official SteamVR Home cover and list icon.', flush=True)
            except (RuntimeError, OSError, ValueError) as exc:
                # Artwork must never turn a working installation into a failure.
                print('Library artwork skipped: ' + str(exc), flush=True)
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
