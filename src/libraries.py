"""Fetch checksum-pinned runtime libraries; never install system packages."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import time
import urllib.parse
import urllib.request

from common import write_json


class ValveOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        target = urllib.parse.urlsplit(new_url)
        if target.scheme != 'https' or target.hostname != 'repo.steampowered.com':
            raise RuntimeError('Refusing a dependency redirect outside Valve\'s HTTPS repository.')
        return super().redirect_request(request, fp, code, message, headers, new_url)


def download(package, cache):
    url = urllib.parse.urlsplit(package['url'])
    if url.scheme != 'https' or url.hostname != 'repo.steampowered.com':
        raise RuntimeError('Dependency URL must be on Valve\'s HTTPS repository.')
    if not 0 < package['size'] <= 32 * 1024 * 1024:
        raise RuntimeError('Invalid dependency size.')
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (package['sha256'] + '.deb')
    def valid(data):
        return len(data) == package['size'] and hashlib.sha256(data).hexdigest() == package['sha256']
    if path.is_file():
        data = path.read_bytes()
        if valid(data):
            return data
    for attempt in range(3):
        try:
            opener = urllib.request.build_opener(ValveOnlyRedirects())
            with opener.open(package['url'], timeout=40) as response:
                if urllib.parse.urlsplit(response.url).hostname != 'repo.steampowered.com':
                    raise RuntimeError('Unexpected download redirect.')
                data = response.read(package['size'] + 1)
            if not valid(data):
                raise RuntimeError('Package size/SHA-256 mismatch: ' + package['name'])
            path.write_bytes(data)
            return data
        except OSError:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def data_archive(data):
    if not data.startswith(b'!<arch>\n'):
        raise RuntimeError('Invalid Debian package header.')
    pos = 8
    while pos + 60 <= len(data):
        header = data[pos:pos + 60]
        size = int(header[48:58])
        start, end = pos + 60, pos + 60 + size
        if size < 0 or header[58:60] != b'`\n' or end > len(data):
            raise RuntimeError('Invalid Debian package member.')
        pos = end + size % 2
        if header[:16].strip().startswith(b'data.tar'):
            return tarfile.open(fileobj=io.BytesIO(data[start:end]), mode='r:*')
    raise RuntimeError('Debian package has no data archive.')


def extract_libraries(data, destination, notices):
    """Copy regular ELF files by basename; never extract archive paths or scripts."""
    destination.mkdir(parents=True, exist_ok=True)
    notices.mkdir(parents=True, exist_ok=True)
    files, links = [], []
    with data_archive(data) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts:
                raise RuntimeError('Unsafe archive member path.')
            if member.isfile() and path.name == 'copyright' and 'doc' in path.parts:
                if member.size > 2 * 1024 * 1024:
                    raise RuntimeError('Oversized copyright file.')
                (notices / (path.parent.name + '-copyright.txt')).write_bytes(archive.extractfile(member).read())
            if '.so' not in path.name:
                continue
            if member.issym():
                target = PurePosixPath(member.linkname)
                if target.is_absolute() or '..' in target.parts:
                    raise RuntimeError('Unsafe library symlink.')
                links.append((path.name, target.name))
                continue
            if not member.isfile():
                continue
            if member.size > 32 * 1024 * 1024:
                raise RuntimeError('Oversized library.')
            payload = archive.extractfile(member).read()
            if payload[:6] != b'\x7fELF\x02\x01' or int.from_bytes(payload[18:20], 'little') != 62:
                raise RuntimeError('Expected an x86-64 ELF library: ' + path.name)
            target = destination / path.name
            if target.is_symlink() or (target.exists() and target.read_bytes() != payload):
                raise RuntimeError('Conflicting runtime library: ' + path.name)
            target.write_bytes(payload)
            files.append(path.name)
    for name, target_name in links:
        if not (destination / target_name).is_file():
            continue  # Ignore unrelated symlinks; validate required SONAMEs below.
        link = destination / name
        if os.path.lexists(link):
            if not link.is_symlink() or os.readlink(link) != target_name:
                raise RuntimeError('Conflicting library link: ' + name)
        else:
            link.symlink_to(target_name)
    if not files:
        raise RuntimeError('No runtime libraries found in package.')
    return files


def install_libraries(lock_path, destination, cache):
    lock = json.loads(lock_path.read_text())
    provenance = []
    for package in lock['packages']:
        print('Runtime library: ' + package['name'], flush=True)
        data = download(package, cache)
        files = extract_libraries(data, destination / 'lib', destination / 'third-party-notices')
        provenance.append(dict(package, files=files))
    required = ['libpng12.so.0', 'libva.so.2', 'libvdpau.so.1', 'libva-x11.so.2',
                'libva-drm.so.2', 'libva-glx.so.2', 'libXfixes.so.3', 'libpulse.so.0']
    for name in required:
        if not (destination / 'lib' / name).is_file():
            raise RuntimeError('Missing extracted library: ' + name)
    write_json(destination / 'dependency-provenance.json', provenance)
