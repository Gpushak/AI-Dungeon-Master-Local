import json
import os
import re
import shutil
from pathlib import Path

from .config import (
    BASE_DIR,
    DEFAULT_API_URL,
    DEFAULT_IMAGE_LOOK,
    DEFAULT_IMAGE_STYLE,
    IMAGE_LOOKS,
    IMAGE_PROMPT_STYLES,
    INTRODUCTION_FILE,
    SETTINGS_FILE,
    WORLD_FILES,
    clamp_response_limits,
    normalize_image_settings,
)
from .i18n import INTRO_PREFIX, normalize_prompt_overrides


class CorruptedDataError(Exception):
    """Файл данных повреждён и не читается даже из резервной копии."""

    def __init__(self, path, detail=""):
        self.path = Path(path)
        self.detail = detail
        super().__init__(f"{self.path.name}: {detail}" if detail else self.path.name)


def backup_path(path):
    return Path(path).with_name(Path(path).name + ".bak")


def atomic_write_text(path, text):
    """Пишет файл атомарно.

    Сначала содержимое попадает во временный файл и принудительно сбрасывается
    на диск, затем прошлое содержимое копируется в .bak, и только потом
    временный файл переименовывается на место. Поэтому обрыв записи
    (сбой питания, кончившееся место) не оставит ни пустого, ни обрезанного
    файла: старая версия останется целой в .bak.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        try:
            shutil.copy2(path, backup_path(path))
        except OSError:
            # Резервная копия — лучшее усилие; запись не должна падать из-за неё
            pass
    os.replace(tmp, path)


def atomic_write_json(path, payload):
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def read_json_with_backup(path, default):
    """Читает JSON, а при повреждении пробует резервную копию.

    Возвращает пару (данные, восстановлено_ли_из_бэкапа). Если не читается ни
    один из файлов — бросает CorruptedDataError вместо молчаливой подстановки
    пустого значения: потерять историю кампании без предупреждения нельзя.
    """
    path = Path(path)
    first_error = None
    for candidate, is_backup in ((path, False), (backup_path(path), True)):
        if not candidate.exists():
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f), is_backup
        except (OSError, ValueError) as e:
            first_error = e
    if first_error is not None:
        raise CorruptedDataError(path, str(first_error))
    return default, False


def format_introduction_history(intro_text):
    intro_text = intro_text.strip()
    return f"{INTRO_PREFIX} {intro_text}" if intro_text else None


def ensure_introduction_in_history(world_path, history):
    world_path = Path(world_path)
    history = list(history)
    intro_path = world_path / INTRODUCTION_FILE
    if not intro_path.exists():
        return history

    intro_text = intro_path.read_text(encoding="utf-8").strip()
    intro_msg = format_introduction_history(intro_text)

    if not intro_msg:
        if history and history[0].startswith(INTRO_PREFIX):
            return history[1:]
        return history

    if history and history[0].startswith(INTRO_PREFIX):
        history[0] = intro_msg
    else:
        history.insert(0, intro_msg)
    return history


# Каталог миров «Приключения». Лежит рядом с мирами песочницы и сам миром не является.
ADVENTURE_DIR = "adventure"


def get_world_list():
    if not BASE_DIR.exists():
        BASE_DIR.mkdir()
    return [d.name for d in BASE_DIR.iterdir() if d.is_dir() and d.name != ADVENTURE_DIR]


LANGUAGE_FILE = "language.txt"
_CYRILLIC_LETTER = re.compile(r"[а-яёА-ЯЁ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")


def save_world_language(world_path, language):
    """Запоминает, для какой локализации создан мир."""
    lang = "en" if str(language or "").lower().startswith("en") else "ru"
    atomic_write_text(Path(world_path) / LANGUAGE_FILE, lang + "\n")


def read_world_language(world_path):
    """ru, en или пусто, если по файлам мира язык не разобрать.

    Новые миры хранят язык в language.txt. Старые определяются по буквам
    вступления и описаний: кириллица — русский шаблон, латиница — английский.
    """
    path = Path(world_path)
    marker = path / LANGUAGE_FILE
    if marker.is_file():
        text = marker.read_text(encoding="utf-8").strip().lower()
        if text.startswith("en"):
            return "en"
        if text.startswith("ru"):
            return "ru"
    cyrillic = latin = 0
    for fname in ("introduction.txt", "plot_basics.txt", "ai_instructions.txt", "author_notes.txt"):
        file_path = path / fname
        if not file_path.is_file():
            continue
        sample = file_path.read_text(encoding="utf-8")
        cyrillic += len(_CYRILLIC_LETTER.findall(sample))
        latin += len(_LATIN_LETTER.findall(sample))
    if cyrillic == 0 and latin == 0:
        return ""
    return "ru" if cyrillic >= latin else "en"


def world_entries():
    """Список миров песочницы с языком: сначала русские, затем английские."""
    return world_entries_in(BASE_DIR)


def world_entries_in(root):
    """Миры в одной папке режима. Каталог приключения в корне песочницы пропускается."""
    root = Path(root)
    if not root.is_dir():
        return []
    skip_container = root.resolve() == Path(BASE_DIR).resolve()
    items = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if skip_container and entry.name == ADVENTURE_DIR:
            continue
        items.append({"name": entry.name, "language": read_world_language(entry)})
    items.sort(key=lambda item: ({"ru": 0, "en": 1}.get(item["language"], 2), item["name"].casefold()))
    return items


def load_world_config(world_name, root=None):
    """Читает файлы мира и историю.

    Возвращает (files_content, history, restored_from_backup). При повреждении
    истории без возможности восстановления бросает CorruptedDataError — вызывающий
    код обязан сообщить игроку, а не затихотно начать новую кампанию.
    root — папка режима. Без неё мир ищется среди песочницы, как раньше.
    """
    world_path = Path(root or BASE_DIR) / str(world_name)
    files_content = {}
    for fname in WORLD_FILES:
        path = world_path / fname
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                files_content[fname] = f.read()
        else:
            files_content[fname] = ""

    history_path = world_path / "history.json"
    history, restored = read_json_with_backup(history_path, [])
    if not isinstance(history, list):
        raise CorruptedDataError(history_path, "ожидался список сообщений")
    return files_content, history, restored


def save_world_files(world_path, files_content):
    world_path = Path(world_path)
    world_path.mkdir(parents=True, exist_ok=True)
    for fname, content in files_content.items():
        atomic_write_text(world_path / fname, content)


def save_history(world_path, history):
    atomic_write_json(Path(world_path) / "history.json", history)


def flag_value(value, default=False):
    """Булево из JSON: строка «false» не должна становиться истиной."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "да"}
    return default


def clamp_reasoning_max_tokens(value, default=1024):
    """Потолок рассуждения: 64–32768. Пустое и битое значение — 1024."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(32768, max(64, number))


TASK_PRESET_ROLES = ("summary", "memory", "scene", "cards")


def normalize_task_presets(value, preset_names=()):
    """Пустое имя роли означает основную конфигурацию. Чужое имя к ней же возвращается."""
    raw = value if isinstance(value, dict) else {}
    known = {str(name) for name in preset_names if str(name).strip()}
    cleaned = {}
    for role in TASK_PRESET_ROLES:
        chosen = str(raw.get(role) or "").strip()
        if chosen not in known:
            chosen = ""
        cleaned[role] = chosen
    return cleaned


def normalize_api_presets(presets):
    if not isinstance(presets, list):
        return []
    normalized = []
    for preset in presets:
        if not isinstance(preset, dict):
            continue
        name = str(preset.get("name", "")).strip()
        if not name:
            continue
        normalized.append(
            {
                "name": name,
                "api_url": str(preset.get("api_url", "")),
                "api_key": str(preset.get("api_key", "")),
                "model": str(preset.get("model", "")),
                "reasoning": flag_value(preset.get("reasoning", False)),
                "reasoning_max_tokens": clamp_reasoning_max_tokens(preset.get("reasoning_max_tokens", 1024)),
            }
        )
    return normalized


def load_global_settings():
    defaults = {
        "api_url": DEFAULT_API_URL,
        "api_key": "",
        "model": "",
        "active_api_preset": "",
        "api_presets": [],
        "temperature": 0.7,
        "max_tokens": 300,
        "context_size": 16384,
        "summary_fill_percent": 80,
        "memory_interval": 5,
        "memory_top_k": 5,
        "stream_mode": True,
        "summary_enabled": True,
        "memory_enabled": True,
        "image_prompt_style": DEFAULT_IMAGE_STYLE,
        "image_look": DEFAULT_IMAGE_LOOK,
        **normalize_image_settings(None),
        "response_limits": dict(clamp_response_limits(None)),
        "language": "ru",
        "prompt_overrides": {"ru": {}, "en": {}},
        "lan_access": True,
        "bind_mode": "lan",
        "reasoning": False,
        "reasoning_max_tokens": 1024,
    }
    # Настройки тоже читаем с попыткой отката на .bak: потерять сохранённые
    # API-ключи из-за битого JSON неприятно, а дефолты работают и без них.
    if SETTINGS_FILE.exists():
        try:
            saved, _ = read_json_with_backup(SETTINGS_FILE, None)
            if isinstance(saved, dict):
                defaults.update(saved)
        except CorruptedDataError:
            pass
    defaults["api_presets"] = normalize_api_presets(defaults.get("api_presets", []))
    active_preset = defaults.get("active_api_preset", "")
    if active_preset and not any(p["name"] == active_preset for p in defaults["api_presets"]):
        defaults["active_api_preset"] = ""
    if defaults.get("image_prompt_style") not in IMAGE_PROMPT_STYLES:
        defaults["image_prompt_style"] = DEFAULT_IMAGE_STYLE
    if defaults.get("image_look") not in IMAGE_LOOKS:
        defaults["image_look"] = DEFAULT_IMAGE_LOOK
    defaults.update(normalize_image_settings(defaults))
    defaults["response_limits"] = clamp_response_limits(defaults.get("response_limits"))
    defaults["summary_fill_percent"] = clamp_summary_fill_percent(defaults.get("summary_fill_percent", 80))
    defaults["prompt_overrides"] = normalize_prompt_overrides(defaults.get("prompt_overrides"))
    defaults["reasoning"] = flag_value(defaults.get("reasoning", False))
    defaults["reasoning_max_tokens"] = clamp_reasoning_max_tokens(defaults.get("reasoning_max_tokens", 1024))
    defaults["task_presets"] = normalize_task_presets(
        defaults.get("task_presets"),
        [item["name"] for item in defaults["api_presets"]],
    )
    return defaults


def clamp_summary_fill_percent(value):
    """Порог автосуммаризации: 50–95%, чтобы до выпадения истории оставался запас."""
    try:
        percent = int(value)
    except (TypeError, ValueError):
        percent = 80
    return min(95, max(50, percent))


SUMMARY_STATE_FILE = "summary_state.json"


def clamp_summary_cursor(covered_count, history_len):
    """Не даёт границе саммари выйти за пределы текущего списка сообщений."""
    history_len = max(0, int(history_len))
    try:
        covered = int(covered_count)
    except (TypeError, ValueError):
        covered = 0
    if covered < 0:
        covered = 0
    if covered > history_len:
        covered = history_len
    return covered


def read_summary_cursor(world_path):
    """Сколько сообщений истории уже вошло в саммари, или None, если метки нет.

    Повреждённый файл трактуется как отсутствующий: границу можно восстановить
    по summary.txt, а молчаливый ноль спрятал бы уже сжатую хронику.
    """
    path = Path(world_path) / SUMMARY_STATE_FILE
    try:
        data, _ = read_json_with_backup(path, None)
    except CorruptedDataError:
        return None
    if not isinstance(data, dict) or "covered_count" not in data:
        return None
    try:
        return int(data["covered_count"])
    except (TypeError, ValueError):
        return None


def default_summary_cursor(world_path, history_len):
    """Миграция мира, в котором ещё нет summary_state.json.

    Непустое саммари значит, что прошлая схема уже сжимала хронику, и шкала
    стартует с нуля. Пустое — вся история ещё не покрыта.
    """
    summary_path = Path(world_path) / "summary.txt"
    summary = ""
    if summary_path.exists():
        try:
            summary = summary_path.read_text(encoding="utf-8")
        except OSError:
            summary = ""
    if summary.strip():
        return clamp_summary_cursor(history_len, history_len)
    return 0


REASONING_FILE = "reasoning.json"


def normalize_reasoning_notes(raw):
    """Индекс сообщения -> текст мысли. В промпт этот словарь не попадает."""
    if not isinstance(raw, dict):
        return {}
    notes = {}
    for key, value in raw.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if index < 0:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                notes[index] = {"text": text, "hidden": False}
            continue
        if not isinstance(value, dict):
            continue
        text = str(value.get("text") or "").strip()
        hidden = flag_value(value.get("hidden", False)) and not text
        if text or hidden:
            notes[index] = {"text": text, "hidden": hidden}
    return notes


def load_reasoning_notes(world_path):
    path = Path(world_path) / REASONING_FILE
    if not path.exists() and not backup_path(path).exists():
        return {}
    data, _restored = read_json_with_backup(path, {})
    return normalize_reasoning_notes(data)


def save_reasoning_notes(world_path, notes):
    payload = {}
    for index, note in sorted(normalize_reasoning_notes({str(key): value for key, value in (notes or {}).items()}).items()):
        payload[str(index)] = note
    atomic_write_json(Path(world_path) / REASONING_FILE, payload)


def shift_reasoning_notes(notes, delta, at=0):
    """Сдвигает индексы, если в начало истории вставили или убрали вступление."""
    if not delta:
        return dict(notes or {})
    shifted = {}
    for index, note in (notes or {}).items():
        moved = index + delta if index >= at else index
        if moved >= 0:
            shifted[moved] = note
    return shifted


def save_summary_cursor(world_path, covered_count):
    atomic_write_json(
        Path(world_path) / SUMMARY_STATE_FILE,
        {"covered_count": max(0, int(covered_count))},
    )


def save_global_settings(settings):
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(SETTINGS_FILE, settings)
