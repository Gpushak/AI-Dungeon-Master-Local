import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from .i18n import default_templates

DEFAULT_API_URL = "http://localhost:1234/v1/chat/completions"

# Форматы промптов для генерации изображений. По умолчанию — Stable Diffusion,
# так как это самая распространённая локальная модель.
IMAGE_PROMPT_STYLES = ("sd", "midjourney", "flux", "generic")
DEFAULT_IMAGE_STYLE = "sd"

# Визуальный стиль дописывается в готовый промпт. none — ничего не добавлять.
IMAGE_LOOKS = ("none", "anime", "realism", "painting", "cinematic")
DEFAULT_IMAGE_LOOK = "none"
IMAGE_LOOK_SUFFIX = {
    "anime": "anime style, cel shading, clean lineart, expressive eyes, vibrant colors",
    "realism": "photorealistic, realistic skin, natural lighting, lifelike proportions, detailed materials",
    "painting": "oil painting, visible brushstrokes, painterly light, fine art",
    "cinematic": "cinematic still, dramatic lighting, shallow depth of field, film color grade",
}

# Сколько токенов можно отдать на ответ вспомогательного промпта.
DEFAULT_RESPONSE_LIMITS = {
    "prompt.memory_index": 350,
    "prompt.summary": 1000,
    "prompt.scene_image": 700,
    "prompt.card_desc_gen": 400,
}
RESPONSE_LIMIT_MAX = 16384

def clamp_response_limits(raw):
    """Полная таблица лимитов: неизвестные и пустые значения остаются встроенными."""
    result = dict(DEFAULT_RESPONSE_LIMITS)
    if not isinstance(raw, dict):
        return result
    for key in DEFAULT_RESPONSE_LIMITS:
        if key not in raw:
            continue
        try:
            value = int(raw[key])
        except (TypeError, ValueError):
            continue
        result[key] = min(RESPONSE_LIMIT_MAX, max(1, value))
    return result


def response_token_limit(limits, key) -> int:
    """Лимит ответа для одного промпта. Неизвестный ключ остаётся на своём встроенном значении."""
    return clamp_response_limits(limits).get(key, DEFAULT_RESPONSE_LIMITS.get(key, 300))


# Куда отправлять уже готовый промпт сцены. off — только текст, без генератора.
IMAGE_BACKENDS = ("off", "comfy", "a1111")
DEFAULT_IMAGE_BACKEND = "off"
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_A1111_URL = "http://127.0.0.1:7860"
DEFAULT_COMFY_WORKFLOW = "scene_api.json"
# None — папка workflows рядом с worlds. Тесты подменяют каталог.
WORKFLOWS_DIR = None
_WORKFLOW_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.json$")
DEFAULT_IMAGE_WIDTH = 1024
DEFAULT_IMAGE_HEIGHT = 1024
DEFAULT_IMAGE_STEPS = 28


def normalize_http_url(value, default):
    """Оставляет http(s)-адрес без хвостового слэша. Пустое и чужое — запасной адрес."""
    text = str(value or "").strip()
    if not text:
        return default
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return default
    return text.rstrip("/")


def normalize_workflow_name(value):
    """Только имя JSON в папке workflows. Старый путь workflows/scene_api.json сжимается до имени."""
    text = str(value or "").strip().replace("\\", "/")
    name = text.rsplit("/", 1)[-1] if text else ""
    if not _WORKFLOW_NAME.fullmatch(name):
        return DEFAULT_COMFY_WORKFLOW
    return name


def workflows_dir():
    """Папка workflow рядом с worlds: в исходниках — корень проекта, у exe — папка программы."""
    if WORKFLOWS_DIR:
        return Path(WORKFLOWS_DIR)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "workflows"
    return PROJECT_ROOT / "workflows"


def ensure_workflows_dir():
    folder = workflows_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def list_workflow_files():
    folder = ensure_workflows_dir()
    names = []
    for path in folder.iterdir():
        if path.is_file() and _WORKFLOW_NAME.fullmatch(path.name):
            names.append(path.name)
    return sorted(names)


def clamp_image_side(value, default):
    """Сторона кадра для Automatic1111: 64–4096 и кратна 8."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    number = min(4096, max(64, number))
    snapped = number - (number % 8)
    return snapped if snapped >= 64 else 64


def clamp_image_steps(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = DEFAULT_IMAGE_STEPS
    return min(150, max(1, number))


def normalize_image_settings(raw):
    """Полный набор полей генератора. Неизвестное значение бэкенда выключает отправку."""
    source = raw if isinstance(raw, dict) else {}
    backend = source.get("image_backend", DEFAULT_IMAGE_BACKEND)
    if backend not in IMAGE_BACKENDS:
        backend = DEFAULT_IMAGE_BACKEND
    return {
        "image_backend": backend,
        "comfy_url": normalize_http_url(source.get("comfy_url"), DEFAULT_COMFY_URL),
        "a1111_url": normalize_http_url(source.get("a1111_url"), DEFAULT_A1111_URL),
        "comfy_workflow": normalize_workflow_name(source.get("comfy_workflow")),
        "image_width": clamp_image_side(source.get("image_width"), DEFAULT_IMAGE_WIDTH),
        "image_height": clamp_image_side(source.get("image_height"), DEFAULT_IMAGE_HEIGHT),
        "image_steps": clamp_image_steps(source.get("image_steps")),
        "image_auto": bool(source.get("image_auto", False)),
        "image_send_negative": bool(source.get("image_send_negative", True)),
    }


def resolve_workflow_path(raw):
    """Файл только внутри папки workflows. Каталоги из настройки отбрасываются."""
    folder = ensure_workflows_dir().resolve()
    path = (folder / normalize_workflow_name(raw)).resolve()
    if path.parent != folder:
        return folder / DEFAULT_COMFY_WORKFLOW
    return path


def apply_image_look(prompt, look):
    """Дописывает фразу стиля в промпт. Параметры Midjourney остаются в конце."""
    suffix = IMAGE_LOOK_SUFFIX.get(look, "")
    text = (prompt or "").strip()
    if not suffix or not text or suffix.lower() in text.lower():
        return text
    match = re.search(r"\s--[A-Za-z]", text)
    if match:
        head = text[: match.start()].rstrip(" ,.")
        return f"{head}, {suffix}{text[match.start() :]}"
    return text.rstrip(" ,.") + ", " + suffix


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _worlds_dir():
    # У собранного exe миры лежат рядом с программой, чтобы папку можно было отдать zip-архивом.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "worlds"
    return PROJECT_ROOT / "worlds"


BASE_DIR = _worlds_dir()

SETTINGS_FILE = BASE_DIR / "settings.json"

WORLD_FILES = {
    "introduction.txt": "introduction.txt",
    "ai_instructions.txt": "ai_instructions.txt",
    "plot_basics.txt": "plot_basics.txt",
    "author_notes.txt": "author_notes.txt",
    "summary.txt": "summary.txt",
}

INTRODUCTION_FILE = "introduction.txt"

DEFAULT_TEMPLATES = default_templates("ru")
STORY_CARDS_KEY = "__story_cards__"

COLORS = {
    "accent": "#e6b450",
    "player_color": "#8bc34a",
    "dm_color": "#DBBA5F",
    "system_color": "#61afef",
    "button_hover": "#d4a340",
    "danger": "#d9534f",
    "danger_hover": "#c9302c",
    "listbox_bg": "#2b2b2b",
    "listbox_sel": "#3a3a3a",
}

WINDOW_SIZE = "900x1200"
