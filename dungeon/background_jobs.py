import json
import re
from datetime import datetime
from threading import Thread

import requests

from .api_stream import MEMORY, SCENE, SCENE_TURNS
from .config import (
    DEFAULT_IMAGE_LOOK,
    IMAGE_LOOKS,
    apply_image_look,
    response_token_limit,
)
from .i18n import DM_PREFIX, localize_history, t
from .memory import (
    count_completed_turns,
    get_recent_turn_messages,
    get_turn_messages,
    parse_memory_index_response,
    save_memory_bank,
)
from .story_cards import format_story_cards_block, retrieve_relevant_cards


class JobsMixin:
    def start_memory_indexing(self, force=False):
        if self.memory_indexing:
            return
        if not self.memory_enabled and not force:
            return
        self.memory_indexing = True
        self._begin_operation(MEMORY)
        self.refresh_busy_state()
        Thread(target=self._run_memory_indexing_impl, args=(force,), daemon=True).start()

    def run_memory_indexing(self, force=False):
        self.root.after(0, lambda: self.start_memory_indexing(force))

    def _run_memory_indexing_impl(self, force=False):
        try:
            if not self.current_world_path:
                return

            current_turns = count_completed_turns(self.history)
            last_indexed = self.memory_bank.get("last_indexed_turn", 0)
            new_turns = current_turns - last_indexed

            if not force and new_turns < self.memory_interval:
                return

            if force and new_turns == 0:
                self.root.after(0, lambda: self.add_system_message(self.tr("msg.no_memory_turns")))
                return

            chunk_size = new_turns if force else self.memory_interval
            turn_start = last_indexed + 1
            turn_end = last_indexed + chunk_size
            messages = get_turn_messages(self.history, turn_start, turn_end)

            if not messages:
                return

            fallback_text = "\n".join(localize_history(self.language, messages))
            prompt = t(self.language, "prompt.memory_index", fragment=fallback_text)

            payload = self._api_payload(
                messages=[{"role": "user", "content": prompt + "\n\n" + t(self.language, "prompt.no_reasoning")}],
                temperature=0.2,
                max_tokens=response_token_limit(getattr(self, "response_limits", None), "prompt.memory_index"),
                stream=True,
            )
            response = self._api_post(payload, stream=True, timeout=120)
            response.raise_for_status()
            raw, cancelled = self._read_response(response, MEMORY)
            if cancelled:
                self.root.after(0, lambda: self.add_system_message(self.tr("msg.memory_stopped")))
                return
            parsed = parse_memory_index_response(raw, fallback_text)

            entry = {
                "id": f"mem_{len(self.memory_bank['entries']) + 1:03d}",
                "turn_start": turn_start,
                "turn_end": turn_end,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **parsed,
            }
            self.memory_bank["entries"].append(entry)
            self.memory_bank["last_indexed_turn"] = turn_end
            save_memory_bank(self.current_world_path, self.memory_bank)

            keys_preview = ", ".join(entry.get("keys", [])[:4]) or "—"
            self.root.after(
                0,
                lambda: self.add_system_message(
                    self.tr("msg.memory_entry", id=entry["id"], summary=entry["summary"][:80], keys=keys_preview)
                ),
            )
            self.root.after(0, self.update_memory_label)

        except requests.exceptions.ConnectionError:
            self.root.after(0, lambda: self.add_system_message(self.tr("msg.memory_offline")))
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, lambda msg=err_msg: self.add_system_message(self.tr("msg.memory_error", msg=msg)))
        finally:
            self.memory_indexing = False
            self._end_operation(MEMORY)
            self.root.after(0, self.refresh_busy_state)

    # --- Промпт изображения сцены ---------------------------------------------

    def start_scene_prompt(self):
        """Собирает контекст сцены и просит модель вернуть промпт + антипромпт."""
        if self.is_busy() or not self.current_world_path:
            return
        recent = get_recent_turn_messages(self.history, SCENE_TURNS)
        if not any(msg.startswith(DM_PREFIX) for msg in recent):
            self.add_system_message(self.tr("scene.needs_history"))
            return

        self.scene_prompt_running = True
        self._begin_operation(SCENE)
        self.refresh_busy_state()
        Thread(target=self._run_scene_prompt, daemon=True).start()

    def generate_scene_prompt(self):
        self.root.after(0, self.start_scene_prompt)

    def _scene_context(self):
        """Текст для промпта: plot_basics, последние ходы, релевантные карточки."""
        world_path = self.current_world_path
        plot_basics = ""
        for fname in ("plot_basics.txt", "ai_instructions.txt", "author_notes.txt"):
            path = world_path / fname
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    plot_basics += f"=== {fname} ===\n{content}\n"

        recent = get_recent_turn_messages(self.history, SCENE_TURNS)
        history_fragment = "\n".join(localize_history(self.language, recent))

        query = "\n".join(recent)
        wish = str(getattr(self, "scene_wish", "") or "").strip()
        if wish:
            query = f"{query}\n{wish}"
        cards = retrieve_relevant_cards(query, self.story_cards, top_k=self.memory_top_k)
        cards_block = format_story_cards_block(cards, self.language)
        return plot_basics, history_fragment, cards_block

    def _run_scene_prompt(self):
        try:
            plot_basics, history_fragment, cards_block = self._scene_context()
            style = self.image_prompt_style
            look = getattr(self, "image_look", DEFAULT_IMAGE_LOOK)
            if look not in IMAGE_LOOKS:
                look = DEFAULT_IMAGE_LOOK
            prompt = t(
                self.language,
                "prompt.scene_image",
                plot_basics=plot_basics or t(self.language, "prompt.none"),
                history_fragment=history_fragment or t(self.language, "prompt.none"),
                cards_block=cards_block or t(self.language, "prompt.none"),
                style_rules=t(self.language, f"prompt.scene_style.{style}"),
            )
            if look != "none":
                prompt += "\n\n" + t(self.language, f"prompt.scene_look.{look}")
            wish = str(getattr(self, "scene_wish", "") or "").strip()
            if wish:
                prompt += "\n\n" + t(self.language, "prompt.scene_wish", wish=wish)
            payload = self._api_payload(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=response_token_limit(getattr(self, "response_limits", None), "prompt.scene_image"),
                stream=True,
            )
            response = self._api_post(payload, stream=True, timeout=120)
            response.raise_for_status()
            raw, cancelled = self._read_response(response, SCENE)
            if cancelled:
                return

            scene_prompt, negative = self._parse_scene_response(raw)
            scene_prompt = apply_image_look(scene_prompt, look)
            self.root.after(0, lambda: self.show_scene_prompt(scene_prompt, negative, style, look))

        except requests.exceptions.ConnectionError:
            self.root.after(0, lambda: self.add_system_message(self.tr("msg.no_server")))
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, lambda msg=err_msg: self.add_system_message(self.tr("msg.scene_prompt_fail", msg=msg)))
        finally:
            self.scene_prompt_running = False
            self._end_operation(SCENE)
            self.root.after(0, self.refresh_busy_state)

    def _parse_scene_response(self, raw):
        """Достаёт промпт и антипромпт из JSON-ответа модели."""
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                scene_prompt = str(data.get("prompt", "")).strip()
                negative = str(data.get("negative_prompt", "")).strip()
                if scene_prompt:
                    return scene_prompt, negative
            except ValueError:
                pass
        # Модель не выдала JSON — показываем ответ как есть
        return cleaned, ""
