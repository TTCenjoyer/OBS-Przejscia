from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'plugin'))

import turniej
import json

from install import configure_collection, merge_times_square, TS_BOARD, TS_PLACEHOLDER


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
        self.assertEqual(turniej.wanted_scene({'view': 'break', 'pendingRound': 2, 'round': 1}), 'break')
        self.assertEqual(turniej.wanted_scene({'view': 'break', 'round': 0}), 'break')
        # przed startem turnieju (brak rundy) pokazujemy otwarcie, potem ekran turnieju
        self.assertEqual(turniej.wanted_scene({'view': 'lobby', 'round': 0}), 'intro')
        self.assertEqual(turniej.wanted_scene({}), 'intro')
        for view in ('round', 'lobby', 'scores', 'bracket'):
            self.assertEqual(turniej.wanted_scene({'view': view, 'round': 2}), 'main')
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


def fake_times_square(root):
    """Minimalny szablon w układzie repozytorium Times-Square-OBS."""
    scene = lambda name, uid, items: {'id': 'scene', 'name': name, 'uuid': uid, 'settings': {'items': items}}
    item = lambda name, uid: {'name': name, 'source_uuid': uid, 'id': 1}
    template = {'name': 'Times Square LIVE', 'scene_order': [{'name': '01 | Obraz na billboardach'}, {'name': '02 | Times Square LIVE'}],
                'sources': [
                    {'id': 'browser_source', 'name': TS_PLACEHOLDER, 'uuid': 'u-board',
                     'settings': {'is_local_file': True, 'local_file': '${ROOT}/samples/plansza-live.html', 'width': 1920}},
                    scene('01 | Obraz na billboardach', 'u-s1', [item(TS_PLACEHOLDER, 'u-board')]),
                    {'id': 'ffmpeg_source', 'name': 'Times Square - tlo 30 s + tracking', 'uuid': 'u-film',
                     'filters': [{'id': 'times_square_live_v1'}], 'settings': {'local_file': '${ROOT}/old.mkv'}},
                    scene('02 | Times Square LIVE', 'u-s2', [item('01 | Obraz na billboardach', 'u-s1'),
                                                             item('Times Square - tlo 30 s + tracking', 'u-film')])],
                'modules': {'scripts-tool': [{'path': '${ROOT}/obs/times-square-live.lua', 'settings': {}}]}}
    (root / 'obs').mkdir(parents=True)
    (root / 'obs' / 'scene-collection.template.json').write_text(json.dumps(template), encoding='utf-8')


class TimesSquareMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / 'Times-Square-OBS'
        fake_times_square(self.repo)
        self.atlas = Path(self.temp.name) / 'film.mkv'
        self.collection = {'name': 'Moja', 'scene_order': [{'name': 'Kamera'}], 'modules': {'scripts-tool': [{'path': 'C:/x/inny.lua', 'settings': {}}]},
                           'sources': [{'id': 'scene', 'name': 'Kamera', 'uuid': 'u-s1', 'settings': {'items': []}}]}

    def tearDown(self):
        self.temp.cleanup()

    def by_name(self, data):
        return {s['name']: s for s in data['sources']}

    def test_adds_scenes_board_and_script_without_touching_rest(self):
        original = json.loads(json.dumps(self.collection))
        result = merge_times_square(self.collection, self.repo, self.atlas, 'http://serwer:3000/')
        self.assertEqual(self.collection, original)
        sources = self.by_name(result)
        self.assertEqual(sources['Kamera'], original['sources'][0])
        board = sources[TS_BOARD]['settings']
        self.assertEqual(board['url'], 'http://serwer:3000/start.html?obs=1')
        self.assertNotIn('local_file', board)
        self.assertFalse(board['is_local_file'])
        self.assertNotIn(TS_PLACEHOLDER, sources)
        self.assertEqual(sources['Times Square - tlo 30 s + tracking']['settings']['local_file'], self.atlas.as_posix())
        self.assertEqual([o['name'] for o in result['scene_order']], ['Kamera', '01 | Obraz na billboardach', '02 | Times Square LIVE'])
        self.assertEqual(result['modules']['scripts-tool'][0], {'path': 'C:/x/inny.lua', 'settings': {}})
        self.assertTrue(result['modules']['scripts-tool'][1]['path'].endswith('obs/times-square-live.lua'))

    def test_uuid_collision_is_remapped_and_items_follow(self):
        result = merge_times_square(self.collection, self.repo, self.atlas)  # 'u-s1' zajęte przez „Kamera”
        sources = self.by_name(result)
        new_uuid = sources['01 | Obraz na billboardach']['uuid']
        self.assertNotEqual(new_uuid, 'u-s1')
        items = sources['02 | Times Square LIVE']['settings']['items']
        self.assertEqual(items[0]['source_uuid'], new_uuid)
        self.assertEqual(items[1]['source_uuid'], sources['Times Square - tlo 30 s + tracking']['uuid'])
        board_item = sources['01 | Obraz na billboardach']['settings']['items'][0]
        self.assertEqual((board_item['name'], board_item['source_uuid']), (TS_BOARD, sources[TS_BOARD]['uuid']))
        self.assertEqual(len({s['uuid'] for s in result['sources']}), len(result['sources']))

    def test_repeat_is_idempotent_and_updates_only_paths(self):
        first = merge_times_square(self.collection, self.repo, self.atlas, 'http://a:3000')
        again = merge_times_square(first, self.repo, self.atlas, 'http://a:3000')
        self.assertEqual(again, first)
        moved = merge_times_square(first, self.repo, self.atlas.with_name('nowy.mkv'), 'http://b:3000')
        sources = self.by_name(moved)
        self.assertEqual(len(moved['sources']), len(first['sources']))
        self.assertEqual(sources[TS_BOARD]['settings']['url'], 'http://b:3000/start.html?obs=1')
        self.assertTrue(sources['Times Square - tlo 30 s + tracking']['settings']['local_file'].endswith('nowy.mkv'))
        kept = merge_times_square(first, self.repo, self.atlas)  # bez adresu: zostaje zapisany
        self.assertEqual(self.by_name(kept)[TS_BOARD]['settings']['url'], 'http://a:3000/start.html?obs=1')

    def test_configure_collection_accepts_times_square(self):
        result = configure_collection(self.collection, Path(self.temp.name) / 'obs', tournament_server='http://a:3000',
                                      times_square=(self.repo, self.atlas))
        self.assertIn('02 | Times Square LIVE', self.by_name(result))
        names = [Path(s['path']).name for s in result['modules']['scripts-tool']]
        self.assertIn('turniej.py', names)
        self.assertIn('times-square-live.lua', names)


if __name__ == '__main__':
    unittest.main()
