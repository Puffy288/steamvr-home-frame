"""Developer rebuild of our own ARM64 adapter; no Valve shader code is needed."""
import hashlib
import json
import platform
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
if platform.machine() not in ('aarch64', 'arm64'):
    raise SystemExit('Build this adapter on ARM64; do not replace the Frame binary with an x86 build.')
subprocess.run(['glslangValidator', '-V', str(root/'coverage.frag'), '-o',
                str(root/'coverage.spv')], check=True)
subprocess.run(['spirv-val', str(root/'coverage.spv')], check=True)
code = (root/'coverage.spv').read_bytes()
words = [int.from_bytes(code[i:i+4], 'little') for i in range(0, len(code), 4)]
(root/'coverage_spv.h').write_text('#include <cstdint>\nstatic const uint32_t coverage_spv[] = {' +
                                  ','.join(hex(x) for x in words) + '};\n')
subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                '-Wno-missing-field-initializers', '-fPIC', '-shared',
                str(root/'coverage_layer.cpp'), '-o', str(root/'libport2_coverage.so'),
                '-lcrypto'], check=True)
integrity = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
             ['libport2_coverage.so', 'supported-game.json']}
(root/'integrity.json').write_text(json.dumps(integrity, indent=2) + '\n')
