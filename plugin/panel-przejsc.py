"""OBS integration for the scene-transition browser dock."""
from pathlib import Path
import ctypes
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'runtime'))
import obspython as obs
from PySide6 import QtCore
import shiboken6

RULES = ROOT / 'przejscia-ustawienia.json'
TOKEN = json.loads((ROOT / 'panel-access.json').read_text(encoding='utf-8'))['token']
api = ctypes.CDLL('obs-frontend-api.dll')
api.obs_frontend_get_main_window.restype = ctypes.c_void_p
qt_widgets = ctypes.CDLL('Qt6Widgets.dll')
split_dock = getattr(qt_widgets, '?splitDockWidget@QMainWindow@@QEAAXPEAVQDockWidget@@0W4Orientation@Qt@@@Z')
split_dock.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
split_dock.restype = None
manager = None
server = None
cache = {'ready': False}
cache_lock = threading.Lock()
rules_lock = threading.Lock()


def read_rules():
    try:
        return json.loads(RULES.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {'version': 2, 'collections': {}}


def save_rules(data):
    temp = RULES.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, RULES)


class DockManager(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.main = shiboken6.wrapInstance(api.obs_frontend_get_main_window(), QtCore.QObject)
        self.placed = False
        self.changed.connect(self.apply_rules, QtCore.Qt.ConnectionType.QueuedConnection)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    @QtCore.Slot()
    def refresh(self):
        collection = obs.obs_frontend_get_current_scene_collection() or ''
        sources = obs.obs_frontend_get_scenes() or []
        scenes = [{'name': obs.obs_source_get_name(s), 'uuid': obs.obs_source_get_uuid(s)} for s in sources]
        obs.source_list_release(sources)
        transitions = obs.obs_frontend_get_transitions() or []
        effects = [{'name': obs.obs_source_get_name(s), 'kind': obs.obs_source_get_id(s)} for s in transitions]
        obs.source_list_release(transitions)
        current = obs.obs_frontend_get_current_scene()
        current_uuid = obs.obs_source_get_uuid(current) if current else ''
        current_name = obs.obs_source_get_name(current) if current else ''
        if current:
            obs.obs_source_release(current)
        data = read_rules().get('collections', {}).get(collection, {})
        data = {k: v for k, v in data.items() if k.startswith(('entry_', 'exit_'))}
        with cache_lock:
            cache.clear()
            cache.update({'ready': True, 'collection': collection, 'scenes': scenes, 'effects': effects,
                          'current_uuid': current_uuid, 'current_name': current_name, 'rules': data})
        if not self.placed:
            self.place_dock()

    def place_dock(self):
        original = self.main.findChild(QtCore.QObject, 'transitionsDock')
        custom = None
        for child in self.main.findChildren(QtCore.QObject):
            if child.property('windowTitle') == 'Przejścia scen' and 'Dock' in child.metaObject().className():
                custom = child
                break
        if custom is None:
            return
        custom.setProperty('minimumWidth', 270)
        custom.setProperty('minimumHeight', 300)
        if original is not None and original.property('visible'):
            split_dock(shiboken6.getCppPointer(self.main)[0], shiboken6.getCppPointer(original)[0],
                       shiboken6.getCppPointer(custom)[0], 2)
        custom.setProperty('floating', False)
        custom.setProperty('visible', True)
        if original is not None:
            original.setProperty('visible', False)
        self.placed = True
        obs.script_log(obs.LOG_INFO, 'Panel Przejścia scen zastąpił standardowy panel przejść.')

    @QtCore.Slot()
    def apply_rules(self):
        current = obs.obs_frontend_get_current_scene()
        if not current:
            return
        collection = obs.obs_frontend_get_current_scene_collection()
        rules = read_rules().get('collections', {}).get(collection, {})
        uuid = obs.obs_source_get_uuid(current)
        kind = 'fade_transition' if obs.obs_source_get_name(current) == 'Przerwa — Beyond the Sea' else 'move_transition'
        transitions = obs.obs_frontend_get_transitions() or []
        effects = {obs.obs_source_get_id(t): obs.obs_source_get_name(t) for t in transitions}
        default = effects.get(kind) or effects.get('fade_transition', '')
        obs.source_list_release(transitions)
        exit_name = rules.get('exit_' + uuid) or default
        exit_ms = int(rules.get('exit_' + uuid + '_ms', 1000) or 1000)
        obs.obs_source_release(current)
        scenes = obs.obs_frontend_get_scenes() or []
        for scene in scenes:
            key = 'entry_' + obs.obs_source_get_uuid(scene)
            private = obs.obs_source_get_private_settings(scene)
            obs.obs_data_set_string(private, 'transition', rules.get(key) or exit_name)
            obs.obs_data_set_int(private, 'transition_duration', int(rules.get(key + '_ms', 0) or exit_ms))
            obs.obs_data_release(private)
        obs.source_list_release(scenes)
        self.refresh()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_OPTIONS(self):
        self.respond(204, {})

    def respond(self, status, data):
        self.send_response(status)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if status != 204:
            try:
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
            return self.respond(403, {'error': 'Brak dostępu'})
        if self.path != '/state':
            return self.respond(404, {})
        with cache_lock:
            snapshot = dict(cache)
        self.respond(200, snapshot)

    def do_POST(self):
        if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
            return self.respond(403, {'error': 'Brak dostępu'})
        if self.path != '/rules':
            return self.respond(404, {})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length < 65536:
                raise ValueError('Nieprawidłowe dane')
            payload = json.loads(self.rfile.read(length))
            with cache_lock:
                state = dict(cache)
            names = {e['name'] for e in state.get('effects', [])} | {''}
            if payload['collection'] != state.get('collection'):
                raise ValueError('Kolekcja scen została zmieniona')
            if payload['scene'] not in {s['uuid'] for s in state.get('scenes', [])}:
                raise ValueError('Scena nie istnieje')
            if payload['exit'] not in names or payload['entry'] not in names:
                raise ValueError('Efekt nie istnieje')
            exit_ms, entry_ms = int(payload['exit_ms']), int(payload['entry_ms'])
            if not 50 <= exit_ms <= 60000 or not 0 <= entry_ms <= 60000:
                raise ValueError('Nieprawidłowy czas')
            with rules_lock:
                data = read_rules()
                rules = data.setdefault('collections', {}).setdefault(payload['collection'], {})
                key = payload['scene']
                rules['exit_' + key], rules['exit_' + key + '_ms'] = payload['exit'], exit_ms
                rules['entry_' + key], rules['entry_' + key + '_ms'] = payload['entry'], entry_ms
                save_rules(data)
            if manager is not None:
                manager.changed.emit()
            self.respond(200, {'ok': True})
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.respond(400, {'error': str(error)})


def create_manager():
    global manager
    if manager is None:
        manager = DockManager()


def on_event(event):
    global manager
    if event in (obs.OBS_FRONTEND_EVENT_FINISHED_LOADING, obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGED):
        create_manager()
    elif event in (obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CLEANUP, obs.OBS_FRONTEND_EVENT_EXIT):
        if manager is not None:
            manager.timer.stop()
            manager.deleteLater()
            manager = None


def script_description():
    return '<b>Panel Przejścia scen</b><br>Panel zastępuje standardowe Efekty przejścia scen i śledzi scenę na programie.'


def script_load(settings):
    global server
    obs.obs_frontend_add_event_callback(on_event)
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(('127.0.0.1', 17863), Handler)
    server.daemon_threads = True
    threading.Thread(target=lambda: server.serve_forever(poll_interval=.1), daemon=True).start()


def script_unload():
    global server, manager
    obs.obs_frontend_remove_event_callback(on_event)
    if manager is not None:
        manager.timer.stop()
        manager.deleteLater()
        manager = None
    if server is not None:
        server.shutdown()
        server.server_close()
        server = None
