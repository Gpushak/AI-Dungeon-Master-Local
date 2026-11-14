from threading import Thread

import customtkinter as ctk

import tkinter as tk

from tkinter import messagebox

from .ai_engine import CARDS

from .config import (
    COLORS,
    INTRODUCTION_FILE,
    WORLD_FILES,
    response_token_limit,
)

from .windowing import place_window

from .story_cards import (
    format_triggers,
    load_story_cards,
    next_card_id,
    parse_triggers,
    save_story_cards,
)

class CardsMixin:
    def _embed_story_cards_editor(self, parent, cards_data, editable=True, on_save=None, persist=True):
        left = ctk.CTkFrame(parent, width=180)
        left.pack(side=ctk.LEFT, fill=ctk.Y, padx=(0, 8))
        left.pack_propagate(False)

        ctk.CTkLabel(left, text=self.tr("cards.list"), font=ctk.CTkFont(weight="bold")).pack(pady=(0, 5))

        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(left, textvariable=search_var, placeholder_text=self.tr("cards.search"))
        search_entry.pack(fill=tk.X, pady=(0, 5))

        list_frame = ctk.CTkFrame(left, fg_color="transparent")
        list_frame.pack(fill=ctk.BOTH, expand=True)

        card_listbox = tk.Listbox(
            list_frame,
            bg=COLORS["listbox_bg"],
            fg="white",
            selectbackground=COLORS["listbox_sel"],
            relief=tk.FLAT,
            font=("Arial", 11),
            highlightthickness=0,
            borderwidth=0,
        )
        card_listbox.pack(side=tk.LEFT, fill=ctk.BOTH, expand=True)

        list_scrollbar = ctk.CTkScrollbar(list_frame, command=card_listbox.yview)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        card_listbox.configure(yscrollcommand=list_scrollbar.set)

        right = ctk.CTkFrame(parent, fg_color="transparent")
        right.pack(side=ctk.RIGHT, fill=ctk.BOTH, expand=True)

        ctk.CTkLabel(right, text=self.tr("cards.title")).pack(anchor=tk.W, padx=5)
        title_entry = ctk.CTkEntry(right)
        title_entry.pack(fill=ctk.X, padx=5, pady=(0, 8))

        ctk.CTkLabel(right, text=self.tr("cards.desc")).pack(anchor=tk.W, padx=5)
        desc_text = ctk.CTkTextbox(right, wrap=tk.WORD, height=180)
        desc_text.pack(fill=ctk.BOTH, expand=True, padx=5, pady=(0, 8))
        desc_text.bind("<Button-3>", self.show_context_menu)

        ctk.CTkLabel(
            right,
            text=self.tr("cards.triggers"),
        ).pack(anchor=tk.W, padx=5)
        triggers_entry = ctk.CTkEntry(right, placeholder_text=self.tr("cards.triggers_ph"))
        triggers_entry.pack(fill=ctk.X, padx=5, pady=(0, 8))

        hint = ctk.CTkLabel(
            right,
            text=self.tr("cards.empty_triggers"),
            text_color="gray",
            font=ctk.CTkFont(size=11),
        )
        hint.pack(anchor=tk.W, padx=5, pady=(0, 8))

        gen_btn_frame = ctk.CTkFrame(right, fg_color="transparent")
        gen_btn_frame.pack(fill=ctk.X, padx=5, pady=(0, 8))
        generate_desc_btn = ctk.CTkButton(
            gen_btn_frame,
            text=self.tr("cards.generate_desc"),
            command=lambda: self._generate_card_description(
                title_entry, desc_text, cards_data, state
            ),
            width=180,
        )
        generate_desc_btn.pack(side=ctk.LEFT)

        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.pack(fill=ctk.X, padx=5, pady=5)

        state = {"selected_index": None, "loading": False, "visible_indices": []}

        def refresh_list(select_index=None):
            card_listbox.delete(0, tk.END)
            query = search_var.get().strip().lower()
            state["visible_indices"] = []
            for index, card in enumerate(cards_data.get("cards", [])):
                searchable_text = " ".join(
                    [
                        str(card.get("title", "")),
                        str(card.get("description", "")),
                        " ".join(str(trigger) for trigger in card.get("triggers", [])),
                    ]
                ).lower()
                if query and query not in searchable_text:
                    continue
                card_listbox.insert(tk.END, card.get("title", self.tr("cards.untitled")))
                state["visible_indices"].append(index)

            if select_index in state["visible_indices"]:
                visible_index = state["visible_indices"].index(select_index)
                card_listbox.selection_set(visible_index)
                card_listbox.activate(visible_index)
                load_card(select_index)
            elif state["visible_indices"]:
                card_listbox.selection_set(0)
                load_card(state["visible_indices"][0])
            else:
                load_card(-1)

        def load_card(index):
            cards = cards_data.get("cards", [])
            if index < 0 or index >= len(cards):
                state["selected_index"] = None
                title_entry.delete(0, tk.END)
                desc_text.delete("1.0", tk.END)
                triggers_entry.delete(0, tk.END)
                return
            state["loading"] = True
            state["selected_index"] = index
            card = cards[index]
            title_entry.delete(0, tk.END)
            title_entry.insert(0, str(card.get("title", "")))
            desc_text.delete("1.0", tk.END)
            desc_text.insert("1.0", str(card.get("description", "")))
            triggers_entry.delete(0, tk.END)
            triggers_entry.insert(0, format_triggers(card.get("triggers", [])))
            state["loading"] = False

        def apply_current_card():
            if state["loading"] or state["selected_index"] is None:
                return
            cards = cards_data.get("cards", [])
            idx = state["selected_index"]
            if idx < 0 or idx >= len(cards):
                return
            cards[idx]["title"] = title_entry.get().strip() or self.tr("cards.untitled")
            cards[idx]["description"] = desc_text.get("1.0", tk.END).strip()
            cards[idx]["triggers"] = parse_triggers(triggers_entry.get())
            refresh_list(select_index=idx)

        def on_card_select(_event=None):
            sel = card_listbox.curselection()
            if not sel or sel[0] >= len(state["visible_indices"]):
                return
            apply_current_card()
            load_card(state["visible_indices"][sel[0]])

        def add_card():
            apply_current_card()
            new_card = {
                "id": next_card_id(cards_data.get("cards", [])),
                "title": self.tr("cards.new"),
                "description": "",
                "triggers": [],
            }
            cards_data.setdefault("cards", []).append(new_card)
            refresh_list(select_index=len(cards_data["cards"]) - 1)

        def delete_card():
            sel = card_listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            if not messagebox.askyesno(self.tr("cards.delete"), self.tr("cards.delete_q")):
                return
            cards_data["cards"].pop(idx)
            refresh_list(select_index=min(idx, len(cards_data.get("cards", [])) - 1) if cards_data.get("cards") else None)

        def save_cards():
            apply_current_card()
            if not persist:
                return
            if on_save:
                on_save()
            elif self.current_world_path:
                save_story_cards(self.current_world_path, cards_data)
                self.story_cards = cards_data
                self.add_system_message(self.tr("msg.cards_saved"))
            self.update_context_indicator()

        card_listbox.bind("<<ListboxSelect>>", on_card_select)
        search_var.trace_add("write", lambda *_: refresh_list(state["selected_index"]))

        if editable:
            ctk.CTkButton(btn_row, text=self.tr("btn.add"), command=add_card, width=100).pack(side=ctk.LEFT, padx=3)
            ctk.CTkButton(
                btn_row,
                text=self.tr("btn.delete_icon"),
                command=delete_card,
                fg_color=COLORS["danger"],
                hover_color=COLORS["danger_hover"],
                width=100,
            ).pack(side=ctk.LEFT, padx=3)
            if persist:
                ctk.CTkButton(
                    btn_row,
                    text=self.tr("btn.save"),
                    command=save_cards,
                    fg_color=COLORS["accent"],
                    text_color="black",
                    width=110,
                ).pack(side=ctk.RIGHT, padx=3)
            else:
                ctk.CTkLabel(
                    btn_row,
                    text=self.tr("cards.save_with_world"),
                    text_color="gray",
                    font=ctk.CTkFont(size=11),
                ).pack(side=ctk.RIGHT, padx=3)

        refresh_list(select_index=0 if cards_data.get("cards") else None)
        return {"refresh": refresh_list, "save": save_cards}

    def _generate_card_description(self, title_entry, desc_text, cards_data, state):
        """Generate card description using AI based on title, plot_basics, and history context."""
        if not self.current_world_path:
            messagebox.showinfo(
                self.tr("cards.generate_desc_title"),
                self.tr("dialog.cards_need_world"),
            )
            return

        card_title = title_entry.get().strip()
        if not card_title:
            messagebox.showwarning(
                self.tr("cards.generate_desc_title"),
                self.tr("cards.enter_title_first"),
            )
            return

        from .storage import WORLD_FILES, INTRODUCTION_FILE
        from .i18n import t

        world_context = ""
        for fname in WORLD_FILES:
            if fname in ("summary.txt", INTRODUCTION_FILE):
                continue
            path = self.current_world_path / fname
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    world_context += f"=== {fname} ===\n{content}\n"

        summary_path = self.current_world_path / "summary.txt"
        summary_content = summary_path.read_text(encoding="utf-8").strip() if summary_path.exists() else ""
        if summary_content:
            from .i18n import t
            world_context += t(self.language, "prompt.summary_header", text=summary_content)

        author_notes_path = self.current_world_path / "author_notes.txt"
        author_notes = author_notes_path.read_text(encoding="utf-8").strip() if author_notes_path.exists() else ""

        history_fragment = ""
        preview_msgs = []
        preview_tokens = 0
        from .tokens import count_tokens
        # Резервируем буфер для промпта, ответа и безопасности
        available_for_history = self.context_size - 1500
        for msg in reversed(self.history):
            msg_tokens = count_tokens(msg) + 1
            if preview_tokens + msg_tokens > available_for_history:
                break
            preview_msgs.insert(0, msg)
            preview_tokens += msg_tokens
        if preview_msgs:
            history_fragment = "\n".join(preview_msgs)

        plot_basics = desc_text.get("1.0", tk.END).strip()

        prompt = t(
            self.language,
            "prompt.card_desc_gen",
            world_context=world_context or t(self.language, "prompt.none"),
            card_title=card_title,
            plot_basics=plot_basics or t(self.language, "prompt.none"),
            author_notes=author_notes or t(self.language, "prompt.none"),
            history_fragment=history_fragment or t(self.language, "prompt.none"),
        )

        gen_btn = desc_text.master.winfo_children()[2] if len(desc_text.master.winfo_children()) > 2 else None
        if gen_btn:
            gen_btn.configure(state="normal", text=self.tr("btn.stop"), command=lambda: self.request_stop(CARDS))
        # Флаг отмены создаём до старта потока, иначе клик по «Стоп» в первые
        # миллисекунды попал бы в никуда.
        self._begin_operation(CARDS)

        def run_generation():
            try:
                with self._use_task_preset("cards"):
                    payload = self._api_payload(
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=response_token_limit(getattr(self, "response_limits", None), "prompt.card_desc_gen"),
                        stream=True,
                    )
                    response = self._api_post(payload, stream=True, timeout=120)
                response.raise_for_status()
                generated_desc, cancelled = self._read_response(response, CARDS)

                if not cancelled:
                    self.root.after(
                        0,
                        lambda: [
                            desc_text.delete("1.0", tk.END),
                            desc_text.insert("1.0", generated_desc),
                        ],
                    )
            except Exception as e:
                err_msg = str(e)
                self.root.after(
                    0,
                    lambda msg=err_msg: messagebox.showerror(
                        self.tr("cards.generate_desc_title"),
                        self.tr("msg.error", msg=msg),
                    ),
                )
            finally:
                self._end_operation(CARDS)
                self.root.after(
                    0,
                    lambda: gen_btn.configure(state="normal", text=self.tr("cards.generate_desc")) if gen_btn else None,
                )

        Thread(target=run_generation, daemon=True).start()

    def open_story_cards_editor(self):
        if not self.current_world_path:
            messagebox.showinfo(self.tr("dialog.cards_title"), self.tr("dialog.cards_need_world"))
            return

        win = ctk.CTkToplevel(self.root)
        win.title(self.tr("dialog.cards_title"))
        win.transient(self.root)
        place_window(win, "850x600", self.root)
        win.grab_set()

        cards_data = load_story_cards(self.current_world_path)

        def save_and_sync():
            save_story_cards(self.current_world_path, cards_data)
            self.story_cards = cards_data

        editor = self._embed_story_cards_editor(win, cards_data, editable=True, on_save=save_and_sync)

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(fill=ctk.X, padx=15, pady=10)
        ctk.CTkButton(btn_frame, text=self.tr("btn.close_x"), command=win.destroy, fg_color="gray").pack(side=ctk.RIGHT)

        win.protocol("WM_DELETE_WINDOW", win.destroy)

