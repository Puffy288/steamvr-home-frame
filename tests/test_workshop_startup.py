import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from workshop_startup import saved_workshop_id, prepare


class SavedHomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = self.root / 'game/steamtours/cfg/machine_vr.vcfg'
        self.cfg.parent.mkdir(parents=True)
        self.cfg.write_text('"schema"\n{\n"steamvrhome_home_map_type" "4"\n'
                            '"steamvrhome_home_map_addon" "2076552094"\n}\n')

    def tearDown(self):
        self.temp.cleanup()

    def test_tracks_future_home_choice_without_rewriting_config(self):
        self.assertEqual(saved_workshop_id(self.root), 2076552094)
        new = self.cfg.read_text().replace('2076552094', '927882107')
        self.cfg.write_text(new)
        self.assertEqual(saved_workshop_id(self.root), 927882107)
        self.assertEqual(self.cfg.read_text(), new)

    def test_builtin_and_invalid_or_ambiguous_ids_are_not_queried(self):
        original = self.cfg.read_text()
        for text in [original.replace('2076552094', 'steamvr_home'),
                     original.replace('2076552094', str(2**64)),
                     original.replace('2076552094', '12;quit'),
                     original + '"steamvrhome_home_map_addon" "123"\n']:
            self.cfg.write_text(text)
            self.assertIsNone(saved_workshop_id(self.root))

    def test_helper_failure_keeps_normal_startup_available(self):
        for failure in [subprocess.TimeoutExpired('helper', 15), OSError('unavailable')]:
            with patch('workshop_startup.subprocess.run', side_effect=failure):
                prepare(self.root, Path('/opt/steamvr'), {})
            self.assertFalse(json.loads((self.root/'logs/workshop-startup.json').read_text())['ready'])

    def test_crashed_helper_cannot_report_success(self):
        result = subprocess.CompletedProcess([], -11, '{"ready":true}\n', '')
        with patch('workshop_startup.subprocess.run', return_value=result) as run:
            prepare(self.root, Path('/opt/steamvr'), {'LD_PRELOAD': 'x86.so', 'LD_LIBRARY_PATH': 'x86'})
        self.assertFalse(json.loads((self.root/'logs/workshop-startup.json').read_text())['ready'])
        self.assertNotIn('LD_PRELOAD', run.call_args.kwargs['env'])
        self.assertNotIn('LD_LIBRARY_PATH', run.call_args.kwargs['env'])


if __name__ == '__main__':
    unittest.main()
