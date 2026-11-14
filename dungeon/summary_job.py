from threading import Thread

from .api_stream import SUMMARY
from .config import INTRODUCTION_FILE, WORLD_FILES, response_token_limit
from .i18n import localize_history, t
from .memory import format_memory_block, retrieve_relevant_memories
from .story_cards import format_story_cards_block, retrieve_relevant_cards
from .storage import atomic_write_text, save_summary_cursor
from .tokens import (
    count_tokens,
    history_window_budget,
    summary_needs_compression,
    unsummarized_token_count,
)


class SummaryMixin:
    def _retrieval_query(self, user_content):
        """Запрос для подбора памяти и карточек: ход игрока и недавняя история."""
        preview_msgs = []
        preview_tokens = 0
        for msg in reversed(self.history):
            msg_tokens = count_tokens(msg) + 1
            if preview_tokens + msg_tokens > 400:
                break
            preview_msgs.insert(0, msg)
            preview_tokens += msg_tokens
        return (user_content or "") + "\n" + "\n".join(preview_msgs)

    def _static_context_text(self, retrieval_query):
        """Всё, что попадает в промпт кроме самой истории хода."""
        context = ""
        if not self.current_world_path:
            return context
        for fname in WORLD_FILES:
            if fname in ("summary.txt", INTRODUCTION_FILE):
                continue
            path = self.current_world_path / fname
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    context += f"=== {fname} ===\n{content}\n"

        summary_path = self.current_world_path / "summary.txt"
        summary_content = summary_path.read_text(encoding="utf-8").strip() if summary_path.exists() else ""
        if summary_content:
            context += t(self.language, "prompt.summary_header", text=summary_content)

        if self.memory_enabled:
            relevant_memories = retrieve_relevant_memories(
                retrieval_query, self.memory_bank, top_k=self.memory_top_k
            )
            memory_block = format_memory_block(relevant_memories, self.language)
            if memory_block:
                context += memory_block

        relevant_cards = retrieve_relevant_cards(
            retrieval_query, self.story_cards, top_k=self.memory_top_k
        )
        cards_block = format_story_cards_block(relevant_cards, self.language)
        if cards_block:
            context += cards_block
        return context

    def static_history_budget(self, extra_tokens=0, retrieval_query=None, apply_floor=True):
        """Бюджет токенов истории: окно минус ответ, статика и запас."""
        if retrieval_query is None:
            retrieval_query = self._retrieval_query("")
        context = self._static_context_text(retrieval_query)
        system_base_text = f"{context}\n{t(self.language, 'prompt.history_header')}\n"
        static_tokens = count_tokens(system_base_text)
        return history_window_budget(
            self.context_size, self.max_tokens, static_tokens, extra_tokens, apply_floor=apply_floor
        )

    def unsummarized_fill(self):
        """Токены новой истории с последней суммаризации и честный остаток окна.

        Пол в 300 токенов здесь не применяется: он нужен только сборке хода,
        чтобы модель не осталась совсем без хроники.
        """
        if not self.current_world_path:
            budget = history_window_budget(self.context_size, self.max_tokens, 0, 0, apply_floor=False)
            return 0, budget
        used = unsummarized_token_count(self.history, self.covered_count)
        budget = self.static_history_budget(0, apply_floor=False)
        return used, budget

    def context_fill_state(self):
        """used, показанный бюджет и доля. При нулевом остатке доля равна 1, если хвост непустой."""
        used, budget = self.unsummarized_fill()
        if budget < 1:
            return used, max(used, 1), (1.0 if used else 0.0)
        return used, budget, used / budget

    def _summary_history_budget(self):
        """Сколько токенов истории отдаём в промпт суммаризации.

        Ниже 800 токенов свежий хвост уже нечем сжимать, поэтому окно
        не опускается под этот пол и модель всё равно вызывается.
        Если старое содержание занимает 80% лимита ответа, к промпту
        добавляется просьба сжать его; она же учтена в бюджете истории.
        """
        summary_path = self.current_world_path / "summary.txt"
        old_summary = (
            summary_path.read_text(encoding="utf-8").strip()
            if summary_path.exists()
            else t(self.language, "prompt.none")
        )
        summary_max_tokens = response_token_limit(getattr(self, "response_limits", None), "prompt.summary")
        compress_note = ""
        if summary_needs_compression(count_tokens(old_summary), summary_max_tokens):
            compress_note = "\n\n" + t(self.language, "prompt.summary_compress")
        prompt_template_base = t(
            self.language,
            "prompt.summary",
            old_summary=old_summary,
            history="",
        ) + compress_note
        safety_buffer = 400
        available = self.context_size - summary_max_tokens - count_tokens(prompt_template_base) - safety_buffer
        if available < 800:
            available = 800
        return available, old_summary, summary_max_tokens, compress_note

    def _remember_summarized_history(self):
        """Отмечает всю текущую историю как вошедшую в summary.txt."""
        self.covered_count = len(self.history)
        if self.current_world_path:
            save_summary_cursor(self.current_world_path, self.covered_count)
        self.root.after(0, self.update_context_indicator)
    def start_global_summary(self):
        if self.summary_indexing:
            return
        self.summary_indexing = True
        self._begin_operation(SUMMARY)
        self.refresh_busy_state()
        Thread(target=self._generate_global_summary_impl, daemon=True).start()

    def generate_global_summary(self):
        self.root.after(0, self.start_global_summary)

    def _generate_global_summary_impl(self):
        try:
            if not self.current_world_path:
                return

            # Тот же пробный запрос, что перед ходом: иначе первый подсчёт
            # завышает кириллицу и в суммаризацию уходит около 10к из 16к.
            self._calibrate_token_scale()

            summary_path = self.current_world_path / "summary.txt"
            available_summary_history, old_summary, summary_max_tokens, compress_note = (
                self._summary_history_budget()
            )

            short_history = []
            current_history_tokens = 0
            for msg in reversed(self.history):
                msg_tokens = count_tokens(msg) + 1
                if current_history_tokens + msg_tokens <= available_summary_history:
                    short_history.insert(0, msg)
                    current_history_tokens += msg_tokens
                else:
                    break

            history_text = "\n".join(localize_history(self.language, short_history))

            prompt = t(
                self.language,
                "prompt.summary",
                old_summary=old_summary,
                history=history_text,
            ) + compress_note

            with self._use_task_preset("summary"):
                payload = self._api_payload(
                    messages=[{"role": "user", "content": prompt + "\n\n" + t(self.language, "prompt.no_reasoning")}],
                    temperature=0.3,
                    max_tokens=summary_max_tokens,
                    stream=True,
                )
                response = self._api_post(payload, stream=True, timeout=240)
            response.raise_for_status()
            new_summary, cancelled = self._read_response(response, SUMMARY)
            if cancelled:
                self.root.after(0, lambda: self.add_system_message(self.tr("msg.summary_stopped")))
                return
            new_summary = new_summary.replace("```json", "").replace("```", "").strip()

            if new_summary:
                atomic_write_text(summary_path, new_summary)
                # Граница сдвигается только после целой записи. Отмена и ошибка
                # полосу не сбрасывают.
                self._remember_summarized_history()
                self.root.after(
                    0, lambda: self.add_system_message(self.tr("msg.summary_ok"))
                )

        except Exception as e:
            err_msg = str(e)
            self.root.after(
                0, lambda msg=err_msg: self.add_system_message(self.tr("msg.summary_fail", msg=msg))
            )
        finally:
            self.summary_indexing = False
            self._end_operation(SUMMARY)
            self.root.after(0, self.refresh_busy_state)
