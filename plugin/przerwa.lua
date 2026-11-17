obs = obslua
local scene_name = "Przerwa — Beyond the Sea"
local gif_name = "Przerwa | GIF — wybierz plik"
local intro_name = "Przerwa | 1. Początek"
local loop_name = "Przerwa | 2. Beyond the Sea — pętla"
local intro_path, loop_path = "", ""
local tournament_url = ""
local tournament_name = "Przerwa | Ekran turnieju"
local phase = "off"
local ready = false
local intro_seen_playing = false
local start_ticks = 0
local frontend_ready = false
local was_on_break = false

local function with_source(name, fn)
    local source = obs.obs_get_source_by_name(name)
    if source then
        fn(source)
        obs.obs_source_release(source)
    end
end

local function stop_audio()
    phase = "off"
    for _, name in ipairs({intro_name, loop_name}) do
        with_source(name, function(s)
            obs.obs_source_set_muted(s, true)
            obs.obs_source_media_stop(s)
        end)
    end
end

local function on_program_scene()
    local scene = obs.obs_frontend_get_current_scene()
    if not scene then return false end
    local matches = obs.obs_source_get_name(scene) == scene_name
    obs.obs_source_release(scene)
    return matches
end

local function add_source(scene, id, name, settings)
    local source = obs.obs_get_source_by_name(name)
    local created = source == nil
    if created then source = obs.obs_source_create(id, name, settings, nil) end
    if not source then return end
    if not obs.obs_scene_find_source(scene, name) then
        local item = obs.obs_scene_add(scene, source)
        if name == gif_name then
            local video = obs.obs_video_info()
            if obs.obs_get_video_info(video) then
                local bounds = obs.vec2()
                bounds.x, bounds.y = video.base_width, video.base_height
                obs.obs_sceneitem_set_bounds_type(item, obs.OBS_BOUNDS_SCALE_INNER)
                obs.obs_sceneitem_set_bounds(item, bounds)
                obs.obs_sceneitem_set_bounds_alignment(item, 0) -- centered
            end
        end
    end
    if id == "ffmpeg_source" and name ~= gif_name then
        obs.obs_source_set_muted(source, true)
        obs.obs_source_update(source, settings)
        obs.obs_source_media_stop(source)
    end
    obs.obs_source_release(source)
end

-- Opcjonalnie: ekran przerwy z serwera turnieju jako źródło przeglądarkowe nad GIF-em.
-- ?obs=1 wyłącza muzykę strony, bo muzykę przerwy gra ten skrypt.
local function ensure_tournament_screen(scene)
    local base = tournament_url:gsub("^%s+", ""):gsub("%s+$", ""):gsub("/+$", "")
    if base == "" then return end
    if not base:find("://", 1, true) then base = "http://" .. base end
    local settings = obs.obs_data_create()
    local width, height = 1920, 1080
    local video = obs.obs_video_info()
    if obs.obs_get_video_info(video) then width, height = video.base_width, video.base_height end
    obs.obs_data_set_string(settings, "url", base .. "/screen?obs=1")
    obs.obs_data_set_int(settings, "width", width)
    obs.obs_data_set_int(settings, "height", height)
    obs.obs_data_set_bool(settings, "reroute_audio", false)
    obs.obs_data_set_bool(settings, "shutdown", false)
    local source = obs.obs_get_source_by_name(tournament_name)
    if source then
        obs.obs_source_update(source, settings)
    else
        source = obs.obs_source_create("browser_source", tournament_name, settings, nil)
    end
    if source then
        if not obs.obs_scene_find_source(scene, tournament_name) then obs.obs_scene_add(scene, source) end
        obs.obs_source_release(source)
    end
    obs.obs_data_release(settings)
end

local function ensure_scene()
    local source = obs.obs_get_source_by_name(scene_name)
    local scene
    if source then
        scene = obs.obs_scene_from_source(source)
    else
        scene = obs.obs_scene_create(scene_name)
    end
    if not scene then
        if source then obs.obs_source_release(source) end
        return false
    end
    local image = obs.obs_data_create()
    obs.obs_data_set_bool(image, "is_local_file", true)
    obs.obs_data_set_bool(image, "looping", true)
    obs.obs_data_set_bool(image, "restart_on_activate", true)
    obs.obs_data_set_bool(image, "close_when_inactive", false)
    obs.obs_data_set_bool(image, "clear_on_media_end", false)
    add_source(scene, "ffmpeg_source", gif_name, image)
    obs.obs_data_release(image)
    ensure_tournament_screen(scene)
    for index, spec in ipairs({{intro_name, intro_path}, {loop_name, loop_path}}) do
        local settings = obs.obs_data_create()
        obs.obs_data_set_bool(settings, "is_local_file", true)
        obs.obs_data_set_string(settings, "local_file", spec[2])
        obs.obs_data_set_bool(settings, "looping", index == 2)
        -- Only this script starts playback, including in Studio Mode preview.
        obs.obs_data_set_bool(settings, "restart_on_activate", false)
        obs.obs_data_set_bool(settings, "close_when_inactive", false)
        obs.obs_data_set_bool(settings, "clear_on_media_end", true)
        add_source(scene, "ffmpeg_source", spec[1], settings)
        obs.obs_data_release(settings)
    end
    if source then obs.obs_source_release(source) else obs.obs_scene_release(scene) end
    stop_audio()
    return true
end

local function start_intro()
    phase = "intro"
    intro_seen_playing = false
    with_source(intro_name, function(s)
        obs.obs_source_media_restart(s)
        obs.obs_source_set_muted(s, false)
    end)
end

function przerwa_tick()
    if not frontend_ready then return end
    if not ready then ready = ensure_scene() end
    if not ready then return end
    local on_break = on_program_scene()
    if on_break and not was_on_break then stop_audio() end
    was_on_break = on_break
    if not on_break then
        -- Keep outgoing music alive while the transition renders it. This lets
        -- the transition and the exit-rules script fade the sound naturally.
        local active = false
        for _, name in ipairs({intro_name, loop_name}) do
            with_source(name, function(s)
                if obs.obs_source_active(s) then active = true end
            end)
        end
        if not active and phase ~= "off" then stop_audio() end
        return
    end
    if phase == "off" then
        -- SCENE_CHANGED can precede activation of scene items. Restarting a
        -- media source before it is showing changes its state without playback.
        with_source(intro_name, function(s)
            if obs.obs_source_active(s) and obs.obs_source_showing(s) then
                phase = "arming"
                start_ticks = 0
            end
        end)
    elseif phase == "arming" then
        start_ticks = start_ticks + 1
        if start_ticks >= 3 then start_intro() end
    elseif phase == "intro" then
        local ended = false
        with_source(intro_name, function(s)
            local state = obs.obs_source_media_get_state(s)
            if state == obs.OBS_MEDIA_STATE_PLAYING then intro_seen_playing = true end
            ended = intro_seen_playing and state == obs.OBS_MEDIA_STATE_ENDED
        end)
        if ended then
            with_source(intro_name, function(s) obs.obs_source_set_muted(s, true) end)
            phase = "loop"
            with_source(loop_name, function(s)
                obs.obs_source_media_restart(s)
                obs.obs_source_set_muted(s, false)
            end)
        end
    end
end

function przerwa_event(event)
    if event == obs.OBS_FRONTEND_EVENT_FINISHED_LOADING or event == obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGED then
        frontend_ready = true
    elseif event == obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CLEANUP then
        frontend_ready = false
        was_on_break = false
        stop_audio()
        ready = false
    elseif event == obs.OBS_FRONTEND_EVENT_EXIT or event == obs.OBS_FRONTEND_EVENT_SCRIPTING_SHUTDOWN then
        frontend_ready = false
    end
end

function script_description()
    return [[<b>Przerwa: GIF + początek + muzyka w pętli</b><br>
Wybierz scenę „Przerwa — Beyond the Sea”. Początek zagra raz, potem drugi plik będzie zapętlony.
Zmiana sceny zatrzymuje dźwięk. Powrót uruchamia początek od nowa.<br><br>
GIF ustaw we właściwościach źródła „Przerwa | GIF — wybierz plik”.
Podgląd w Trybie studia nie uruchamia muzyki; uruchamia ją dopiero przejście na program.]]
end

function script_defaults(settings)
    obs.obs_data_set_default_string(settings, "tournament_url", "")
    obs.obs_data_set_default_string(settings, "intro", script_path() .. "Poczatek.wav")
    obs.obs_data_set_default_string(settings, "loop", script_path() .. "BeyondTheSea-petla.mp3")
end

function script_properties()
    local props = obs.obs_properties_create()
    obs.obs_properties_add_path(props, "intro", "Początek — jeden raz", obs.OBS_PATH_FILE, "Audio (*.wav *.mp3 *.ogg *.flac)", nil)
    obs.obs_properties_add_path(props, "loop", "Muzyka — pętla", obs.OBS_PATH_FILE, "Audio (*.wav *.mp3 *.ogg *.flac)", nil)
    obs.obs_properties_add_text(props, "tournament_url", "Adres serwera turnieju (ekran przerwy; puste = tylko GIF)", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_button(props, "repair", "Utwórz / napraw scenę", function()
        stop_audio()
        ready = ensure_scene()
        return true
    end)
    return props
end

function script_update(settings)
    stop_audio()
    intro_path = obs.obs_data_get_string(settings, "intro")
    loop_path = obs.obs_data_get_string(settings, "loop")
    tournament_url = obs.obs_data_get_string(settings, "tournament_url")
    ready = false
end

function script_load(settings)
    obs.obs_frontend_add_event_callback(przerwa_event)
    obs.timer_add(przerwa_tick, 25)
end

function script_unload()
    obs.timer_remove(przerwa_tick)
    obs.obs_frontend_remove_event_callback(przerwa_event)
    stop_audio()
end
