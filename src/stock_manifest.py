"""Copy only original Home files listed in Steam's cached plaintext manifests.

Payload magic and field numbers follow SteamKit2's DepotManifest and generated
ContentManifest schema. Existing user files are never copied. Every selected
file is verified against the manifest's SHA-1 content digest after copying.
"""
import hashlib
from pathlib import Path, PurePosixPath
import struct
import os
import shutil


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError('Truncated manifest integer')
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, offset
    raise ValueError('Invalid manifest integer')


def fields(data):
    offset = 0
    while offset < len(data):
        key, offset = varint(data, offset)
        wire = key & 7
        if wire == 0:
            value, offset = varint(data, offset)
        else:
            if wire == 2:
                length, offset = varint(data, offset)
            elif wire in (1, 5):
                length = {1: 8, 5: 4}[wire]
            else:
                raise ValueError('Unsupported manifest wire format')
            value = data[offset:offset + length]
            if len(value) != length:
                raise ValueError('Truncated manifest')
            offset += length
        yield key >> 3, value


def entries(manifest):
    data = manifest.read_bytes()
    if len(data) < 8:
        raise ValueError('Truncated Steam manifest')
    magic, length = struct.unpack_from('<II', data)
    if magic != 0x71F617D0 or length > len(data) - 8:
        raise ValueError('Unrecognized Steam manifest')
    prefix = 'tools/steamvr_environments/game/'
    for tag, payload in fields(data[8:8 + length]):
        if tag != 1:
            continue
        item = dict(fields(payload))
        name = item[1].decode().replace('\\', '/')
        if not name.startswith(prefix):
            continue
        relative = PurePosixPath(name[len(prefix):])
        if not relative.parts or '..' in relative.parts or relative.is_absolute() or '\x00' in name:
            raise ValueError('Unsafe manifest path')
        if item.get(3, 0) != 0 or item.get(7):
            raise ValueError('Unrecognized file flags; do not guess')
        digest = item[5]
        if len(digest) != 20:
            raise ValueError('Missing content digest')
        yield relative, item[2], digest.hex()


def merge_verified(depot_game, manifest, destination):
    """Link verified immutable files; privately copy executable and configuration.

    Only manifest entries are eligible, so old console logs, saved rooms and
    developer files in a reused Steam cache never become part of a new install.
    """
    copied = []
    for relative, size, digest in entries(manifest):
        original = depot_game / relative
        target = destination / relative
        if (original.is_symlink() or not original.is_file()
                or any(p.is_symlink() for p in original.parents if p != depot_game and depot_game in p.parents)):
            raise RuntimeError('Missing original regular file: ' + str(relative))
        if original.stat().st_size != size:
            raise RuntimeError('Original file size mismatch: ' + str(relative))
        if os.path.lexists(target):
            raise RuntimeError('Conflicting depot file: ' + str(relative))
        with original.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha1').hexdigest()
        if actual != digest:
            raise RuntimeError('Valve content hash mismatch: ' + str(relative) +
                               '. Re-download the pinned Home depot through Steam, then retry.')
        target.parent.mkdir(parents=True, exist_ok=True)
        if 'cfg' in relative.parts or str(relative) == 'bin/linuxsteamrt64/steamtours':
            shutil.copy2(original, target)
        else:
            target.symlink_to(original)
        copied.append({'path': str(relative), 'size': size, 'sha1': digest})
    if not copied:
        raise RuntimeError('Steam manifest contains no Home files.')
    return copied
