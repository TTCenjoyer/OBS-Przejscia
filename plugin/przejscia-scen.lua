-- OBS Studio 32+: Narzędzia > Skrypty > przejscia-scen.lua
obs = obslua
local bit = require("bit")
local settings_ref = nil
local ready, exiting = false, false
local watched_transitions = nil
local break_scene = "Przerwa — Beyond the Sea"
local mic_name = "Mikrofon/Wejście liniowe"
local restore_pending, restore_muted, loaded_settings = false, false, false
local original_overrides = {}
local last_context = nil
local audio_fade = nil
local startup_volumes = nil
local external_rules = nil
local external_text = nil
local rules_ticks = 0
local rules_file = script_path() .. "przejscia-ustawienia.json"
local function rules()
    return external_rules or settings_ref
end
local function load_external_rules()
    local file = io.open(rules_file, "rb")
    if not file then return end
    local content = file:read("*a"); file:close()
    if content == external_text then return end
    local root = obs.obs_data_create_from_json(content)
    if not root then return end
    local collections = obs.obs_data_get_obj(root, "collections")
    local collection = obs.obs_frontend_get_current_scene_collection()
    local data = collections and obs.obs_data_get_obj(collections, collection) or nil
    if data then
        if external_rules then obs.obs_data_release(external_rules) end
        external_rules = data
        external_text = content
        last_context = nil
    end
    if collections then obs.obs_data_release(collections) end
    obs.obs_data_release(root)
end
local function clock_ns()
    if obs.os_gettime_ns then return obs.os_gettime_ns() end
    if obs.obs_get_video_frame_time then return obs.obs_get_video_frame_time() end
    return nil
end

local function scene_key(scene)
    return "exit_" .. obs.obs_source_get_uuid(scene)
end

local function restore_microphone()
    if not restore_pending then return end
    local mic = obs.obs_get_source_by_name(mic_name)
    if mic then
        obs.obs_source_set_muted(mic, restore_muted)
        obs.obs_source_release(mic)
    end
    restore_pending = false
end

local function update_microphone(scene)
    if not scene or obs.obs_source_get_name(scene) ~= break_scene then
        restore_microphone()
        return
    end
    local mic = obs.obs_get_source_by_name(mic_name)
    if not mic then return end
    if not restore_pending then
        restore_muted = obs.obs_source_muted(mic)
        restore_pending = true
    end
    local uuid = obs.obs_source_get_uuid(mic)
    if audio_fade and audio_fade.entries[uuid] and not audio_fade.finished then
        obs.obs_source_release(mic)
        return
    end
    if not obs.obs_source_muted(mic) then obs.obs_source_set_muted(mic, true) end
    obs.obs_source_release(mic)
end

local function restore_music_levels()
    if not audio_fade then return end
    for uuid, entry in pairs(audio_fade.entries) do
        local source = obs.obs_get_source_by_uuid(uuid)
        if source then
            obs.obs_source_set_volume(source, entry.volume)
            obs.obs_source_release(source)
        end
    end
    audio_fade = nil
end

local function scene_audio(scene_source)
    local result, visited = {}, {}
    local function visit(source)
        local uuid = obs.obs_source_get_uuid(source)
        if visited[uuid] then return end
        visited[uuid] = true
        local scene = obs.obs_scene_from_source(source)
        if not scene and obs.obs_group_from_source then scene = obs.obs_group_from_source(source) end
        if scene then
            local items = obs.obs_scene_enum_items(scene)
            if items then
                for _, item in ipairs(items) do
                    if obs.obs_sceneitem_visible(item) then visit(obs.obs_sceneitem_get_source(item)) end
                end
                obs.sceneitem_list_release(items)
            end
        elseif bit.band(obs.obs_source_get_output_flags(source), obs.OBS_SOURCE_AUDIO) ~= 0 then
            result[uuid] = true
        end
    end
    if scene_source then visit(scene_source) end
    for channel = 1, 5 do
        local source = obs.obs_get_output_source(channel)
        if source then
            local is_mic = obs.obs_source_get_name(source) == mic_name
            if not is_mic or not scene_source or obs.obs_source_get_name(scene_source) ~= break_scene then
                result[obs.obs_source_get_uuid(source)] = true
            end
            obs.obs_source_release(source)
        end
    end
    return result
end

function transition_started(calldata)
    local transition = obs.calldata_source(calldata, "source")
    if not transition then return end
    local from = obs.obs_transition_get_source(transition, obs.OBS_TRANSITION_SOURCE_A)
    local target = obs.obs_transition_get_source(transition, obs.OBS_TRANSITION_SOURCE_B)
    local from_break = from and obs.obs_source_get_name(from) == break_scene
    local to_break = target and obs.obs_source_get_name(target) == break_scene
    if to_break and not restore_pending then
        local mic = obs.obs_get_source_by_name(mic_name)
        if mic then
            restore_muted = obs.obs_source_muted(mic)
            restore_pending = true
            obs.obs_source_release(mic)
        end
    end
    if obs.obs_source_get_id(transition) == "fade_transition" then
        local duration = obs.obs_frontend_get_transition_duration()
        if target then
            local private = obs.obs_source_get_private_settings(target)
            local override_duration = obs.obs_data_get_int(private, "transition_duration")
            if override_duration > 0 then duration = override_duration end
            obs.obs_data_release(private)
        end
        local outgoing, incoming = scene_audio(from), scene_audio(target)
        local entries = {}
        for uuid in pairs(incoming) do entries[uuid] = true end
        for uuid in pairs(outgoing) do entries[uuid] = true end
        local previous = audio_fade
        for uuid in pairs(entries) do
            local source = obs.obs_get_source_by_uuid(uuid)
            if source then
                local old = previous and previous.entries[uuid]
                local volume = old and old.volume or obs.obs_source_get_volume(source)
                local start_gain = outgoing[uuid] and 1 or 0
                if old then start_gain = volume > 0 and obs.obs_source_get_volume(source) / volume or 0 end
                entries[uuid] = {volume = volume, from = outgoing[uuid], to = incoming[uuid],
                    first = start_gain, last = incoming[uuid] and 1 or 0,
                    microphone = obs.obs_source_get_name(source) == mic_name}
                obs.obs_source_set_volume(source, volume * start_gain)
                obs.obs_source_release(source)
            else entries[uuid] = nil end
        end
        if previous then
            for uuid, entry in pairs(previous.entries) do
                if not entries[uuid] then
                    local source = obs.obs_get_source_by_uuid(uuid)
                    if source then
                        obs.obs_source_set_volume(source, entry.volume)
                        obs.obs_source_release(source)
                    end
                end
            end
        end
        audio_fade = {elapsed = 0, started = clock_ns(), duration = math.max(1, duration),
            entries = entries, target_break = to_break, finished = false}
        if from_break then restore_microphone() end
    else
        restore_music_levels()
        if from_break then restore_microphone() end
    end
    if from then obs.obs_source_release(from) end
    if target then obs.obs_source_release(target) end
end

function transition_stopped(calldata)
    last_context = nil
end

local function fade_music_tick()
    if not audio_fade then return end
    local now = clock_ns()
    if now and audio_fade.started then
        audio_fade.elapsed = (now - audio_fade.started) / 1000000
    else audio_fade.elapsed = audio_fade.elapsed + 10 end
    local progress = math.min(1, math.max(0, audio_fade.elapsed / audio_fade.duration))
    audio_fade.finished = progress >= 1
    for uuid, entry in pairs(audio_fade.entries) do
        local source = obs.obs_get_source_by_uuid(uuid)
        if source then
            local gain = entry.first + (entry.last - entry.first) * progress
            obs.obs_source_set_volume(source, entry.volume * gain)
            if audio_fade.finished then
                if entry.microphone and audio_fade.target_break then obs.obs_source_set_muted(source, true) end
                if entry.to or entry.microphone or not obs.obs_source_active(source) or obs.obs_source_muted(source) then
                    if not entry.to and not obs.obs_source_active(source) and obs.obs_source_get_id(source) == "ffmpeg_source" then
                        obs.obs_source_media_stop(source)
                    end
                    obs.obs_source_set_volume(source, entry.volume)
                    audio_fade.entries[uuid] = nil
                end
            end
            obs.obs_source_release(source)
        else audio_fade.entries[uuid] = nil end
    end
    if not next(audio_fade.entries) then audio_fade = nil end
end

local function watch_transitions()
    if watched_transitions then return end
    watched_transitions = obs.obs_frontend_get_transitions()
    if not watched_transitions then return end
    for _, source in ipairs(watched_transitions) do
        local handler = obs.obs_source_get_signal_handler(source)
        obs.signal_handler_connect(handler, "transition_start", transition_started)
        obs.signal_handler_connect(handler, "transition_stop", transition_stopped)
    end
end

local function unwatch_transitions()
    if not watched_transitions then return end
    for _, source in ipairs(watched_transitions) do
        local handler = obs.obs_source_get_signal_handler(source)
        obs.signal_handler_disconnect(handler, "transition_start", transition_started)
        obs.signal_handler_disconnect(handler, "transition_stop", transition_stopped)
    end
    obs.source_list_release(watched_transitions)
    watched_transitions = nil
end

local function configured_transition(scene)
    local key = scene_key(scene)
    local name = rules() and obs.obs_data_get_string(rules(), key) or ""
    local duration = rules() and obs.obs_data_get_int(rules(), key .. "_ms") or 0
    if duration <= 0 then duration = 1000 end
    local fallback_id = obs.obs_source_get_name(scene) == break_scene and "fade_transition" or "move_transition"
    local transitions = obs.obs_frontend_get_transitions()
    if not transitions then return nil, duration end
    local found = nil
    for _, transition in ipairs(transitions) do
        if (name ~= "" and obs.obs_source_get_name(transition) == name)
            or (name == "" and obs.obs_source_get_id(transition) == fallback_id) then
            found = obs.obs_source_get_ref(transition)
            break
        end
    end
    if not found and name == "" then
        for _, transition in ipairs(transitions) do
            if obs.obs_source_get_id(transition) == "fade_transition" then
                found = obs.obs_source_get_ref(transition)
                break
            end
        end
    end
    obs.source_list_release(transitions)
    return found, duration
end

local function prepare_exit(scene)
    local context = obs.obs_source_get_uuid(scene)
    if context == last_context then return end
    local wanted, duration = configured_transition(scene)
    if not wanted then return end
    local exit_name = obs.obs_source_get_name(wanted)
    local scenes = obs.obs_frontend_get_scenes()
    if scenes then
        for _, destination in ipairs(scenes) do
            local uuid = obs.obs_source_get_uuid(destination)
            local entry = obs.obs_data_get_string(rules(), "entry_" .. uuid)
            local entry_duration = obs.obs_data_get_int(rules(), "entry_" .. uuid .. "_ms")
            if entry == "" then entry = exit_name end
            if entry_duration <= 0 then entry_duration = duration end
            local private = obs.obs_source_get_private_settings(destination)
            if not original_overrides[uuid] then
                local backup_key = "native_backup_" .. uuid
                local original
                if obs.obs_data_get_bool(settings_ref, backup_key) then
                    original = {
                        transition = obs.obs_data_get_string(settings_ref, backup_key .. "_name"),
                        duration = obs.obs_data_get_int(settings_ref, backup_key .. "_ms"),
                        has_transition = obs.obs_data_get_bool(settings_ref, backup_key .. "_has_name"),
                        has_duration = obs.obs_data_get_bool(settings_ref, backup_key .. "_has_ms")
                    }
                else
                    original = {
                        transition = obs.obs_data_get_string(private, "transition"),
                        duration = obs.obs_data_get_int(private, "transition_duration"),
                        has_transition = obs.obs_data_has_user_value(private, "transition"),
                        has_duration = obs.obs_data_has_user_value(private, "transition_duration")
                    }
                    obs.obs_data_set_bool(settings_ref, backup_key, true)
                    obs.obs_data_set_string(settings_ref, backup_key .. "_name", original.transition)
                    obs.obs_data_set_int(settings_ref, backup_key .. "_ms", original.duration)
                    obs.obs_data_set_bool(settings_ref, backup_key .. "_has_name", original.has_transition)
                    obs.obs_data_set_bool(settings_ref, backup_key .. "_has_ms", original.has_duration)
                end
                original_overrides[uuid] = original
            end
            -- OBS resolves destination overrides before starting the animation.
            -- This uses the native swap path and preserves the program picture.
            obs.obs_data_set_string(private, "transition", entry)
            obs.obs_data_set_int(private, "transition_duration", entry_duration)
            obs.obs_data_release(private)
        end
        obs.source_list_release(scenes)
    end
    obs.obs_source_release(wanted)
    last_context = context
end

local function restore_native_overrides()
    local scenes = obs.obs_frontend_get_scenes()
    if scenes then
        for _, scene in ipairs(scenes) do
            local original = original_overrides[obs.obs_source_get_uuid(scene)]
            if original then
                local private = obs.obs_source_get_private_settings(scene)
                if original.has_transition then
                    obs.obs_data_set_string(private, "transition", original.transition)
                else obs.obs_data_unset_user_value(private, "transition") end
                if original.has_duration then
                    obs.obs_data_set_int(private, "transition_duration", original.duration)
                else obs.obs_data_unset_user_value(private, "transition_duration") end
                obs.obs_data_release(private)
            end
        end
        obs.source_list_release(scenes)
    end
    original_overrides = {}
end

function scene_exit_tick()
    if not ready or exiting then return end
    if startup_volumes then
        for uuid, volume in pairs(startup_volumes) do
            local source = obs.obs_get_source_by_uuid(uuid)
            if source then
                obs.obs_source_set_volume(source, volume)
                obs.obs_source_release(source)
            end
        end
        startup_volumes = nil
    end
    rules_ticks = rules_ticks + 1
    if rules_ticks >= 10 then rules_ticks = 0; load_external_rules() end
    watch_transitions()
    fade_music_tick()
    local scene = obs.obs_frontend_get_current_scene()
    if not scene then return end
    update_microphone(scene)
    prepare_exit(scene)
    obs.obs_source_release(scene)
end

function scene_exit_event(event)
    if event == obs.OBS_FRONTEND_EVENT_FINISHED_LOADING
        or event == obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGED then
        ready = true
        load_external_rules()
        last_context = nil
    elseif event == obs.OBS_FRONTEND_EVENT_SCENE_CHANGED then
        if not ready then return end
        local scene = obs.obs_frontend_get_current_scene()
        update_microphone(scene)
        if scene then obs.obs_source_release(scene) end
        last_context = nil
    elseif event == obs.OBS_FRONTEND_EVENT_TRANSITION_STOPPED then
        transition_stopped(nil)
    elseif event == obs.OBS_FRONTEND_EVENT_SCENE_LIST_CHANGED then
        last_context = nil
    elseif event == obs.OBS_FRONTEND_EVENT_SCENE_COLLECTION_CLEANUP
        or event == obs.OBS_FRONTEND_EVENT_EXIT
        or event == obs.OBS_FRONTEND_EVENT_SCRIPTING_SHUTDOWN then
        exiting = true
        restore_microphone()
        restore_music_levels()
        restore_native_overrides()
        unwatch_transitions()
    end
end

function script_description()
    return [[<b>Przejścia wejścia i wyjścia scen</b><br>
Dla każdej sceny wybierz efekt wyjścia oraz czas. Efekt wejścia domyślnie
dziedziczy wyjście poprzedniej sceny. Własny efekt wejścia ma pierwszeństwo.<br><br>
Domyślnie: Move; wyjście z „Przerwa — Beyond the Sea”: Zanikanie (1 s).
Ustawienia są zapisywane osobno dla każdej kolekcji i przypisane do identyfikatora sceny,
więc zmiana jej nazwy nie usuwa przypisanego efektu.<br><br>
Mikrofon podczas przerwy jest wyciszany; po wyjściu wraca do poprzedniego stanu.
Zanikanie równocześnie wycisza źródła sceny A i zgłaśnia źródła sceny B,
również w odsłuchu. Źródła wspólne dla obu scen pozostają bez zmian.
Podgląd w Trybie studia nie uruchamia tych reguł.]]
end

function script_defaults(settings)
    obs.obs_data_set_default_string(settings, "mic_name", "Mikrofon/Wejście liniowe")
end

function script_properties()
    local props = obs.obs_properties_create()
    if external_rules then
        obs.obs_properties_add_text(props, "dock_info", "Ustawienia są w panelu Przejścia scen, obok listy scen. Panel pokazuje aktualną scenę na programie.", obs.OBS_TEXT_INFO)
        return props
    end
    local scenes = obs.obs_frontend_get_scenes()
    local transitions = obs.obs_frontend_get_transitions()
    if scenes then
        for _, scene in ipairs(scenes) do
            local key = scene_key(scene)
            local group = obs.obs_properties_create()
            local list = obs.obs_properties_add_list(group, key, "Efekt wyjścia", obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
            local default = obs.obs_source_get_name(scene) == break_scene and "Domyślne: Zanikanie" or "Domyślne: Move"
            obs.obs_property_list_add_string(list, default, "")
            if transitions then
                for _, transition in ipairs(transitions) do
                    local name = obs.obs_source_get_name(transition)
                    obs.obs_property_list_add_string(list, name, name)
                end
            end
            obs.obs_properties_add_int(group, key .. "_ms", "Czas wyjścia w ms (0 = 1000)", 0, 60000, 50)
            local entry_key = "entry_" .. obs.obs_source_get_uuid(scene)
            local entry_list = obs.obs_properties_add_list(group, entry_key, "Efekt wejścia", obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
            obs.obs_property_list_add_string(entry_list, "Z efektu wyjścia poprzedniej sceny", "")
            if transitions then
                for _, transition in ipairs(transitions) do
                    local name = obs.obs_source_get_name(transition)
                    obs.obs_property_list_add_string(entry_list, name, name)
                end
            end
            obs.obs_properties_add_int(group, entry_key .. "_ms", "Czas wejścia w ms (0 = odziedzicz)", 0, 60000, 50)
            obs.obs_properties_add_group(props, "group_" .. key, "Scena: " .. obs.obs_source_get_name(scene), obs.OBS_GROUP_NORMAL, group)
        end
        obs.source_list_release(scenes)
    end
    if transitions then obs.source_list_release(transitions) end
    local list = obs.obs_properties_add_list(props, "mic_name", "Mikrofon wyciszany na przerwie", obs.OBS_COMBO_TYPE_EDITABLE, obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_list_add_string(list, mic_name, mic_name)
    obs.obs_properties_add_button(props, "refresh", "Odśwież listę scen i efektów", function()
        last_context = nil
        unwatch_transitions()
        return true
    end)
    return props
end

function script_update(settings)
    local name = obs.obs_data_get_string(settings, "mic_name")
    if name ~= mic_name then restore_microphone() end
    mic_name = name
    if not loaded_settings then
        restore_pending = obs.obs_data_get_bool(settings, "restore_pending")
        restore_muted = obs.obs_data_get_bool(settings, "restore_muted")
        loaded_settings = true
        if obs.obs_data_get_bool(settings, "audio_restore_pending") then
            startup_volumes = {}
            local restore = obs.obs_data_get_obj(settings, "audio_restore")
            local sources = obs.obs_enum_sources()
            if restore and sources then
                for _, source in ipairs(sources) do
                    local uuid = obs.obs_source_get_uuid(source)
                    if obs.obs_data_has_user_value(restore, uuid) then
                        startup_volumes[uuid] = obs.obs_data_get_double(restore, uuid)
                    end
                end
            end
            if sources then obs.source_list_release(sources) end
            if restore then obs.obs_data_release(restore) end
        end
    end
    if settings_ref then obs.obs_data_release(settings_ref) end
    obs.obs_data_addref(settings)
    settings_ref = settings
    last_context = nil
end

function script_save(settings)
    obs.obs_data_set_bool(settings, "restore_pending", restore_pending)
    obs.obs_data_set_bool(settings, "restore_muted", restore_muted)
    obs.obs_data_set_bool(settings, "audio_restore_pending", audio_fade ~= nil)
    if audio_fade then
        local restore = obs.obs_data_create()
        for uuid, entry in pairs(audio_fade.entries) do
            obs.obs_data_set_double(restore, uuid, entry.volume)
        end
        obs.obs_data_set_obj(settings, "audio_restore", restore)
        obs.obs_data_release(restore)
    end
end

function script_load(settings)
    obs.obs_frontend_add_event_callback(scene_exit_event)
    obs.timer_add(scene_exit_tick, 10)
end

function script_unload()
    exiting = true
    obs.timer_remove(scene_exit_tick)
    obs.obs_frontend_remove_event_callback(scene_exit_event)
    restore_microphone()
    restore_music_levels()
    restore_native_overrides()
    unwatch_transitions()
    if settings_ref then obs.obs_data_release(settings_ref); settings_ref = nil end
    if external_rules then obs.obs_data_release(external_rules); external_rules = nil end
end
