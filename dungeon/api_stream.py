import codecs
import json
import time
from threading import Event

import requests

from .text_utils import extract_message_text, strip_reasoning_blocks

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
    choice = _first_choice(data)
    delta = choice.get("delta")
    if isinstance(delta, dict):
        return _raw_content(delta.get("content"))
    # Некоторые серверы присылают в дельте сразу объект message
    message = choice.get("message")
    if isinstance(message, dict):
        return _raw_content(message.get("content"))
    return _raw_content(message)


def _iter_response_deltas(response, usage_box=None):
    """Отдаёт текстовые дельты из ответа OpenAI-совместимого API.

    Понимает и поток SSE, и обычный JSON: если сервер проигнорировал
    stream, тело разбирается как единый объект и отдаётся одной дельтой.
    Благодаря общему чтению любая генерация (ответ Мастера, суммаризация,
    память, описание карточки) принимает одинаковый прерываемый цикл.
    usage_box, если передан, заполняется последним объектом usage.
    """
    decoder = codecs.getincrementaldecoder("utf-8")("ignore")
    buffer = ""
    body_lines = []
    saw_sse = False

    def parse_data_line(line):
        try:
            data = json.loads(line[5:].strip())
        except ValueError:
            return ""
        _remember_usage(data, usage_box)
        return _delta_content(data)

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
            content = parse_data_line(line)
            if content:
                yield content

    # Последняя строка часто приходит без перевода строки
    tail = buffer.strip()
    if not tail:
        return
    if tail.startswith("data:"):
        if tail[5:].strip() == "[DONE]":
            return
        content = parse_data_line(tail)
        if content:
            yield content
    elif not saw_sse:
        body_lines.append(tail)

    if not saw_sse:
        try:
            data = json.loads("\n".join(body_lines))
        except ValueError:
            return
        _remember_usage(data, usage_box)
        content = extract_message_text(_first_choice(data).get("message"))
        if content:
            yield content


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

    def _api_payload(self, **fields):
        payload = dict(fields)
        if self.model:
            payload["model"] = self.model
        # Disable chain-of-thought across common OpenAI-compatible providers.
        payload["include_reasoning"] = False
        payload["reasoning"] = {"effort": "none", "exclude": True, "enabled": False}
        payload["reasoning_effort"] = "none"
        payload["enable_thinking"] = False
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        # DeepSeek-specific parameters
        payload["thinking"] = {"enabled": False}
        payload["no_thinking"] = True
        if fields.get("stream"):
            # Без этого поток не содержит usage, и «Ответ» приходится оценивать локально.
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _api_post(self, payload, **request_kwargs):
        response = requests.post(self.api_url, json=payload, headers=self._api_headers(), **request_kwargs)
        if response.status_code == 400:
            stripped = {
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "include_reasoning",
                    "reasoning",
                    "reasoning_effort",
                    "enable_thinking",
                    "chat_template_kwargs",
                    "thinking",
                    "no_thinking",
                    "stream_options",
                }
            }
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

    def _read_response(self, response, cancel_key, on_delta=None):
        """Читает ответ API целиком, прерываясь по запросу остановки.

        on_delta вызывается для каждой дельты и возвращает текст, который
        нужно оставить в ответе (None — ничего не добавлять).
        Возвращает пару (текст, признак прерывания).
        """
        parts = []
        cancelled = False
        usage = {}
        self._last_api_usage = None
        try:
            for delta in _iter_response_deltas(response, usage):
                if self.is_cancelled(cancel_key):
                    cancelled = True
                    break
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
