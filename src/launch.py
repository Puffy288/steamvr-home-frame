"""Foreground launcher so Steam's Play/Stop state follows the actual VR process."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from common import INSTALL, live_process, other_home_process, identity, write_json
from mirror import hide_companion


def launch(install, extra, show_mirror=False, emulated_vulkan=False):
    config = json.loads((install / 'installation.json').read_text())
    game = install / 'game'
    fex = Path(config['fex'])
    exe = game / 'bin/linuxsteamrt64/steamtours'
    for path in [fex, exe, Path(config['rootfs']), Path(config['vr']) / 'bin/linux64/vrclient.so']:
        if not path.exists():
            raise RuntimeError('Required file is missing; run the installer again: ' + str(path))
    state_path = install / 'process.json'
    with (install / 'launch.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('SteamVR Home is already running.')
        running = live_process(state_path) or other_home_process()
        if running:
            raise RuntimeError('Another SteamVR Home process is running. Close Home before starting it again.')
        env = os.environ.copy()
        for key in ['LD_LIBRARY_PATH', 'LD_PRELOAD']:
            env.pop(key, None)
        env['FEX_ROOTFS'] = config['rootfs']
        env['SDL_AUDIODRIVER'] = 'pulseaudio'
        runtime = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        env['PULSE_SERVER'] = 'unix:' + runtime + '/pulse/native'
        library_paths = [install / 'lib', game / 'bin/linuxsteamrt64',
                                      game / 'steamtours/bin/linuxsteamrt64',
                                      Path(config['vr']) / 'bin/linux64']
        prefix = fex.parent.parent
        host = prefix / 'lib/aarch64-linux-gnu/fex-emu/HostThunks'
        guest = prefix / 'share/fex-emu/GuestThunks'
        if not emulated_vulkan and (install / 'vulkan/libvulkan.so.1').is_file() and (host / 'libvulkan-host.so').is_file():
            # Only Home sees this library override. No system/rootfs files change.
            env['FEX_THUNKHOSTLIBS'] = str(host)
            env['FEX_THUNKGUESTLIBS'] = str(guest)
            library_paths.insert(0, install / 'vulkan')
            print('Graphics: forwarding Vulkan to the native ARM driver.', flush=True)
        else:
            print('Graphics: using the emulated Vulkan driver.', flush=True)
        libraries = ':'.join(map(str, library_paths))
        # Keep Steam's shortcut game ID so its VR/Stop tracking follows Home.
        # The content app ID remains SteamVR's for entitlement and Workshop.
        game_id = os.environ.get('SteamGameId', '250820')
        if not game_id.isdecimal():
            game_id = '250820'
        command = [str(fex), '/usr/bin/env', 'LD_LIBRARY_PATH=' + libraries,
                   'SteamAppId=250820', 'SteamGameId=' + game_id, str(exe),
                   '-vulkan', '-vr', '-condebug', '-game', str(game / 'steamtours'),
                   # Let Home load its saved environment (including Workshop homes).
                   # Forcing an addon/map here overrides that choice on every launch.
                   '-autofidelityconfig', 'frame_smooth', '-forcefidelitylevel', '4'] + extra
        logs = install / 'logs'
        logs.mkdir(exist_ok=True)
        log_path = logs / ('home-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.log')
        with log_path.open('w') as log:
            process = subprocess.Popen(command, cwd=game, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT)
        write_json(state_path, {'pid': process.pid, 'start_ticks': identity(process.pid),
                              'log': str(log_path)})
        print('SteamVR Home started. Log:', log_path, flush=True)
        finished = threading.Event()
        mirror_thread = None
        if not show_mirror:
            mirror_thread = threading.Thread(target=hide_companion, args=(process.pid, finished), daemon=True)
            mirror_thread.start()
        def stop(signum, frame):
            if process.poll() is None:
                process.terminate()
        old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            result = process.wait()
        finally:
            finished.set()
            if mirror_thread:
                mirror_thread.join(timeout=2)
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
            state_path.unlink(missing_ok=True)
        if result not in (0, -signal.SIGTERM):
            raise RuntimeError(f'Home exited with code {result}. Log: {log_path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', type=Path, default=INSTALL)
    parser.add_argument('--show-mirror', action='store_true', help='Leave the desktop companion window visible.')
    parser.add_argument('--emulated-vulkan', action='store_true', help='Use the fallback x86 Vulkan driver.')
    parser.add_argument('action', choices=['start', 'stop', 'status'], nargs='?', default='start')
    args, extra = parser.parse_known_args()
    if args.action == 'start':
        launch(args.install_dir, extra, args.show_mirror, args.emulated_vulkan)
    elif args.action == 'status':
        state = live_process(args.install_dir / 'process.json')
        print('Home is running.' if state else 'Home is stopped.')
    else:
        state = live_process(args.install_dir / 'process.json')
        if state:
            os.kill(state['pid'], signal.SIGTERM)
            for _ in range(100):
                if not live_process(args.install_dir / 'process.json'):
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Home is still shutting down.')
        print('Home is stopped.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        message = str(exc)
        print('ERROR:', message, file=sys.stderr)
        # Steam launches have no terminal; expose actionable errors in the desktop.
        if not sys.stderr.isatty() and os.environ.get('DISPLAY'):
            import shutil
            if shutil.which('kdialog'):
                subprocess.run(['kdialog', '--title', 'SteamVR Home (Frame - Unofficial)', '--error', message], check=False)
        sys.exit(1)
