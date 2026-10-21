import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import coverage as adapter


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'coverage'
        self.folder.mkdir()
        (self.root / 'game').mkdir()
        (self.root / 'game/shader.vpk').write_bytes(b'game')
        (self.folder / 'libport2_coverage.so').write_bytes(b'own library')
        supported = {'files': {'shader.vpk': hashlib.sha256(b'game').hexdigest()}}
        (self.folder / 'supported-game.json').write_text(json.dumps(supported))
        integrity = {name: adapter.digest(self.folder/name) for name in
                     ['libport2_coverage.so', 'supported-game.json']}
        (self.folder / 'integrity.json').write_text(json.dumps(integrity))

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, env, native=True):
        with patch.object(adapter.platform, 'machine', return_value='aarch64'), \
             patch.object(adapter.subprocess, 'run', return_value=Mock(returncode=0)):
            return adapter.prepare(self.root, env, native)

    def test_valid_build_enables_private_layer(self):
        env = {'VK_INSTANCE_LAYERS': 'ANOTHER', 'VK_LAYER_PATH': '/existing'}
        self.assertEqual(self.prepare(env)[-1], '1')
        self.assertEqual(env['VK_INSTANCE_LAYERS'], 'VK_LAYER_PORT2_coverage:ANOTHER')
        self.assertTrue(env['VK_LAYER_PATH'].endswith(':/existing'))

    def test_changed_game_uses_normal_colour_rendering(self):
        (self.root / 'game/shader.vpk').write_bytes(b'changed')
        env = {}
        self.assertEqual(self.prepare(env)[-1], '0')
        self.assertNotIn('VK_INSTANCE_LAYERS', env)

    def test_missing_adapter_uses_normal_colour_rendering(self):
        (self.folder / 'libport2_coverage.so').unlink()
        self.assertEqual(self.prepare({})[-1], '0')

    def test_modified_adapter_is_not_loaded(self):
        (self.folder / 'libport2_coverage.so').write_bytes(b'changed')
        self.assertEqual(self.prepare({})[-1], '0')

    def test_emulated_driver_does_not_enable_prepass(self):
        self.assertEqual(self.prepare({}, native=False)[-1], '0')

    def test_missing_native_dependency_uses_normal_colour_rendering(self):
        with patch.object(adapter.platform, 'machine', return_value='aarch64'), \
             patch.object(adapter.subprocess, 'run', return_value=Mock(returncode=1)):
            self.assertEqual(adapter.prepare(self.root, {}, True)[-1], '0')


if __name__ == '__main__':
    unittest.main()
