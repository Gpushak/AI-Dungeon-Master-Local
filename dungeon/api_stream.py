import codecs
import json
import time
from contextlib import contextmanager
from threading import Event

import requests

from .storage import clamp_reasoning_max_tokens
from .text_utils import strip_reasoning_blocks

# Операции, которые можно прервать кнопкой остановки
ACTION = "action"
SUMMARY = "summary"
MEMORY = "memory"
CARDS = "cards"
SCENE = "scene"
IMAGE = "image"

# Размер порции при чтении потока. Меньше — плавнее отображение, но больше
# вызовов чтения; None означает «копить всё до конца» (поток перестаёт быть
# потоком). 64 байта — компромисс, дающий отзывчивый вывод без накладных.
STREAM_CHUNK_SIZE = 64

# Сколько последних ходов мастера попадает в промпт изображения сцены
SCENE_TURNS = 5


def _first_choice(data):
    """Достаёт первый элемент choices из разобранного ответа API."""
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return {}
    choice = choices[0]
    return choice if isinstance(choice, dict) else {}


def _raw_content(value):
    """Текст из поля content без обрезки пробелов: приходит строкой или
    списком частей (мультимодальный формат некоторых провайдеров)."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts = []
    for part in value:
        if isinstance(part, dict):
            if part.get("type") in ("text", "output_text"):
                parts.append(part.get("text") or "")
        elif isinstance(part, str):
            parts.append(part)
    return "".join(parts)


def _remember_usage(data, usage_box):
    """Запоминает usage из чанка, если сервер прислал счётчик модели.

    В потоке usage обычно лежит в последнем чанке и может прийти без текста.
    """
    if usage_box is None or not isinstance(data, dict):
        return
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return
    if "completion_tokens" not in usage and "prompt_tokens" not in usage:
        return
    usage_box.clear()
    usage_box.update(usage)


def _delta_content(data):
    """Текст одной дельты потока (choices[0].delta.content)."""
    for kind, text in _choice_parts(data):
        if kind == "content" and text:
            return text
    return ""


def _reasoning_text(value):
    """Текст рассуждения: строка, кусок сообщения или список частей."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "reasoning"):
            found = value.get(key)
            if isinstance(found, str) and found:
                return found
        return ""
    if isinstance(value, list):
        return _raw_content(value)
    return ""


def _message_parts(source):
    """Пара (канал, текст). Канал reasoning не смешивается с рассказом."""
    if not isinstance(source, dict):
        text = _raw_content(source)
        return [("content", text)] if text else []
    parts = []
    reasoning = _reasoning_text(source.get("reasoning_content"))
    if not reasoning:
        reasoning = _reasoning_text(source.get("reasoning"))
    if reasoning:
        parts.append(("reasoning", reasoning))
    content = _raw_content(source.get("content"))
    if content:
        parts.append(("content", content))
    return parts


def _choice_parts(data):
    choice = _first_choice(data)
    delta = choice.get("delta")
    if isinstance(delta, dict):
        parts = _message_parts(delta)
        if parts:
            return parts
    message = choice.get("message")
    if isinstance(message, dict):
        return _message_parts(message)
    return []


def reasoning_effort_name(limit):
    """У OpenAI нет числового потолка: до 512 low, до 2048 medium, дальше high."""
    if limit <= 512:
        return "low"
    if limit <= 2048:
        return "medium"
    return "high"


def reasoning_token_count(usage):
    """Сколько токенов мысли насчитала модель, даже если текст не прислала."""
    if not isinstance(usage, dict):
        return 0
    sources = (usage, usage.get("completion_tokens_details"), usage.get("output_tokens_details"))
    for source in sources:
        if not isinstance(source, dict):
            continue
        value = source.get("reasoning_tokens")
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return 0


_REASONING_STRIP_KEYS = {
    "include_reasoning",
    "reasoning",
    "reasoning_effort",
    "enable_thinking",
    "chat_template_kwargs",
    "thinking",
    "no_thinking",
    "max_completion_tokens",
    "stream_options",
}


def _iter_response_deltas(response, usage_box=None):
    """Отдаёт только текст ответа. Рассуждение остаётся в отдельном канале."""
    for kind, text in _iter_response_parts(response, usage_box):
        if kind == "content" and text:
            yield text


def _iter_response_parts(response, usage_box=None):
    """Отдаёт пары (канал, текст) из потока SSE или обычного JSON.

    Канал content — рассказ. Канал reasoning — отдельное поле
    reasoning_content или reasoning. Теги внутри content здесь не режутся:
    это делает фильтр хода, чтобы мысль не пропала раньше, чем её отделят.
    """
    decoder = codecs.getincrementaldecoder("utf-8")("ignore")
    buffer = ""
    body_lines = []
    saw_sse = False

    def parse_data_line(line):
        try:
            data = json.loads(line[5:].strip())
        except ValueError:
            return []
        _remember_usage(data, usage_box)
        return _choice_parts(data)

    # chunk_size=None заставляет urllib3 копить данные в буфер до упора: текст
    # приходил одним куском в самом конце и «потоковый» режим не работал.
    # Небольшой размер чанка отдаёт байты по мере поступления, а DeltaBatcher
    # потом собирает их в пачки, чтобы не дёргать интерфейс на каждый байт.
    for chunk in response.iter_content(chunk_size=STREAM_CHUNK_SIZE):
        if not chunk:
            continue
        buffer += decoder.decode(chunk)
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            if not line.startswith("data:"):
                body_lines.append(line)
                continue
            saw_sse = True
            if line[5:].strip() == "[DONE]":
                return
            for kind, text in parse_data_line(line):
                if text:
                    yield kind, text

    # Последняя строка часто приходит без перевода строки
    tail = buffer.strip()
    if not tail:
        return
    if tail.startswith("data:"):
        if tail[5:].strip() == "[DONE]":
            return
        for kind, text in parse_data_line(tail):
            if text:
                yield kind, text
    elif not saw_sse:
        body_lines.append(tail)

    if not saw_sse:
        try:
            data = json.loads("\n".join(body_lines))
        except ValueError:
            return
        _remember_usage(data, usage_box)
        message = _first_choice(data).get("message")
        for kind, text in _message_parts(message if isinstance(message, dict) else {}):
            if text:
                yield kind, text


class DeltaBatcher:
    """Копит дельты и отдаёт их пачками.

    Раньше на каждую дельту планировался отдельный вызов Tk, а вставка
    заканчивалась see(END), из-за чего виджет пересчитывал раскладку на
    каждом токене. Теперь текст уходит в интерфейс пачками примерно раз в
    50 мс — на ответ в 800 токенов это единицы вставок вместо восьмисот.
    """

    FLUSH_INTERVAL = 0.05

    def __init__(self, flush):
        self._flush = flush
        self._pending = []
        self._last_flush = 0.0

    def add(self, text):
        self._pending.append(text)
        now = time.monotonic()
        if now - self._last_flush >= self.FLUSH_INTERVAL:
            self.flush_now()

    def flush_now(self):
        if not self._pending:
            return
        chunk = "".join(self._pending)
        self._pending.clear()
        self._last_flush = time.monotonic()
        self._flush(chunk)

class ApiMixin:
    def _api_headers(self):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _task_preset(self, role):
        """Сохранённая конфигурация функции. Пустое значение — основная."""
        chosen = str((getattr(self, "task_presets", {}) or {}).get(role) or "").strip()
        if not chosen:
            return None
        for item in getattr(self, "api_presets", []) or []:
            if isinstance(item, dict) and item.get("name") == chosen:
                return item
        return None

    @contextmanager
    def _use_task_preset(self, role):
        """На время запроса подменяет адрес, ключ и модель. Рассуждение не включает."""
        found = self._task_preset(role)
        if not found:
            yield
            return
        saved = (self.api_url, self.api_key, self.model)
        self.api_url = str(found.get("api_url") or "")
        self.api_key = str(found.get("api_key") or "")
        self.model = str(found.get("model") or "")
        try:
            yield
        finally:
            self.api_url, self.api_key, self.model = saved

    def _api_payload(self, **fields):
        allow_reasoning = bool(fields.pop("allow_reasoning", False))
        payload = dict(fields)
        if self.model:
            payload["model"] = self.model
        if allow_reasoning:
            # Один набор полей на разные серверы: незнакомые ключи они пропускают.
            # Общий max_tokens растёт на бюджет мысли, потому что локальные
            # серверы часто считают мысль и ответ одним лимитом.
            limit = clamp_reasoning_max_tokens(getattr(self, "reasoning_max_tokens", 1024))
            effort = reasoning_effort_name(limit)
            try:
                reply_limit = int(payload.get("max_tokens") or 0)
            except (TypeError, ValueError):
                reply_limit = 0
            if reply_limit > 0:
                total = reply_limit + limit
                payload["max_tokens"] = total
                payload["max_completion_tokens"] = total
            payload["include_reasoning"] = True
            payload["reasoning"] = {
                "effort": effort,
                "max_tokens": limit,
                "exclude": False,
                "enabled": True,
            }
            payload["reasoning_effort"] = effort
            payload["enable_thinking"] = True
            payload["chat_template_kwargs"] = {"enable_thinking": True}
            payload["thinking"] = {"type": "enabled"}
        else:
            # Disable chain-of-thought across common OpenAI-compatible providers.
            payload["include_reasoning"] = False
            payload["reasoning"] = {"effort": "none", "exclude": True, "enabled": False}
            payload["reasoning_effort"] = "none"
            payload["enable_thinking"] = False
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            # DeepSeek-specific parameters
            payload["thinking"] = {"enabled": False}
            payload["no_thinking"] = True
        if payload.get("stream"):
            # Без этого поток не содержит usage, и «Ответ» приходится оценивать локально.
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _api_post(self, payload, **request_kwargs):
        response = requests.post(self.api_url, json=payload, headers=self._api_headers(), **request_kwargs)
        if response.status_code == 400:
            stripped = {key: value for key, value in payload.items() if key not in _REASONING_STRIP_KEYS}
            if stripped != payload:
                response.close()
                retry = requests.post(self.api_url, json=stripped, headers=self._api_headers(), **request_kwargs)
                if retry.ok:
                    return retry
        response.raise_for_status()
        return response

    # --- Прерывание генерации ------------------------------------------------

    def _begin_operation(self, key):
        """Регистрирует запущенную операцию с собственным флагом отмены.

        Флаг создаётся заново на каждый запуск, иначе остановка одной
        операции «залипла» бы на всех следующих.
        """
        self._cancel_events[key] = Event()
        return self._cancel_events[key]

    def _end_operation(self, key):
        self._cancel_events.pop(key, None)

    def is_cancelled(self, key):
        event = self._cancel_events.get(key)
        return event is not None and event.is_set()

    def request_stop(self, key=None):
        """Просит прервать текущие операции. Возвращает список прерванных."""
        keys = (key,) if key else tuple(self._cancel_events)
        stopped = []
        for op in keys:
            event = self._cancel_events.get(op)
            if event is not None and not event.is_set():
                event.set()
                stopped.append(op)
        return stopped

    def _read_response(self, response, cancel_key, on_delta=None, on_reasoning=None):
        """Читает ответ API целиком, прерываясь по запросу остановки.

        on_delta вызывается для каждой дельты рассказа и возвращает текст,
        который нужно оставить в ответе (None — ничего не добавлять).
        on_reasoning, если передан, получает отдельный канал мысли.
        Возвращает пару (текст, признак прерывания).
        """
        parts = []
        cancelled = False
        usage = {}
        self._last_api_usage = None
        try:
            for kind, delta in _iter_response_parts(response, usage):
                if self.is_cancelled(cancel_key):
                    cancelled = True
                    break
                if kind == "reasoning":
                    if on_reasoning is not None:
                        on_reasoning(delta)
                    continue
                if on_delta is None:
                    parts.append(delta)
                else:
                    piece = on_delta(delta)
                    if piece:
                        parts.append(piece)
        finally:
            # Закрытие соединения освобождает сокет и срывает генерацию на
            # стороне сервера, а не просто перестаёт читать поток.
            response.close()
        if usage:
            self._last_api_usage = dict(usage)
        return strip_reasoning_blocks("".join(parts)).strip(), cancelled
