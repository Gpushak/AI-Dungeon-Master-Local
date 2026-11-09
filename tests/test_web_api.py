"""Проверка веб-версии через HTTP, без окна Tk и без сети."""

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dungeon.config as config  # noqa: E402
import dungeon.storage as storage  # noqa: E402
import web.session as session_mod  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from web.server import create_app  # noqa: E402


class _Response:
    def raise_for_status(self):
        return None

    def close(self):
        return None


def _try_symlink(link: Path, target: Path, directory=False):
    """Создаёт ссылку. Без права Windows возвращает False, а не роняет набор."""
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            return False
        raise
    return True


def _use_tmp(tmp: Path):
    tmp.mkdir(parents=True, exist_ok=True)
    settings = tmp / "settings.json"
    config.BASE_DIR = tmp
    config.SETTINGS_FILE = settings
    # Папка workflow не должна лежать внутри корня миров: игра считает каждую подпапку миром.
    flows = Path(str(tmp) + "-workflows")
    if flows.exists():
        shutil.rmtree(flows)
    config.WORKFLOWS_DIR = flows
    storage.BASE_DIR = tmp
    storage.SETTINGS_FILE = settings
    session_mod.BASE_DIR = tmp


def test_file_save_and_summary_threshold(tmp_path=None):
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        client = TestClient(create_app())
        created = client.post("/api/worlds", json={"name": "Camp"})
        assert created.status_code == 200, created.text
        saved = client.put("/api/files/plot_basics.txt", json={"content": "новый сюжет"})
        assert saved.status_code == 200, saved.text
        assert "новый сюжет" in client.get("/api/files").json()["plot_basics.txt"]
        assert (tmp / "Camp" / "plot_basics.txt").read_text(encoding="utf-8") == "новый сюжет"

        history = ["Игрок: " + ("слово " * 400)]
        (tmp / "Camp" / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        opened = client.post("/api/worlds/open", json={"name": "Camp"})
        assert opened.status_code == 200, opened.text
        updated = client.put("/api/settings", json={"context_size": 200, "max_tokens": 300, "summary_fill_percent": 80})
        assert updated.status_code == 200, updated.text
        state = client.get("/api/state").json()
        assert state["fill"]["summary_fill_percent"] == 80
        assert state["fill"]["ratio"] >= 0.8
        assert state["fill"]["color"] == "danger"

        rejected = client.put(
            "/api/settings",
            json={"prompt_overrides": {"ru": {"prompt.summary": "без полей"}, "en": {}}},
        )
        assert rejected.status_code == 400
    print("OK  файл мира пишется, полоса видит порог, битый промпт не сохраняется")


def test_history_opens_on_the_tail():
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        client = TestClient(create_app())
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        history = [f"Игрок: реплика {index} " + ("слово " * 80) for index in range(30)]
        (tmp / "Camp" / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        opened = client.post("/api/worlds/open", json={"name": "Camp"})
        assert opened.status_code == 200, opened.text
        state = opened.json()
        assert state["history_total"] >= 30
        assert state["history_from"] > 0
        assert state["history"][0]["index"] == state["history_from"]
        assert state["history"][-1]["text"].startswith("реплика 29")
        assert len(state["history"]) < state["history_total"]

        earlier = client.get("/api/history", params={"before": state["history_from"]})
        assert earlier.status_code == 200, earlier.text
        page = earlier.json()
        assert page["history_from"] < state["history_from"]
        assert page["history"][-1]["index"] == state["history_from"] - 1
    print("OK  при открытии приходит хвост истории, более ранний кусок запрашивается отдельно")


def test_turn_and_stop():
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200

        def finish_read(_response, _key, on_delta=None):
            if on_delta:
                on_delta("Готово")
            return "Готово", False

        session._api_post = lambda payload, **kwargs: _Response()
        session._read_response = finish_read
        assert client.post("/api/turn", json={"text": "осмотреться"}).status_code == 200
        deadline = time.time() + 3
        text = ""
        while time.time() < deadline:
            state = client.get("/api/state").json()
            text = "\n".join(row["text"] for row in state["history"])
            if "Готово" in text and not state["status"]["busy"]:
                break
            time.sleep(0.05)
        assert "Готово" in text
        assert "осмотреться" in text

        hold = {"cancel": False}

        def blocking_read(_response, key, on_delta=None):
            while not session.is_cancelled(key):
                time.sleep(0.02)
            if on_delta:
                on_delta("обрыв")
            return "обрыв", True

        session._read_response = blocking_read
        assert client.post("/api/turn", json={"text": "ждать"}).status_code == 200
        time.sleep(0.1)
        stopped = client.post("/api/stop")
        assert stopped.status_code == 200
        assert stopped.json()["stopped"]
        deadline = time.time() + 3
        while time.time() < deadline and client.get("/api/state").json()["status"]["busy"]:
            time.sleep(0.05)
        assert client.get("/api/state").json()["status"]["busy"] is False
        hold["cancel"] = True
    print("OK  ход дописывает ответ, стоп отпускает генерацию")


def test_direction_turn():
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        seen = {}

        def finish_read(_response, _key, on_delta=None):
            if on_delta:
                on_delta("Сцена сдвинулась")
            return "Сцена сдвинулась", False

        def capture(payload, **kwargs):
            seen["user"] = payload["messages"][-1]["content"]
            return _Response()

        session._api_post = capture
        session._read_response = finish_read
        assert client.post("/api/turn", json={"direction": "герой находит ключ"}).status_code == 200
        deadline = time.time() + 3
        text = ""
        while time.time() < deadline:
            state = client.get("/api/state").json()
            text = "\n".join(row["text"] for row in state["history"])
            if "Сцена сдвинулась" in text and not state["status"]["busy"]:
                break
            time.sleep(0.05)
        assert "герой находит ключ" in text
        assert text.count("герой находит ключ") == 1
        assert "Сцена сдвинулась" in text
        assert "герой находит ключ" in seen["user"]
        assert "Автор задаёт направление" in seen["user"]
    print("OK  «Дальше?» записывает направление один раз и отдаёт его в ход")


def test_lan_setting_roundtrip():
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        client = TestClient(create_app())
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        opened = client.get("/api/settings")
        assert opened.status_code == 200
        assert opened.json()["lan_access"] is True
        saved = client.put("/api/settings", json={"lan_access": False})
        assert saved.status_code == 200, saved.text
        assert saved.json()["lan_access"] is False
        again = client.get("/api/settings")
        assert again.json()["lan_access"] is False
        info = client.get("/api/network")
        assert info.status_code == 200, info.text
        body = info.json()
        assert body["local_url"] == "http://127.0.0.1:8765"
        assert body["listening"] == "127.0.0.1"
        assert isinstance(body["lan_urls"], list)
        assert isinstance(body["tailscale_urls"], list)
        assert again.json()["bind_mode"] == "local"
        hint = client.get("/api/strings").json()["dialog.lan_hint"]
        assert "Wi-Fi" in hint
    print("OK  доступ из локальной сети сохраняется и показывает адрес")


def test_world_export_and_import():
    import io
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        client = TestClient(create_app())
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        assert client.put("/api/files/plot_basics.txt", json={"content": "сюжет для переноса"}).status_code == 200
        (tmp / "Camp" / "settings.json").write_text('{"api_key":"nope"}', encoding="utf-8")
        (tmp / "Camp" / "notes.txt.bak").write_text("резерв", encoding="utf-8")

        exported = client.get("/api/worlds/Camp/export")
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            names = set(archive.namelist())
            assert "plot_basics.txt" in names
            assert "history.json" in names
            assert "notes.txt.bak" in names
            assert "settings.json" not in names
            assert archive.read("plot_basics.txt").decode("utf-8") == "сюжет для переноса"

        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as archive:
            archive.writestr("Camp/plot_basics.txt", "сюжет из папки")
            archive.writestr("Camp/history.json", json.dumps(["Игрок: привет"], ensure_ascii=False))
            archive.writestr("Camp/__MACOSX/skip.txt", "мусор")
            archive.writestr("Camp/settings.json", '{"api_key":"nope"}')
        brought = client.post(
            "/api/worlds/import?name=Camp%202",
            content=nested.getvalue(),
            headers={"Content-Type": "application/zip"},
        )
        assert brought.status_code == 200, brought.text
        assert brought.json()["name"] == "Camp 2"
        assert client.get("/api/state").json()["world"] == "Camp 2"
        assert (tmp / "Camp 2" / "plot_basics.txt").read_text(encoding="utf-8") == "сюжет из папки"
        assert not (tmp / "Camp 2" / "settings.json").exists()

        again = client.post(
            "/api/worlds/import?name=Camp%202",
            content=exported.content,
            headers={"Content-Type": "application/zip"},
        )
        assert again.status_code == 409

        slipped = io.BytesIO()
        with zipfile.ZipFile(slipped, "w") as archive:
            archive.writestr("../settings.json", "secret")
            archive.writestr("history.json", "[]")
        rejected = client.post(
            "/api/worlds/import?name=Escape",
            content=slipped.getvalue(),
            headers={"Content-Type": "application/zip"},
        )
        assert rejected.status_code == 400
        assert not (tmp / "Escape").exists()
        if (tmp / "settings.json").exists():
            assert "secret" not in (tmp / "settings.json").read_text(encoding="utf-8")
    print("OK  мир выгружается в zip и поднимается из архива без настроек и чужих путей")


def test_player_line_is_visible_before_the_reply():
    import tempfile
    import threading

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        release = threading.Event()

        def blocking_read(_response, key, on_delta=None):
            while not release.is_set() and not session.is_cancelled(key):
                time.sleep(0.02)
            return "Готово", False

        session._api_post = lambda payload, **kwargs: _Response()
        session._read_response = blocking_read
        assert client.post("/api/turn", json={"text": "осмотреться"}).status_code == 200
        state = client.get("/api/state").json()
        player = [row for row in state["history"] if row["kind"] == "player"]
        assert player and player[-1]["text"] == "осмотреться"
        assert all(row["kind"] != "dm" for row in state["history"])
        assert state["status"]["busy"] is True
        release.set()
        deadline = time.time() + 3
        while time.time() < deadline and client.get("/api/state").json()["status"]["busy"]:
            time.sleep(0.05)
        done = client.get("/api/state").json()
        assert done["status"]["busy"] is False
        assert sum(1 for row in done["history"] if row["text"] == "осмотреться") == 1
        assert any(row["kind"] == "dm" and "Готово" in row["text"] for row in done["history"])
    print("OK  реплика игрока есть в ленте до окончания ответа и не дублируется")


def test_reply_tokens_follow_model_usage():
    import tempfile

    from dungeon.api_stream import _iter_response_deltas
    from dungeon.tokens import count_tokens, reply_tokens

    narration = "Темный коридор тянется дальше. " * 40
    assert count_tokens(narration) > 40
    assert reply_tokens({"completion_tokens": 19}, narration) == 19
    assert reply_tokens({"completion_tokens": True}, narration) == count_tokens(narration)
    assert reply_tokens(None, narration) == count_tokens(narration)

    class _Chunks:
        def __init__(self, chunks):
            self._chunks = chunks

        def iter_content(self, chunk_size=None):
            yield from self._chunks

    usage = {}
    pieces = "".join(
        _iter_response_deltas(
            _Chunks(
                [
                    'data: {"choices":[{"delta":{"content":"Раз"}}]}\n'.encode(),
                    'data: {"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":19,"total_tokens":27}}\n'.encode(),
                    b"data: [DONE]\n",
                ]
            ),
            usage,
        )
    )
    assert pieces == "Раз"
    assert usage["completion_tokens"] == 19

    plain = {}
    body = '{"choices":[{"message":{"content":"Два"}}],"usage":{"completion_tokens":2}}'.encode()
    assert "".join(_iter_response_deltas(_Chunks([body]), plain)) == "Два"
    assert plain["completion_tokens"] == 2

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        assert client.put(
            "/api/settings",
            json={"summary_enabled": False, "memory_enabled": False},
        ).status_code == 200
        seen = {}

        def finish_read(_response, _key, on_delta=None):
            session._last_api_usage = {"prompt_tokens": 8, "completion_tokens": 19}
            if on_delta:
                on_delta(narration)
            return narration, False

        def capture(payload, **kwargs):
            seen["stream_options"] = payload.get("stream_options")
            return _Response()

        session._api_post = capture
        session._read_response = finish_read
        assert client.post("/api/turn", json={"text": "осмотреться"}).status_code == 200
        deadline = time.time() + 3
        notice = ""
        while time.time() < deadline:
            state = client.get("/api/state").json()
            notice = (state["notices"] or [""])[-1]
            if "Ответ: 19" in notice and not state["status"]["busy"]:
                break
            time.sleep(0.05)
        assert "Ответ: 19" in notice
        assert f"Ответ: {count_tokens(narration)}" not in notice
        assert seen["stream_options"] == {"include_usage": True}
    print("OK  строка «Ответ» берёт completion_tokens модели, а не локальную оценку")


def test_resume_sees_partial_reply_and_finished_jobs():
    import tempfile

    from dungeon.i18n import DM_PREFIX

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        session.processing = True
        session.start_dm_stream()
        session.append_to_dm_stream("Первая ")
        session.append_to_dm_stream("часть")
        live = client.get("/api/state").json()
        assert live["streaming"] is True
        assert live["draft"] == "Первая часть"
        assert live["status"]["busy"] is True
        assert live["status"]["text"] == "Генерация..."
        assert live["rev"] >= 1
        session.history.append(f"{DM_PREFIX} Первая часть")
        session.finalize_dm_stream("Первая часть")
        session.processing = False
        session.summary_indexing = True
        summary = client.get("/api/state").json()
        assert summary["draft"] == ""
        assert summary["streaming"] is False
        assert summary["status"]["text"] == "Суммаризация..."
        assert any(row["kind"] == "dm" and row["text"] == "Первая часть" for row in summary["history"])
        session.summary_indexing = False
        session.memory_indexing = True
        assert client.get("/api/state").json()["status"]["text"] == "Индексация памяти..."
        session.memory_indexing = False
        done = client.get("/api/state").json()
        assert done["status"]["busy"] is False
        assert done["status"]["text"] == "Готов"
    print("OK  снимок состояния хранит недописанный ответ и статус фона")


def test_state_is_not_cached():
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        client = TestClient(create_app())
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        response = client.get("/api/state")
        assert response.status_code == 200
        cache = response.headers.get("cache-control", "")
        assert "no-store" in cache
        page = client.get("/")
        assert "no-store" in page.headers.get("cache-control", "")
        assert "app.js?v=16" in page.text
        assert "style.css?v=16" in page.text
        assert 'rel="icon"' in page.text
        icon = client.get("/favicon.ico")
        assert icon.status_code == 200
        assert icon.content[:4] == b"\x00\x00\x01\x00"
    print("OK  страница и состояние не кэшируются браузером телефона")


def test_context_scale_follows_model_prompt():
    from dungeon.tokens import (
        count_tokens,
        model_token_scale,
        observe_model_prompt,
        prompt_token_count,
        raw_count_tokens,
        set_model_token_scale,
    )

    text = "Темный коридор тянется дальше. " * 80
    set_model_token_scale(1.0)
    try:
        raw = raw_count_tokens(text)
        assert count_tokens(text) == raw
        assert observe_model_prompt(500, {"prompt_tokens": 100}) is False
        assert model_token_scale() == 1.0
        assert observe_model_prompt(16000, {"prompt_tokens": 12000}) is True
        scale = model_token_scale()
        assert 0.75 <= scale <= 0.85
        assert count_tokens(text) < raw
        assert prompt_token_count({"prompt_tokens": 12000}, 16000) == 12000
        assert observe_model_prompt(16000, {"prompt_tokens": True}) is False
    finally:
        set_model_token_scale(1.0)
    print("OK  шкала контекста сжимает локальный счёт до prompt_tokens модели")


def test_first_turn_learns_scale_before_packing():
    """Первый ход сверяет счётчик до нарезки истории, иначе в модель уходит урезанный промпт."""
    import tempfile

    from dungeon.tokens import (
        model_token_scale,
        raw_count_tokens,
        set_model_token_scale,
    )

    class _UsageResponse(_Response):
        def __init__(self, usage):
            self._usage = usage

        def json(self):
            return {"usage": self._usage}

    set_model_token_scale(1.0)
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            _use_tmp(tmp)
            app = create_app()
            session = app.state.session
            client = TestClient(app)
            assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
            piece = "слово " * 80
            one = raw_count_tokens(f"Игрок: реплика 0 {piece}") + 1
            total = int(26000 / max(one, 1)) + 5
            history = [f"Игрок: реплика {index} {piece}" for index in range(total)]
            (tmp / "Camp" / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
            assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 200
            assert client.put(
                "/api/settings",
                json={
                    "context_size": 16384,
                    "max_tokens": 400,
                    "summary_enabled": False,
                    "memory_enabled": False,
                },
            ).status_code == 200
            calls = []

            def finish_read(_response, _key, on_delta=None):
                if on_delta:
                    on_delta("Готово")
                return "Готово", False

            def post(payload, **kwargs):
                calls.append(payload)
                if payload.get("stream") is False and payload.get("max_tokens") == 1:
                    content = payload["messages"][0]["content"]
                    reported = max(1, int(raw_count_tokens(content) * 0.7))
                    return _UsageResponse({"prompt_tokens": reported, "completion_tokens": 1})
                return _Response()

            session._api_post = post
            session._read_response = finish_read
            assert client.post("/api/turn", json={"text": "осмотреться"}).status_code == 200
            deadline = time.time() + 4
            while time.time() < deadline and client.get("/api/state").json()["status"]["busy"]:
                time.sleep(0.05)
            turn = next(payload for payload in calls if payload.get("stream"))
            sent = raw_count_tokens(turn["messages"][0]["content"]) + raw_count_tokens(turn["messages"][1]["content"])
            assert model_token_scale() < 0.85
            # Без сверки локальный потолок около 16к. После неё в промпт входит больше текста.
            assert sent > 17000
    finally:
        set_model_token_scale(1.0)
    print("OK  первый ход узнаёт масштаб до нарезки истории")


def test_summary_learns_scale_before_packing():
    """Суммаризация сверяет счётчик до нарезки, иначе в модель уходит около 10к из 16к."""
    import tempfile

    from dungeon.tokens import model_token_scale, raw_count_tokens, set_model_token_scale

    class _UsageResponse(_Response):
        def __init__(self, usage):
            self._usage = usage

        def json(self):
            return {"usage": self._usage}

    set_model_token_scale(1.0)
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            _use_tmp(tmp)
            app = create_app()
            session = app.state.session
            client = TestClient(app)
            assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
            piece = "слово " * 80
            one = raw_count_tokens(f"Игрок: реплика 0 {piece}") + 1
            total = int(26000 / max(one, 1)) + 5
            history = [f"Игрок: реплика {index} {piece}" for index in range(total)]
            (tmp / "Camp" / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
            assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 200
            assert client.put(
                "/api/settings",
                json={"context_size": 16384, "memory_enabled": False},
            ).status_code == 200
            calls = []

            def finish_read(_response, _key, on_delta=None):
                return "Краткая хроника", False

            def post(payload, **kwargs):
                calls.append(payload)
                if payload.get("stream") is False and payload.get("max_tokens") == 1:
                    content = payload["messages"][0]["content"]
                    reported = max(1, int(raw_count_tokens(content) * 0.7))
                    return _UsageResponse({"prompt_tokens": reported, "completion_tokens": 1})
                return _Response()

            session._api_post = post
            session._read_response = finish_read
            assert client.post("/api/summary").status_code == 200
            deadline = time.time() + 4
            while time.time() < deadline and client.get("/api/state").json()["status"]["busy"]:
                time.sleep(0.05)
            summary = next(payload for payload in calls if payload.get("max_tokens") == 1000)
            sent = raw_count_tokens(summary["messages"][0]["content"])
            assert model_token_scale() < 0.85
            assert sent > 17000
    finally:
        set_model_token_scale(1.0)
    print("OK  суммаризация узнаёт масштаб до нарезки истории")


def test_bind_modes():
    from web.netbind import host_for_mode, is_tailscale_ip, saved_mode, share_urls, split_addresses

    assert is_tailscale_ip("100.96.1.2")
    assert is_tailscale_ip("100.64.0.1")
    assert is_tailscale_ip("100.127.255.255")
    assert not is_tailscale_ip("100.63.1.1")
    assert not is_tailscale_ip("100.128.0.1")
    assert not is_tailscale_ip("192.168.0.9")
    assert host_for_mode("local") == "127.0.0.1"
    assert host_for_mode("lan") == "0.0.0.0"
    assert host_for_mode("tailscale") == "0.0.0.0"
    assert saved_mode({}) == "lan"
    assert saved_mode({"lan_access": False}) == "local"
    assert saved_mode({"bind_mode": "tailscale", "lan_access": False}) == "tailscale"
    lan, tailscale = split_addresses(["127.0.0.1", "192.168.0.9", "100.64.0.8", "169.254.1.1"])
    assert lan == ["192.168.0.9"]
    assert tailscale == ["100.64.0.8"]
    urls = share_urls("tailscale", 8765, {"lan": ["192.168.0.9"], "tailscale": ["100.64.0.8"]})
    assert urls["local"] == "http://127.0.0.1:8765"
    assert urls["share"] == ["http://100.64.0.8:8765"]
    print("OK  режим запуска отличает Wi-Fi от Tailscale")


def test_preset_switch_updates_connection():
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()

        def _offline(*_args, **_kwargs):
            raise OSError("offline")

        app.state.session._api_post = _offline
        client = TestClient(app)
        saved = client.put(
            "/api/settings",
            json={
                "api_url": "http://localhost:1234/v1/chat/completions",
                "api_key": "",
                "model": "gemma",
                "active_api_preset": "Local",
                "api_presets": [
                    {
                        "name": "Local",
                        "api_url": "http://localhost:1234/v1/chat/completions",
                        "api_key": "",
                        "model": "gemma",
                    },
                    {
                        "name": "Remote",
                        "api_url": "http://example.test/v1/chat/completions",
                        "api_key": "secret",
                        "model": "other",
                    },
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        state = client.get("/api/state").json()
        assert state["presets"]["active"] == "Local"
        assert [item["name"] for item in state["presets"]["items"]] == ["Local", "Remote"]
        assert "api_key" not in state["presets"]["items"][1]
        switched = client.post("/api/presets/activate", json={"name": "Remote"})
        assert switched.status_code == 200, switched.text
        body = switched.json()
        assert body["active"] == "Remote"
        assert "secret" not in json.dumps(body)
        settings = client.get("/api/settings").json()
        assert settings["model"] == "other"
        assert settings["api_url"] == "http://example.test/v1/chat/completions"
        assert "secret" not in json.dumps(settings)
        assert "api_key" not in settings
        assert settings["api_key_set"] is True
        assert settings["api_key_last4"] == "cret"
        assert json.loads((tmp / "settings.json").read_text(encoding="utf-8"))["api_key"] == "secret"
        assert settings["active_api_preset"] == "Remote"
        missing = client.post("/api/presets/activate", json={"name": "Nope"})
        assert missing.status_code == 404
    print("OK  список моделей переключает сохранённую конфигурацию")


def test_model_switch_keeps_summary_bar_scaled():
    """Смена модели не рисует шкалу сырым счётчиком и помнит уже измеренный масштаб."""
    import tempfile

    from dungeon.tokens import calibration_sample, raw_count_tokens, set_model_token_scale

    class _UsageResponse(_Response):
        def __init__(self, usage):
            self._usage = usage

        def json(self):
            return {"usage": self._usage}

    set_model_token_scale(1.0)
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            _use_tmp(tmp)
            app = create_app()
            session = app.state.session
            client = TestClient(app)
            assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
            assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 200
            session.history = ["Игрок: " + ("тёмный коридор тянется дальше. " * 40)]
            session.covered_count = 0
            session.model = "alpha"
            set_model_token_scale(0.75)
            session._remember_token_scale()
            saved = client.put(
                "/api/settings",
                json={
                    "model": "alpha",
                    "summary_enabled": False,
                    "memory_enabled": False,
                    "active_api_preset": "Alpha",
                    "api_presets": [
                        {
                            "name": "Alpha",
                            "api_url": "http://127.0.0.1:9/v1/chat/completions",
                            "api_key": "",
                            "model": "alpha",
                        },
                        {
                            "name": "Beta",
                            "api_url": "http://127.0.0.1:9/v1/chat/completions",
                            "api_key": "",
                            "model": "beta",
                        },
                    ],
                },
            )
            assert saved.status_code == 200, saved.text
            used_a, budget_a, _ratio_a = session.context_fill_state()
            set_model_token_scale(1.0)
            used_raw, budget_raw, _ratio_raw = session.context_fill_state()
            set_model_token_scale(0.75)
            session._remember_token_scale()
            assert used_a < used_raw
            assert budget_a > budget_raw
            sample_raw = raw_count_tokens(calibration_sample())
            calls = []

            def post(payload, **_kwargs):
                calls.append(payload.get("model"))
                return _UsageResponse({"prompt_tokens": int(sample_raw * 0.8)})

            session._api_post = post
            switched = client.post("/api/presets/activate", json={"name": "Beta"})
            assert switched.status_code == 200, switched.text
            assert calls == ["beta"]
            fill = client.get("/api/state").json()["fill"]
            assert fill["used"] < used_raw
            assert fill["budget"] > budget_raw
            back = client.post("/api/presets/activate", json={"name": "Alpha"})
            assert back.status_code == 200, back.text
            assert calls == ["beta"]
            restored = client.get("/api/state").json()["fill"]
            assert restored["used"] == used_a
            assert restored["budget"] == budget_a
    finally:
        set_model_token_scale(1.0)
    print("OK  смена модели не раздувает шкалу до сырого счёта")


def test_finished_reply_is_settled_before_processing_ends():
    """Финал хода уже содержит обе реплики и закрытый черновик, пока processing ещё истинен."""
    import tempfile

    from dungeon.i18n import DM_PREFIX, PLAYER_PREFIX

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        session.processing = True
        session.history.append(f"{PLAYER_PREFIX} осмотреться")
        session.start_dm_stream()
        session.append_to_dm_stream("Тропа ")
        session.history.append(f"{DM_PREFIX} Тропа вывела к реке")
        session.finalize_dm_stream("Тропа вывела к реке")
        assert session.processing is True
        done = client.get("/api/state").json()
        assert done["streaming"] is False
        assert done["draft"] == ""
        assert any(row["kind"] == "player" and row["text"] == "осмотреться" for row in done["history"])
        assert any(row["kind"] == "dm" and row["text"] == "Тропа вывела к реке" for row in done["history"])
        assert done["fill"]["label"]
    print("OK  финал хода закрывает черновик до конца обработки")


def test_world_language_marks_and_english_token_scale():
    """Русский и английский миры помечены отдельно, и у английского свой масштаб."""
    import re
    import tempfile

    import dungeon.tokens as tokens
    from dungeon.storage import read_world_language
    from dungeon.tokens import calibration_sample, model_token_scale, raw_count_tokens, set_model_token_scale

    english = calibration_sample("en")
    assert raw_count_tokens(english) >= 1000
    assert raw_count_tokens(calibration_sample("ru")) >= 1000
    assert not re.search(r"[а-яёА-ЯЁ]", english)

    class _CharEncoder:
        def encode(self, text, disallowed_special=()):
            return [1] * max(1, len(text))

    tokens._TOKENIZER = _CharEncoder()
    tokens._TOKENIZER_LOADED = True
    tokens._TOKENIZER_IS_TARGET = False
    try:
        latin = "The road led across a dark field toward a distant fire. "
        cyrillic = "Ночь была тихой, и дорога вела через тёмное поле. "
        assert tokens.raw_count_tokens(latin) == len(latin)
        assert tokens.raw_count_tokens(cyrillic) < len(cyrillic)
    finally:
        tokens._TOKENIZER = None
        tokens._TOKENIZER_LOADED = False
        tokens._TOKENIZER_IS_TARGET = False

    set_model_token_scale(1.0)
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            _use_tmp(tmp)
            app = create_app()
            session = app.state.session
            client = TestClient(app)
            assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
            assert (tmp / "Camp" / "language.txt").read_text(encoding="utf-8").strip() == "ru"
            shore = tmp / "Shore"
            shore.mkdir()
            (shore / "introduction.txt").write_text("A quiet harbor at dawn.", encoding="utf-8")
            assert read_world_language(shore) == "en"
            session.model = "alpha"
            set_model_token_scale(0.75)
            session._remember_token_scale()
            calls = []

            class _UsageResponse(_Response):
                def __init__(self, usage):
                    self._usage = usage

                def json(self):
                    return {"usage": self._usage}

            def post(payload, **_kwargs):
                text = payload["messages"][0]["content"]
                calls.append(text)
                assert "Ночь" not in text
                raw = raw_count_tokens(text)
                return _UsageResponse({"prompt_tokens": int(raw * 0.9)})

            session._api_post = post
            session.language = "en"
            assert client.post("/api/worlds", json={"name": "Harbor"}).status_code == 200
            assert (tmp / "Harbor" / "language.txt").read_text(encoding="utf-8").strip() == "en"
            assert len(calls) == 1
            assert calls[0].startswith("The night was quiet")
            assert model_token_scale() > 0.9
            assert abs(model_token_scale() - 0.75) > 0.05
            assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 200
            assert len(calls) == 1
            assert abs(model_token_scale() - 0.75) < 0.001
            worlds = client.get("/api/worlds").json()["worlds"]
            assert [item["name"] for item in worlds] == ["Camp", "Harbor", "Shore"]
            assert [item["language"] for item in worlds] == ["ru", "en", "en"]
    finally:
        set_model_token_scale(1.0)
    print("OK  миры помечены языком, английский масштаб не берётся из русской пробы")


def test_prompt_limits_and_scene_look():
    import tempfile

    from dungeon.config import apply_image_look
    from dungeon.i18n import t

    styled = apply_image_look("a knight on a road --ar 16:9 --v 7", "anime")
    assert styled.index("anime style") < styled.index("--ar")
    assert apply_image_look(styled, "anime") == styled
    assert "anime style, cel shading" in t("en", "prompt.scene_look.anime")
    assert "photorealistic, realistic skin" in t("ru", "prompt.scene_look.realism")

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        view = client.get("/api/settings").json()
        assert view["response_limits"]["prompt.memory_index"] == 350
        assert view["response_limits"]["prompt.scene_image"] == 700
        assert view["response_limits"]["prompt.summary"] == 1000
        assert view["response_limits"]["prompt.card_desc_gen"] == 400
        prompts = [item for group in view["prompts"] for item in group["prompts"]]
        assert next(item for item in prompts if item["key"] == "prompt.memory_index")["limit"] == 350
        assert "limit" not in next(item for item in prompts if item["key"] == "prompt.continue")

        updated = client.put(
            "/api/settings",
            json={"response_limits": {"prompt.memory_index": 120, "prompt.scene_image": 900, "prompt.summary": "нет"}},
        )
        assert updated.status_code == 200, updated.text
        limits = updated.json()["response_limits"]
        assert limits["prompt.memory_index"] == 120
        assert limits["prompt.scene_image"] == 900
        assert limits["prompt.summary"] == 1000
        assert client.put("/api/settings", json={"response_limits": {"prompt.memory_index": 0}}).json()["response_limits"]["prompt.memory_index"] == 1

        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        history = ["Игрок: осмотреться", "Мастер: Тропа вывела к реке."]
        (tmp / "Camp" / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 200
        assert session._summary_history_budget()[2] == 1000
        options = client.put("/api/scene/options", json={"image_prompt_style": "flux", "image_look": "anime"})
        assert options.status_code == 200, options.text
        assert options.json()["image_prompt_style"] == "flux"
        assert options.json()["image_look"] == "anime"
        calls = []

        def post(payload, **_kwargs):
            calls.append(payload)
            return _Response()

        def finish_read(_response, _key, on_delta=None):
            return '{"prompt": "a river path --ar 16:9", "negative_prompt": "blurry"}', False

        session._api_post = post
        session._read_response = finish_read
        session.response_limits["prompt.scene_image"] = 900
        assert client.post(
            "/api/scene",
            json={"image_prompt_style": "midjourney", "image_look": "realism"},
        ).status_code == 200
        deadline = time.time() + 3
        scene = None
        while time.time() < deadline:
            scene = client.get("/api/scene").json()["scene"]
            if scene and scene.get("prompt"):
                break
            time.sleep(0.05)
        assert calls, "промпт сцены не ушёл в модель"
        sent = calls[-1]["messages"][0]["content"]
        assert calls[-1]["max_tokens"] == 900
        assert "СТИЛЬ ИЗОБРАЖЕНИЯ: реализм" in sent
        assert "photorealistic, realistic skin" in sent
        assert scene["style"] == "midjourney"
        assert scene["look"] == "realism"
        assert "photorealistic, realistic skin" in scene["prompt"]
        assert scene["prompt"].index("photorealistic") < scene["prompt"].index("--ar")
        assert scene["negative"] == "blurry"
        stored = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
        assert stored["image_look"] == "realism"
        assert stored["image_prompt_style"] == "midjourney"
        assert stored["response_limits"]["prompt.scene_image"] == 900

        marker = "MARKER_EARLY_CARD"
        session.history = [f"Игрок: {marker} {i}" for i in range(15)]
        session.response_limits["prompt.card_desc_gen"] = 180
        calls.clear()
        idle_deadline = time.time() + 3
        while time.time() < idle_deadline and client.get("/api/state").json()["status"]["busy"]:
            time.sleep(0.05)
        described = client.post("/api/cards/describe", json={"title": "Страж", "description": "у ворот"})
        assert described.status_code == 200, described.text
        deadline = time.time() + 3
        while time.time() < deadline and not calls:
            time.sleep(0.05)
        assert calls, "описание карточки не ушло в модель"
        assert calls[-1]["max_tokens"] == 180
        card_prompt = calls[-1]["messages"][0]["content"]
        assert f"{marker} 0" in card_prompt
        assert f"{marker} 14" in card_prompt
        idle_deadline = time.time() + 3
        while time.time() < idle_deadline and client.get("/api/state").json()["status"]["busy"]:
            time.sleep(0.05)

        before = client.get("/api/settings").json()
        switched = client.put("/api/settings", json={"language": "en"})
        assert switched.status_code == 200, switched.text
        body = switched.json()
        assert body["language"] == "en"
        assert body["temperature"] == before["temperature"]
        assert body["max_tokens"] == before["max_tokens"]
        assert body["api_url"] == before["api_url"]
        assert body["response_limits"]["prompt.card_desc_gen"] == 180
    print("OK  лимиты промптов меняются, стиль дописывается в промпт сцены")


def test_world_guards_settings_and_startup():
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        broken = tmp / "Broken"
        broken.mkdir()
        (broken / "history.json").write_text("{", encoding="utf-8")
        client = TestClient(create_app())
        state = client.get("/api/state").json()
        assert state["world"] is None
        assert state["notices"]
        assert "Broken" in state["notices"][-1]
        assert client.post("/api/worlds/open", json={"name": "Broken"}).status_code == 409
        assert client.get("/api/state").json()["world"] is None

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        outside = Path(tempfile.mkdtemp())
        (outside / "history.json").write_text("[]", encoding="utf-8")
        link = tmp / "Linked"
        linked = _try_symlink(link, outside, directory=True)
        release = __import__("threading").Event()
        try:
            assert client.post("/api/worlds/open", json={"name": ".."}).status_code == 400
            assert client.post("/api/worlds/open", json={"name": "../Camp"}).status_code == 400
            assert client.post("/api/worlds/open", json={"name": str(outside)}).status_code == 400
            if linked:
                assert client.post("/api/worlds/open", json={"name": "Linked"}).status_code == 400
            assert client.get("/api/state").json()["world"] == "Camp"
            assert client.delete("/api/worlds/%2e%2e").status_code == 400
            assert (tmp / "Camp").is_dir()
            if linked:
                assert client.delete("/api/worlds/Linked").status_code == 400
                assert outside.is_dir()
                assert (outside / "history.json").is_file()

            kept = client.put("/api/settings", json={"temperature": "hot", "context_size": 0, "max_tokens": None})
            assert kept.status_code == 200, kept.text
            saved = kept.json()
            assert saved["temperature"] == 0.7
            assert saved["context_size"] == 1
            assert saved["max_tokens"] == 300
            tiny = client.put("/api/settings", json={"context_size": 200})
            assert tiny.status_code == 200
            assert tiny.json()["context_size"] == 200

            empty = client.post("/api/scene")
            assert empty.status_code == 200, empty.text
            assert empty.json()["ok"] is False
            assert empty.json()["notice"]

            blank = client.put("/api/files/plot_basics.txt", json={"content": None})
            assert blank.status_code == 200, blank.text
            assert (tmp / "Camp" / "plot_basics.txt").read_text(encoding="utf-8") == ""

            def blocking_read(_response, key, on_delta=None):
                while not release.is_set() and not session.is_cancelled(key):
                    time.sleep(0.02)
                return "Готово", False

            session._api_post = lambda payload, **kwargs: _Response()
            session._read_response = blocking_read
            assert client.post("/api/turn", json={"text": "ждать"}).status_code == 200
            assert client.post("/api/summary").status_code == 409
            assert client.post("/api/worlds", json={"name": "Other"}).status_code == 409
            assert not (tmp / "Other").exists()
            assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 409
            assert client.put("/api/files/plot_basics.txt", json={"content": "нельзя"}).status_code == 409
            assert (tmp / "Camp" / "plot_basics.txt").read_text(encoding="utf-8") == ""
            assert client.delete("/api/worlds/Camp").status_code == 409
            assert (tmp / "Camp").is_dir()
        finally:
            release.set()
            deadline = time.time() + 3
            while time.time() < deadline and client.get("/api/state").json()["status"]["busy"]:
                time.sleep(0.05)
            import shutil
            shutil.rmtree(outside, ignore_errors=True)

        removed = client.delete("/api/worlds/Camp")
        assert removed.status_code == 200, removed.text
        state = removed.json()
        assert state["world"] is None
        assert state["history"] == []
        assert state["fill"]["used"] == 0
        assert state["fill"]["ratio"] == 0
        assert state["memory"]["entries"] == []
        assert client.post("/api/summary").status_code == 409
    note = "" if linked else " Ссылку на чужую папку пропустили: у процесса нет этого права Windows."
    print("OK  чужие пути закрыты, битый мир не роняет сервер, ход блокирует правки" + note)


def _js_function(source, name):
    marker = f"function {name}"
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(name)


def test_markup_stays_text():
    import tempfile

    markup = "<script>alert(1)</script><button>click</button>"
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        client = TestClient(create_app())
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        history = [f"Мастер: {markup}", f"Игрок: {markup}"]
        (tmp / "Camp" / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        cards = {"cards": [{"id": "card_001", "title": markup, "description": markup, "triggers": [markup]}]}
        (tmp / "Camp" / "story_cards.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
        opened = client.post("/api/worlds/open", json={"name": "Camp"})
        assert opened.status_code == 200, opened.text
        state = opened.json()
        texts = [row["text"] for row in state["history"]]
        assert markup in texts
        listed = client.get("/api/cards").json()
        assert listed["cards"][0]["title"] == markup
        assert listed["cards"][0]["description"] == markup
        assert listed["cards"][0]["triggers"] == [markup]
        raw = client.get("/api/state").text
        assert markup in raw
        assert raw.lstrip().startswith("{")

        page = client.get("/")
        api = client.get("/api/state")
        for response in (page, api):
            policy = response.headers["content-security-policy"]
            assert "script-src 'self'" in policy
            assert "style-src 'self'" in policy
            assert "unsafe-inline" not in policy
            assert "*" not in policy

    source = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    log_source = _js_function(source, "renderLog")
    assert "innerHTML" not in log_source
    assert "setNodeText(p, plainText(row.text))" in log_source
    assert ".innerHTML" not in source
    setter = _js_function(source, "setNodeText")
    script = r"""
const fs = require("fs");
const setter = fs.readFileSync(0, "utf8");
class TextNode {
  constructor(text) { this.nodeType = 3; this.nodeValue = String(text); }
  get textContent() { return this.nodeValue; }
}
class Element {
  constructor() { this.nodeType = 1; this.childNodes = []; }
  get children() { return this.childNodes.filter((node) => node.nodeType === 1); }
  get textContent() { return this.childNodes.map((node) => node.textContent).join(""); }
  set textContent(value) { this.replaceChildren(new TextNode(value)); }
  replaceChildren(...nodes) { this.childNodes = nodes; }
  set innerHTML(html) {
    const element = new Element();
    element.childNodes = [new TextNode(String(html).replace(/<[^>]+>/g, ""))];
    this.childNodes = [element];
  }
}
const document = { createTextNode: (text) => new TextNode(text) };
const setNodeText = new Function("document", setter + "\nreturn setNodeText;")(document);
const markup = "<script>alert(1)</script><button>click</button>";
const node = new Element();
setNodeText(node, markup);
if (node.textContent !== markup || node.children.length !== 0) {
  console.error(JSON.stringify({ text: node.textContent, children: node.children.length }));
  process.exit(1);
}
"""
    import subprocess

    checked = subprocess.run(["node", "-e", script], input=setter, text=True, capture_output=True, check=False)
    assert checked.returncode == 0, checked.stderr or checked.stdout
    print("OK  чужой текст остаётся строкой, страница не берёт скрипты с других сайтов")


def test_world_paths_and_hidden_key():
    import io
    import shutil
    import tempfile
    import zipfile

    secret = "sk-test-DoNotLeak-4491"
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        client = TestClient(create_app())
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        outside = Path(tempfile.mkdtemp())
        try:
            assert client.post("/api/worlds/open", json={"name": ".."}).status_code == 400
            assert client.post("/api/worlds/open", json={"name": "../Camp"}).status_code == 400
            assert client.post("/api/worlds/open", json={"name": str(outside)}).status_code == 400
            assert client.post("/api/worlds/open", json={"name": "/etc"}).status_code == 400
            link = tmp / "Linked"
            linked = _try_symlink(link, outside, directory=True)
            if linked:
                assert client.post("/api/worlds/open", json={"name": "Linked"}).status_code == 400
                assert client.delete("/api/worlds/Linked").status_code == 400
                assert outside.is_dir()

                leak = outside / "leak.txt"
                leak.write_text("OUTSIDE_FILE_SECRET", encoding="utf-8")
                plot = tmp / "Camp" / "plot_basics.txt"
                plot.unlink()
                assert _try_symlink(plot, leak)
                files = client.get("/api/files")
                assert files.status_code == 200, files.text
                assert files.json()["plot_basics.txt"] == ""
                assert "OUTSIDE_FILE_SECRET" not in files.text
                exported = client.get("/api/worlds/Camp/export")
                assert exported.status_code == 200, exported.text
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    names = set(archive.namelist())
                    blob = b"\n".join(archive.read(name) for name in names)
                assert "plot_basics.txt" not in names
                assert b"OUTSIDE_FILE_SECRET" not in blob

                (outside / "history.json").write_text(
                    json.dumps(["Мастер: OUTSIDE_HISTORY_SECRET"], ensure_ascii=False),
                    encoding="utf-8",
                )
                history_path = tmp / "Camp" / "history.json"
                history_path.unlink()
                assert _try_symlink(history_path, outside / "history.json")
                opened = client.post("/api/worlds/open", json={"name": "Camp"})
                assert opened.status_code == 200, opened.text
                assert "OUTSIDE_HISTORY_SECRET" not in opened.text
                assert leak.read_text(encoding="utf-8") == "OUTSIDE_FILE_SECRET"

            slipped = io.BytesIO()
            with zipfile.ZipFile(slipped, "w") as archive:
                archive.writestr("../settings.json", "ZIP_TRAVERSAL_SECRET")
                archive.writestr("history.json", "[]")
            rejected = client.post(
                "/api/worlds/import?name=Escape",
                content=slipped.getvalue(),
                headers={"Content-Type": "application/zip"},
            )
            assert rejected.status_code == 400
            assert not (tmp / "Escape").exists()
            if (tmp / "settings.json").exists():
                assert "ZIP_TRAVERSAL_SECRET" not in (tmp / "settings.json").read_text(encoding="utf-8")

            saved = client.put(
                "/api/settings",
                json={
                    "api_key": secret,
                    "temperature": 0.5,
                    "active_api_preset": "Hidden",
                    "api_presets": [
                        {
                            "name": "Hidden",
                            "api_url": "http://example.test/v1/chat/completions",
                            "api_key": secret,
                            "model": "hidden",
                        }
                    ],
                },
            )
            assert saved.status_code == 200, saved.text
            assert secret not in saved.text
            body = saved.json()
            assert "api_key" not in body
            assert body["api_key_set"] is True
            assert body["api_key_last4"] == "4491"
            assert "api_key" not in body["api_presets"][0]
            assert body["api_presets"][0]["api_key_set"] is True
            kept = client.put(
                "/api/settings",
                json={
                    "api_key": "",
                    "temperature": 0.4,
                    "api_presets": [
                        {
                            "name": "Hidden",
                            "api_url": "http://example.test/v1/chat/completions",
                            "api_key": "",
                            "model": "hidden",
                        }
                    ],
                },
            )
            assert kept.status_code == 200, kept.text
            assert kept.json()["temperature"] == 0.4
            assert secret not in kept.text
            stored = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
            assert stored["api_key"] == secret
            assert stored["api_presets"][0]["api_key"] == secret
            assert secret not in client.get("/api/settings").text
            assert secret not in client.get("/api/state").text
            assert secret not in client.get("/api/prompt").text
            packed = client.get("/api/worlds/Camp/export")
            assert packed.status_code == 200, packed.text
            assert secret.encode() not in packed.content
            replaced = client.put("/api/settings", json={"api_key": "sk-test-Replacement-0009"})
            assert replaced.status_code == 200, replaced.text
            assert "sk-test-Replacement-0009" not in replaced.text
            assert json.loads((tmp / "settings.json").read_text(encoding="utf-8"))["api_key"] == "sk-test-Replacement-0009"
        finally:
            shutil.rmtree(outside, ignore_errors=True)
    note = "" if linked else " Ссылки на чужие файлы пропустили: у процесса нет этого права Windows."
    print("OK  чужие пути и сохранённый ключ не выходят через веб-API" + note)


def test_overlapping_jobs_start_once():
    import tempfile
    import threading

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        client.put("/api/settings", json={"summary_enabled": False, "memory_enabled": False})
        hold = threading.Event()
        posts = []
        kinds = []

        def post(payload, **_kwargs):
            posts.append(payload)
            hold.wait(3)
            return _Response()

        def read(_response, key, on_delta=None):
            kinds.append(key)
            return '{"summary":"заметка","keys":["ключ"],"location":"зал","npcs":["страж"],"prompt":"hall","negative_prompt":"blur"}', False

        session._api_post = post
        session._read_response = read

        def race(calls):
            barrier = threading.Barrier(len(calls))
            results = []

            def run(fn):
                barrier.wait()
                results.append(bool(fn()))

            threads = [threading.Thread(target=run, args=(fn,)) for fn in calls]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            return results

        def release():
            hold.set()
            deadline = time.time() + 3
            while time.time() < deadline and session.is_busy():
                time.sleep(0.02)
            assert not session.is_busy(), session.status_view()
            hold.clear()

        def claim_once(calls):
            before = len(posts)
            results = race(calls)
            deadline = time.time() + 3
            while time.time() < deadline and len(posts) < before + 1:
                time.sleep(0.01)
            assert sorted(results) == [False, True], results
            assert len(posts) == before + 1, posts[before:]
            release()

        claim_once([
            lambda: session.describe_card("Страж", "у ворот"),
            lambda: session.describe_card("Страж", "у ворот"),
        ])
        claim_once([
            lambda: session.describe_card("Страж", "у ворот"),
            lambda: session.submit_turn("осмотреться"),
        ])
        assert sum(1 for line in session.history if line == "Игрок: осмотреться") == 1
        claim_once([
            lambda: session.submit_turn("шагнуть"),
            lambda: session.submit_turn("шагнуть"),
        ])
        assert sum(1 for line in session.history if line == "Игрок: шагнуть") == 1
        claim_once([lambda: session.summarize(), lambda: session.summarize()])
        session.history = ["Игрок: осмотреться", "Мастер: В зале темно."]
        claim_once([lambda: session.start_scene_prompt(), lambda: session.start_scene_prompt()])

        session.memory_bank = {"last_indexed_turn": 0, "entries": []}
        session.memory_enabled = True
        session.memory_interval = 1
        session.processing = True
        session._schedule_summary_after_turn = True
        session._schedule_memory_after_turn = True
        kinds.clear()
        hold.set()
        session._finish_player_turn()
        deadline = time.time() + 3
        while time.time() < deadline and not {"summary", "memory"} <= set(kinds):
            time.sleep(0.02)
        from dungeon.api_stream import MEMORY, SUMMARY
        assert SUMMARY in kinds and MEMORY in kinds, kinds
        deadline = time.time() + 3
        while time.time() < deadline and session.is_busy():
            time.sleep(0.02)
        assert not session.is_busy()
    print("OK  два одновременных запуска не открывают вторую работу")


def _wait_idle(client, timeout=4):
    deadline = time.time() + timeout
    state = client.get("/api/state").json()
    while time.time() < deadline:
        state = client.get("/api/state").json()
        if not state["status"]["busy"]:
            return state
        time.sleep(0.05)
    raise AssertionError("ход не завершился")


def _names(payload):
    return [item["name"] if isinstance(item, dict) else item for item in payload["worlds"]]


def test_modes_keep_worlds_in_separate_folders():
    import io
    import tempfile
    import zipfile

    from dungeon.i18n import t

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        client = TestClient(create_app())
        strings = client.get("/api/strings").json()
        assert strings["btn.modes"] == "Режимы"
        assert strings["mode.sandbox"] == "Песочница"
        assert strings["mode.adventure"] == "Приключение"
        assert strings["dialog.sandbox_d20"] == "Проверка d20"
        assert t("en", "mode.adventure") == "Adventure"
        assert client.get("/api/state").json()["play_mode"] == "sandbox"

        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        assert (tmp / "Camp").is_dir()
        assert not (tmp / "Camp" / "mode.txt").exists()
        (tmp / "Old").mkdir()
        (tmp / "Old" / "introduction.txt").write_text("старый лагерь", encoding="utf-8")

        switched = client.post("/api/mode", json={"play_mode": "adventure"})
        assert switched.status_code == 200, switched.text
        adventure = switched.json()
        assert adventure["play_mode"] == "adventure"
        assert adventure["world"] is None
        assert _names(adventure) == []
        assert json.loads((tmp / "settings.json").read_text(encoding="utf-8"))["play_mode"] == "adventure"

        created = client.post("/api/worlds", json={"name": "Quest"})
        assert created.status_code == 200, created.text
        assert (tmp / "adventure" / "Quest" / "mode.txt").read_text(encoding="utf-8").strip() == "adventure"
        assert not (tmp / "Quest").exists()
        assert _names(client.get("/api/worlds").json()) == ["Quest"]
        assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 404
        assert client.delete("/api/worlds/Camp").status_code == 404
        assert (tmp / "Camp").is_dir()

        exported = client.get("/api/worlds/Quest/export")
        assert exported.status_code == 200, exported.text
        assert client.delete("/api/worlds/Quest").status_code == 200
        assert not (tmp / "adventure" / "Quest").exists()
        brought = client.post(
            "/api/worlds/import?name=Quest",
            content=exported.content,
            headers={"Content-Type": "application/zip"},
        )
        assert brought.status_code == 200, brought.text
        assert (tmp / "adventure" / "Quest" / "mode.txt").read_text(encoding="utf-8").strip() == "adventure"
        assert not (tmp / "Quest").exists()
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            assert "mode.txt" in archive.namelist()

        sandbox = client.post("/api/mode", json={"play_mode": "sandbox"})
        assert sandbox.status_code == 200, sandbox.text
        assert _names(sandbox.json()) == ["Camp", "Old"]
        assert "Quest" not in _names(sandbox.json())
        assert client.post("/api/worlds/open", json={"name": "Quest"}).status_code == 404
        assert client.post("/api/worlds", json={"name": "adventure"}).status_code == 400
        assert client.get("/api/state").json()["world"] == "Camp"
    print("OK  миры приключения лежат отдельно и не видны в песочнице")


def test_d20_discards_unknown_difficulty_and_uses_a_known_roll():
    import tempfile

    import dungeon.adventure as adventure
    from dungeon.tokens import set_model_token_scale

    assert adventure.accepted_dc(15) is None
    assert adventure.accepted_dc(12) is None
    assert adventure.accepted_dc("13") == 13
    assert adventure.accepted_dc(19) == 19
    assert adventure.roll_succeeds(1, 10) is False
    assert adventure.roll_succeeds(20, 19) is True
    assert adventure.roll_succeeds(13, 13) is True
    assert adventure.roll_succeeds(12, 13) is False

    set_model_token_scale(0.8)
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            _use_tmp(tmp)
            app = create_app()
            session = app.state.session
            client = TestClient(app)
            assert client.post("/api/mode", json={"play_mode": "adventure"}).status_code == 200
            assert client.post("/api/worlds", json={"name": "Quest"}).status_code == 200
            calls = []
            rolls = {"n": 0, "value": 17}
            checks = [
                '{"needed": true, "name": "Ловкость", "dc": 15}',
                '{"needed": true, "name": "Сила", "dc": 13}',
            ]

            def fake_roll():
                rolls["n"] += 1
                return rolls["value"]

            adventure.roll_d20 = fake_roll

            def post(payload, **_kwargs):
                calls.append(payload)
                return _Response()

            def read(_response, _key, on_delta=None):
                payload = calls[-1]
                content = payload["messages"][-1]["content"]
                if payload["messages"][0]["role"] == "system":
                    if on_delta:
                        on_delta("Готово")
                    return "Готово", False
                if "characters" in content:
                    return '{"equipment":"","appearance":"","stats":{},"characters":[]}', False
                return checks.pop(0), False

            session._api_post = post
            session._read_response = read
            blocked = client.post("/api/turn", json={"text": "осмотреться"})
            assert blocked.status_code == 409
            assert blocked.json()["detail"] == "hero"
            assert calls == []
            assert not (tmp / "adventure" / "Quest" / "hero.json").exists()

            saved = client.put(
                "/api/hero",
                json={"name": "Мира", "appearance": "плащ", "equipment": "лук", "strength": 10},
            )
            assert saved.status_code == 200, saved.text
            assert client.post("/api/turn", json={"text": "осмотреться"}).status_code == 200
            _wait_idle(client)
            narration = [item for item in calls if item["messages"][0]["role"] == "system"]
            assert narration[0]["messages"][-1]["content"] == "осмотреться"
            assert rolls["n"] == 0
            assert "Мира" in narration[0]["messages"][0]["content"]

            assert client.post("/api/turn", json={"text": "толкнуть дверь"}).status_code == 200
            state = _wait_idle(client)
            narration = [item for item in calls if item["messages"][0]["role"] == "system"]
            user = narration[-1]["messages"][-1]["content"]
            assert "Сила" in user and "17" in user and "успех" in user
            assert rolls["n"] == 1
            assert any(row["kind"] == "player" and "17" in row["text"] for row in state["history"])
            assert "Мира" in narration[-1]["messages"][0]["content"]
    finally:
        set_model_token_scale(1.0)
    print("OK  чужая сложность отбрасывается, известный d20 попадает в промпт")


def test_d20_prompt_names_each_outcome():
    import tempfile

    import dungeon.adventure as adventure
    from dungeon.i18n import t
    from dungeon.tokens import set_model_token_scale

    assert adventure.roll_outcome(20, 19) == "critical_success"
    assert adventure.roll_outcome(20, 25) == "critical_success"
    assert adventure.roll_outcome(13, 13) == "success"
    assert adventure.roll_outcome(12, 13) == "failure"
    assert adventure.roll_outcome(1, 10) == "critical_failure"
    assert adventure.roll_outcome(1, 1) == "critical_failure"

    cues = {
        lang: {name: t(lang, f"check.cue.{name}") for name in (
            "critical_success", "success", "failure", "critical_failure",
        )}
        for lang in ("ru", "en")
    }
    assert len(set(cues["ru"].values())) == 4
    assert len(set(cues["en"].values())) == 4
    assert "Описывай" in cues["ru"]["success"]
    assert "Narrate" in cues["en"]["success"]

    cases = [
        ("ru", 20, 19, "critical_success"),
        ("ru", 13, 13, "success"),
        ("ru", 12, 13, "failure"),
        ("ru", 1, 10, "critical_failure"),
        ("en", 20, 19, "critical_success"),
        ("en", 16, 13, "success"),
        ("en", 9, 10, "failure"),
        ("en", 1, 19, "critical_failure"),
    ]
    step = {"i": 0}

    set_model_token_scale(0.8)
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            _use_tmp(tmp)
            app = create_app()
            session = app.state.session
            client = TestClient(app)
            assert client.post("/api/mode", json={"play_mode": "adventure"}).status_code == 200
            assert client.post("/api/worlds", json={"name": "Quest"}).status_code == 200
            assert client.put("/api/hero", json={"name": "Мира", "strength": 10}).status_code == 200
            calls = []

            def fake_roll():
                rolled = cases[step["i"]][1]
                step["i"] += 1
                return rolled

            adventure.roll_d20 = fake_roll

            def post(payload, **_kwargs):
                calls.append(payload)
                return _Response()

            def read(_response, _key, on_delta=None):
                payload = calls[-1]
                content = payload["messages"][-1]["content"]
                if payload["messages"][0]["role"] == "system":
                    if on_delta:
                        on_delta("Готово")
                    return "Готово", False
                if "characters" in content:
                    return '{"equipment":"","appearance":"","stats":{},"characters":[]}', False
                _lang, _roll, dc, _outcome = cases[step["i"]]
                return json.dumps({"needed": True, "name": "Сила", "dc": dc}, ensure_ascii=False), False

            session._api_post = post
            session._read_response = read
            set_model_token_scale(0.8)
            for lang, roll, _dc, outcome in cases:
                session.language = lang
                before = len(calls)
                assert client.post("/api/turn", json={"text": "толкнуть дверь"}).status_code == 200
                state = _wait_idle(client)
                narration = [
                    item for item in calls[before:]
                    if item["messages"][0]["role"] == "system"
                ]
                assert narration, calls[before:]
                user = narration[-1]["messages"][-1]["content"]
                expected = cues[lang][outcome]
                assert expected in user, user
                for other, text in cues[lang].items():
                    if other != outcome:
                        assert text not in user
                assert str(roll) in user
                player = [row for row in state["history"] if row["kind"] == "player"][-1]
                assert str(roll) in player["text"]
                assert expected not in player["text"]
    finally:
        set_model_token_scale(1.0)
    print("OK  промпт называет все четыре исхода броска на языке хода")


def test_named_foe_gets_a_card_and_unnamed_guard_does_not():
    import tempfile

    import dungeon.adventure as adventure
    from dungeon.tokens import set_model_token_scale

    set_model_token_scale(0.8)
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            _use_tmp(tmp)
            app = create_app()
            session = app.state.session
            client = TestClient(app)
            assert client.post("/api/mode", json={"play_mode": "adventure"}).status_code == 200
            assert client.post("/api/worlds", json={"name": "Quest"}).status_code == 200
            assert client.put("/api/hero", json={"name": "Мира", "strength": 10}).status_code == 200
            follow = json.dumps(
                {
                    "equipment": "сабля",
                    "appearance": "",
                    "stats": {"strength": 16},
                    "characters": [
                        {
                            "name": "Арион",
                            "description": "уже есть",
                            "triggers": ["арион"],
                            "returns": True,
                            "conflict": True,
                        },
                        {
                            "name": "Капитан Рен",
                            "description": "Враг с саблей.",
                            "triggers": ["рен", "капитан"],
                            "returns": False,
                            "conflict": True,
                        },
                        {
                            "name": "",
                            "description": "безымянная стража у ворот",
                            "triggers": ["стража"],
                            "returns": True,
                            "conflict": True,
                        },
                        {
                            "name": "стражник",
                            "description": "просто стоит",
                            "triggers": ["стражник"],
                            "returns": False,
                            "conflict": False,
                        },
                    ],
                },
                ensure_ascii=False,
            )

            def post(payload, **_kwargs):
                session._last_payload = payload
                return _Response()

            def read(_response, _key, on_delta=None):
                content = session._last_payload["messages"][-1]["content"]
                if session._last_payload["messages"][0]["role"] == "system":
                    if on_delta:
                        on_delta("Сталь звенит")
                    return "Сталь звенит", False
                if "characters" in content:
                    return follow, False
                return '{"needed": false}', False

            adventure.roll_d20 = lambda: 11
            session._api_post = post
            session._read_response = read
            assert client.post("/api/turn", json={"text": "атаковать капитана"}).status_code == 200
            _wait_idle(client)
            cards = client.get("/api/cards").json()["cards"]
            titles = [card["title"] for card in cards]
            assert titles.count("Арион") == 1
            assert "Капитан Рен" in titles
            assert "стражник" not in titles
            assert all(str(card.get("title") or "").strip() for card in cards)
            foe = next(card for card in cards if card["title"] == "Капитан Рен")
            assert {"id", "title", "description", "triggers"} <= set(foe)
            assert "рен" in foe["triggers"]
            hero = json.loads((tmp / "adventure" / "Quest" / "hero.json").read_text(encoding="utf-8"))
            assert hero["equipment"] == "сабля"
            assert hero["strength"] == 10
            pending = client.get("/api/state").json()["pending_stats"]
            assert pending["stats"]["strength"] == 16
            accepted = client.post("/api/hero/stats", json={"accept": True})
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["hero"]["strength"] == 16
            assert accepted.json()["pending_stats"] is None
    finally:
        set_model_token_scale(1.0)
    print("OK  именной враг получает карточку, безымянная стража нет, характеристики ждут подтверждения")


def test_sandbox_flags_enable_mechanics_without_moving_worlds():
    import tempfile

    import dungeon.adventure as adventure
    from dungeon.tokens import set_model_token_scale

    set_model_token_scale(0.8)
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            _use_tmp(tmp)
            app = create_app()
            session = app.state.session
            client = TestClient(app)
            opened = client.get("/api/settings").json()
            assert opened["sandbox_d20"] is False
            assert opened["sandbox_hero"] is False
            assert opened["sandbox_npc"] is False
            assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
            assert client.post("/api/mode", json={"play_mode": "adventure"}).status_code == 200
            assert client.post("/api/worlds", json={"name": "Quest"}).status_code == 200
            assert client.post("/api/mode", json={"play_mode": "sandbox"}).status_code == 200
            assert _names(client.get("/api/worlds").json()) == ["Camp"]

            saved = client.put(
                "/api/settings",
                json={"sandbox_d20": True, "sandbox_hero": True, "sandbox_npc": True},
            )
            assert saved.status_code == 200, saved.text
            body = saved.json()
            assert body["sandbox_d20"] is True
            assert body["sandbox_hero"] is True
            assert body["sandbox_npc"] is True
            assert body["play_mode"] == "sandbox"
            assert _names(client.get("/api/worlds").json()) == ["Camp"]
            stored = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
            assert stored["sandbox_d20"] is True
            assert stored["sandbox_hero"] is True
            assert stored["sandbox_npc"] is True
            assert (tmp / "Quest").exists() is False
            assert (tmp / "adventure" / "Quest").is_dir()

            calls = []

            def post(payload, **_kwargs):
                calls.append(payload)
                return _Response()

            def read(_response, _key, on_delta=None):
                content = calls[-1]["messages"][-1]["content"]
                if calls[-1]["messages"][0]["role"] == "system":
                    if on_delta:
                        on_delta("Тишина")
                    return "Тишина", False
                if "characters" in content:
                    return json.dumps(
                        {
                            "equipment": "",
                            "appearance": "",
                            "stats": {},
                            "characters": [
                                {
                                    "name": "Смотритель",
                                    "description": "Вернётся к воротам.",
                                    "triggers": ["смотритель"],
                                    "returns": True,
                                    "conflict": False,
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ), False
                return '{"needed": true, "name": "Восприятие", "dc": 10}', False

            adventure.roll_d20 = lambda: 14
            set_model_token_scale(0.8)
            session._api_post = post
            session._read_response = read
            blocked = client.post("/api/turn", json={"text": "прислушаться"})
            assert blocked.status_code == 409
            assert blocked.json()["detail"] == "hero"
            assert calls == []

            assert client.put(
                "/api/settings",
                json={"sandbox_hero": False, "sandbox_npc": False},
            ).status_code == 200
            assert client.post("/api/turn", json={"text": "прислушаться"}).status_code == 200
            _wait_idle(client)
            kinds = [
                "narration" if item["messages"][0]["role"] == "system" else "side"
                for item in calls
            ]
            assert kinds == ["side", "narration"]
            assert "14" in calls[1]["messages"][-1]["content"]
            assert "Смотритель" not in [card["title"] for card in client.get("/api/cards").json()["cards"]]

            calls.clear()
            assert client.put(
                "/api/settings",
                json={"sandbox_d20": False, "sandbox_hero": True, "sandbox_npc": True},
            ).status_code == 200
            assert client.put("/api/hero", json={"name": "Мира"}).status_code == 200
            assert client.post("/api/turn", json={"text": "осмотреться"}).status_code == 200
            _wait_idle(client)
            titles = [card["title"] for card in client.get("/api/cards").json()["cards"]]
            assert "Смотритель" in titles
            assert _names(client.get("/api/worlds").json()) == ["Camp"]

            calls.clear()
            assert client.put(
                "/api/settings",
                json={"sandbox_d20": False, "sandbox_hero": False, "sandbox_npc": False},
            ).status_code == 200
            set_model_token_scale(0.8)
            assert client.post("/api/turn", json={"text": "ждать"}).status_code == 200
            _wait_idle(client)
            assert len(calls) == 1
            assert calls[0]["messages"][0]["role"] == "system"
    finally:
        set_model_token_scale(1.0)
    print("OK  три флага песочницы включают те же механики и не меняют список миров")



def _tiny_png():
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def _sd_workflow():
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative", "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1,
                "steps": 20,
                "cfg": 7,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "scene", "images": ["8", 0]}},
    }


def test_comfy_prompt_injection_and_a1111_payload():
    import base64
    from unittest.mock import patch

    from dungeon import image_gen

    source = _sd_workflow()
    updated, report = image_gen.apply_prompts(source, "a knight", "blurry", seed=42)
    assert source["6"]["inputs"]["text"] == "old positive"
    assert updated["6"]["inputs"]["text"] == "a knight"
    assert updated["7"]["inputs"]["text"] == "blurry"
    assert updated["3"]["inputs"]["seed"] == 42
    assert updated["3"]["inputs"]["steps"] == 20
    assert updated["4"]["inputs"]["ckpt_name"] == "model.safetensors"
    assert updated["5"]["inputs"]["width"] == 512
    assert updated["9"]["inputs"]["filename_prefix"] == "scene"
    assert ("6", "text") in report["written"]
    assert ("7", "text") in report["written"]

    flux = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux.safetensors"}},
        "9": {"class_type": "CLIPLoader", "inputs": {"clip_name": "clip.safetensors", "type": "flux"}},
        "2": {
            "class_type": "CLIPTextEncodeFlux",
            "inputs": {"clip_l": "old l", "t5xxl": "old t5", "guidance": 3.5, "clip": ["9", 0]},
        },
        "3": {"class_type": "FluxGuidance", "inputs": {"guidance": 3.5, "conditioning": ["2", 0]}},
        "5": {"class_type": "RandomNoise", "inputs": {"noise_seed": 5}},
        "7": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["3", 0]}},
    }
    flux_out, _flux_report = image_gen.apply_prompts(flux, "river", "blur", seed=7)
    assert flux_out["2"]["inputs"]["clip_l"] == "river"
    assert flux_out["2"]["inputs"]["t5xxl"] == "river"
    assert flux_out["2"]["inputs"]["guidance"] == 3.5
    assert flux_out["5"]["inputs"]["noise_seed"] == 7
    assert flux_out["1"]["inputs"]["unet_name"] == "flux.safetensors"

    try:
        image_gen.coerce_workflow({"nodes": [], "links": []})
        raise AssertionError("ui workflow accepted")
    except image_gen.ImageGenError as exc:
        assert exc.code == "ui_workflow"
    try:
        image_gen.load_workflow(ROOT / "workflows" / "missing-scene.json")
        raise AssertionError("missing workflow accepted")
    except image_gen.ImageGenError as exc:
        assert exc.code == "missing_workflow"

    real = ROOT / "workflows" / "scene_api.json"
    if real.is_file():
        raw = json.loads(real.read_text(encoding="utf-8"))
        coerced = image_gen.coerce_workflow(raw)
        before = json.loads(json.dumps(coerced))
        changed, real_report = image_gen.apply_prompts(coerced, "POSITIVE_MARK", "NEGATIVE_MARK", seed=11)
        written = set(real_report["written"])
        seeds = set(real_report["seeds"])
        assert real_report["positive_nodes"]
        for node_id, node in before.items():
            assert changed[node_id]["class_type"] == node["class_type"]
            for key, value in (node.get("inputs") or {}).items():
                if (node_id, key) in written or (node_id, key) in seeds:
                    continue
                assert changed[node_id]["inputs"][key] == value

    png = _tiny_png()
    calls = []

    class Resp:
        def __init__(self, payload=None, content=b"", status=200):
            self._payload = {} if payload is None else payload
            self.content = content
            self.status_code = status
            self.text = ""

        def json(self):
            return self._payload

    def post(url, json=None, timeout=None):
        calls.append((url, json))
        return Resp({"images": [base64.b64encode(png).decode()]})

    with patch("dungeon.image_gen.requests.post", post):
        data = image_gen.generate_a1111("http://127.0.0.1:7860", "knight", "blur", 1024, 1024, 28, None)
    assert data == png
    assert calls[0][0].endswith("/sdapi/v1/txt2img")
    assert calls[0][1]["prompt"] == "knight"
    assert calls[0][1]["negative_prompt"] == "blur"
    assert calls[0][1]["width"] == 1024
    assert calls[0][1]["steps"] == 28

    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "scene_api.json"
        path.write_text(json.dumps(_sd_workflow()), encoding="utf-8")
        posted = {}

        def post_comfy(url, json=None, timeout=None):
            posted["body"] = json
            return Resp({"prompt_id": "abc"})

        def get_comfy(url, params=None, timeout=None):
            if str(url).endswith("/history/abc"):
                return Resp(
                    {
                        "abc": {
                            "outputs": {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}},
                            "status": {"completed": True, "status_str": "success"},
                        }
                    }
                )
            assert params["filename"] == "a.png"
            return Resp(content=png)

        with patch("dungeon.image_gen.requests.post", post_comfy), patch("dungeon.image_gen.requests.get", get_comfy):
            downloaded = image_gen.generate_comfy("http://127.0.0.1:8188", path, "a knight", "blurry", None)
        assert downloaded == png
        sent = posted["body"]["prompt"]
        assert sent["6"]["inputs"]["text"] == "a knight"
        assert sent["7"]["inputs"]["text"] == "blurry"
        assert sent["5"]["inputs"]["width"] == 512
        assert sent["3"]["inputs"]["seed"] != 1
    print("OK  промпт попадает в граф ComfyUI и в запрос Automatic1111")


def test_scene_image_api():
    import tempfile
    from unittest.mock import patch

    from dungeon import image_gen

    png = _tiny_png()
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        saved = client.put(
            "/api/settings",
            json={
                "image_backend": "comfy",
                "comfy_url": "http://127.0.0.1:9000/",
                "comfy_workflow": "workflows/scene_api.json",
                "a1111_url": "not a url",
                "image_width": 1000,
                "image_height": 770,
                "image_steps": 0,
                "image_auto": True,
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["image_backend"] == "comfy"
        assert body["comfy_url"] == "http://127.0.0.1:9000"
        assert body["a1111_url"] == "http://127.0.0.1:7860"
        assert body["comfy_workflow"] == "scene_api.json"
        assert body["image_width"] == 1000
        assert body["image_height"] == 768
        assert body["image_steps"] == 1
        assert body["image_auto"] is True
        assert body["image_send_negative"] is True
        stored = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
        assert stored["image_backend"] == "comfy"
        assert stored["image_auto"] is True
        assert client.put("/api/settings", json={"image_backend": "midjourney"}).json()["image_backend"] == "off"
        assert client.put("/api/settings", json={"image_backend": "a1111", "image_auto": False}).status_code == 200

        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        assert (tmp / "Camp" / "img_bib").is_dir()
        assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 200
        refused = client.post("/api/scene/image")
        assert refused.status_code == 200, refused.text
        assert refused.json()["ok"] is False

        session.last_scene = {"prompt": "knight", "negative": "blur", "style": "sd", "look": "none"}
        with patch("dungeon.image_gen.generate", return_value=png):
            started = client.post("/api/scene/image")
            assert started.status_code == 200, started.text
            assert started.json()["ok"] is True
            scene = _wait_scene_image(client)
        assert scene["prompt"] == "knight"
        assert scene["image"].startswith("/api/scene/image?name=")
        picture = client.get(scene["image"])
        assert picture.status_code == 200
        assert picture.content == png
        assert (tmp / "Camp" / "img_bib").is_dir()
        assert not (tmp / "Camp" / "images").exists()
        library = client.get("/api/images").json()["images"]
        assert library and library[0]["name"] in scene["image"]
        edited = client.put("/api/scene/text", json={"prompt": "edited knight", "negative": "dust"})
        assert edited.status_code == 200, edited.text
        assert edited.json()["scene"]["prompt"] == "edited knight"
        assert client.get("/api/scene").json()["scene"]["negative"] == "dust"
        seen = {}

        def grab(_spec, prompt, negative, _cancel):
            seen["prompt"] = prompt
            seen["negative"] = negative
            return png

        with patch("dungeon.image_gen.generate", side_effect=grab):
            sent = None
            for _ in range(20):
                sent = client.post("/api/scene/image", json={"prompt": "from button", "negative": "soft"})
                if sent.status_code != 409:
                    break
                time.sleep(0.05)
            assert sent.status_code == 200, sent.text
            scene = _wait_scene_image(client)
        assert seen["prompt"] == "from button"
        assert seen["negative"] == "soft"
        assert scene["prompt"] == "from button"
        turned = client.put("/api/settings", json={"image_send_negative": False})
        assert turned.status_code == 200, turned.text
        assert turned.json()["image_send_negative"] is False
        with patch("dungeon.image_gen.generate", side_effect=grab):
            sent = None
            for _ in range(20):
                sent = client.post("/api/scene/image", json={"prompt": "from button", "negative": "soft"})
                if sent.status_code != 409:
                    break
                time.sleep(0.05)
            assert sent.status_code == 200, sent.text
            scene = _wait_scene_image(client)
        assert seen["negative"] == ""
        assert scene["negative"] == "soft"
        current_name = scene["image"].split("name=", 1)[-1]
        removed = client.delete(f"/api/images/{current_name}")
        assert removed.status_code == 200, removed.text
        assert all(item["name"] != current_name for item in removed.json()["images"])
        assert client.get("/api/scene/image", params={"name": current_name}).status_code == 404
        assert client.get("/api/scene").json()["scene"]["image"] == ""
        assert client.delete("/api/images/../settings.json").status_code in (404, 405, 400)
        flows = config.WORKFLOWS_DIR
        (flows / "other.json").write_text("{}", encoding="utf-8")
        (flows / "notes.txt").write_text("no", encoding="utf-8")
        (tmp / "outside.json").write_text("{}", encoding="utf-8")
        assert client.get("/api/workflows").json()["workflows"] == ["other.json"]
        assert client.get("/api/scene/image", params={"name": "../settings.json"}).status_code == 404
        assert client.get("/api/scene/image", params={"name": "settings.json"}).status_code == 404
        (tmp / "secret.png").write_bytes(png)
        assert client.get("/api/scene/image", params={"name": "secret.png"}).status_code == 404

        class Resp:
            status_code = 200
            text = ""

            def json(self):
                return {}

        with patch("dungeon.image_gen.requests.get", return_value=Resp()):
            tested = client.post(
                "/api/image/test",
                json={"image_backend": "comfy", "comfy_url": "http://127.0.0.1:8188"},
            )
        assert tested.status_code == 200, tested.text
        assert tested.json()["ok"] is True

        spec = session.image_spec()
        spec["image_backend"] = "comfy"
        try:
            image_gen.generate(spec, "knight", "", None)
            raise AssertionError("missing workflow accepted")
        except image_gen.ImageGenError as exc:
            assert exc.code == "missing_workflow"

        history = ["Игрок: осмотреться", "Мастер: Тропа вывела к реке."]
        (tmp / "Camp" / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 200
        session.last_scene = None
        assert client.put("/api/settings", json={"image_backend": "a1111", "image_auto": True}).status_code == 200

        def post(payload, **_kwargs):
            return _Response()

        def finish_read(_response, _key, on_delta=None):
            return '{"prompt": "a river", "negative_prompt": "blur"}', False

        session._api_post = post
        session._read_response = finish_read
        with patch("dungeon.image_gen.generate", return_value=png) as generate:
            assert client.post("/api/scene", json={"image_prompt_style": "sd", "image_look": "none"}).status_code == 200
            scene = _wait_scene_image(client)
        assert generate.called
        assert "a river" in scene["prompt"]
        assert scene["image"].startswith("/api/scene/image?name=")
        assert client.get(scene["image"]).content == png
    print("OK  картинка сцены сохраняется в мире и не читается снаружи папки")


def test_scene_wish_changes_only_the_scene_prompt():
    import tempfile

    class _Chunks:
        def __init__(self, raw):
            self._raw = raw

        def raise_for_status(self):
            return None

        def close(self):
            return None

        def json(self):
            return {}

        def iter_content(self, chunk_size=None):
            yield self._raw

    def stream(lines):
        return _Chunks(("\n".join(lines) + "\n").encode("utf-8"))

    def scene_text(payload):
        message = payload["messages"][0]
        if message.get("role") == "user" and "текущей сцены" in message.get("content", ""):
            return message["content"]
        return ""

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.put(
            "/api/settings",
            json={"summary_enabled": False, "memory_enabled": False, "image_auto": False},
        ).status_code == 200
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        history = ["Игрок: осмотреться", "Мастер: Тропа вывела к реке."]
        cards = {
            "cards": [
                {
                    "id": "lamp",
                    "title": "Старый фонарь",
                    "triggers": ["wishlamp"],
                    "description": "Медный фонарь висит у двери.",
                }
            ]
        }
        (tmp / "Camp" / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        (tmp / "Camp" / "story_cards.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
        assert client.post("/api/worlds/open", json={"name": "Camp"}).status_code == 200
        strings = client.get("/api/strings").json()
        assert strings["scene.wish"] == "Что показать"
        assert "prompt.scene_wish" not in {
            item["key"] for group in client.get("/api/settings").json()["prompts"] for item in group["prompts"]
        }

        calls = []

        def post(payload, **_kwargs):
            calls.append(payload)
            content = scene_text(payload)
            if content:
                raw = json.dumps({"prompt": "river path", "negative_prompt": "blurry"}, ensure_ascii=False)
                line = "data: " + json.dumps({"choices": [{"delta": {"content": raw}}]}, ensure_ascii=False)
                return stream([line, "data: [DONE]"])
            if payload.get("max_tokens") == 1:
                return stream(["data: [DONE]"])
            return stream(['data: {"choices":[{"delta":{"content":"Тишина у реки."}}]}', "data: [DONE]"])

        def wait_done(expected):
            deadline = time.time() + 3
            while time.time() < deadline:
                if len(calls) >= expected and not client.get("/api/state").json()["status"]["busy"]:
                    return
                time.sleep(0.05)
            raise AssertionError(f"ожидалось {expected} запросов, пришло {len(calls)}")

        session._api_post = post
        assert client.post("/api/scene", json={"image_prompt_style": "sd", "image_look": "none"}).status_code == 200
        wait_done(1)
        assert client.post("/api/scene", json={"wish": "   "}).status_code == 200
        wait_done(2)
        plain = scene_text(calls[0])
        blank = scene_text(calls[1])
        assert plain and plain == blank
        assert "Пожелание игрока" not in plain
        assert "Старый фонарь" not in plain
        assert "wishlamp" not in plain

        wish = "крупный план wishlamp у двери"
        assert client.post("/api/scene", json={"wish": wish}).status_code == 200
        wait_done(3)
        asked = scene_text(calls[2])
        assert "Пожелание игрока к кадру" in asked
        assert wish in asked
        assert "Старый фонарь" in asked
        assert "Медный фонарь висит у двери." in asked
        view = client.get("/api/scene").json()
        assert view["wish"] == wish
        assert view["scene"]["prompt"] == "river path"
        assert wish not in view["scene"]["prompt"]

        long_wish = ("А" * 2000) + "ХВОСТ"
        assert client.post("/api/scene", json={"wish": long_wish}).status_code == 200
        wait_done(4)
        stored = client.get("/api/scene").json()["wish"]
        assert stored == "А" * 2000
        assert "ХВОСТ" not in scene_text(calls[3])
        assert stored in scene_text(calls[3])

        calls.clear()
        assert client.post("/api/turn", json={"text": "идти вдоль реки"}).status_code == 200
        deadline = time.time() + 3
        while time.time() < deadline:
            state = client.get("/api/state").json()
            if any(row["text"] == "Тишина у реки." for row in state["history"]) and not state["status"]["busy"]:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("ход не завершился")
        spoken = "\n".join(
            message.get("content", "")
            for payload in calls
            for message in payload.get("messages", [])
        )
        assert "крупный план" not in spoken
        assert "ХВОСТ" not in spoken
        assert "А" * 200 not in spoken
        camp = tmp / "Camp"
        for name in ("history.json", "summary.txt", "memory.json", "plot_basics.txt"):
            path = camp / name
            if path.exists():
                assert "крупный план" not in path.read_text(encoding="utf-8")
        assert "крупный план" not in (tmp / "settings.json").read_text(encoding="utf-8")
        print("OK  пустое пожелание не меняет промпт сцены, заполненное остаётся только в этом запросе")


def test_reasoning_stays_out_of_the_story():
    import tempfile

    import dungeon.api_stream as api_stream
    from dungeon.api_stream import reasoning_effort_name
    from dungeon.text_utils import StreamThinkFilter

    assert reasoning_effort_name(512) == "low"
    assert reasoning_effort_name(513) == "medium"
    assert reasoning_effort_name(2048) == "medium"
    assert reasoning_effort_name(2049) == "high"
    think = StreamThinkFilter()
    assert think.feed("<thi") == ""
    assert think.feed("nk>секрет</think>Ответ") == "Ответ"
    assert think.take_reasoning() == "секрет"

    class _Chunks:
        def __init__(self, raw):
            self._raw = raw

        def raise_for_status(self):
            return None

        def close(self):
            return None

        def json(self):
            return {}

        def iter_content(self, chunk_size=None):
            yield self._raw

    def stream(lines):
        return _Chunks(("\n".join(lines) + "\n").encode("utf-8"))

    def wait_idle(client, needle):
        deadline = time.time() + 3
        state = {}
        while time.time() < deadline:
            state = client.get("/api/state").json()
            text = "\n".join(row["text"] for row in state["history"])
            if needle in text and not state["status"]["busy"]:
                return state
            time.sleep(0.05)
        raise AssertionError(needle)

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        _use_tmp(tmp)
        app = create_app()
        session = app.state.session
        client = TestClient(app)
        assert client.post("/api/worlds", json={"name": "Camp"}).status_code == 200
        opened = client.get("/api/settings")
        assert opened.json()["reasoning"] is False
        assert opened.json()["reasoning_max_tokens"] == 1024
        clamped = client.put("/api/settings", json={"reasoning_max_tokens": 10, "summary_enabled": False, "memory_enabled": False})
        assert clamped.status_code == 200, clamped.text
        assert clamped.json()["reasoning_max_tokens"] == 64
        assert client.put("/api/settings", json={"reasoning_max_tokens": 999999}).json()["reasoning_max_tokens"] == 32768

        off = session._api_payload(messages=[{"role": "user", "content": "ход"}], max_tokens=300, stream=True)
        assert off["enable_thinking"] is False
        assert off["no_thinking"] is True
        assert off["reasoning"]["effort"] == "none"
        assert off["reasoning"]["exclude"] is True
        assert off["max_tokens"] == 300
        assert "max_completion_tokens" not in off

        class _Code:
            def __init__(self, code):
                self.status_code = code
                self.ok = 200 <= code < 300

            def close(self):
                return None

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise api_stream.requests.HTTPError("bad")

        posted = []

        def fake_post(_url, json=None, headers=None, **_kwargs):
            posted.append(json)
            return _Code(400 if len(posted) == 1 else 200)

        original = api_stream.requests.post
        api_stream.requests.post = fake_post
        try:
            session.reasoning_max_tokens = 1500
            allowed = session._api_payload(
                messages=[{"role": "user", "content": "ход"}],
                max_tokens=300,
                stream=True,
                allow_reasoning=True,
            )
            session._api_post(allowed, stream=True)
        finally:
            api_stream.requests.post = original
            session.reasoning_max_tokens = 1024
        assert posted[0]["enable_thinking"] is True
        assert posted[0]["thinking"] == {"type": "enabled"}
        assert posted[0]["reasoning"]["max_tokens"] == 1500
        assert posted[0]["reasoning"]["effort"] == "medium"
        assert posted[0]["reasoning"]["exclude"] is False
        assert "no_thinking" not in posted[0]
        assert posted[0]["max_tokens"] == 1800
        assert posted[0]["max_completion_tokens"] == 1800
        assert "<think>" not in (posted[0].get("stop") or [])
        assert "enable_thinking" not in posted[1]
        assert posted[1].get("reasoning_effort") != "none"
        assert posted[1]["max_tokens"] == 1800

        calls = []

        def post(payload, **_kwargs):
            calls.append(payload)
            if payload.get("max_tokens") == 1:
                return stream(["data: [DONE]"])
            return stream(
                [
                    'data: {"choices":[{"delta":{"content":"<think>тайна</think>Ответ готов."}}]}',
                    "data: [DONE]",
                ]
            )

        session._api_post = post
        assert client.post("/api/turn", json={"text": "осмотреться"}).status_code == 200
        quiet = wait_idle(client, "Ответ готов")
        story = "\n".join(row["text"] for row in quiet["history"])
        assert "тайна" not in story
        assert all(not row.get("reasoning") for row in quiet["history"])
        turn = next(item for item in calls if item.get("messages") and item["messages"][0].get("role") == "system")
        assert turn["enable_thinking"] is False
        assert turn["no_thinking"] is True
        assert "<think>" in turn["stop"]
        assert "без размышлений" in turn["messages"][0]["content"]
        assert turn["max_tokens"] == 300

        saved = client.put(
            "/api/settings",
            json={
                "reasoning": True,
                "reasoning_max_tokens": 1500,
                "model": "thinker",
                "active_api_preset": "Thinker",
                "api_presets": [
                    {
                        "name": "Thinker",
                        "api_url": "http://localhost:1234/v1/chat/completions",
                        "api_key": "",
                        "model": "thinker",
                        "reasoning": True,
                        "reasoning_max_tokens": 1500,
                    },
                    {
                        "name": "Plain",
                        "api_url": "http://localhost:9/v1/chat/completions",
                        "api_key": "",
                        "model": "plain",
                        "reasoning": False,
                        "reasoning_max_tokens": 256,
                    },
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["reasoning"] is True
        assert saved.json()["reasoning_max_tokens"] == 1500
        thinker = next(item for item in saved.json()["api_presets"] if item["name"] == "Thinker")
        assert thinker["reasoning"] is True
        assert thinker["reasoning_max_tokens"] == 1500
        stored = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
        assert stored["api_presets"][0]["reasoning"] is True
        assert stored["reasoning_max_tokens"] == 1500

        calls.clear()

        def post_on(payload, **_kwargs):
            calls.append(payload)
            if payload.get("max_tokens") == 1:
                return stream(["data: [DONE]"])
            if payload.get("messages", [{}])[0].get("role") != "system":
                return stream(['data: {"choices":[{"delta":{"content":"Кратко."}}]}', "data: [DONE]"])
            return stream(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"сначала проверю дверь"}}]}',
                    'data: {"choices":[{"delta":{"content":"<think>ещё мысль</think>Дверь открыта."}}]}',
                    "data: [DONE]",
                ]
            )

        session._api_post = post_on
        assert client.post("/api/turn", json={"text": "открыть дверь"}).status_code == 200
        told = wait_idle(client, "Дверь открыта")
        reply = next(row for row in told["history"] if row["text"] == "Дверь открыта.")
        assert "сначала проверю дверь" in reply["reasoning"]
        assert "ещё мысль" in reply["reasoning"]
        assert "сначала проверю дверь" not in reply["text"]
        assert "<think>" not in reply["text"]
        notes = json.loads((tmp / "Camp" / "reasoning.json").read_text(encoding="utf-8"))
        assert notes[str(reply["index"])]["text"].count("мысль") == 1
        spoken = next(item for item in calls if item.get("messages") and item["messages"][0].get("role") == "system")
        assert spoken["enable_thinking"] is True
        assert "no_thinking" not in spoken
        assert "<think>" not in spoken["stop"]
        assert "без размышлений" not in spoken["messages"][0]["content"]
        assert spoken["max_tokens"] == 300 + 1500
        assert spoken["reasoning"]["max_tokens"] == 1500
        assert "сначала проверю дверь" not in spoken["messages"][0]["content"]

        assert client.post("/api/undo").status_code == 200
        after_undo = client.get("/api/state").json()
        assert all(row.get("text") != "Дверь открыта." for row in after_undo["history"])
        assert "сначала проверю дверь" not in (tmp / "Camp" / "reasoning.json").read_text(encoding="utf-8")

        def post_hidden(payload, **_kwargs):
            calls.append(payload)
            if payload.get("messages", [{}])[0].get("role") != "system":
                return stream(['data: {"choices":[{"delta":{"content":"Кратко."}}]}', "data: [DONE]"])
            return stream(
                [
                    'data: {"choices":[{"delta":{"content":"Тишина."}}]}',
                    'data: {"usage":{"prompt_tokens":4,"completion_tokens":12,"completion_tokens_details":{"reasoning_tokens":9}}}',
                    "data: [DONE]",
                ]
            )

        calls.clear()
        session._api_post = post_hidden
        assert client.post("/api/turn", json={"text": "прислушаться"}).status_code == 200
        hidden = wait_idle(client, "Тишина")
        quiet_row = next(row for row in hidden["history"] if row["text"] == "Тишина.")
        assert quiet_row["reasoning_hidden"] is True
        assert "reasoning" not in quiet_row
        follow = next(item for item in calls if item.get("messages") and item["messages"][0].get("role") == "system")
        assert "сначала проверю дверь" not in follow["messages"][0]["content"]
        assert "ещё мысль" not in follow["messages"][0]["content"]

        def post_summary(payload, **_kwargs):
            calls.append(payload)
            return stream(['data: {"choices":[{"delta":{"content":"Кратко."}}]}', "data: [DONE]"])

        calls.clear()
        session._api_post = post_summary
        assert client.post("/api/summary").status_code == 200
        deadline = time.time() + 3
        while time.time() < deadline and client.get("/api/state").json()["status"]["busy"]:
            time.sleep(0.05)
        assert calls
        assert all(item["enable_thinking"] is False and item["no_thinking"] is True for item in calls)
        assert all(item.get("max_tokens") != 300 + 1500 for item in calls)

        plain = client.post("/api/presets/activate", json={"name": "Plain"})
        assert plain.status_code == 200, plain.text
        applied = client.get("/api/settings").json()
        assert applied["reasoning"] is False
        assert applied["reasoning_max_tokens"] == 256
        assert applied["model"] == "plain"
        again = client.post("/api/presets/activate", json={"name": "Thinker"})
        assert again.status_code == 200, again.text
        restored = client.get("/api/settings").json()
        assert restored["reasoning"] is True
        assert restored["reasoning_max_tokens"] == 1500
    print("OK  рассуждение отделено от рассказа и выключается вместе с конфигурацией")


def _wait_scene_image(client, timeout=4):
    deadline = time.time() + timeout
    scene = None
    while time.time() < deadline:
        scene = client.get("/api/scene").json()["scene"]
        if scene and scene.get("image") and not scene.get("image_pending"):
            return scene
        time.sleep(0.05)
    raise AssertionError(f"картинка не появилась: {scene}")


if __name__ == "__main__":
    test_file_save_and_summary_threshold()
    test_history_opens_on_the_tail()
    test_turn_and_stop()
    test_direction_turn()
    test_player_line_is_visible_before_the_reply()
    test_reply_tokens_follow_model_usage()
    test_resume_sees_partial_reply_and_finished_jobs()
    test_state_is_not_cached()
    test_context_scale_follows_model_prompt()
    test_first_turn_learns_scale_before_packing()
    test_summary_learns_scale_before_packing()
    test_lan_setting_roundtrip()
    test_world_export_and_import()
    test_bind_modes()
    test_preset_switch_updates_connection()
    test_model_switch_keeps_summary_bar_scaled()
    test_finished_reply_is_settled_before_processing_ends()
    test_world_language_marks_and_english_token_scale()
    test_prompt_limits_and_scene_look()
    test_world_guards_settings_and_startup()
    test_markup_stays_text()
    test_world_paths_and_hidden_key()
    test_overlapping_jobs_start_once()
    test_modes_keep_worlds_in_separate_folders()
    test_d20_discards_unknown_difficulty_and_uses_a_known_roll()
    test_d20_prompt_names_each_outcome()
    test_named_foe_gets_a_card_and_unnamed_guard_does_not()
    test_sandbox_flags_enable_mechanics_without_moving_worlds()
    test_comfy_prompt_injection_and_a1111_payload()
    test_scene_image_api()
    test_scene_wish_changes_only_the_scene_prompt()
    test_reasoning_stays_out_of_the_story()
    print("ALL WEB TESTS PASSED")
