"""Локальный сервер веб-версии. Слушает только этот компьютер."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dungeon.config import ensure_workflows_dir, list_workflow_files
from dungeon.storage import CorruptedDataError
from web.netbind import default_route_ipv4, network_addresses
from web.session import GameSession


def _static_dir():
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        for candidate in (root / "web" / "static", root / "static"):
            if candidate.is_dir():
                return candidate
        return root / "web" / "static"
    return Path(__file__).resolve().parent / "static"


STATIC_DIR = _static_dir()
WEB_PORT = 8765
# Скрипты и стили только со своего адреса: чужой сайт не может вставить разметку.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


def app_icon_path():
    """Файл иконки, который пользователь положил в папку проекта."""
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        root = Path(__file__).resolve().parent.parent
    for candidate in (root / "AIDM_ICO.ico", STATIC_DIR / "AIDM_ICO.ico"):
        if candidate.is_file():
            return candidate
    return None


def local_ipv4s():
    """Адрес Wi-Fi, через который компьютер выходит наружу."""
    primary = default_route_ipv4()
    if primary:
        return [primary]
    return network_addresses()["lan"][:1]


def create_app(session: GameSession | None = None, bind_host: str = "127.0.0.1") -> FastAPI:
    ensure_workflows_dir()
    app = FastAPI(title="AIDM Web")

    @app.middleware("http")
    async def disable_http_cache(request, call_next):
        # Телефон иначе запоминает первый кусок /api/state и показывает его
        # вместо уже дописанного ответа.
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        return response

    app.state.session = session or GameSession()
    app.state.bind_host = bind_host
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def game() -> GameSession:
        return app.state.session

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico")
    def favicon():
        icon = app_icon_path()
        if icon is None:
            raise HTTPException(status_code=404)
        return FileResponse(icon, media_type="image/x-icon")

    @app.get("/api/state")
    def state(start: int | None = None):
        return game().state_view(start)

    @app.get("/api/history")
    def history(before: int):
        return game().history_page(before)

    @app.get("/api/strings")
    def strings():
        return game().strings_view()

    @app.get("/api/events")
    async def events():
        session_obj = game()
        sub = session_obj.subscribe()

        async def stream():
            try:
                while True:
                    try:
                        event = await asyncio.to_thread(sub.get, True, 15)
                    except Exception:
                        yield ": ping\n\n"
                        continue
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            finally:
                session_obj.unsubscribe(sub)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/worlds")
    def worlds():
        return {"worlds": game().state_view()["worlds"], "current": game().world_name}

    @app.get("/api/worlds/template")
    def world_template():
        return game().world_template()

    @app.post("/api/toggles/summary")
    def toggle_summary():
        return game().toggle_summary()

    @app.post("/api/toggles/memory")
    def toggle_memory():
        return game().toggle_memory()

    @app.post("/api/worlds")
    def create_world(payload: dict):
        try:
            name = game().create_world(payload.get("name", ""), payload.get("files"), payload.get("cards"))
        except ValueError:
            raise HTTPException(400, "bad name")
        except FileExistsError:
            raise HTTPException(409, "exists")
        except RuntimeError:
            raise HTTPException(409, "busy")
        return {"name": name, "state": game().state_view()}

    @app.post("/api/worlds/open")
    def open_world(payload: dict):
        try:
            game().load_world(payload.get("name", ""))
        except FileNotFoundError:
            raise HTTPException(404, "missing")
        except ValueError:
            raise HTTPException(400, "bad name")
        except RuntimeError:
            raise HTTPException(409, "busy")
        except CorruptedDataError:
            notice = game().notices[-1] if game().notices else "corrupt"
            raise HTTPException(409, notice)
        except Exception as exc:
            raise HTTPException(409, str(exc))
        return game().state_view()

    @app.get("/api/worlds/{name}/export")
    def export_world(name: str):
        try:
            payload, cleaned = game().export_world_bytes(name)
        except FileNotFoundError:
            raise HTTPException(404, "missing")
        except RuntimeError:
            raise HTTPException(409, "busy")
        except ValueError:
            raise HTTPException(400, "bad name")
        filename = quote(f"{cleaned}.zip")
        return Response(
            payload,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=\"world.zip\"; filename*=UTF-8''{filename}"},
        )

    @app.post("/api/worlds/import")
    async def import_world(request: Request, name: str = ""):
        try:
            imported = game().import_world_bytes(name, await request.body())
        except RuntimeError:
            raise HTTPException(409, "busy")
        except FileExistsError:
            raise HTTPException(409, "exists")
        except ValueError:
            raise HTTPException(400, "bad archive")
        except Exception as exc:
            raise HTTPException(409, str(exc))
        return {"name": imported, "state": game().state_view()}

    @app.delete("/api/worlds/{name}")
    def delete_world(name: str):
        try:
            removed = game().delete_world(name)
        except ValueError:
            raise HTTPException(400, "bad name")
        except RuntimeError:
            raise HTTPException(409, "busy")
        if not removed:
            raise HTTPException(404, "missing")
        return game().state_view()

    @app.post("/api/mode")
    def set_mode(payload: dict):
        try:
            return game().set_play_mode(payload.get("play_mode", ""))
        except RuntimeError:
            raise HTTPException(409, "busy")

    @app.get("/api/hero")
    def hero():
        if not game().current_world_path:
            raise HTTPException(409, "no world")
        return {"hero": game().hero}

    @app.put("/api/hero")
    def save_hero(payload: dict):
        try:
            game().save_hero_card(payload)
        except ValueError:
            raise HTTPException(400, "hero")
        except RuntimeError:
            raise HTTPException(409, "no world")
        return game().state_view()

    @app.post("/api/hero/stats")
    def hero_stats(payload: dict):
        if not game().current_world_path:
            raise HTTPException(409, "no world")
        return game().resolve_pending_stats(bool(payload.get("accept")))

    @app.post("/api/turn")
    def turn(payload: dict):
        if game().hero_required_missing():
            raise HTTPException(409, "hero")
        started = game().submit_turn(payload.get("text", ""), payload.get("direction", ""))
        if not started:
            raise HTTPException(409, "busy or no world")
        return {"ok": True}

    @app.post("/api/stop")
    def stop():
        return {"stopped": game().stop()}

    @app.post("/api/undo")
    def undo():
        if not game().undo():
            raise HTTPException(409, "cannot undo")
        return game().state_view()

    @app.post("/api/regenerate")
    def regenerate():
        if game().hero_required_missing():
            raise HTTPException(409, "hero")
        if not game().regenerate():
            raise HTTPException(409, "cannot regenerate")
        return {"ok": True}

    @app.post("/api/history/{index}")
    def edit_history(index: int, payload: dict):
        if not game().edit_message(index, payload.get("text", "")):
            raise HTTPException(409, "cannot edit")
        return game().state_view()

    @app.post("/api/summary")
    def summary():
        if not game().current_world_path:
            raise HTTPException(409, "no world")
        if not game().summarize():
            raise HTTPException(409, "busy")
        return {"ok": True}

    @app.get("/api/files")
    def files():
        if not game().current_world_path:
            raise HTTPException(409, "no world")
        return game().world_files()

    @app.put("/api/files/{name}")
    def save_file(name: str, payload: dict):
        try:
            saved = game().save_world_file(name, payload.get("content", ""))
        except RuntimeError:
            raise HTTPException(409, "busy")
        if not saved:
            raise HTTPException(404, "unknown file")
        return {"ok": True, "fill": game().fill_view()}

    @app.get("/api/cards")
    def cards():
        return game().story_cards

    @app.put("/api/cards")
    def save_cards(payload: dict):
        try:
            saved = game().save_cards(payload)
        except RuntimeError:
            raise HTTPException(409, "busy")
        if not saved:
            raise HTTPException(409, "no world")
        return game().story_cards

    @app.post("/api/cards/describe")
    def describe_card(payload: dict):
        if not game().describe_card(payload.get("title", ""), payload.get("description", "")):
            raise HTTPException(409, "busy or no world")
        return {"ok": True}

    @app.get("/api/memory")
    def memory():
        return game().memory_view()

    @app.get("/api/network")
    def network():
        port = WEB_PORT
        listening = app.state.bind_host
        addresses = network_addresses()
        return {
            "lan_access": bool(game().lan_access),
            "bind_mode": game().bind_mode,
            "listening": listening,
            "port": port,
            "local_url": f"http://127.0.0.1:{port}",
            "lan_urls": [f"http://{ip}:{port}" for ip in local_ipv4s()],
            "tailscale_urls": [f"http://{ip}:{port}" for ip in addresses["tailscale"]],
        }

    @app.get("/api/settings")
    def settings():
        return game().settings_view()

    @app.put("/api/settings")
    def save_settings(payload: dict):
        try:
            problems = game().apply_settings(payload)
        except RuntimeError:
            raise HTTPException(409, "busy")
        if problems:
            raise HTTPException(400, detail={"prompts": problems})
        return game().settings_view()

    @app.post("/api/presets/activate")
    def activate_preset(payload: dict):
        try:
            return game().activate_preset(payload.get("name", ""))
        except KeyError:
            raise HTTPException(404, "missing")
        except RuntimeError:
            raise HTTPException(409, "busy")

    @app.get("/api/prompt")
    def last_prompt():
        return {"prompt": game().prompt_view()}

    @app.post("/api/scene")
    def scene(payload: dict | None = Body(default=None)):
        if not game().current_world_path or game().is_busy():
            raise HTTPException(409, "busy or no world")
        if isinstance(payload, dict):
            game().set_scene_options(payload.get("image_prompt_style"), payload.get("image_look"))
        started = game().start_scene_prompt()
        if started:
            return {"ok": True, "notice": ""}
        if game().is_busy():
            raise HTTPException(409, "busy or no world")
        notice = game().notices[-1] if game().notices else ""
        return {"ok": False, "notice": notice}

    @app.get("/api/scene")
    def last_scene():
        return game().scene_view()

    @app.put("/api/scene/options")
    def scene_options(payload: dict):
        return game().set_scene_options(payload.get("image_prompt_style"), payload.get("image_look"))

    @app.put("/api/scene/text")
    def scene_text(payload: dict):
        if not game().current_world_path:
            raise HTTPException(409, "no world")
        return game().update_scene_text(payload.get("prompt", ""), payload.get("negative", ""))

    @app.get("/api/workflows")
    def workflows():
        return {"workflows": list_workflow_files()}

    @app.get("/api/images")
    def images():
        if not game().current_world_path:
            raise HTTPException(409, "no world")
        return game().image_library_view()

    @app.delete("/api/images/{name}")
    def delete_image(name: str):
        if not game().current_world_path:
            raise HTTPException(409, "no world")
        if not game().delete_scene_image(name):
            raise HTTPException(status_code=404, detail="missing")
        return game().image_library_view()

    @app.post("/api/scene/image")
    def scene_image_start(payload: dict | None = Body(default=None)):
        if not game().current_world_path or game().is_busy():
            raise HTTPException(409, "busy or no world")
        if isinstance(payload, dict) and ("prompt" in payload or "negative" in payload):
            game().update_scene_text(payload.get("prompt", ""), payload.get("negative", ""))
        started = game().start_scene_image()
        if started:
            return {"ok": True, "notice": ""}
        if game().is_busy():
            raise HTTPException(409, "busy or no world")
        notice = game().notices[-1] if game().notices else ""
        return {"ok": False, "notice": notice}

    @app.get("/api/scene/image")
    def scene_image(name: str | None = None):
        path = game().scene_image_path(name)
        if path is None:
            raise HTTPException(status_code=404)
        media = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media)

    @app.post("/api/image/test")
    def image_test(payload: dict | None = Body(default=None)):
        return game().test_image_connection(payload)

    return app
