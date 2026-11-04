"""Игровое состояние без Tk: те же ходы, но результат уходит событиями."""

from __future__ import annotations

import io
import queue
import re
import shutil
import threading
import zipfile
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

import dungeon.adventure as adventure_rules
from dungeon.ai_engine import ACTION, CARDS, AIEngineMixin
from dungeon.api_stream import IMAGE, MEMORY, SCENE, SCENE_TURNS, SUMMARY
from dungeon import image_gen
from dungeon.session import SharedTurnMixin
from dungeon.config import (
    BASE_DIR,
    DEFAULT_IMAGE_LOOK,
    DEFAULT_IMAGE_STYLE,
    DEFAULT_RESPONSE_LIMITS,
    IMAGE_BACKENDS,
    IMAGE_LOOKS,
    IMAGE_PROMPT_STYLES,
    INTRODUCTION_FILE,
    WORLD_FILES,
    clamp_response_limits,
    list_workflow_files,
    normalize_image_settings,
    response_token_limit,
)
from dungeon.i18n import (
    DM_PREFIX,
    INTRO_PREFIX,
    PLAYER_PREFIX,
    dm_text,
    is_dm_msg,
    PROMPT_GROUPS,
    builtin_prompt,
    default_templates,
    intro_text,
    is_intro_msg,
    is_player_msg,
    normalize_lang,
    player_text,
    prompt_edit_issues,
    set_prompt_overrides,
    t,
)
from dungeon.memory import (
    count_completed_turns,
    get_recent_turn_messages,
    load_memory_bank,
    save_memory_bank,
    sync_memory_bank_after_undo,
)
from dungeon.story_cards import default_story_cards, load_story_cards, save_story_cards
from dungeon.tokens import (
    count_tokens,
    counter_kind,
    format_token_count,
    model_scale_observed,
    model_token_scale,
    set_model_token_scale,
)
from dungeon.storage import (
    ADVENTURE_DIR,
    CorruptedDataError,
    atomic_write_text,
    clamp_summary_cursor,
    clamp_summary_fill_percent,
    ensure_introduction_in_history,
    format_introduction_history,
    load_global_settings,
    load_world_config,
    normalize_api_presets,
    save_global_settings,
    save_history,
    save_summary_cursor,
    save_world_files,
    save_world_language,
    world_entries_in,
)


def _as_float(value, default, low, high):
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return min(high, max(low, number))


def _as_int(value, default, low, high):
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


def _scale_langs(raw):
    """Масштаб одного языка или старое число, снятое русской пробой."""
    langs = {}
    if isinstance(raw, dict):
        pairs = raw.items()
    else:
        pairs = (("ru", raw),)
    for lang, scale in pairs:
        code = "en" if str(lang or "").lower().startswith("en") else "ru" if str(lang or "").lower().startswith("ru") else ""
        if not code:
            continue
        try:
            value = float(scale)
        except (TypeError, ValueError):
            continue
        if value > 0:
            langs[code] = value
    return langs


def _scale_table(raw):
    """Масштаб токенов по виду счётчика, модели и языку текста."""
    table = {}
    if not isinstance(raw, dict):
        return table
    for kind, models in raw.items():
        if not isinstance(kind, str) or not isinstance(models, dict):
            continue
        bucket = {}
        for name, scale in models.items():
            if not isinstance(name, str) or not name:
                continue
            langs = _scale_langs(scale)
            if langs:
                bucket[name] = langs
        if bucket:
            table[kind] = bucket
    return table


_BAD_WORLD_NAME = set('\\/:*?"<>|')
_MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
_MAX_UNPACKED_BYTES = 200 * 1024 * 1024
_MAX_ARCHIVE_FILES = 200


def clean_world_name(name):
    cleaned = str(name or "").strip()
    if not cleaned or cleaned in {".", ".."} or any(char in cleaned for char in _BAD_WORLD_NAME):
        raise ValueError("bad name")
    return cleaned


def world_directory(name, root=None):
    """Папка мира внутри каталога режима. Чужие пути и ссылки наружу не открываем."""
    cleaned = clean_world_name(name)
    base = (BASE_DIR if root is None else root).resolve()
    if base == BASE_DIR.resolve() and cleaned == ADVENTURE_DIR:
        raise ValueError("bad name")
    candidate = base / cleaned
    if candidate.is_symlink():
        raise ValueError("bad name")
    world_path = candidate.resolve()
    if world_path.parent != base:
        raise ValueError("bad name")
    return cleaned, world_path


def allowed_world_filename(name):
    """В архив мира входят только его текстовые файлы, не настройки программы."""
    if not name or name.startswith(".") or name in {".", ".."}:
        return False
    if name.lower() in {"settings.json", "settings.json.bak"}:
        return False
    lowered = name.lower()
    return lowered.endswith((".txt", ".json", ".txt.bak", ".json.bak"))


def _archive_parts(filename):
    relative = str(filename or "").replace("\\", "/").lstrip("/")
    parts = [part for part in relative.split("/") if part not in ("", ".")]
    if not parts or any(part in {".", ".."} or part.startswith(".") or part == "__MACOSX" for part in parts):
        if any(part == ".." for part in parts):
            raise ValueError("path")
        return None
    return parts


def read_world_archive(payload):
    if not payload or len(payload) > _MAX_ARCHIVE_BYTES:
        raise ValueError("size")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("zip") from exc
    with archive:
        chosen = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = _archive_parts(info.filename)
            if parts:
                chosen.append((info, parts))
        if chosen and all(len(parts) >= 2 for _, parts in chosen):
            roots = {parts[0] for _, parts in chosen}
            if len(roots) == 1:
                chosen = [(info, parts[1:]) for info, parts in chosen]
        files = {}
        total = 0
        for info, parts in chosen:
            if len(parts) != 1 or not allowed_world_filename(parts[0]):
                continue
            total += max(0, info.file_size)
            if len(files) >= _MAX_ARCHIVE_FILES or total > _MAX_UNPACKED_BYTES:
                raise ValueError("size")
            data = archive.read(info)
            if len(data) > _MAX_UNPACKED_BYTES:
                raise ValueError("size")
            files[parts[0]] = data
    if not files:
        raise ValueError("empty")
    return files


class _UiBridge:
    """Подменяет root.after: колбэк выполняется сразу и только кладёт событие."""

    def __init__(self, emit):
        self._emit = emit

    def after(self, _delay, callback=None, *args):
        if callback is not None:
            callback(*args)


_SCENE_IMAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(png|jpg|jpeg|webp)$")
IMAGE_LIBRARY = "img_bib"

# Сколько хвоста отдавать странице за один раз: не весь мир, а читаемый кусок.
HISTORY_PAGE_MESSAGES = 40
HISTORY_PAGE_CHARS = 14000


class GameSession(SharedTurnMixin, AIEngineMixin):
    def __init__(self):
        self._subscribers = []
        self._sub_lock = threading.Lock()
        # Один замок на проверку «уже занято» и подъём флага. Иначе два запроса
        # успевают оба увидеть простой и запустить две генерации.
        self._job_lock = threading.RLock()
        self.root = _UiBridge(self.emit)
        self.notices = []
        self.cards_running = False
        self.last_scene = None
        settings = load_global_settings()
        self.language = normalize_lang(settings.get("language", "ru"))
        self.prompt_overrides = set_prompt_overrides(settings.get("prompt_overrides"))
        self.current_world_path = None
        self.world_name = None
        self.history = []
        self.api_url = settings["api_url"]
        self.api_key = settings.get("api_key", "")
        self.model = settings.get("model", "")
        self.token_scales = _scale_table(settings.get("token_scales"))
        saved_scale_model = str(settings.get("token_scale_model") or "")
        saved_counter = str(settings.get("token_scale_counter") or "")
        try:
            legacy_scale = float(settings.get("token_scale", 1.0))
        except (TypeError, ValueError):
            legacy_scale = 1.0
        if saved_scale_model and saved_counter and abs(legacy_scale - 1.0) > 0.001:
            models = self.token_scales.setdefault(saved_counter, {})
            if saved_scale_model not in models:
                models[saved_scale_model] = {"ru": legacy_scale}
        self._restore_token_scale(self.model)
        self.active_api_preset = settings.get("active_api_preset", "")
        self.api_presets = settings.get("api_presets", [])
        self.temperature = settings["temperature"]
        self.max_tokens = settings["max_tokens"]
        self.context_size = settings["context_size"]
        self.summary_fill_percent = settings["summary_fill_percent"]
        self.memory_interval = settings["memory_interval"]
        self.memory_top_k = settings["memory_top_k"]
        self.stream_mode = settings["stream_mode"]
        self.summary_enabled = settings.get("summary_enabled", True)
        self.memory_enabled = settings.get("memory_enabled", True)
        self.lan_access = bool(settings.get("lan_access", True))
        raw_mode = settings.get("play_mode")
        self.play_mode = raw_mode if raw_mode in (adventure_rules.SANDBOX_MODE, adventure_rules.ADVENTURE_MODE) else adventure_rules.SANDBOX_MODE
        self.sandbox_d20 = bool(settings.get("sandbox_d20", False))
        self.sandbox_hero = bool(settings.get("sandbox_hero", False))
        self.sandbox_npc = bool(settings.get("sandbox_npc", False))
        self.hero = None
        self.pending_stats = None
        self._roll_narration = ""
        mode = settings.get("bind_mode")
        self.bind_mode = mode if mode in ("local", "lan", "tailscale") else ("lan" if self.lan_access else "local")
        self.image_prompt_style = settings.get("image_prompt_style", DEFAULT_IMAGE_STYLE)
        self.image_look = settings.get("image_look", DEFAULT_IMAGE_LOOK)
        if self.image_look not in IMAGE_LOOKS:
            self.image_look = DEFAULT_IMAGE_LOOK
        self._apply_image_settings(normalize_image_settings(settings))
        self.response_limits = clamp_response_limits(settings.get("response_limits"))
        self.covered_count = 0
        self.context_ratio = 0.0
        self.context_tokens = 0
        self.context_budget = 1
        self.turns_since_memory = 0
        self.memory_bank = {"last_indexed_turn": 0, "entries": []}
        self.story_cards = {"cards": []}
        self.processing = False
        self.draft_text = ""
        self._dm_streaming = False
        self.revision = 0
        self.stream_start_index = None
        self.last_sent_prompt = None
        self.memory_indexing = False
        self.summary_indexing = False
        self.scene_prompt_running = False
        self.scene_image_running = False
        self._image_target = None
        self._schedule_summary_after_turn = False
        self._schedule_memory_after_turn = False
        self._cancel_events = {}
        for item in self.mode_world_entries():
            try:
                self.load_world(item["name"])
                break
            except ValueError:
                continue
            except CorruptedDataError:
                # Сообщение уже лежит в notices. Не подменяем его другим миром
                # и не роняем сервер: страницу всё равно можно открыть.
                break

    def tr(self, key, **kwargs):
        return t(self.language, key, **kwargs)

    def mode_root(self):
        if self.play_mode == adventure_rules.ADVENTURE_MODE:
            return BASE_DIR / ADVENTURE_DIR
        return BASE_DIR

    def mode_world_entries(self):
        return world_entries_in(self.mode_root())

    def _world_path(self, name):
        cleaned = str(name or "").strip()
        if not cleaned or any(ch in cleaned for ch in '\\/:*?"<>|') or cleaned in {".", ".."}:
            raise ValueError("bad name")
        if self.play_mode != adventure_rules.ADVENTURE_MODE and cleaned == ADVENTURE_DIR:
            raise ValueError("bad name")
        return self.mode_root() / cleaned

    def d20_enabled(self):
        return self.play_mode == adventure_rules.ADVENTURE_MODE or bool(self.sandbox_d20)

    def hero_enabled(self):
        return self.play_mode == adventure_rules.ADVENTURE_MODE or bool(self.sandbox_hero)

    def npc_enabled(self):
        return self.play_mode == adventure_rules.ADVENTURE_MODE or bool(self.sandbox_npc)

    def hero_required_missing(self):
        return bool(self.current_world_path and self.hero_enabled() and not adventure_rules.hero_is_ready(self.hero))

    def _clear_open_world(self):
        self.current_world_path = None
        self.world_name = None
        self.history = []
        self.covered_count = 0
        self.turns_since_memory = 0
        self.story_cards = {"cards": []}
        self.memory_bank = {"last_indexed_turn": 0, "entries": []}
        self.hero = None
        self.pending_stats = None
        self.last_sent_prompt = None
        self.draft_text = ""
        self._dm_streaming = False
        self.notices = []
        self.update_context_indicator()
        self.update_memory_label()
        self.refresh_busy_state()
        self.emit("history")

    def _mode_directory(self, name):
        return world_directory(name, self.mode_root())

    def set_play_mode(self, mode):
        with self._job_lock:
            if self.is_busy():
                raise RuntimeError("busy")
            chosen = adventure_rules.ADVENTURE_MODE if mode == adventure_rules.ADVENTURE_MODE else adventure_rules.SANDBOX_MODE
            if chosen != self.play_mode:
                self.play_mode = chosen
                self.save_settings()
                worlds = self.mode_world_entries()
                if worlds:
                    self._load_world(worlds[0]["name"])
                else:
                    self._clear_open_world()
            return self.state_view()

    def _static_context_text(self, retrieval_query):
        """Веб-обёртка: карточка героя всегда в промпте и не ищется среди story_cards."""
        context = super()._static_context_text(retrieval_query)
        if self.hero_enabled():
            context += adventure_rules.format_hero_block(self.hero, self.language)
        return context

    def _ask_json(self, prompt):
        payload = self._api_payload(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
            stream=True,
        )
        response = self._api_post(payload, stream=True, timeout=60)
        response.raise_for_status()
        text, cancelled = self._read_response(response, ACTION)
        if cancelled:
            return None
        return adventure_rules.extract_json_object(text)

    def _replace_staged_player_line(self, previous, updated):
        if previous == updated:
            return
        line = f"{PLAYER_PREFIX} {updated}"
        if previous and self.history and is_player_msg(self.history[-1]) and player_text(self.history[-1]) == previous:
            self.history[-1] = line
        elif not previous:
            if not self.history or self.history[-1] != line:
                self.history.append(line)
        else:
            return
        if self.current_world_path:
            save_history(self.current_world_path, self.history)
        self.emit("history")

    def roll_narration_cue(self):
        cue = str(self._roll_narration or "")
        self._roll_narration = ""
        return cue

    def prepare_adventure_action(self, user_input="", direction_hint=None):
        self._roll_narration = ""
        if not self.d20_enabled():
            return user_input, direction_hint
        try:
            return self._attach_roll(user_input, direction_hint)
        except Exception:
            self._roll_narration = ""
            return user_input, direction_hint

    def _attach_roll(self, user_input, direction_hint):
        action = (direction_hint or user_input or "").strip() or self.tr("prompt.continue")
        check = adventure_rules.parse_check(self._ask_json(self.tr("prompt.check", action=action)))
        if not check:
            return user_input, direction_hint
        rolled = int(adventure_rules.roll_d20())
        success = adventure_rules.roll_succeeds(rolled, check["dc"])
        self._roll_narration = adventure_rules.format_roll_cue(
            self.language, adventure_rules.roll_outcome(rolled, check["dc"])
        )
        fact = adventure_rules.format_roll_fact(self.language, check["name"], check["dc"], rolled, success)
        if direction_hint:
            updated = f"{direction_hint.rstrip()}\n{fact}"
            self._replace_staged_player_line(direction_hint, updated)
            return user_input, updated
        base = user_input or ""
        updated = f"{base.rstrip()}\n{fact}" if base.strip() else fact
        self._replace_staged_player_line(base, updated)
        return updated, direction_hint

    def finish_adventure_action(self, user_input="", direction_hint=None):
        if not self.hero_enabled() and not self.npc_enabled():
            return
        if not self.current_world_path or not self.history or not is_dm_msg(self.history[-1]):
            return
        try:
            self._apply_followup(user_input, direction_hint)
        except Exception:
            return

    def _apply_followup(self, user_input, direction_hint):
        action = (direction_hint or user_input or "").strip() or self.tr("prompt.none")
        hero_text = (
            adventure_rules.hero_summary(self.hero, self.language)
            if self.hero_enabled()
            else self.tr("prompt.none")
        )
        prompt = self.tr(
            "prompt.followup",
            hero=hero_text,
            action=action,
            reply=dm_text(self.history[-1]),
        )
        data = adventure_rules.parse_followup(self._ask_json(prompt) or {})
        if self.hero_enabled() and adventure_rules.hero_is_ready(self.hero):
            changed = False
            if data["equipment"] and data["equipment"] != str(self.hero.get("equipment") or ""):
                self.hero["equipment"] = data["equipment"]
                changed = True
            if data["appearance"] and data["appearance"] != str(self.hero.get("appearance") or ""):
                self.hero["appearance"] = data["appearance"]
                changed = True
            if changed:
                adventure_rules.save_hero(self.current_world_path, self.hero)
            queued = adventure_rules.changed_stats(self.hero, data["stats"])
            self.pending_stats = (
                {"stats": queued, "current": {key: self.hero.get(key, 10) for key in queued}}
                if queued
                else None
            )
        if self.npc_enabled():
            updated, added = adventure_rules.cards_with_characters(self.story_cards, data["characters"])
            if added:
                save_story_cards(self.current_world_path, updated)
                self.story_cards = updated
        self.emit("history")

    def save_hero_card(self, payload):
        if not self.current_world_path:
            raise RuntimeError("no world")
        self.hero = adventure_rules.normalize_hero(payload)
        adventure_rules.save_hero(self.current_world_path, self.hero)
        self.pending_stats = None
        self.emit("history")
        return self.hero

    def resolve_pending_stats(self, accept):
        pending = self.pending_stats or {}
        self.pending_stats = None
        if accept and adventure_rules.hero_is_ready(self.hero):
            for key, value in (pending.get("stats") or {}).items():
                if key in adventure_rules.STAT_KEYS:
                    self.hero[key] = adventure_rules.clamp_stat(value)
            if self.current_world_path:
                adventure_rules.save_hero(self.current_world_path, self.hero)
        self.emit("history")
        return self.state_view()

    def emit(self, kind, **data):
        self.revision += 1
        event = {"kind": kind, "rev": self.revision, **data}
        with self._sub_lock:
            subs = list(self._subscribers)
        for sub in subs:
            sub.put(event)

    def subscribe(self):
        sub = queue.Queue()
        with self._sub_lock:
            self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub):
        with self._sub_lock:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

    def is_busy(self):
        return bool(
            self.processing
            or self.memory_indexing
            or self.summary_indexing
            or self.scene_prompt_running
            or self.scene_image_running
            or self.cards_running
        )

    def add_system_message(self, message):
        self.notices = [message] if message else []
        self.emit("system", text=message or "")

    def add_player_message(self, message):
        self.emit("history")

    def start_dm_stream(self):
        self.draft_text = ""
        self._dm_streaming = True
        self.emit("dm_start")

    def append_to_dm_stream(self, chunk):
        self.draft_text += chunk
        self.emit("dm_delta", text=chunk, full=self.draft_text)

    def abort_dm_stream(self):
        self.draft_text = ""
        self._dm_streaming = False
        self.emit("dm_abort")

    def finalize_dm_stream(self, final_text):
        self.draft_text = ""
        self._dm_streaming = False
        self.emit("dm_done", text=final_text)
        self.emit("history")

    def _finish_player_turn(self):
        self._dm_streaming = False
        with self._job_lock:
            self.processing = False
            self._end_operation(ACTION)
            start_summary = bool(self._schedule_summary_after_turn) and not self.summary_indexing
            start_memory = (
                bool(self._schedule_memory_after_turn)
                and not self.memory_indexing
                and bool(self.memory_enabled)
            )
            self._schedule_summary_after_turn = False
            self._schedule_memory_after_turn = False
            if start_summary:
                self.summary_indexing = True
            if start_memory:
                self.memory_indexing = True
        self.update_context_indicator()
        if start_summary:
            self._begin_operation(SUMMARY)
        if start_memory:
            self._begin_operation(MEMORY)
        self.refresh_busy_state()
        if start_summary:
            threading.Thread(target=self._generate_global_summary_impl, daemon=True).start()
        if start_memory:
            threading.Thread(target=self._run_memory_indexing_impl, args=(False,), daemon=True).start()

    def start_global_summary(self):
        with self._job_lock:
            if self.summary_indexing or not self.current_world_path:
                return
            if self.processing or self.scene_prompt_running or self.scene_image_running or self.cards_running:
                return
            self.summary_indexing = True
        self._begin_operation(SUMMARY)
        self.refresh_busy_state()
        threading.Thread(target=self._generate_global_summary_impl, daemon=True).start()

    def start_memory_indexing(self, force=False):
        with self._job_lock:
            if self.memory_indexing:
                return
            if not self.memory_enabled and not force:
                return
            if self.processing or self.scene_prompt_running or self.scene_image_running or self.cards_running:
                return
            self.memory_indexing = True
        self._begin_operation(MEMORY)
        self.refresh_busy_state()
        threading.Thread(target=self._run_memory_indexing_impl, args=(force,), daemon=True).start()

    def start_scene_prompt(self):
        with self._job_lock:
            if self.is_busy() or not self.current_world_path:
                return False
            recent = get_recent_turn_messages(self.history, SCENE_TURNS)
            if not any(str(msg).startswith(DM_PREFIX) for msg in recent):
                self.add_system_message(self.tr("scene.needs_history"))
                return False
            self.scene_prompt_running = True
        self._begin_operation(SCENE)
        self.refresh_busy_state()
        threading.Thread(target=self._run_scene_prompt, daemon=True).start()
        return True

    def show_scene_prompt(self, scene_prompt, negative_prompt, style="sd", look="none"):
        auto = (
            bool(self.image_auto)
            and self.image_backend in ("comfy", "a1111")
            and bool(str(scene_prompt or "").strip())
        )
        self.last_scene = {
            "prompt": scene_prompt,
            "negative": negative_prompt,
            "style": style,
            "look": look,
            "image": "",
            "image_file": "",
            "image_pending": auto,
        }
        self.emit("scene", **self.last_scene)
        self.add_system_message(self.tr("msg.scene_prompt_done"))
        if auto:
            self._arm_scene_image()

    def scene_view(self):
        return {
            "scene": self.last_scene,
            "image_prompt_style": self.image_prompt_style,
            "image_styles": list(IMAGE_PROMPT_STYLES),
            "image_look": self.image_look,
            "image_looks": list(IMAGE_LOOKS),
            "image_backend": self.image_backend,
        }

    def update_scene_text(self, prompt, negative=""):
        """Запоминает правку промпта, не запуская генерацию и не перерисовывая панель."""
        if not self.current_world_path:
            return None
        scene = dict(self.last_scene or {})
        scene["prompt"] = str(prompt if prompt is not None else "")
        scene["negative"] = str(negative if negative is not None else "")
        scene.setdefault("style", self.image_prompt_style)
        scene.setdefault("look", self.image_look)
        scene.setdefault("image", "")
        scene.setdefault("image_file", "")
        scene.setdefault("image_pending", False)
        self.last_scene = scene
        return self.scene_view()

    def start_scene_image(self):
        with self._job_lock:
            if self.is_busy() or not self.current_world_path:
                return False
            prompt = str((self.last_scene or {}).get("prompt") or "").strip()
            if not prompt:
                self.add_system_message(self.tr("scene.needs_prompt"))
                return False
            if self.image_backend not in ("comfy", "a1111"):
                self.add_system_message(self.tr("scene.image_off"))
                return False
            self.last_scene = dict(self.last_scene)
            self.last_scene["image_pending"] = True
            self.emit("scene", **self.last_scene)
            return self._arm_scene_image()

    def _arm_scene_image(self):
        self.scene_image_running = True
        self._image_target = {
            "backend": self.image_backend,
            "url": self.comfy_url if self.image_backend == "comfy" else self.a1111_url,
        }
        self._begin_operation(IMAGE)
        self.refresh_busy_state()
        threading.Thread(target=self._run_scene_image, daemon=True).start()
        return True

    def _run_scene_image(self):
        scene = dict(self.last_scene or {})
        prompt = str(scene.get("prompt") or "").strip()
        negative = str(scene.get("negative") or "")
        if not self.image_send_negative:
            negative = ""
        spec = self.image_spec()
        cancel = self._cancel_events.get(IMAGE)
        try:
            data = image_gen.generate(spec, prompt, negative, cancel)
            if not data:
                self._finish_scene_image(stopped=True)
                return
            name = self._save_scene_image(data)
            self._finish_scene_image(name=name)
        except image_gen.ImageGenError as exc:
            self._finish_scene_image(error=exc)
        except Exception as exc:
            self._finish_scene_image(error=exc)
        finally:
            self.scene_image_running = False
            self._image_target = None
            self._end_operation(IMAGE)
            self.refresh_busy_state()

    def _finish_scene_image(self, name=None, error=None, stopped=False):
        scene = dict(self.last_scene or {})
        scene["image_pending"] = False
        if name:
            scene["image_file"] = name
            scene["image"] = "/api/scene/image?name=" + quote(name)
            self.last_scene = scene
            self.emit("scene", **scene)
            self.add_system_message(self.tr("msg.scene_image_done"))
            return
        self.last_scene = scene or None
        if scene:
            self.emit("scene", **scene)
        if stopped:
            self.add_system_message(self.tr("msg.image_stopped"))
        elif error is not None:
            self.add_system_message(self._image_error_text(error))

    def _image_library_dir(self):
        if not self.current_world_path:
            return None
        return (Path(self.current_world_path) / IMAGE_LIBRARY).resolve()

    def _ensure_image_library(self, world_path):
        folder = Path(world_path) / IMAGE_LIBRARY
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def image_library_view(self):
        folder = self._image_library_dir()
        items = []
        if folder is not None and folder.is_dir():
            files = [path for path in folder.iterdir() if path.is_file() and _SCENE_IMAGE_NAME.fullmatch(path.name)]
            files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            items = [
                {"name": path.name, "url": "/api/scene/image?name=" + quote(path.name)}
                for path in files
            ]
        return {"images": items}

    def delete_scene_image(self, name):
        path = self.scene_image_path(name)
        if path is None:
            return False
        path.unlink()
        if self.last_scene and self.last_scene.get("image_file") == path.name:
            scene = dict(self.last_scene)
            scene["image"] = ""
            scene["image_file"] = ""
            scene["image_pending"] = False
            self.last_scene = scene
            self.emit("scene", **scene)
        return True

    def _save_scene_image(self, data):
        suffix = image_gen.image_suffix(data)
        folder = self._ensure_image_library(self.current_world_path)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}{suffix}"
        path = folder / name
        if path.exists():
            name = f"{stamp}-{datetime.now().strftime('%f')}{suffix}"
            path = folder / name
        path.write_bytes(data)
        return name

    def scene_image_path(self, name=None):
        """Файл картинки только из img_bib текущего мира. Чужой путь не отдаётся."""
        if not self.current_world_path:
            return None
        raw = name if name is not None else ((self.last_scene or {}).get("image_file") or "")
        raw = str(raw or "")
        if not raw or raw != Path(raw).name or not _SCENE_IMAGE_NAME.fullmatch(raw):
            return None
        folder = self._image_library_dir()
        candidate = (folder / raw).resolve()
        if candidate.parent != folder or not candidate.is_file():
            return None
        return candidate

    def image_spec(self):
        return {
            "image_backend": self.image_backend,
            "comfy_url": self.comfy_url,
            "a1111_url": self.a1111_url,
            "comfy_workflow": self.comfy_workflow,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "image_steps": self.image_steps,
            "image_send_negative": self.image_send_negative,
        }

    def test_image_connection(self, payload=None):
        payload = payload if isinstance(payload, dict) else {}
        current = self.image_spec()
        current["image_auto"] = self.image_auto
        current.update({key: payload[key] for key in current if key in payload})
        spec = normalize_image_settings(current)
        url = spec["comfy_url"] if spec["image_backend"] == "comfy" else spec["a1111_url"]
        try:
            image_gen.test_connection(spec["image_backend"], url)
        except image_gen.ImageGenError as exc:
            return {"ok": False, "notice": self._image_error_text(exc)}
        return {"ok": True, "notice": self.tr("scene.image_test_ok")}

    def _apply_image_settings(self, spec):
        self.image_backend = spec["image_backend"]
        self.comfy_url = spec["comfy_url"]
        self.a1111_url = spec["a1111_url"]
        self.comfy_workflow = spec["comfy_workflow"]
        self.image_width = spec["image_width"]
        self.image_height = spec["image_height"]
        self.image_steps = spec["image_steps"]
        self.image_auto = spec["image_auto"]
        self.image_send_negative = spec["image_send_negative"]

    def _image_error_text(self, exc):
        if isinstance(exc, image_gen.ImageGenError):
            key = {
                "missing_workflow": "scene.image_missing_workflow",
                "ui_workflow": "scene.image_ui_workflow",
                "bad_workflow": "scene.image_bad_workflow",
                "no_prompt_nodes": "scene.image_no_nodes",
                "offline": "scene.image_offline",
                "rejected": "scene.image_rejected",
                "empty": "scene.image_empty",
                "timeout": "scene.image_timeout",
                "backend_off": "scene.image_off",
            }.get(exc.code, "msg.scene_image_fail")
            return self.tr(key, msg=exc.detail or "")
        return self.tr("msg.scene_image_fail", msg=str(exc))

    def set_scene_options(self, style=None, look=None):
        """Запоминает формат модели и визуальный стиль, выбранные на вкладке сцены."""
        changed = False
        if style in IMAGE_PROMPT_STYLES and style != self.image_prompt_style:
            self.image_prompt_style = style
            changed = True
        if look in IMAGE_LOOKS and look != self.image_look:
            self.image_look = look
            changed = True
        if changed:
            self.save_settings()
        return self.scene_view()

    def refresh_busy_state(self):
        self.emit("status", **self.status_view())

    def update_memory_label(self):
        self.emit("memory", **self.memory_view())
        self.emit("meters", **self.meters_view())

    def update_summary_label(self):
        self.emit("fill", **self.fill_view())
        self.emit("meters", **self.meters_view())

    def _context_fill_color(self, ratio):
        threshold = max(1, int(self.summary_fill_percent)) / 100
        if ratio >= threshold:
            return "danger"
        if ratio >= threshold * 0.75:
            return "accent"
        return "ok"

    def update_context_indicator(self):
        used, budget, ratio = self.context_fill_state()
        self.context_tokens = used
        self.context_budget = max(1, int(budget))
        self.context_ratio = ratio
        self.emit("fill", **self.fill_view())
        self.emit("meters", **self.meters_view())

    def fill_view(self):
        ratio = float(self.context_ratio or 0)
        return {
            "used": int(self.context_tokens or 0),
            "budget": int(self.context_budget or 1),
            "ratio": ratio,
            "percent": int(round(ratio * 100)),
            "color": self._context_fill_color(ratio),
            "label": self.tr(
                "context.since_summary",
                used=format_token_count(self.context_tokens or 0),
                total=format_token_count(self.context_budget or 1),
            ),
            "summary_enabled": bool(self.summary_enabled),
            "summary_fill_percent": int(self.summary_fill_percent),
        }

    def status_view(self):
        if self.processing:
            text = self.tr("status.generating")
        elif self.summary_indexing and self.memory_indexing:
            text = self.tr("status.summary_memory")
        elif self.summary_indexing:
            text = self.tr("status.summary")
        elif self.memory_indexing:
            text = self.tr("status.memory")
        elif self.scene_image_running:
            text = self.tr("status.scene_image")
        elif self.scene_prompt_running:
            text = self.tr("status.scene_prompt")
        elif self.cards_running:
            text = self.tr("cards.generate_desc")
        else:
            text = self.tr("ready")
        return {"busy": self.is_busy(), "stop": bool(self.processing or self.cards_running or self.is_busy()), "text": text}

    def memory_view(self):
        entries = self.memory_bank.get("entries", []) if self.memory_bank else []
        remaining = max(0, int(self.memory_interval) - int(self.turns_since_memory or 0))
        return {
            "enabled": bool(self.memory_enabled),
            "entries": entries,
            "remaining": remaining,
            "interval": int(self.memory_interval),
            "last_indexed_turn": int((self.memory_bank or {}).get("last_indexed_turn") or 0),
        }

    def _fragment_start(self, end):
        end = max(0, min(int(end), len(self.history)))
        start = end
        chars = 0
        while start > 0:
            nxt = start - 1
            piece = len(self.history[nxt] or "")
            if (end - nxt) > HISTORY_PAGE_MESSAGES or (start < end and chars + piece > HISTORY_PAGE_CHARS):
                break
            start = nxt
            chars += piece
        return start

    def history_rows(self, start, end):
        rows = []
        start = max(0, min(int(start), len(self.history)))
        end = max(start, min(int(end), len(self.history)))
        for index in range(start, end):
            msg = self.history[index]
            if is_player_msg(msg):
                kind, text = "player", player_text(msg)
            elif is_dm_msg(msg):
                kind, text = "dm", dm_text(msg)
            elif is_intro_msg(msg):
                kind, text = "intro", intro_text(msg)
            else:
                kind, text = "other", msg
            rows.append({"index": index, "kind": kind, "text": text})
        return rows

    def history_page(self, before):
        total = len(self.history)
        end = max(0, min(int(before), total))
        start = self._fragment_start(end)
        return {
            "history": self.history_rows(start, end),
            "history_from": start,
            "history_total": total,
        }

    def state_view(self, start=None):
        total = len(self.history)
        if start is None:
            start = self._fragment_start(total)
        else:
            start = max(0, min(int(start), total))
        return {
            "world": self.world_name,
            "worlds": self.mode_world_entries(),
            "play_mode": self.play_mode,
            "needs_hero": self.hero_required_missing(),
            "hero": self.hero,
            "pending_stats": self.pending_stats,
            "language": self.language,
            "history": self.history_rows(start, total),
            "history_from": start,
            "history_total": total,
            "notices": list(self.notices),
            "rev": self.revision,
            "streaming": bool(self._dm_streaming),
            "draft": self.draft_text if self._dm_streaming else "",
            "fill": self.fill_view(),
            "status": self.status_view(),
            "memory": self.memory_view(),
            "meters": self.meters_view(),
            "cards": self.story_cards,
            "presets": self.presets_view(),
        }

    def meters_view(self):
        entries = len((self.memory_bank or {}).get("entries", []))
        ratio = float(self.context_ratio or 0)
        if not self.current_world_path:
            summary_text = self.tr("summary_until")
            memory_text = self.tr("memory_until")
            summary_color = ""
            memory_color = ""
        elif self.summary_enabled:
            summary_text = self.tr("summary.fill", percent=int(round(ratio * 100)))
            summary_color = self._context_fill_color(ratio)
        else:
            summary_text = self.tr("summary.off")
            summary_color = ""
        if self.current_world_path and self.memory_enabled:
            remaining = max(0, int(self.memory_interval) - int(self.turns_since_memory or 0))
            memory_text = self.tr("memory.until", n=entries, remaining=remaining)
            memory_color = "accent" if remaining <= 1 else ""
        elif self.current_world_path:
            memory_text = self.tr("memory.off", n=entries)
            memory_color = ""
        return {
            "summary_enabled": bool(self.summary_enabled),
            "memory_enabled": bool(self.memory_enabled),
            "summary_text": summary_text,
            "memory_text": memory_text,
            "summary_color": summary_color,
            "memory_color": memory_color,
            "summary_toggle": self.tr("toggle.summary_on" if self.summary_enabled else "toggle.summary_off"),
            "memory_toggle": self.tr("toggle.memory_on" if self.memory_enabled else "toggle.memory_off"),
        }

    def toggle_summary(self):
        self.summary_enabled = not self.summary_enabled
        self.save_settings()
        self.update_context_indicator()
        return self.meters_view()

    def toggle_memory(self):
        self.memory_enabled = not self.memory_enabled
        self.save_settings()
        self.update_memory_label()
        return self.meters_view()

    def world_template(self):
        templates = default_templates(self.language)
        return {
            "name": self.tr("dialog.default_world_name"),
            "files": {fname: templates.get(fname, "") for fname in WORLD_FILES},
            "cards": default_story_cards(self.language),
        }

    def load_world(self, world_name):
        with self._job_lock:
            return self._load_world(world_name)

    def _load_world(self, world_name):
        if self.is_busy():
            raise RuntimeError("busy")
        cleaned, world_path = self._mode_directory(world_name)
        if not world_path.is_dir():
            raise FileNotFoundError(cleaned)
        previous_lang = self._count_language()
        try:
            _files, loaded_history, restored = load_world_config(cleaned, self.mode_root())
        except CorruptedDataError as exc:
            self.add_system_message(
                self.tr("dialog.corrupt_history", name=cleaned, file=exc.path.name, detail=exc.detail)
            )
            raise
        self.current_world_path = world_path
        self.world_name = cleaned
        self.last_sent_prompt = None
        self.notices = []
        self.history = ensure_introduction_in_history(world_path, loaded_history)
        if self.history != loaded_history:
            save_history(world_path, self.history)
        self._load_summary_cursor(loaded_history)
        self.memory_bank = load_memory_bank(world_path)
        self.story_cards = load_story_cards(world_path)
        self.hero = adventure_rules.load_hero(world_path)
        self.pending_stats = None
        current_turns = count_completed_turns(self.history)
        self.turns_since_memory = current_turns - self.memory_bank.get("last_indexed_turn", 0)
        if restored:
            self.add_system_message(self.tr("msg.history_restored"))
        self.add_system_message(self.tr("msg.world_loaded", name=cleaned))
        self._switch_count_language(previous_lang)
        self.update_memory_label()
        self.update_context_indicator()
        self.emit("history")

    def _remember_token_scale(self, model=None, lang=None):
        """Запоминает уже измеренный масштаб за моделью и языком текста."""
        name = str(self.model if model is None else model or "")
        language = normalize_lang(self._count_language() if lang is None else lang)
        if not name or not model_scale_observed():
            return
        bucket = self.token_scales.setdefault(counter_kind(), {})
        slot = bucket.get(name)
        if not isinstance(slot, dict):
            slot = {}
            bucket[name] = slot
        slot[language] = model_token_scale()

    def _restore_token_scale(self, model, lang=None):
        """Возвращает сохранённый масштаб. False, если эту пару ещё не сверяли."""
        language = normalize_lang(self._count_language() if lang is None else lang)
        saved = self.token_scales.get(counter_kind(), {}).get(str(model or ""))
        value = None
        if isinstance(saved, dict):
            value = saved.get(language)
        elif isinstance(saved, (int, float)) and language == "ru":
            value = float(saved)
        if value is None:
            set_model_token_scale(1.0)
            return False
        set_model_token_scale(value)
        return model_scale_observed()

    def _switch_count_language(self, previous_lang):
        """Берёт масштаб языка мира. Русская поправка не применяется к английскому тексту."""
        previous = normalize_lang(previous_lang)
        current = self._count_language()
        if previous == current:
            return
        self._remember_token_scale(lang=previous)
        if self._restore_token_scale(self.model, current):
            return
        self._calibrate_token_scale()
        self._remember_token_scale()

    def _switch_model_scale(self, previous_model):
        """Перед перерисовкой шкалы берёт масштаб новой модели, а не сырой счётчик.

        Неизвестную модель сначала сверяет коротким запросом. Пока проба не
        дошла, шкала остаётся на локальной оценке, как до первого хода.
        """
        previous = str(previous_model or "")
        current = str(self.model or "")
        if previous == current:
            return
        self._remember_token_scale(previous)
        if self._restore_token_scale(current):
            return
        self._calibrate_token_scale()
        self._remember_token_scale(current)

    def save_settings(self):
        self._remember_token_scale()
        save_global_settings(
            {
                "api_url": self.api_url,
                "api_key": self.api_key,
                "model": self.model,
                "active_api_preset": self.active_api_preset,
                "api_presets": self.api_presets,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "context_size": self.context_size,
                "summary_fill_percent": self.summary_fill_percent,
                "memory_interval": self.memory_interval,
                "memory_top_k": self.memory_top_k,
                "stream_mode": self.stream_mode,
                "summary_enabled": self.summary_enabled,
                "memory_enabled": self.memory_enabled,
                "image_prompt_style": self.image_prompt_style,
                "image_look": self.image_look,
                **self.image_spec(),
                "image_auto": self.image_auto,
                "response_limits": self.response_limits,
                "language": self.language,
                "prompt_overrides": self.prompt_overrides,
                "lan_access": self.lan_access,
                "bind_mode": self.bind_mode,
                "play_mode": self.play_mode,
                "sandbox_d20": bool(self.sandbox_d20),
                "sandbox_hero": bool(self.sandbox_hero),
                "sandbox_npc": bool(self.sandbox_npc),
                "token_scale": model_token_scale(),
                "token_scale_model": self.model,
                "token_scale_counter": counter_kind(),
                "token_scales": self.token_scales,
            }
        )

    def settings_view(self):
        groups = []
        for group_key, keys in PROMPT_GROUPS:
            prompts = []
            for key in keys:
                override = self.prompt_overrides.get(self.language, {}).get(key, "")
                builtin = builtin_prompt(self.language, key)
                item = {
                    "key": key,
                    "name": self.tr("prompt_name." + key[len("prompt.") :]),
                    "text": override if isinstance(override, str) and override.strip() else builtin,
                    "builtin": builtin,
                    "override": override,
                }
                if key in DEFAULT_RESPONSE_LIMITS:
                    item["limit"] = self.response_limits.get(key, DEFAULT_RESPONSE_LIMITS[key])
                prompts.append(item)
            groups.append({"title": self.tr(group_key), "prompts": prompts})
        return {
            "api_url": self.api_url,
            "api_key": self.api_key,
            "model": self.model,
            "active_api_preset": self.active_api_preset,
            "api_presets": self.api_presets,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "context_size": self.context_size,
            "summary_fill_percent": self.summary_fill_percent,
            "memory_interval": self.memory_interval,
            "memory_top_k": self.memory_top_k,
            "stream_mode": self.stream_mode,
            "summary_enabled": self.summary_enabled,
            "memory_enabled": self.memory_enabled,
            "image_prompt_style": self.image_prompt_style,
            "image_styles": list(IMAGE_PROMPT_STYLES),
            "image_look": self.image_look,
            "image_looks": list(IMAGE_LOOKS),
            "image_backends": list(IMAGE_BACKENDS),
            **self.image_spec(),
            "image_auto": self.image_auto,
            "workflows": list_workflow_files(),
            "response_limits": dict(self.response_limits),
            "language": self.language,
            "lan_access": self.lan_access,
            "bind_mode": self.bind_mode,
            "play_mode": self.play_mode,
            "sandbox_d20": bool(self.sandbox_d20),
            "sandbox_hero": bool(self.sandbox_hero),
            "sandbox_npc": bool(self.sandbox_npc),
            "prompts": groups,
            "prompt_overrides": self.prompt_overrides,
        }

    def apply_settings(self, payload):
        with self._job_lock:
            return self._apply_settings(payload)

    def _apply_settings(self, payload):
        if self.is_busy():
            raise RuntimeError("busy")
        overrides = payload.get("prompt_overrides", self.prompt_overrides)
        language = normalize_lang(payload.get("language", self.language))
        problems = []
        if isinstance(overrides, dict):
            for lang in ("ru", "en"):
                bucket = overrides.get(lang) or {}
                if not isinstance(bucket, dict):
                    continue
                for key, text in bucket.items():
                    issues = prompt_edit_issues(lang, key, text if isinstance(text, str) else "")
                    if issues:
                        problems.append({"lang": lang, "key": key, **issues})
        if problems:
            return problems
        previous_count_lang = self._count_language()
        self.language = language
        self.api_url = str(payload.get("api_url", self.api_url) or "")
        self.api_key = str(payload.get("api_key", self.api_key) or "")
        previous_model = self.model
        self.active_api_preset = str(payload.get("active_api_preset", self.active_api_preset) or "")
        self.api_presets = normalize_api_presets(payload.get("api_presets", self.api_presets))
        self.temperature = _as_float(payload.get("temperature", self.temperature), self.temperature, 0, 2)
        self.max_tokens = _as_int(payload.get("max_tokens", self.max_tokens), self.max_tokens, 1, 100000)
        self.context_size = _as_int(payload.get("context_size", self.context_size), self.context_size, 1, 2_000_000)
        self.summary_fill_percent = clamp_summary_fill_percent(payload.get("summary_fill_percent", self.summary_fill_percent))
        self.memory_interval = _as_int(payload.get("memory_interval", self.memory_interval), self.memory_interval, 1, 1000)
        self.memory_top_k = _as_int(payload.get("memory_top_k", self.memory_top_k), self.memory_top_k, 1, 100)
        self.stream_mode = bool(payload.get("stream_mode", self.stream_mode))
        self.summary_enabled = bool(payload.get("summary_enabled", self.summary_enabled))
        self.memory_enabled = bool(payload.get("memory_enabled", self.memory_enabled))
        self.lan_access = bool(payload.get("lan_access", self.lan_access))
        if "sandbox_d20" in payload:
            self.sandbox_d20 = bool(payload.get("sandbox_d20"))
        if "sandbox_hero" in payload:
            self.sandbox_hero = bool(payload.get("sandbox_hero"))
        if "sandbox_npc" in payload:
            self.sandbox_npc = bool(payload.get("sandbox_npc"))
        if not self.lan_access:
            self.bind_mode = "local"
        elif self.bind_mode == "local":
            self.bind_mode = "lan"
        style = payload.get("image_prompt_style", self.image_prompt_style)
        self.image_prompt_style = style if style in IMAGE_PROMPT_STYLES else DEFAULT_IMAGE_STYLE
        look = payload.get("image_look", self.image_look)
        self.image_look = look if look in IMAGE_LOOKS else DEFAULT_IMAGE_LOOK
        current = self.image_spec()
        current["image_auto"] = self.image_auto
        for key in (
            "image_backend",
            "comfy_url",
            "a1111_url",
            "comfy_workflow",
            "image_width",
            "image_height",
            "image_steps",
            "image_auto",
            "image_send_negative",
        ):
            if key in payload:
                current[key] = payload[key]
        self._apply_image_settings(normalize_image_settings(current))
        if "response_limits" in payload:
            self.response_limits = clamp_response_limits(payload.get("response_limits"))
        self.prompt_overrides = set_prompt_overrides(overrides)
        self._switch_count_language(previous_count_lang)
        self.model = str(payload.get("model", self.model) or "")
        self._switch_model_scale(previous_model)
        self.save_settings()
        self.update_context_indicator()
        self.update_memory_label()
        self.refresh_busy_state()
        return []

    def presets_view(self):
        return {
            "active": self.active_api_preset or "",
            "items": [
                {"name": item["name"], "model": item.get("model") or ""}
                for item in self.api_presets
            ],
        }

    def activate_preset(self, name):
        """Подставляет сохранённые адрес, ключ и модель и сразу записывает настройки."""
        with self._job_lock:
            return self._activate_preset(name)

    def _activate_preset(self, name):
        if self.is_busy():
            raise RuntimeError("busy")
        wanted = str(name or "").strip()
        found = next((item for item in self.api_presets if item["name"] == wanted), None)
        if found is None:
            raise KeyError(wanted)
        previous_model = self.model
        self.api_url = found.get("api_url") or ""
        self.api_key = found.get("api_key") or ""
        self.model = found.get("model") or ""
        self.active_api_preset = found["name"]
        self._switch_model_scale(previous_model)
        self.save_settings()
        self.update_context_indicator()
        return self.presets_view()

    def strings_view(self):
        keys = [
            "app_title",
            "ready",
            "btn.send",
            "btn.make_move",
            "btn.menu",
            "btn.models",
            "btn.modes",
            "mode.sandbox",
            "mode.adventure",
            "models.empty",
            "dialog.section_sandbox_mechanics",
            "dialog.sandbox_d20",
            "dialog.sandbox_hero",
            "dialog.sandbox_npc",
            "hero.title",
            "hero.name",
            "hero.appearance",
            "hero.equipment",
            "hero.strength",
            "hero.dexterity",
            "hero.constitution",
            "hero.intelligence",
            "hero.wisdom",
            "hero.charisma",
            "hero.required",
            "hero.confirm_title",
            "hero.confirm_hint",
            "hero.confirm",
            "hero.reject",
            "btn.next",
            "btn.stop",
            "btn.undo",
            "btn.edit_last",
            "btn.save_ok",
            "btn.reroll",
            "btn.summary",
            "btn.memory",
            "btn.scene_prompt",
            "btn.scene_image",
            "btn.gallery",
            "btn.prompt",
            "btn.world_files",
            "btn.cards",
            "btn.worlds",
            "btn.ai_settings",
            "btn.load",
            "btn.export",
            "btn.import",
            "btn.create_ok",
            "btn.cancel",
            "btn.cancel_plain",
            "btn.save",
            "btn.save_as",
            "btn.delete_icon",
            "btn.reset_prompt",
            "btn.create",
            "btn.delete",
            "btn.add",
            "btn.close",
            "dialog.next_title",
            "dialog.next_hint",
            "dialog.empty_next",
            "dialog.world_name",
            "dialog.import_failed",
            "dialog.edit_dm",
            "dialog.edit_dm_label",
            "dialog.edit_player",
            "dialog.edit_player_label",
            "dialog.edit_prev",
            "dialog.edit_next",
            "dialog.tab_ai",
            "dialog.tab_game",
            "dialog.lan_title",
            "dialog.lan_access",
            "dialog.lan_hint",
            "dialog.lan_restart",
            "dialog.lan_this_computer",
            "dialog.lan_phone",
            "dialog.lan_tailscale",
            "dialog.lan_none",
            "dialog.tab_prompts",
            "dialog.api_config",
            "dialog.api_url",
            "dialog.api_key",
            "dialog.show_key",
            "dialog.model",
            "dialog.manual_preset",
            "dialog.preset_name",
            "dialog.delete_preset_pick",
            "dialog.delete_preset_q",
            "dialog.temperature",
            "dialog.max_tokens",
            "dialog.context_size",
            "dialog.gen_params",
            "dialog.stream",
            "dialog.section_summary",
            "dialog.auto_summary",
            "dialog.summary_fill",
            "dialog.section_memory",
            "dialog.memory_bank",
            "dialog.memory_every",
            "dialog.memory_top_k",
            "dialog.image_style",
            "dialog.image_look",
            "dialog.section_image",
            "dialog.image_backend",
            "image_backend.off",
            "image_backend.comfy",
            "image_backend.a1111",
            "dialog.comfy_url",
            "dialog.a1111_url",
            "dialog.comfy_workflow",
            "dialog.workflow_empty",
            "dialog.workflow_hint",
            "dialog.image_width",
            "dialog.image_height",
            "dialog.image_steps",
            "dialog.image_auto",
            "dialog.image_send_negative",
            "dialog.image_test",
            "dialog.response_limit",
            "image_style.sd",
            "image_style.midjourney",
            "image_style.flux",
            "image_style.generic",
            "image_look.none",
            "image_look.anime",
            "image_look.realism",
            "image_look.painting",
            "image_look.cinematic",
            "scene.format",
            "scene.look",
            "scene.prompt_label",
            "scene.negative_label",
            "world_file.introduction.txt",
            "world_file.ai_instructions.txt",
            "world_file.plot_basics.txt",
            "world_file.author_notes.txt",
            "world_file.summary.txt",
            "cards.list",
            "cards.search",
            "cards.title",
            "cards.desc",
            "cards.triggers",
            "cards.triggers_ph",
            "cards.empty_triggers",
            "cards.untitled",
            "cards.new",
            "cards.delete_q",
            "cards.generate_desc",
            "cards.enter_title_first",
            "dialog.your_worlds",
            "dialog.delete_world_q",
            "dialog.create_world",
            "dialog.default_world_name",
            "dialog.bad_name_msg",
            "world_file.story_cards",
            "no_worlds",
            "worlds.lang.ru",
            "worlds.lang.en",
            "status.generating",
            "status.summary",
            "status.memory",
            "status.summary_memory",
            "status.scene_prompt",
            "status.scene_image",
            "dialog.busy",
            "dialog.no_world",
            "dialog.no_prompt",
            "dialog.prompt_time",
            "dialog.prompt_body",
            "dialog.memory_empty",
            "dialog.memory_stats",
            "dialog.memory_entry",
            "dialog.memory_title",
            "log.earlier",
            "btn.copy",
            "msg.prompt_copied",
            "scene.copy_prompt",
            "scene.copy_negative",
            "scene.copied_prompt",
            "scene.copied_negative",
            "scene.needs_history",
            "scene.needs_world",
            "scene.needs_prompt",
            "scene.image_alt",
            "gallery.empty",
            "gallery.delete",
            "gallery.delete_q",
            "scene.image_off",
            "scene.image_test_ok",
        ]
        return {key: self.tr(key) for key in keys}

    def begin_action_turn(self):
        self.notices = []
        self.draft_text = ""
        self.emit("system", text="")
        self.processing = True
        self._begin_operation(ACTION)
        self.refresh_busy_state()

    def _stage_player_line(self, text):
        """Кладёт реплику игрока в ленту до запроса к модели."""
        text = (text or "").strip()
        if not text:
            return
        line = f"{PLAYER_PREFIX} {text}"
        if self.history and self.history[-1] == line:
            return
        self.history.append(line)
        if self.current_world_path:
            save_history(self.current_world_path, self.history)
        self.emit("history")

    def submit_turn(self, text="", direction=""):
        with self._job_lock:
            if self.is_busy() or not self.current_world_path or self.hero_required_missing():
                return False
            self.processing = True
            if direction:
                direction = direction.strip()
                self._stage_player_line(direction)
                args, kwargs = ("",), {"direction_hint": direction}
            else:
                text = (text or "").strip()
                self._stage_player_line(text)
                args, kwargs = (text,), None
        self._dispatch_turn(self.process_action, args, kwargs)
        return True

    def stop(self):
        target = self._image_target
        stopped = self.request_stop()
        if target and IMAGE in stopped:
            image_gen.interrupt(target.get("backend"), target.get("url"))
        if stopped:
            self.add_system_message(self.tr("msg.stop_requested"))
            self.refresh_busy_state()
        return stopped

    def undo(self):
        with self._job_lock:
            return self._undo()

    def _undo(self):
        if self.is_busy() or not self.history or not self.current_world_path:
            return False
        self.history.pop()
        self.covered_count = clamp_summary_cursor(self.covered_count, len(self.history))
        save_history(self.current_world_path, self.history)
        save_summary_cursor(self.current_world_path, self.covered_count)
        self.memory_bank, self.turns_since_memory = sync_memory_bank_after_undo(self.history, self.memory_bank)
        save_memory_bank(self.current_world_path, self.memory_bank)
        self.update_context_indicator()
        self.update_memory_label()
        self.add_system_message(self.tr("msg.undone"))
        self.emit("history")
        return True

    def rewind_last_reply(self):
        if self.history and is_dm_msg(self.history[-1]):
            self.history.pop()
        self.covered_count = clamp_summary_cursor(self.covered_count, len(self.history))
        if self.current_world_path:
            save_summary_cursor(self.current_world_path, self.covered_count)
        if self.history and is_player_msg(self.history[-1]):
            return player_text(self.history[-1])
        return ""

    def regenerate(self):
        with self._job_lock:
            if self.is_busy() or not self.history or not self.current_world_path or self.hero_required_missing():
                return False
            self.processing = True
            last_player_input = self.rewind_last_reply()
            save_history(self.current_world_path, self.history)
        self.update_context_indicator()
        self.emit("history")
        self._dispatch_turn(self.process_action, (last_player_input,))
        return True

    def edit_message(self, index, text):
        with self._job_lock:
            return self._edit_message(index, text)

    def _edit_message(self, index, text):
        if self.is_busy() or not self.current_world_path:
            return False
        if index < 0 or index >= len(self.history):
            return False
        msg = self.history[index]
        if is_dm_msg(msg):
            prefix = DM_PREFIX
        elif is_player_msg(msg):
            prefix = PLAYER_PREFIX
        else:
            return False
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        new_line = f"{prefix} {cleaned}"
        changed = self.history[index] != new_line
        self.history[index] = new_line
        if changed:
            self.note_history_revised(index)
        save_history(self.current_world_path, self.history)
        self.update_context_indicator()
        self.emit("history")
        return True

    def sync_introduction_to_history(self, intro):
        before = list(self.history)
        intro_msg = format_introduction_history(intro)
        if self.history and self.history[0].startswith(INTRO_PREFIX):
            if intro_msg:
                self.history[0] = intro_msg
            else:
                self.history.pop(0)
        elif intro_msg:
            self.history.insert(0, intro_msg)
        delta = self._introduction_cursor_delta(before, self.history)
        if self.covered_count > 0 and delta:
            self.covered_count += delta
        self.covered_count = clamp_summary_cursor(self.covered_count, len(self.history))
        save_history(self.current_world_path, self.history)
        if self.current_world_path:
            save_summary_cursor(self.current_world_path, self.covered_count)
        self.update_context_indicator()
        self.emit("history")

    def world_files(self):
        if not self.current_world_path:
            return {}
        files = {}
        for fname in WORLD_FILES:
            path = self.current_world_path / fname
            files[fname] = path.read_text(encoding="utf-8") if path.exists() else ""
        return files

    def save_world_file(self, name, content):
        with self._job_lock:
            return self._save_world_file(name, content)

    def _save_world_file(self, name, content):
        if not self.current_world_path or name not in WORLD_FILES:
            return False
        if self.is_busy():
            raise RuntimeError("busy")
        if not isinstance(content, str):
            content = "" if content is None else str(content)
        atomic_write_text(self.current_world_path / name, content)
        if name == INTRODUCTION_FILE:
            self.sync_introduction_to_history(content.strip())
        else:
            self.update_context_indicator()
        self.add_system_message(self.tr("msg.file_saved", name=name))
        return True

    def save_cards(self, cards):
        with self._job_lock:
            return self._save_cards(cards)

    def _save_cards(self, cards):
        if not self.current_world_path or not isinstance(cards, dict):
            return False
        if self.is_busy():
            raise RuntimeError("busy")
        save_story_cards(self.current_world_path, cards)
        self.story_cards = cards
        self.update_context_indicator()
        self.add_system_message(self.tr("msg.cards_saved"))
        self.emit("history")
        return True

    def _flush_open_world(self):
        if not self.current_world_path:
            return
        save_history(self.current_world_path, self.history)
        save_summary_cursor(self.current_world_path, self.covered_count)
        save_memory_bank(self.current_world_path, self.memory_bank)

    def export_world_bytes(self, name):
        with self._job_lock:
            return self._export_world_bytes(name)

    def _export_world_bytes(self, name):
        cleaned, world_path = self._mode_directory(name)
        if not world_path.is_dir():
            raise FileNotFoundError(cleaned)
        if self.world_name == cleaned:
            if self.is_busy():
                raise RuntimeError("busy")
            self._flush_open_world()
        buffer = io.BytesIO()
        count = 0
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(world_path.iterdir(), key=lambda item: item.name):
                if path.is_symlink() or not path.is_file():
                    continue
                if path.resolve().parent != world_path or not allowed_world_filename(path.name):
                    continue
                archive.write(path, path.name)
                count += 1
        if count == 0:
            raise FileNotFoundError(cleaned)
        return buffer.getvalue(), cleaned

    def import_world_bytes(self, name, payload):
        with self._job_lock:
            return self._import_world_bytes(name, payload)

    def _import_world_bytes(self, name, payload):
        if self.is_busy():
            raise RuntimeError("busy")
        try:
            cleaned, world_path = self._mode_directory(name)
        except ValueError as exc:
            raise ValueError("bad archive") from exc
        if world_path.exists():
            raise FileExistsError(cleaned)
        files = read_world_archive(payload)
        world_path.mkdir(parents=True)
        self._ensure_image_library(world_path)
        try:
            for filename, data in files.items():
                (world_path / filename).write_bytes(data)
            if self.play_mode == adventure_rules.ADVENTURE_MODE:
                adventure_rules.write_mode_mark(world_path)
            self.load_world(cleaned)
        except Exception:
            if self.world_name != cleaned:
                shutil.rmtree(world_path, ignore_errors=True)
            raise
        return cleaned

    def create_world(self, name, files=None, cards=None):
        with self._job_lock:
            return self._create_world(name, files, cards)

    def _create_world(self, name, files=None, cards=None):
        if self.is_busy():
            raise RuntimeError("busy")
        cleaned, world_path = self._mode_directory(name)
        if world_path.exists():
            raise FileExistsError(cleaned)
        content = dict(default_templates(self.language))
        if isinstance(files, dict):
            for fname in WORLD_FILES:
                if fname in files:
                    content[fname] = str(files[fname])
        save_world_files(world_path, content)
        save_world_language(world_path, self.language)
        if self.play_mode == adventure_rules.ADVENTURE_MODE:
            adventure_rules.write_mode_mark(world_path)
        card_data = cards if isinstance(cards, dict) else default_story_cards(self.language)
        save_story_cards(world_path, card_data)
        intro = str(content.get(INTRODUCTION_FILE, "")).strip()
        initial = [format_introduction_history(intro)] if intro else []
        save_history(world_path, initial)
        self._ensure_image_library(world_path)
        self.load_world(cleaned)
        return cleaned

    def delete_world(self, name):
        with self._job_lock:
            return self._delete_world(name)

    def _delete_world(self, name):
        cleaned, world_path = self._mode_directory(name)
        if not world_path.is_dir():
            return False
        if self.is_busy() and self.world_name == cleaned:
            raise RuntimeError("busy")
        shutil.rmtree(world_path)
        if self.world_name != cleaned:
            return True
        self.current_world_path = None
        self.world_name = None
        self.history = []
        self.covered_count = 0
        self.turns_since_memory = 0
        self.story_cards = {"cards": []}
        self.memory_bank = {"last_indexed_turn": 0, "entries": []}
        self.hero = None
        self.pending_stats = None
        self.last_sent_prompt = None
        self.draft_text = ""
        self._dm_streaming = False
        self.notices = []
        loaded = False
        for item in self.mode_world_entries():
            candidate = item["name"]
            if candidate == cleaned:
                continue
            try:
                self.load_world(candidate)
                loaded = True
                break
            except ValueError:
                continue
            except CorruptedDataError:
                break
        if not loaded:
            self.update_memory_label()
            self.update_context_indicator()
            self.refresh_busy_state()
            self.emit("history")
        return True

    def summarize(self):
        with self._job_lock:
            if not self.current_world_path or self.is_busy():
                return False
            self.summary_indexing = True
        self._begin_operation(SUMMARY)
        self.refresh_busy_state()
        threading.Thread(target=self._generate_global_summary_impl, daemon=True).start()
        return True

    def describe_card(self, title, description=""):
        with self._job_lock:
            if not self.current_world_path or self.is_busy():
                return False
            self.cards_running = True
        self._begin_operation(CARDS)
        self.refresh_busy_state()
        history = list(self.history)
        card_limit = response_token_limit(self.response_limits, "prompt.card_desc_gen")
        history_budget = max(0, int(self.context_size or 0) - 1500)

        def run():
            try:
                world_context = ""
                for fname in WORLD_FILES:
                    if fname in ("summary.txt", INTRODUCTION_FILE):
                        continue
                    path = self.current_world_path / fname
                    if path.exists():
                        content = path.read_text(encoding="utf-8").strip()
                        if content:
                            world_context += f"=== {fname} ===\n{content}\n"
                summary_path = self.current_world_path / "summary.txt"
                summary_content = summary_path.read_text(encoding="utf-8").strip() if summary_path.exists() else ""
                if summary_content:
                    world_context += self.tr("prompt.summary_header", text=summary_content)
                author_path = self.current_world_path / "author_notes.txt"
                author_notes = author_path.read_text(encoding="utf-8").strip() if author_path.exists() else ""
                preview = []
                preview_tokens = 0
                for msg in reversed(history):
                    msg_tokens = count_tokens(msg) + 1
                    if preview_tokens + msg_tokens > history_budget:
                        break
                    preview.insert(0, msg)
                    preview_tokens += msg_tokens
                history_fragment = "\n".join(preview)
                prompt = self.tr(
                    "prompt.card_desc_gen",
                    world_context=world_context or self.tr("prompt.none"),
                    card_title=title,
                    plot_basics=description or self.tr("prompt.none"),
                    author_notes=author_notes or self.tr("prompt.none"),
                    history_fragment=history_fragment or self.tr("prompt.none"),
                )
                payload = self._api_payload(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=card_limit,
                    stream=True,
                )
                response = self._api_post(payload, stream=True, timeout=120)
                response.raise_for_status()
                generated, cancelled = self._read_response(response, CARDS)
                if not cancelled:
                    self.emit("card_desc", title=title, text=generated)
            except Exception as exc:
                self.add_system_message(self.tr("msg.error", msg=str(exc)))
            finally:
                with self._job_lock:
                    self.cards_running = False
                self._end_operation(CARDS)
                self.refresh_busy_state()

        threading.Thread(target=run, daemon=True).start()
        return True

    def prompt_view(self):
        return self.last_sent_prompt
