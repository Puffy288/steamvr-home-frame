"""Small, dependency-free client for Steam's LOCAL Chromium debugging API.

Uses only 127.0.0.1:8080 and the Steam SharedJSContext. Never enables a
network listener, changes authentication, or connects to remote debugging URLs.
"""
import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.parse
import urllib.request


class SteamUIError(RuntimeError):
    pass


class LocalOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # The local endpoint is fixed. Do not follow redirects to another
        # service, including another port on this machine.
        raise SteamUIError('Steam UI redirects are not accepted.')


class SteamUI:
    def __init__(self):
        self.sock = None
        self.counter = 0
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), LocalOnlyRedirects())
        try:
            with opener.open('http://127.0.0.1:8080/json', timeout=5) as response:
                data = response.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise SteamUIError('Oversized Steam UI target listing.')
                targets = json.loads(data)
            target = next(t for t in targets if t.get('title') == 'SharedJSContext'
                          and urllib.parse.urlsplit(t.get('url', '')).hostname == 'steamloopback.host')
            url = urllib.parse.urlsplit(target['webSocketDebuggerUrl'])
            if url.scheme != 'ws' or url.hostname != '127.0.0.1' or url.port != 8080:
                raise SteamUIError('Steam returned a non-local debugging URL.')
            self.sock = socket.create_connection(('127.0.0.1', 8080), timeout=15)
            key = base64.b64encode(os.urandom(16)).decode()
            request = (f'GET {url.path} HTTP/1.1\r\nHost: 127.0.0.1:8080\r\n'
                       f'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                       f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n')
            self.sock.sendall(request.encode())
            header = bytearray()
            while not header.endswith(b'\r\n\r\n'):
                header.extend(self.read(1))
                if len(header) > 16384:
                    raise SteamUIError('Oversized WebSocket handshake.')
            lines = header.decode().split('\r\n')
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            fields = {name.lower(): value.strip() for name, value in
                      (line.split(':', 1) for line in lines[1:] if ':' in line)}
            if ' 101 ' not in lines[0] or fields.get('sec-websocket-accept', '') != expected:
                raise SteamUIError('Steam rejected the WebSocket handshake.')
        except Exception as exc:
            self.close()
            raise SteamUIError('Cannot reach the Steam library UI. Keep Steam signed in and enable '
                               'CEF Remote Debugging in Steam Developer settings, then restart Steam '
                               'and run this installer again. See README.md.') from exc

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def read(self, count):
        data = bytearray()
        while len(data) < count:
            part = self.sock.recv(count - len(data))
            if not part:
                raise SteamUIError('Steam closed its UI connection.')
            data.extend(part)
        return bytes(data)

    def send(self, payload, opcode=1):
        mask = os.urandom(4)
        n = len(payload)
        header = bytes([0x80 | opcode])
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack('!H', n)
        else:
            header += bytes([0x80 | 127]) + struct.pack('!Q', n)
        self.sock.sendall(header + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(payload)))

    def receive(self):
        message = bytearray()
        while True:
            first, second = self.read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', self.read(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self.read(8))[0]
            if size > 16 * 1024 * 1024:
                raise SteamUIError('Oversized Steam UI response.')
            mask = self.read(4) if second & 128 else None
            payload = self.read(size)
            if mask:
                payload = bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
            opcode = first & 15
            if opcode == 8:
                raise SteamUIError('Steam closed its UI connection.')
            if opcode == 9:
                self.send(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1):
                raise SteamUIError('Unexpected WebSocket message.')
            message.extend(payload)
            if len(message) > 16 * 1024 * 1024:
                raise SteamUIError('Oversized Steam UI response.')
            if first & 128:
                return json.loads(message)

    def evaluate(self, expression, timeout=30):
        self.counter += 1
        self.sock.settimeout(timeout)
        self.send(json.dumps({'id': self.counter, 'method': 'Runtime.evaluate', 'params': {
            'expression': expression, 'returnByValue': True, 'awaitPromise': True,
            'timeout': timeout * 1000}}).encode())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.sock.settimeout(max(.1, deadline - time.monotonic()))
            reply = self.receive()
            if reply.get('id') != self.counter:
                continue
            if reply.get('error') or reply.get('result', {}).get('exceptionDetails'):
                raise SteamUIError('Steam UI operation failed: ' + json.dumps(reply)[:1600])
            return reply.get('result', {}).get('result', {}).get('value')
        raise SteamUIError('Steam UI operation timed out.')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
