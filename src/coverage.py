"""Enable the accepted coverage correction only for the verified native build.

The ordinary configuration disables the optional alpha prepass. Only a verified
adapter and known game build may turn it on. Unsupported/missing components keep
the original colour rendering, at a possible performance cost.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from common import write_json


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(install, env, native):
    result = {'enabled': False, 'reason': 'Native ARM Vulkan forwarding is required.'}
    folder = install / 'coverage'
    # Never inherit an experimental coverage layer from a developer shell.
    for key in ['VK_INSTANCE_LAYERS', 'VK_LAYER_PATH', 'VK_ADD_LAYER_PATH']:
        if 'PORT2' in env.get(key, '') or 'coverage-correction' in env.get(key, ''):
            env.pop(key, None)
    try:
        if not native or platform.machine() not in ('aarch64', 'arm64'):
            raise RuntimeError(result['reason'])
        supported = json.loads((folder / 'supported-game.json').read_text())
        integrity = json.loads((folder / 'integrity.json').read_text())
        for name in ['libport2_coverage.so', 'supported-game.json']:
            if digest(folder / name) != integrity[name]:
                raise RuntimeError('Coverage package integrity check failed: ' + name)
        for name, expected in supported['files'].items():
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts:
                raise RuntimeError('Invalid supported-build path')
            if digest(install / 'game' / relative) != expected:
                raise RuntimeError('Home build changed: ' + name)
        library = folder / 'libport2_coverage.so'
        # Loading this private library does not initialize Vulkan or the GPU.
        probe = subprocess.run([sys.executable, '-c',
                                'import ctypes,sys; ctypes.CDLL(sys.argv[1])', str(library)],
                               capture_output=True, timeout=5, env=env)
        if probe.returncode:
            raise RuntimeError('Coverage library dependencies are unavailable.')
        manifests = folder / 'manifests'
        manifests.mkdir(exist_ok=True)
        write_json(manifests / 'coverage.json', {
            'file_format_version': '1.2.0', 'layer': {
                'name': 'VK_LAYER_PORT2_coverage', 'type': 'GLOBAL',
                'library_path': str(library), 'api_version': '1.3.0',
                'implementation_version': '1',
                'description': 'Home alpha-depth coverage correction',
                'functions': {'vkNegotiateLoaderLayerInterfaceVersion':
                              'vkNegotiateLoaderLayerInterfaceVersion'}}})
        existing_layers = env.get('VK_INSTANCE_LAYERS', '')
        env['VK_INSTANCE_LAYERS'] = 'VK_LAYER_PORT2_coverage' + (
            ':' + existing_layers if existing_layers else '')
        existing_path = env.get('VK_LAYER_PATH', '')
        env['VK_LAYER_PATH'] = str(manifests) + (os.pathsep + existing_path if existing_path else '')
        result = {'enabled': True, 'reason': 'Verified adapter and supported Home build.'}
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result['reason'] = str(exc)
    write_json(install / 'logs/coverage-startup.json', result)
    print('Coverage:', result['reason'], flush=True)
    return ['+vr_depth_prepass_alphatested', '1' if result['enabled'] else '0']
