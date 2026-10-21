import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import struct
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from libraries import extract_libraries, data_archive, download, ValveOnlyRedirects
from common import live_process, identity, write_json
from install import merge_assets, require_fresh_destination
from shortcut import add_shortcut, remove_shortcut
from steamui import LocalOnlyRedirects, SteamUIError
from quality import configure_quality
from vr_application import manifest


def deb(entries):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w:gz') as archive:
        for name, content, link in entries:
            item = tarfile.TarInfo(name)
            if link:
                item.type = tarfile.SYMTYPE
                item.linkname = link
                archive.addfile(item)
            else:
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
    data = payload.getvalue()
    header = f'{"data.tar.gz/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(data):<10}`\n'.encode()
    return b'!<arch>\n' + header + data + (b'\n' if len(data) % 2 else b'')


def elf(machine=62):
    data = bytearray(80)
    data[:6] = b'\x7fELF\x02\x01'
    data[18:20] = machine.to_bytes(2, 'little')
    return bytes(data)


def make_manifest(root, names):
    def number(n):
        out = bytearray()
        while n > 127:
            out.append((n & 127) | 128)
            n >>= 7
        return bytes(out) + bytes([n])
    def value(tag, data):
        return number(tag * 8 + 2) + number(len(data)) + data
    payload = b''
    for name in names:
        data = (root / name).read_bytes()
        item = value(1, ('tools/steamvr_environments/game/' + name).encode())
        item += number(2 * 8) + number(len(data))
        item += value(5, hashlib.sha1(data).digest())
        payload += value(1, item)
    path = root.parent / 'test.manifest'
    path.write_bytes(struct.pack('<II', 0x71F617D0, len(payload)) + payload)
    return path


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def extract(self, entries):
        return extract_libraries(deb(entries), self.root / 'lib', self.root / 'notices')

    def test_only_libraries_and_notices(self):
        self.extract([('./usr/lib/x86_64-linux-gnu/libsample.so.1.0', elf(), None),
                      ('./usr/lib/x86_64-linux-gnu/libsample.so.1', b'', 'libsample.so.1.0'),
                      ('./usr/share/doc/sample/copyright', b'copyright notice', None),
                      ('./postinst', b'never run this', None)])
        self.assertEqual((self.root/'lib/libsample.so.1').read_bytes(), elf())
        self.assertEqual((self.root/'notices/sample-copyright.txt').read_text(), 'copyright notice')
        self.assertFalse((self.root/'postinst').exists())

    def test_reject_path_traversal(self):
        with self.assertRaises(RuntimeError):
            self.extract([('../../escaped.so', elf(), None)])
        self.assertFalse((self.root.parent/'escaped.so').exists())

    def test_reject_outside_symlink(self):
        with self.assertRaises(RuntimeError):
            self.extract([('usr/lib/libbad.so', b'', '../../outside')])

    def test_reject_host_architecture(self):
        with self.assertRaises(RuntimeError):
            self.extract([('usr/lib/libbad.so', elf(183), None)])

    def test_reject_conflicting_libraries(self):
        self.extract([('usr/lib/libsample.so.1', elf(), None)])
        with self.assertRaises(RuntimeError):
            self.extract([('usr/lib/libsample.so.1', elf()+b'changed', None)])

    def test_reject_invalid_archive(self):
        with self.assertRaises(RuntimeError):
            data_archive(b'not a package')

    def test_bad_checksum_never_cached_or_extracted(self):
        class Response(io.BytesIO):
            url = 'https://repo.steampowered.com/file.deb'
        package = {'name': 'sample', 'url': Response.url, 'sha256': '0'*64, 'size': 3}
        with patch('urllib.request.build_opener', return_value=Mock(open=Mock(return_value=Response(b'bad')))):
            with self.assertRaisesRegex(RuntimeError, 'mismatch'):
                download(package, self.root/'cache')
        self.assertEqual(list((self.root/'cache').iterdir()), [])

    def test_non_valve_url_rejected(self):
        with self.assertRaises(RuntimeError):
            download({'url':'https://example.com/package.deb'},self.root/'cache')

    def test_verified_cache_reused(self):
        data = b'cached package'
        sha = hashlib.sha256(data).hexdigest()
        cache = self.root/'cache'
        cache.mkdir()
        (cache/(sha+'.deb')).write_bytes(data)
        package = {'url':'https://repo.steampowered.com/file.deb','sha256':sha,'size':len(data)}
        with patch('urllib.request.build_opener', side_effect=AssertionError('network not needed')):
            self.assertEqual(download(package, cache), data)

    def test_redirect_outside_valve_rejected_before_fetch(self):
        with self.assertRaisesRegex(RuntimeError,'redirect outside'):
            ValveOnlyRedirects().redirect_request(None,None,302,'Found',{},'https://example.com/file')


class LayoutTests(unittest.TestCase):
    def test_quality_changes_do_not_write_through_depot_link(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, game = root/'source', root/'game'
            source.mkdir()
            (game/'steamtours/cfg').mkdir(parents=True)
            original = ('"SunLightMaxShadowBufferSize" "3072"\n'
                        '"VrDefaultShadowTextureWidth" "6144"\n'
                        '"VrDefaultShadowTextureHeight" "6144"\n'
                        '"CubemapFog" "1"\n')
            depot = root/'depot-gameinfo.gi'
            depot.write_text(original)
            target = game/'steamtours/gameinfo.gi'
            target.symlink_to(depot)
            (source/'frame-fidelity.csv').write_text('profile')
            (source/'frame-quality.cfg').write_text('settings')
            configure_quality(source, game)
            self.assertEqual(depot.read_text(), original)
            self.assertFalse(target.is_symlink())
            self.assertIn('"CubemapFog" "1"', target.read_text())
            self.assertIn('"SunLightMaxShadowBufferSize" "1536"', target.read_text())

    def test_unknown_gameinfo_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'game/steamtours').mkdir(parents=True)
            target = root/'game/steamtours/gameinfo.gi'
            target.write_text('unexpected format')
            with self.assertRaisesRegex(RuntimeError, 'Unrecognized'):
                configure_quality(root, root/'game')
            self.assertEqual(target.read_text(), 'unexpected format')

    def test_vr_manifest_cannot_claim_valves_content_app(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(RuntimeError, 'non-Steam'):
                manifest(root, 250820)
            self.assertFalse((root/'port2.vrmanifest').exists())
            path = manifest(root, 4198328907)
            application = json.loads(path.read_text())['applications'][0]
            self.assertEqual(application['app_key'], 'steam.app.4198328907')
            self.assertEqual(application['binary_path_linux'], str(root/'Launch.sh'))
            self.assertEqual(application['binary_path_linux_arm'], str(root/'Launch.sh'))
            self.assertNotIn('image_path', application)
            cover = root/'home-cover.png'
            cover.write_bytes(b'local downloaded cover')
            application = json.loads(manifest(root, 4198328907).read_text())['applications'][0]
            self.assertEqual(application['image_path'], str(cover))
            cover.unlink()
            cover.symlink_to(root/'missing.png')
            application = json.loads(manifest(root, 4198328907).read_text())['applications'][0]
            self.assertNotIn('image_path', application)

    def test_main_executable_is_copied_for_private_game_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            binary=root/'binary/bin/linuxsteamrt64'
            binary.mkdir(parents=True)
            (binary/'steamtours').write_bytes(b'program')
            manifest = make_manifest(root/'binary', ['bin/linuxsteamrt64/steamtours'])
            merge_assets(root/'binary',root/'game',manifest)
            executable=root/'game/bin/linuxsteamrt64/steamtours'
            self.assertFalse(executable.is_symlink())
            self.assertEqual(executable.read_bytes(),b'program')

    def test_depots_unchanged_and_cfg_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            assets=root/'assets'
            (assets/'steamtours/cfg').mkdir(parents=True)
            (assets/'steamtours/cfg/default.cfg').write_text('default')
            (assets/'steamtours/content.vpk').write_bytes(b'asset')
            manifest = make_manifest(assets, ['steamtours/cfg/default.cfg', 'steamtours/content.vpk'])
            (assets/'steamtours/cfg/machine_vr.vcfg').write_text('private old saved room')
            merge_assets(assets,root/'game',manifest)
            cfg=root/'game/steamtours/cfg/default.cfg'
            self.assertFalse(cfg.is_symlink())
            cfg.write_text('changed')
            self.assertEqual((assets/'steamtours/cfg/default.cfg').read_text(),'default')
            self.assertTrue((root/'game/steamtours/content.vpk').is_symlink())
            self.assertFalse((root/'game/steamtours/cfg/machine_vr.vcfg').exists())

    def test_changed_valve_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); assets = root/'assets'; assets.mkdir()
            (assets/'file').write_bytes(b'known')
            manifest = make_manifest(assets, ['file'])
            (assets/'file').write_bytes(b'other')
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                merge_assets(assets, root/'game', manifest)
            self.assertFalse((root/'game/file').exists())

    def test_existing_install_and_dangling_link_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); install = root/'existing'; install.mkdir()
            (install/'save').write_text('keep me')
            with self.assertRaisesRegex(RuntimeError, 'fresh installation'):
                require_fresh_destination(install)
            self.assertEqual((install/'save').read_text(), 'keep me')
            link = root/'link'; link.symlink_to(root/'absent')
            with self.assertRaisesRegex(RuntimeError, 'fresh installation'):
                require_fresh_destination(link)
            require_fresh_destination(root/'unused')

    def test_stale_pid_not_claimed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json'
            write_json(path,{'pid':os.getpid(),'start_ticks':'not-the-same-process'})
            self.assertIsNone(live_process(path))
            write_json(path,{'pid':os.getpid(),'start_ticks':identity(os.getpid())})
            self.assertIsNotNone(live_process(path))


class ShortcutTests(unittest.TestCase):
    def test_local_ui_never_follows_redirects(self):
        with self.assertRaises(SteamUIError):
            LocalOnlyRedirects().redirect_request(None, None, 302, 'Found', {}, 'https://example.com/')

    def test_matching_shortcut_is_reused(self):
        class UI:
            calls=[]
            def evaluate(self, text):
                self.calls.append(text)
                if text.startswith('appStore.'):
                    return [{'id':123,'name':'SteamVR Home (Frame - Unofficial)'}]
                return True
        ui=UI()
        with patch('shortcut.details',return_value={'exe':'"/example/Launch.sh"','name':'SteamVR Home (Frame - Unofficial)','vr':True}):
            self.assertEqual(add_shortcut(ui,Path('/example')),123)
        self.assertFalse(any('AddShortcut' in call for call in ui.calls))

    def test_same_name_different_target_preserved(self):
        class UI:
            def evaluate(self,text):
                return [{'id':123,'name':'SteamVR Home (Frame - Unofficial)'}]
        with patch('shortcut.details',return_value={'exe':'"/someone-elses/Launch.sh"','vr':True}):
            with self.assertRaisesRegex(RuntimeError,'different shortcut'):
                add_shortcut(UI(),Path('/example'))

    def test_uninstall_preserves_changed_shortcut(self):
        class UI:
            def evaluate(self,text):
                if 'RemoveShortcut' in text:
                    raise AssertionError('must not remove changed shortcut')
                return [123]
        with patch('shortcut.details',return_value={'exe':'"/other/tool"'}):
            with self.assertRaisesRegex(RuntimeError,'target has changed'):
                remove_shortcut(UI(),Path('/example'),123)


if __name__=='__main__':
    unittest.main()
