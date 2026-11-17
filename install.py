"""Windows installer. Run with 64-bit Python 3.12 while OBS is closed."""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import sys
import uuid

FILES = ('przerwa.lua', 'przejscia-scen.lua', 'panel-przejsc.py', 'panel.html')
SCRIPTS = FILES[:3]
BREAK_SCENE = 'Przerwa — Beyond the Sea'


def ini_get(text, section, key):
    match = re.search(r'(?ms)^\[' + re.escape(section) + r'\][^\n]*\n(.*?)(?=^\[|\Z)', text)
    value = re.search(r'(?m)^' + re.escape(key) + r'=(.*)$', match[1]) if match else None
    return value[1].strip() if value else None


def ini_set(text, section, key, value):
    header = re.search(r'(?m)^\[' + re.escape(section) + r'\][^\n]*\n?', text)
    if header is None:
        return text.rstrip() + '\n\n[' + section + ']\n' + key + '=' + value + '\n'
    tail = text[header.end():]
    next_header = re.search(r'(?m)^\[', tail)
    end = header.end() + (next_header.start() if next_header else len(tail))
    body = text[header.end():end]
    pattern = r'(?m)^' + re.escape(key) + r'=[^\n]*'
    line = key + '=' + value
    if re.search(pattern, body):
        body = re.sub(pattern, lambda _: line, body)
    else:
        body = body.rstrip('\n') + ('\n' if body else '') + line + '\n'
    return text[:header.end()] + body + text[end:]


def configure_collection(original, target, microphone=None, intro=None, loop=None):
    """Change only this package's script registrations; retain scenes and sources."""
    data = copy.deepcopy(original)
    scripts = data.setdefault('modules', {}).setdefault('scripts-tool', [])
    for name in SCRIPTS:
        matches = [s for s in scripts if Path(s.get('path', '').replace('\\', '/')).name == name]
        settings = copy.deepcopy(matches[0].get('settings', {})) if matches else {}
        if name == 'przerwa.lua':
            for key, path in [('intro', intro), ('loop', loop)]:
                if path is not None:
                    settings[key] = Path(path).resolve().as_posix()
                else:
                    settings.setdefault(key, '')
        elif name == 'przejscia-scen.lua':
            default_mic = original.get('AudioInputCapture1', {}).get('name')
            if not default_mic:
                default_mic = next((s['name'] for s in original.get('sources', [])
                                    if s.get('id') == 'wasapi_input_capture'), 'Mikrofon/Wejście liniowe')
            if microphone is not None:
                settings['mic_name'] = microphone
            else:
                settings.setdefault('mic_name', default_mic)
        scripts[:] = [s for s in scripts if s not in matches]
        scripts.append({'path': (target / name).as_posix(), 'settings': settings})
    return data


def initial_rules(data):
    transitions = data.get('transitions', [])
    # OBS often omits built-in Fade from the collection JSON. An empty value
    # lets the engine resolve its localized name from the running OBS instance.
    fade = next((t['name'] for t in transitions if t.get('id') == 'fade_transition'), '')
    move = next((t['name'] for t in transitions if t.get('id') == 'move_transition'), fade)
    rules = {}
    for source in data.get('sources', []):
        if source.get('id') != 'scene' or not source.get('uuid'):
            continue
        key = source['uuid']
        rules.update({'exit_' + key: fade if source['name'] == BREAK_SCENE else move,
                      'exit_' + key + '_ms': 1000, 'entry_' + key: '', 'entry_' + key + '_ms': 0})
    # A new break scene will receive its UUID when OBS first loads the Lua script.
    return {'version': 2, 'collections': {data['name']: rules}}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def prepare_local_files(target, collection):
    target.mkdir(parents=True, exist_ok=True)
    if not (target / 'panel-access.json').exists():
        write_json(target / 'panel-access.json', {'token': secrets.token_urlsafe(32)})
    token = json.loads((target / 'panel-access.json').read_text(encoding='utf-8'))['token']
    (target / 'panel-config.js').write_text(
        'window.OBS_PANEL_CONFIG = ' + json.dumps({'base': 'http://127.0.0.1:17863', 'token': token}) + ';\n',
        encoding='utf-8')
    path = target / 'przejscia-ustawienia.json'
    rules = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {'version': 2, 'collections': {}}
    for name, values in initial_rules(collection)['collections'].items():
        existing = rules.setdefault('collections', {}).setdefault(name, {})
        for key, value in values.items():
            existing.setdefault(key, value)
    write_json(path, rules)


def obs_running():
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq obs64.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, check=True)
    return any(row and row[0].lower() == 'obs64.exe' for row in csv.reader(io.StringIO(result.stdout)))


def main():
    parser = argparse.ArgumentParser(description='Instalacja panelu i skryptów OBS Przejścia (zamknij OBS).')
    parser.add_argument('--config-dir', type=Path, help='Katalog konfiguracji OBS, również w wersji portable')
    parser.add_argument('--collection', help='Nazwa pliku kolekcji w basic/scenes, np. Kolekcja.json')
    parser.add_argument('--destination', type=Path, help='Stały katalog instalacji')
    parser.add_argument('--microphone', help='Dokładna nazwa źródła mikrofonu wyciszanego na przerwie')
    parser.add_argument('--intro', type=Path, help='Własny plik audio odtwarzany raz')
    parser.add_argument('--loop', type=Path, help='Własny plik audio odtwarzany w pętli')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        parser.error('Wymagany Windows i 64-bitowy Python 3.12.')
    if obs_running():
        parser.error('Zamknij OBS przed instalacją. Instalator nie zamyka go automatycznie.')
    for path in (args.intro, args.loop):
        if path is not None and not path.is_file():
            parser.error('Plik audio nie istnieje: ' + str(path))
    config = (args.config_dir or Path(os.environ['APPDATA']) / 'obs-studio').resolve()
    target = (args.destination or Path(os.environ['LOCALAPPDATA']) / 'OBS-Przejscia').resolve()
    user_ini = config / 'user.ini'
    text = user_ini.read_text(encoding='utf-8-sig')
    filename = args.collection or ini_get(text, 'Basic', 'SceneCollectionFile')
    if not filename or Path(filename).name != filename:
        parser.error('Nie znaleziono aktywnej kolekcji. Uruchom OBS przynajmniej raz lub podaj --collection.')
    if not filename.endswith('.json'):
        filename += '.json'
    scene_path = config / 'basic' / 'scenes' / filename
    data = json.loads(scene_path.read_text(encoding='utf-8-sig'))
    docks = json.loads(ini_get(text, 'BasicWindow', 'ExtraBrowserDocks') or '[]')
    dock = next((d for d in docks if d.get('title') == 'Przejścia scen'), None)
    if dock is None:
        dock = {'title': 'Przejścia scen', 'uuid': uuid.uuid4().hex}
        docks.append(dock)
    dock['url'] = (target / 'panel.html').as_uri()
    text = ini_set(text, 'BasicWindow', 'ExtraBrowserDocks', json.dumps(docks, ensure_ascii=False, separators=(',', ':')))
    text = ini_set(text, 'Python', 'Path64bit', Path(sys.executable).parent.as_posix())
    updated = configure_collection(data, target, args.microphone, args.intro, args.loop)

    target.mkdir(parents=True, exist_ok=True)
    backup = target / 'backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup.mkdir(parents=True)
    shutil.copy2(user_ini, backup / 'user.ini')
    shutil.copy2(scene_path, backup / scene_path.name)
    source = Path(__file__).resolve().parent
    for name in FILES:
        shutil.copy2(source / 'plugin' / name, target / name)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', '--target', str(target / 'runtime'),
                    '-r', str(source / 'requirements.txt')], check=True)
    prepare_local_files(target, data)
    # Stop before writing OBS configuration if it was opened during dependency installation.
    if obs_running():
        parser.error('OBS został otwarty podczas instalacji. Zamknij go i uruchom instalator ponownie.')
    try:
        write_json(scene_path, updated)
        user_ini.write_text(text, encoding='utf-8')
    except OSError:
        shutil.copy2(backup / 'user.ini', user_ini)
        shutil.copy2(backup / scene_path.name, scene_path)
        raise
    print('Zainstalowano w:', target)
    print('Kopia konfiguracji:', backup)
    print('Uruchom OBS. Pliki muzyki wybierzesz w Narzędzia > Skrypty > przerwa.lua.')
    print('GIF / MP4 wybierzesz we właściwościach źródła Przerwa | GIF — wybierz plik.')


if __name__ == '__main__':
    main()
