from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'plugin'))

import turniej
from install import configure_collection


class TournamentLogicTests(unittest.TestCase):
    def test_normalize_server(self):
        self.assertEqual(turniej.normalize_server(' http://192.168.1.10:3000/ '), 'http://192.168.1.10:3000')
        self.assertEqual(turniej.normalize_server('localhost:3000'), 'http://localhost:3000')
        self.assertEqual(turniej.normalize_server('https://turniej.example.pl//'), 'https://turniej.example.pl')
        self.assertEqual(turniej.normalize_server(''), '')
        self.assertEqual(turniej.normalize_server(None), '')
        self.assertEqual(turniej.normalize_server('ftp://serwer'), '')

    def test_screen_url_marks_obs_mode(self):
        self.assertEqual(turniej.screen_url('192.168.1.10:3000/'), 'http://192.168.1.10:3000/screen?obs=1')

    def test_iter_events_reads_json_and_skips_noise(self):
        lines = [b': keepalive\n', b'data: {"view": "break"}\n', b'\n', b'data: nie-json\n', b'\n',
                 b'data: {"view":\n', b'data:  "round"}\n', b'\n', b'data: {"view": "lobby"}']
        events = list(turniej.iter_events(lines))
        self.assertEqual(events, [{'view': 'break'}, {'view': 'round'}])

    def test_wanted_scene(self):
        self.assertEqual(turniej.wanted_scene({'view': 'break', 'pendingRound': 2}), 'break')
        for view in ('round', 'lobby', 'scores', 'bracket'):
            self.assertEqual(turniej.wanted_scene({'view': view}), 'main')
        self.assertEqual(turniej.wanted_scene({}), 'main')
        self.assertIsNone(turniej.wanted_scene(['view']))
        self.assertIsNone(turniej.wanted_scene(None))


class InstallerTournamentTests(unittest.TestCase):
    collection = {'name': 'Test', 'sources': [], 'transitions': [], 'modules': {}}

    def settings(self, result, name):
        return next(s for s in result['modules']['scripts-tool'] if s['path'].endswith(name))['settings']

    def test_registers_tournament_script_with_server(self):
        target = Path(tempfile.gettempdir()) / 'obs-test'
        result = configure_collection(self.collection, target, tournament_server='http://192.168.1.10:3000')
        self.assertEqual(self.settings(result, 'turniej.py')['server'], 'http://192.168.1.10:3000')
        self.assertEqual(self.settings(result, 'przerwa.lua')['tournament_url'], 'http://192.168.1.10:3000')

    def test_defaults_and_reinstall_keep_saved_server(self):
        target = Path(tempfile.gettempdir()) / 'obs-test'
        first = configure_collection(self.collection, target)
        self.assertEqual(self.settings(first, 'turniej.py')['server'], 'http://localhost:3000')
        self.assertEqual(self.settings(first, 'przerwa.lua')['tournament_url'], '')
        saved = configure_collection(self.collection, target, tournament_server='http://turniej:3000')
        again = configure_collection(saved, target)
        self.assertEqual(self.settings(again, 'turniej.py')['server'], 'http://turniej:3000')
        self.assertEqual(self.settings(again, 'przerwa.lua')['tournament_url'], 'http://turniej:3000')


if __name__ == '__main__':
    unittest.main()
