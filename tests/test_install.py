import copy
import json
from pathlib import Path
import tempfile
import unittest

from install import configure_collection, ini_get, ini_set, prepare_local_files, initial_rules


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.collection = {
            'name': 'Test', 'current_scene': 'Camera',
            'sources': [{'id': 'scene', 'name': 'Camera', 'uuid': 'scene-a', 'settings': {'items': []}},
                        {'id': 'wasapi_input_capture', 'name': 'Test microphone', 'filters': [{'name': 'Gain'}]}],
            'transitions': [{'id': 'fade_transition', 'name': 'Fade'}, {'id': 'move_transition', 'name': 'Move'}],
            'modules': {'another-module': {'enabled': True}, 'scripts-tool': [
                {'path': 'C:/other/script.lua', 'settings': {'value': 42}},
                {'path': 'C:/old/przejscia-scen.lua', 'settings': {'saved_flag': True}}]}}

    def test_only_package_registrations_change(self):
        original = copy.deepcopy(self.collection)
        target = Path(tempfile.gettempdir()) / 'obs-test'
        result = configure_collection(self.collection, target, microphone='Selected mic')
        self.assertEqual(self.collection, original)
        self.assertEqual(result['sources'], original['sources'])
        self.assertEqual(result['transitions'], original['transitions'])
        self.assertEqual(result['current_scene'], original['current_scene'])
        self.assertEqual(result['modules']['another-module'], {'enabled': True})
        scripts = result['modules']['scripts-tool']
        self.assertEqual(scripts[0], original['modules']['scripts-tool'][0])
        engine = next(s for s in scripts if s['path'].endswith('przejscia-scen.lua'))
        self.assertEqual(engine['settings'], {'saved_flag': True, 'mic_name': 'Selected mic'})
        self.assertEqual(configure_collection(result, target), result)

    def test_detects_global_microphone(self):
        self.collection['AudioInputCapture1'] = {'name': 'Global mic'}
        result = configure_collection(self.collection, Path(tempfile.gettempdir()))
        engine = next(s for s in result['modules']['scripts-tool'] if s['path'].endswith('przejscia-scen.lua'))
        self.assertEqual(engine['settings']['mic_name'], 'Global mic')

    def test_builtin_fade_uses_obs_localized_default(self):
        self.collection['transitions'] = []
        self.assertEqual(initial_rules(self.collection)['collections']['Test']['exit_scene-a'], '')

    def test_ini_dock_json_does_not_modify_other_sections(self):
        text = '[General]\nPath64bit=leave-alone\n\n[BasicWindow]\nExtraBrowserDocks=[{"title":"Other"}]\n\n[Python]\nPath64bit=old\n'
        self.assertEqual(json.loads(ini_get(text, 'BasicWindow', 'ExtraBrowserDocks')), [{'title': 'Other'}])
        updated = ini_set(text, 'Python', 'Path64bit', 'D:/Python312')
        updated = ini_set(updated, 'NewSection', 'Path', 'D:/new')
        self.assertEqual(ini_get(updated, 'General', 'Path64bit'), 'leave-alone')
        self.assertEqual(ini_get(updated, 'Python', 'Path64bit'), 'D:/Python312')
        self.assertEqual(ini_get(updated, 'BasicWindow', 'ExtraBrowserDocks'), '[{"title":"Other"}]')
        self.assertEqual(ini_get(updated, 'NewSection', 'Path'), 'D:/new')
        self.assertEqual(ini_set(updated, 'Python', 'Path64bit', 'D:/Python312'), updated)

    def test_install_generates_private_token_and_preserves_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            prepare_local_files(target, self.collection)
            token = json.loads((target / 'panel-access.json').read_text(encoding='utf-8'))['token']
            self.assertGreaterEqual(len(token), 40)
            self.assertIn(token, (target / 'panel-config.js').read_text(encoding='utf-8'))
            path = target / 'przejscia-ustawienia.json'
            data = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(data['collections']['Test']['exit_scene-a'], 'Move')
            data['collections']['Test']['exit_scene-a'] = 'Fade'
            data['collections']['Other collection'] = {'keep': True}
            path.write_text(json.dumps(data), encoding='utf-8')
            prepare_local_files(target, self.collection)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), data)
            self.assertEqual(json.loads((target / 'panel-access.json').read_text(encoding='utf-8'))['token'], token)


if __name__ == '__main__':
    unittest.main()
