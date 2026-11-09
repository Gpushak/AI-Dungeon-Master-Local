from datetime import datetime

import requests

from .api_stream import ACTION, DeltaBatcher, reasoning_token_count
from .i18n import DM_PREFIX, PLAYER_PREFIX, localize_history, normalize_lang, t
from .storage import read_world_language, save_history
from .text_utils import StreamThinkFilter, clean_dm_response, clean_stream_chunk
from .tokens import (
    calibration_sample,
    count_tokens,
    history_window_budget,
    model_scale_observed,
    observe_model_prompt,
    prompt_token_count,
    raw_count_tokens,
    reply_tokens,
    scale_token_count,
    summary_due,
)


class TurnMixin:
    def _calibrate_token_scale(self):
        """Один короткий запрос до нарезки истории, если масштаб ещё не известен.

        Пока локальный счётчик не сверен с моделью, он завышает кириллицу:
        первый ход после запуска упирается в свои 16к и в модель уходит около 10к.
        Следующие ходы уже знают масштаб. Проба делается до сборки промпта.
        """
        if model_scale_observed() or getattr(self, "_calibrating_scale", False):
            return
        self._calibrating_scale = True
        try:
            sample = calibration_sample(self._count_language())
            raw = raw_count_tokens(sample)
            payload = self._api_payload(
                messages=[{"role": "user", "content": sample}],
                temperature=0,
                max_tokens=1,
                stream=False,
            )
            try:
                response = self._api_post(payload, stream=False, timeout=30)
                response.raise_for_status()
                data = response.json()
            except Exception:
                return
            usage = data.get("usage") if isinstance(data, dict) else None
            if observe_model_prompt(raw, usage) and hasattr(self, "save_settings"):
                self.save_settings()
        finally:
            self._calibrating_scale = False

    def _count_language(self):
        """Язык текста, по которому сверяем масштаб: язык мира, иначе язык интерфейса."""
        path = getattr(self, "current_world_path", None)
        if path:
            lang = read_world_language(path)
            if lang:
                return lang
        return normalize_lang(getattr(self, "language", "ru"))

    def process_action(self, user_input="", direction_hint=None):
        self._last_api_usage = None
        try:
            # Веб-режим «Приключение» дописывает факт броска к действию до обычного хода.
            prepare = getattr(self, "prepare_adventure_action", None)
            if prepare is not None:
                user_input, direction_hint = prepare(user_input, direction_hint)
            self._calibrate_token_scale()
            if direction_hint:
                direction_hint = direction_hint.strip()
                history_label = direction_hint
                if direction_hint and (
                    not self.history or f"{PLAYER_PREFIX} {history_label}" != self.history[-1]
                ):
                    self.history.append(f"{PLAYER_PREFIX} {history_label}")
                user_content = t(self.language, "prompt.direction", hint=direction_hint)
            else:
                if user_input and (not self.history or f"{PLAYER_PREFIX} {user_input}" != self.history[-1]):
                    self.history.append(f"{PLAYER_PREFIX} {user_input}")
                user_content = user_input if user_input else t(self.language, "prompt.continue")

            cue = getattr(self, "roll_narration_cue", None)
            if cue is not None:
                extra = cue()
                if extra:
                    user_content = f"{user_content.rstrip()}\n{extra}"

            retrieval_query = self._retrieval_query(user_content)
            context = self._static_context_text(retrieval_query)

            system_base_text = f"{context}\n{t(self.language, 'prompt.history_header')}\n"
            static_tokens = count_tokens(system_base_text)
            user_tokens = count_tokens(user_content)
            # Пол в 300 токенов здесь намеренный: ход не должен остаться без истории.
            # Полоса считает тот же остаток без пола и без текста игрока.
            available_history_tokens = history_window_budget(
                self.context_size, self.max_tokens, static_tokens, user_tokens
            )

            short_history = []
            current_history_tokens = 0

            history_pool = self.history[:-1] if (user_input or direction_hint) else self.history
            for msg in reversed(history_pool):
                msg_tokens = count_tokens(msg) + 1
                if current_history_tokens + msg_tokens <= available_history_tokens:
                    short_history.insert(0, msg)
                    current_history_tokens += msg_tokens
                else:
                    break

            history_text = "\n".join(localize_history(self.language, short_history))
            system_final_content = f"""{context}\n{t(self.language, 'prompt.history_header')}\n{history_text}"""
            reasoning_on = bool(getattr(self, "reasoning", False))
            system_message = system_final_content
            if not reasoning_on:
                system_message += "\n\n" + t(self.language, "prompt.no_reasoning")
            # Масштаб токенов считается по тексту хода, как и раньше, без хвоста
            # «без размышлений»: его длина не должна сдвигать сверку с моделью.
            raw_prompt = raw_count_tokens(system_final_content) + raw_count_tokens(user_content)
            prompt_tokens = scale_token_count(raw_prompt)

            self.last_sent_prompt = {
                "system": system_final_content,
                "user": user_content,
                "tokens": prompt_tokens,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            stops = [
                f"\n{PLAYER_PREFIX}",
                PLAYER_PREFIX,
                f"\n{t(self.language, 'hist.player')}",
                t(self.language, "hist.player"),
                "<|im_end|>",
                "<|eot_id|>",
                "```",
                "---",
            ]
            if not reasoning_on:
                stops.extend(["<think>", "</think>"])

            payload = self._api_payload(
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_content},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                # Поток запрашивается всегда: только так ответ можно прервать
                # кнопкой остановки. stream_mode теперь управляет показом.
                stream=True,
                stop=stops,
                allow_reasoning=reasoning_on,
            )

            response = self._api_post(payload, stream=True, timeout=180)
            response.raise_for_status()

            # Заголовок Мастера рисуем только после успешного ответа: иначе
            # при ошибке подключения осталась бы висящая метка в логе.
            self.root.after(0, self.start_dm_stream)

            think_filter = StreamThinkFilter()
            reason_box = []
            # Дельты копятся и уходят в Tk пачками — см. DeltaBatcher
            batcher = DeltaBatcher(
                lambda chunk: self.root.after(0, lambda c=chunk: self.append_to_dm_stream(c))
            )
            reason_batcher = DeltaBatcher(
                lambda chunk: self.root.after(0, lambda c=chunk: self._emit_reasoning(c))
            )

            def remember_reasoning(piece):
                if not piece or not reasoning_on:
                    return
                reason_box.append(piece)
                if self.stream_mode:
                    reason_batcher.add(piece)

            def on_reasoning(delta):
                remember_reasoning(clean_stream_chunk(delta))

            def on_delta(delta):
                content = clean_stream_chunk(think_filter.feed(delta))
                remember_reasoning(clean_stream_chunk(think_filter.take_reasoning()))
                if content and self.stream_mode:
                    batcher.add(content)
                return content

            if reasoning_on:
                ai_text, cancelled = self._read_response(response, ACTION, on_delta, on_reasoning)
            else:
                ai_text, cancelled = self._read_response(response, ACTION, on_delta)
            think_filter.finish()
            remember_reasoning(clean_stream_chunk(think_filter.take_reasoning()))
            # Хвост, накопившийся за последние 50 мс, показываем сразу
            batcher.flush_now()
            reason_batcher.flush_now()

            if not ai_text:
                # Пустой ответ: убираем заголовок Мастера, чтобы не оставлять
                # висящий курсор в логе, и сообщаем причину.
                self.root.after(0, self.abort_dm_stream)
                key = "msg.action_stopped" if cancelled else "msg.empty_model"
                self.root.after(0, lambda k=key: self.add_system_message(self.tr(k)))
                return

            final_narration = clean_dm_response(ai_text)

            # Сначала история, потом событие финала. В вебе after выполняется
            # сразу: иначе страница успевает увидеть пустой черновик без ответа.
            self.history.append(f"{DM_PREFIX} {final_narration}")
            save_history(self.current_world_path, self.history)
            self._store_turn_reasoning(reason_box, reasoning_on)
            self.root.after(0, lambda f=final_narration: self.finalize_dm_stream(f))

            if cancelled:
                # Частичный ответ сохраняем в истории, но фоновые задачи не
                # запускаем — пользователь явно попросил остановиться.
                self.root.after(0, lambda: self.add_system_message(self.tr("msg.action_stopped")))
                return

            usage = getattr(self, "_last_api_usage", None)
            if observe_model_prompt(raw_prompt, usage) and hasattr(self, "save_settings"):
                self.save_settings()
            prompt_tokens = prompt_token_count(usage, raw_prompt)
            if isinstance(self.last_sent_prompt, dict):
                self.last_sent_prompt["tokens"] = prompt_tokens
            completion_tokens = reply_tokens(usage, final_narration)
            total_tokens = prompt_tokens + completion_tokens

            self.root.after(0, self.update_context_indicator)

            self.root.after(
                0,
                lambda p=prompt_tokens, c=completion_tokens, t=total_tokens: self.add_system_message(
                    self.tr("msg.tokens", p=p, c=c, t=t, ctx=self.context_size)
                ),
            )

            _used, _budget, fill_ratio = self.context_fill_state()
            self._schedule_summary_after_turn = summary_due(
                fill_ratio, self.summary_fill_percent, self.summary_enabled
            )
            if self._schedule_summary_after_turn:
                self.root.after(0, lambda: self.add_system_message(self.tr("msg.reviewing")))

            self._schedule_memory_after_turn = (
                self.memory_enabled and self.turns_since_memory >= self.memory_interval
            )
            if self._schedule_memory_after_turn:
                self.turns_since_memory = 0
                self.root.after(0, self.update_memory_label)

            follow = getattr(self, "finish_adventure_action", None)
            if follow is not None:
                follow(user_input, direction_hint)

        except requests.exceptions.ConnectionError:
            self.root.after(0, lambda: self.add_system_message(self.tr("msg.no_server")))
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, lambda msg=err_msg: self.add_system_message(self.tr("msg.error", msg=msg)))
        finally:
            self.root.after(0, self._finish_player_turn)

    def _emit_reasoning(self, chunk):
        hook = getattr(self, "append_reasoning_stream", None)
        if hook is not None and chunk:
            hook(chunk)

    def _store_turn_reasoning(self, reason_box, reasoning_on):
        record = getattr(self, "record_turn_reasoning", None)
        if record is None or not reasoning_on or not self.history:
            return
        text = "".join(reason_box).strip()
        hidden = not text and reasoning_token_count(getattr(self, "_last_api_usage", None)) > 0
        if not text and not hidden:
            return
        record(len(self.history) - 1, {"text": text, "hidden": hidden})

    def _finish_player_turn(self):
        self.processing = False
        self._end_operation(ACTION)
        # В том числе после остановки: обрыв ответа уже в истории, полоса должна его учесть.
        self.update_context_indicator()
        if self._schedule_summary_after_turn:
            self._schedule_summary_after_turn = False
            self.start_global_summary()
        if self._schedule_memory_after_turn:
            self._schedule_memory_after_turn = False
            self.start_memory_indexing()
        self.refresh_busy_state()
