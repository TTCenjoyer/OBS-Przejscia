"""Integracja OBS z serwerem turnieju TTC: scena na programie zależy od tego, co pokazuje ekran widowni.

Skrypt słucha publicznego strumienia stanu ekranu (`/events?role=screen`), niczego do serwera nie wysyła.
Gdy turniej przechodzi w przerwę techniczną, OBS przełącza się na scenę przerwy; po przerwie wraca na
scenę z ekranem turnieju. Przełączenie przechodzi przez zwykłe reguły przejść z panelu „Przejścia scen”
(Zanikanie, wyciszanie mikrofonu, muzyka przerwy).
"""
import json
import threading
import urllib.error
import urllib.request

try:
    import obspython as obs
except ImportError:  # testy poza OBS
    obs = None

DEFAULT_SERVER = 'http://localhost:3000'
MAIN_SCENE = 'Turniej — Ekran'
MAIN_SOURCE = 'Turniej | Ekran'
BREAK_SCENE = 'Przerwa — Beyond the Sea'
INTRO_SCENE = '02 | Times Square LIVE'
POLL_MS = 250

server = DEFAULT_SERVER
auto_switch = True
main_scene = MAIN_SCENE
break_scene = BREAK_SCENE
intro_scene = INTRO_SCENE
listener = None
applied = None  # ostatnio wykonane przełączenie: 'main' albo 'break'
warned = set()


# ---- logika niezależna od OBS (testowana osobno) ----

def normalize_server(value):
    """Adres serwera bez końcowego ukośnika; pusty tekst, gdy adres jest nieprawidłowy."""
    value = (value or '').strip().rstrip('/')
    if not value:
        return ''
    if '://' not in value:
        value = 'http://' + value
    if not value.startswith(('http://', 'https://')):
        return ''
    return value


def screen_url(base):
    # obs=1: strona nie odtwarza muzyki przerwy (gra ją OBS) i nie pokazuje podpowiedzi o dźwięku
    return normalize_server(base) + '/screen?obs=1'


def iter_events(lines):
    """Zdarzenia SSE: z kolejnych linii (bytes lub str) zwraca zdekodowane obiekty JSON."""
    buffer = []
    for raw in lines:
        line = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
        line = line.rstrip('\r\n')
        if line.startswith('data:'):
            buffer.append(line[5:].lstrip())
        elif line == '' and buffer:
            text, buffer = '\n'.join(buffer), []
            try:
                yield json.loads(text)
            except ValueError:
                continue


def wanted_scene(state):
    """'break' w przerwie technicznej, 'intro' przed startem turnieju (jeszcze bez rundy), inaczej 'main'.

    None, gdy stan jest nieczytelny."""
    if not isinstance(state, dict):
        return None
    if state.get('view') == 'break':
        return 'break'
    if not state.get('round'):
        return 'intro'
    return 'main'


class Listener(threading.Thread):
    """Czyta strumień stanu w osobnym wątku i trzyma ostatni stan; ponawia połączenie po błędzie."""

    def __init__(self, base):
        super().__init__(daemon=True)
        self.base = base
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.connected = False
        self.error = ''

    def take(self):
        with self.lock:
            state, self.latest = self.latest, None
        return state

    def run(self):
        delay = 1
        while not self.stop_event.is_set():
            try:
                request = urllib.request.Request(self.base + '/events?role=screen', headers={'Accept': 'text/event-stream'})
                with urllib.request.urlopen(request, timeout=30) as response:
                    self.connected, self.error, delay = True, '', 1
                    for event in iter_events(response):
                        with self.lock:
                            self.latest = event
                        if self.stop_event.is_set():
                            break
            except (urllib.error.URLError, OSError, ValueError) as error:
                self.error = str(error)
            self.connected = False
            self.stop_event.wait(delay)
            delay = min(delay * 2, 10)

    def stop(self):
        self.stop_event.set()


# ---- część OBS ----

def log(level, text):
    if obs is not None:
        obs.script_log(level, text)


def warn_once(key, text):
    if key not in warned:
        warned.add(key)
        log(obs.LOG_WARNING, text)


def ensure_main_scene():
    """Tworzy scenę z ekranem turnieju (źródło przeglądarkowe na całą planszę) albo aktualizuje jego adres."""
    base = normalize_server(server)
    if not base:
        return False
    existing = obs.obs_get_source_by_name(main_scene)
    scene = obs.obs_scene_from_source(existing) if existing else obs.obs_scene_create(main_scene)
    if not scene:
        if existing:
            obs.obs_source_release(existing)
        return False
    settings = obs.obs_data_create()
    video = obs.obs_video_info()
    width, height = (1920, 1080)
    if obs.obs_get_video_info(video):
        width, height = video.base_width, video.base_height
    obs.obs_data_set_string(settings, 'url', screen_url(base))
    obs.obs_data_set_int(settings, 'width', width)
    obs.obs_data_set_int(settings, 'height', height)
    obs.obs_data_set_bool(settings, 'reroute_audio', True)  # dźwięki rund trafiają do miksera OBS
    obs.obs_data_set_bool(settings, 'shutdown', False)
    source = obs.obs_get_source_by_name(MAIN_SOURCE)
    if source:
        obs.obs_source_update(source, settings)
    else:
        source = obs.obs_source_create('browser_source', MAIN_SOURCE, settings, None)
        if source and not obs.obs_scene_find_source(scene, MAIN_SOURCE):
            obs.obs_scene_add(scene, source)
    if source:
        obs.obs_source_release(source)
    obs.obs_data_release(settings)
    if existing:
        obs.obs_source_release(existing)
    else:
        obs.obs_scene_release(scene)
    return True


def switch_to(name):
    source = obs.obs_get_source_by_name(name)
    if not source:
        warn_once('missing:' + name, 'Nie ma sceny „' + name + '”. Utwórz ją albo ustaw jej nazwę we właściwościach skryptu.')
        return False
    try:
        if obs.obs_frontend_preview_program_mode_active():
            # w trybie studia: scena trafia na podgląd i od razu przechodzi na program zwykłym przejściem
            obs.obs_frontend_set_current_preview_scene(source)
            obs.obs_frontend_preview_program_trigger_transition()
        else:
            obs.obs_frontend_set_current_scene(source)
    finally:
        obs.obs_source_release(source)
    return True


def scene_exists(name):
    source = obs.obs_get_source_by_name(name)
    if source:
        obs.obs_source_release(source)
    return source is not None


def scene_for(kind):
    if kind == 'break':
        return break_scene
    if kind == 'intro':
        # otwarcie (np. Times Square) tylko jeśli taka scena istnieje; bez niej od razu ekran turnieju
        if scene_exists(intro_scene):
            return intro_scene
        warn_once('intro:' + intro_scene, 'Nie ma sceny otwarcia „' + intro_scene + '”, pokazuję ekran turnieju.')
    return main_scene


def tick():
    global applied
    if listener is None:
        return
    state = listener.take()
    if state is None:
        return
    wanted = wanted_scene(state)
    if wanted is None or not auto_switch or wanted == applied:
        return
    name = scene_for(wanted)
    if switch_to(name):
        applied = wanted
        log(obs.LOG_INFO, 'Turniej: scena „' + name + '”.')


def on_event(event):
    global applied
    if event in (obs.OBS_FRONTEND_EVENT_FINISHED_LOADING, obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGED):
        applied = None
        warned.clear()
        try:
            ensure_main_scene()
        except Exception as error:  # nie blokuj ładowania OBS błędem tworzenia sceny
            log(obs.LOG_WARNING, 'Nie udało się utworzyć sceny ekranu turnieju: ' + str(error))


def start_listener():
    global listener
    stop_listener()
    base = normalize_server(server)
    if base:
        listener = Listener(base)
        listener.start()


def stop_listener():
    global listener
    if listener is not None:
        listener.stop()
        listener = None


def script_description():
    status = 'Brak adresu serwera.'
    if listener is not None:
        status = 'Połączono z serwerem turnieju.' if listener.connected else 'Łączenie z serwerem turnieju… ' + listener.error
    return ('<b>Turniej TTC: sceny OBS według stanu gry</b><br>Przerwa techniczna w turnieju przełącza OBS na scenę przerwy, '
            'a po niej wraca na scenę z ekranem turnieju. Przed startem turnieju pokazuje scenę otwarcia (np. Times Square). Skrypt tylko czyta stan ekranu widowni.<br><br>' + status)


def script_defaults(settings):
    obs.obs_data_set_default_string(settings, 'server', DEFAULT_SERVER)
    obs.obs_data_set_default_bool(settings, 'auto_switch', True)
    obs.obs_data_set_default_string(settings, 'main_scene', MAIN_SCENE)
    obs.obs_data_set_default_string(settings, 'break_scene', BREAK_SCENE)
    obs.obs_data_set_default_string(settings, 'intro_scene', INTRO_SCENE)


def script_properties():
    props = obs.obs_properties_create()
    obs.obs_properties_add_text(props, 'server', 'Adres serwera turnieju', obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_bool(props, 'auto_switch', 'Przełączaj sceny automatycznie')
    obs.obs_properties_add_text(props, 'main_scene', 'Scena z ekranem turnieju', obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, 'break_scene', 'Scena przerwy', obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, 'intro_scene', 'Scena otwarcia (przed startem turnieju)', obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_button(props, 'create', 'Utwórz / napraw scenę ekranu turnieju',
                                  lambda *_: (ensure_main_scene(), True)[1])
    return props


def script_update(settings):
    global server, auto_switch, main_scene, break_scene, intro_scene, applied
    new_server = obs.obs_data_get_string(settings, 'server')
    changed = normalize_server(new_server) != normalize_server(server) or listener is None
    server = new_server
    auto_switch = obs.obs_data_get_bool(settings, 'auto_switch')
    main_scene = obs.obs_data_get_string(settings, 'main_scene') or MAIN_SCENE
    break_scene = obs.obs_data_get_string(settings, 'break_scene') or BREAK_SCENE
    intro_scene = obs.obs_data_get_string(settings, 'intro_scene') or INTRO_SCENE
    applied = None
    if changed:
        start_listener()


def script_load(settings):
    obs.obs_frontend_add_event_callback(on_event)
    obs.timer_add(tick, POLL_MS)


def script_unload():
    obs.timer_remove(tick)
    obs.obs_frontend_remove_event_callback(on_event)
    stop_listener()
