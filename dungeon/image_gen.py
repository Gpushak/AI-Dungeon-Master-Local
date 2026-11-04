"""Отправка промпта сцены в локальный ComfyUI или Automatic1111/Forge."""

from __future__ import annotations

import base64
import copy
import json
import random
import time
import uuid
from pathlib import Path
from threading import Event, Thread

import requests

from .config import resolve_workflow_path

# Узлы, в которых лежит seed. Меняется на каждый запуск, остальной граф — нет.
SEED_CLASSES = {
    "KSampler",
    "KSamplerAdvanced",
    "SamplerCustom",
    "SamplerCustomAdvanced",
    "RandomNoise",
}
# Поля текста у стандартных кодировщиков CLIP. Связи (списки) не перезаписываются.
TEXT_FIELDS = ("text", "text_g", "text_l", "clip_l", "clip_g", "t5xxl")
# У этих узлов единственный вход conditioning — это положительный промпт.
GUIDER_CLASSES = {"BasicGuider", "CFGGuider", "DualCFGGuider", "PerpNegGuider"}


class ImageGenError(Exception):
    """Ошибка генерации с коротким кодом для текста интерфейса."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = str(detail or "")
        super().__init__(self.detail or code)


def image_suffix(data: bytes) -> str:
    """Расширение по сигнатуре. Чужие байты не сохраняем как картинку."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    raise ImageGenError("empty")


def load_workflow(path):
    """Читает API-граф ComfyUI. Обычный Save (массив nodes) не подходит."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ImageGenError("missing_workflow", str(file_path))
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImageGenError("bad_workflow", str(exc)) from exc
    return coerce_workflow(data)


def coerce_workflow(data):
    if isinstance(data, dict) and isinstance(data.get("nodes"), list):
        raise ImageGenError("ui_workflow")
    if isinstance(data, dict) and isinstance(data.get("prompt"), dict) and not _is_api_graph(data):
        data = data["prompt"]
        if isinstance(data, dict) and isinstance(data.get("nodes"), list):
            raise ImageGenError("ui_workflow")
    if not _is_api_graph(data):
        raise ImageGenError("bad_workflow")
    return data


def apply_prompts(workflow, positive, negative, seed=None):
    """Подставляет тексты в узлы положительного и отрицательного промпта.

    Граф не размечается плейсхолдерами: текст находится по связям семплера
    или гида. Возвращает копию графа и отчёт, какие поля изменены.
    """
    graph = copy.deepcopy(workflow)
    if seed is None:
        seed = random.randrange(0, 2**31 - 1)
    else:
        seed = int(seed)
    sources = []
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if _link_target(inputs.get("positive")) or _link_target(inputs.get("negative")):
            sources.append(str(node_id))
        elif node.get("class_type") in GUIDER_CLASSES and _link_target(inputs.get("conditioning")):
            sources.append(str(node_id))
    positive_ids = []
    negative_ids = []
    seen_pos = set()
    seen_neg = set()
    for node_id in sources:
        inputs = graph[node_id].get("inputs") or {}
        pos = _link_target(inputs.get("positive"))
        neg = _link_target(inputs.get("negative"))
        if pos is None and graph[node_id].get("class_type") in GUIDER_CLASSES:
            pos = _link_target(inputs.get("conditioning"))
        if pos:
            positive_ids.extend(_text_nodes(graph, pos, seen_pos))
        if neg:
            negative_ids.extend(_text_nodes(graph, neg, seen_neg))
    if not positive_ids:
        raise ImageGenError("no_prompt_nodes")
    written = []
    pos_set = set(positive_ids)
    for node_id in positive_ids:
        written.extend(_write_text(graph[node_id], node_id, positive))
    for node_id in negative_ids:
        if node_id in pos_set:
            continue
        written.extend(_write_text(graph[node_id], node_id, negative or ""))
    seeds = []
    for node_id, node in graph.items():
        if not isinstance(node, dict) or node.get("class_type") not in SEED_CLASSES:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for field in ("seed", "noise_seed"):
            value = inputs.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            inputs[field] = seed
            seeds.append((str(node_id), field))
    report = {
        "positive_nodes": positive_ids,
        "negative_nodes": [node_id for node_id in negative_ids if node_id not in pos_set],
        "written": written,
        "seeds": seeds,
        "seed": seed,
    }
    return graph, report


def a1111_payload(prompt, negative, width, height, steps):
    return {
        "prompt": prompt,
        "negative_prompt": negative or "",
        "width": int(width),
        "height": int(height),
        "steps": int(steps),
        "seed": -1,
    }


def test_connection(backend, url, timeout=5):
    """Короткий запрос без постановки картинки в очередь."""
    if backend == "comfy":
        path = "/system_stats"
    elif backend == "a1111":
        path = "/sdapi/v1/options"
    else:
        raise ImageGenError("backend_off")
    base = str(url or "").rstrip("/")
    if not base:
        raise ImageGenError("offline")
    try:
        response = requests.get(base + path, timeout=timeout)
    except requests.ConnectionError as exc:
        raise ImageGenError("offline") from exc
    except requests.Timeout as exc:
        raise ImageGenError("timeout") from exc
    if response.status_code >= 400:
        raise ImageGenError("rejected", (response.text or "")[:400])
    return True


def interrupt(backend, url):
    """Просит сервер бросить текущую картинку. Ошибка сети здесь не важна."""
    base = str(url or "").rstrip("/")
    if not base or backend not in ("comfy", "a1111"):
        return
    path = "/interrupt" if backend == "comfy" else "/sdapi/v1/interrupt"
    try:
        requests.post(base + path, timeout=5)
    except requests.RequestException:
        return


def generate(spec, prompt, negative, cancel_event):
    """Возвращает байты картинки или None, если генерацию остановили."""
    backend = spec.get("image_backend")
    if backend == "comfy":
        return generate_comfy(
            spec.get("comfy_url") or "",
            resolve_workflow_path(spec.get("comfy_workflow")),
            prompt,
            negative,
            cancel_event,
        )
    if backend == "a1111":
        return generate_a1111(
            spec.get("a1111_url") or "",
            prompt,
            negative,
            spec.get("image_width"),
            spec.get("image_height"),
            spec.get("image_steps"),
            cancel_event,
        )
    raise ImageGenError("backend_off")


def generate_comfy(url, workflow_path, prompt, negative, cancel_event):
    if _cancelled(cancel_event):
        return None
    graph, _report = apply_prompts(load_workflow(workflow_path), prompt, negative or "")
    base = str(url or "").rstrip("/")
    try:
        queued = requests.post(
            base + "/prompt",
            json={"prompt": graph, "client_id": uuid.uuid4().hex},
            timeout=30,
        )
    except requests.ConnectionError as exc:
        raise ImageGenError("offline") from exc
    except requests.Timeout as exc:
        raise ImageGenError("timeout") from exc
    if queued.status_code >= 400:
        raise ImageGenError("rejected", _response_message(queued))
    try:
        body = queued.json()
    except ValueError as exc:
        raise ImageGenError("rejected", (queued.text or "")[:400]) from exc
    prompt_id = body.get("prompt_id") if isinstance(body, dict) else None
    if not prompt_id:
        raise ImageGenError("rejected", _queue_error(body))
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if _cancelled(cancel_event):
            interrupt("comfy", base)
            return None
        try:
            history = requests.get(f"{base}/history/{prompt_id}", timeout=15)
        except requests.ConnectionError as exc:
            raise ImageGenError("offline") from exc
        except requests.Timeout:
            continue
        if history.status_code >= 400:
            raise ImageGenError("rejected", (history.text or "")[:400])
        try:
            payload = history.json()
        except ValueError:
            payload = None
        item = payload.get(prompt_id) if isinstance(payload, dict) else None
        if isinstance(item, dict):
            images = _history_images(item)
            if images:
                return _download_comfy_image(base, images[0])
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            if status.get("status_str") == "error":
                raise ImageGenError("rejected", _comfy_error_text(item))
            if status.get("completed"):
                raise ImageGenError("empty")
        if cancel_event is None:
            time.sleep(0.4)
        elif cancel_event.wait(0.4):
            interrupt("comfy", base)
            return None
    raise ImageGenError("timeout")


def generate_a1111(url, prompt, negative, width, height, steps, cancel_event):
    if _cancelled(cancel_event):
        return None
    base = str(url or "").rstrip("/")
    payload = a1111_payload(prompt, negative, width, height, steps)
    box = {}
    done = Event()

    def run():
        try:
            response = requests.post(base + "/sdapi/v1/txt2img", json=payload, timeout=600)
            if response.status_code >= 400:
                box["error"] = ImageGenError("rejected", (response.text or "")[:400])
            else:
                try:
                    body = response.json()
                except ValueError as exc:
                    box["error"] = ImageGenError("rejected", str(exc)[:400])
                    return
                images = body.get("images") if isinstance(body, dict) else None
                if not images:
                    box["error"] = ImageGenError("empty")
                else:
                    try:
                        box["data"] = base64.b64decode(images[0])
                    except (ValueError, TypeError):
                        box["error"] = ImageGenError("empty")
        except requests.ConnectionError:
            box["error"] = ImageGenError("offline")
        except requests.Timeout:
            box["error"] = ImageGenError("timeout")
        except requests.RequestException as exc:
            box["error"] = ImageGenError("rejected", str(exc)[:400])
        finally:
            done.set()

    Thread(target=run, daemon=True).start()
    while not done.wait(0.4):
        if _cancelled(cancel_event):
            interrupt("a1111", base)
            return None
    if box.get("data"):
        return box["data"]
    if _cancelled(cancel_event):
        return None
    raise box.get("error") or ImageGenError("empty")


def _is_api_graph(data):
    if not isinstance(data, dict) or not data:
        return False
    nodes = [value for value in data.values() if isinstance(value, dict)]
    if not nodes or len(nodes) != len(data):
        return False
    return all(isinstance(node.get("class_type"), str) and node.get("class_type") for node in nodes)


def _link_target(value):
    if isinstance(value, (list, tuple)) and value and not isinstance(value[0], (list, tuple, dict)):
        return str(value[0])
    return None


def _text_nodes(graph, node_id, seen):
    node_id = str(node_id)
    if node_id in seen:
        return []
    seen.add(node_id)
    node = graph.get(node_id)
    if not isinstance(node, dict):
        return []
    found = []
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    if any(isinstance(inputs.get(field), str) for field in TEXT_FIELDS):
        found.append(node_id)
    for value in inputs.values():
        child = _link_target(value)
        if child:
            found.extend(_text_nodes(graph, child, seen))
    return found


def _write_text(node, node_id, text):
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    written = []
    for field in TEXT_FIELDS:
        if isinstance(inputs.get(field), str):
            inputs[field] = text
            written.append((str(node_id), field))
    return written


def _history_images(item):
    outputs = item.get("outputs") if isinstance(item.get("outputs"), dict) else {}
    images = []
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for image in node_out.get("images") or []:
            if isinstance(image, dict) and image.get("filename"):
                images.append(image)
    preferred = [image for image in images if image.get("type") != "temp"]
    return preferred or images


def _download_comfy_image(url, info):
    try:
        response = requests.get(
            url + "/view",
            params={
                "filename": info.get("filename") or "",
                "subfolder": info.get("subfolder") or "",
                "type": info.get("type") or "output",
            },
            timeout=60,
        )
    except requests.ConnectionError as exc:
        raise ImageGenError("offline") from exc
    except requests.Timeout as exc:
        raise ImageGenError("timeout") from exc
    if response.status_code >= 400 or not response.content:
        raise ImageGenError("empty")
    return response.content


def _comfy_error_text(item):
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    parts = []
    for message in status.get("messages") or []:
        if isinstance(message, (list, tuple)) and len(message) >= 2 and isinstance(message[1], dict):
            text = message[1].get("exception_message") or message[1].get("message")
            if text:
                parts.append(str(text))
    if not parts and status.get("status_str"):
        parts.append(str(status.get("status_str")))
    return " ".join(parts)[:400]


def _queue_error(body):
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err)[:400]
    if err:
        return str(err)[:400]
    try:
        return json.dumps(body, ensure_ascii=False)[:400]
    except TypeError:
        return ""


def _response_message(response):
    try:
        return _queue_error(response.json()) or (response.text or "")[:400]
    except ValueError:
        return (response.text or "")[:400]


def _cancelled(cancel_event):
    return cancel_event is not None and cancel_event.is_set()
