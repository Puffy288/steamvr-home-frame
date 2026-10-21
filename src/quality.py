"""Apply measured rendering defaults only to the private installation."""
import os
from pathlib import Path
import re
import shutil
import tempfile


def configure_quality(source, game):
    path = game / 'steamtours/gameinfo.gi'
    text = path.read_text()
    values = {'SunLightMaxShadowBufferSize': 1536,
              'VrDefaultShadowTextureWidth': 4096,
              'VrDefaultShadowTextureHeight': 4096}
    for key, value in values.items():
        text, count = re.subn(r'("' + re.escape(key) + r'"\s*")\d+(\")',
                              lambda m: m[1] + str(value) + m[2], text)
        if count != 1:
            raise RuntimeError('Unrecognized Home rendering configuration: ' + key)
    # gameinfo starts as a link to Valve's depot. Replace the link atomically;
    # writing through it would modify the original content used by other ports.
    fd, temporary = tempfile.mkstemp(prefix='gameinfo.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    shutil.copy2(source / 'frame-fidelity.csv', game / 'steamtours/vr_fidelity_levels_override.csv')
    shutil.copy2(source / 'frame-quality.cfg', game / 'steamtours/cfg/frame-port2.cfg')
