import customtkinter as ctk

import tkinter as tk

from tkinter import (
    messagebox,
    simpledialog,
)

from .config import (
    COLORS,
    DEFAULT_RESPONSE_LIMITS,
    IMAGE_LOOKS,
    IMAGE_PROMPT_STYLES,
    clamp_response_limits,
)

from .i18n import (
    PROMPT_GROUPS,
    builtin_prompt,
    prompt_edit_issues,
    prompt_placeholders,
    set_prompt_overrides,
)

from .windowing import place_window

class SettingsMixin:
    def open_ai_settings(self):
        MANUAL_PRESET = self.tr("dialog.manual_preset")

        win = ctk.CTkToplevel(self.root)
        win.title(self.tr("dialog.ai_settings"))
        win.transient(self.root)
        place_window(win, "780x680", self.root)
        win.grab_set()

        tabview = ctk.CTkTabview(win)
        tabview.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))
        ai_tab = tabview.add(self.tr("dialog.tab_ai"))
        game_tab = tabview.add(self.tr("dialog.tab_game"))
        prompt_tab = tabview.add(self.tr("dialog.tab_prompts"))

        scroll = ctk.CTkScrollableFrame(ai_tab)
        scroll.pack(fill=tk.BOTH, expand=True)
        game = ctk.CTkScrollableFrame(game_tab)
        game.pack(fill=tk.BOTH, expand=True)

        api_presets_local = [dict(p) for p in self.api_presets]

        ctk.CTkLabel(scroll, text=self.tr("dialog.api_config"), font=("", 13, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 0))

        preset_row = ctk.CTkFrame(scroll, fg_color="transparent")
        preset_row.pack(fill=tk.X, padx=10, pady=(5, 5))

        initial_preset = (
            self.active_api_preset
            if any(p["name"] == self.active_api_preset for p in api_presets_local)
            else MANUAL_PRESET
        )
        preset_var = ctk.StringVar(value=initial_preset)

        def get_preset_values():
            return [MANUAL_PRESET] + [p["name"] for p in api_presets_local]

        api_url_entry = ctk.CTkEntry(scroll, placeholder_text="http://localhost:1234/v1/chat/completions")
        api_key_entry = ctk.CTkEntry(scroll, placeholder_text="sk-...", show="*")
        model_entry = ctk.CTkEntry(scroll, placeholder_text="deepseek/deepseek-v3.2")

        def fill_api_fields(preset):
            api_url_entry.delete(0, tk.END)
            api_url_entry.insert(0, preset.get("api_url", ""))
            api_key_entry.delete(0, tk.END)
            api_key_entry.insert(0, preset.get("api_key", ""))
            model_entry.delete(0, tk.END)
            model_entry.insert(0, preset.get("model", ""))

        def on_preset_selected(choice):
            if choice == MANUAL_PRESET:
                return
            preset = next((p for p in api_presets_local if p["name"] == choice), None)
            if preset:
                fill_api_fields(preset)

        preset_menu = ctk.CTkOptionMenu(
            preset_row,
            variable=preset_var,
            values=get_preset_values(),
            command=on_preset_selected,
            width=220,
        )
        preset_menu.pack(side=tk.LEFT, padx=(0, 5))

        def refresh_preset_menu(select_name=None):
            values = get_preset_values()
            preset_menu.configure(values=values)
            if select_name and select_name in values:
                preset_var.set(select_name)
            elif preset_var.get() not in values:
                preset_var.set(MANUAL_PRESET)

        preset_btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        preset_btn_row.pack(fill=tk.X, padx=10, pady=(0, 10))

        def save_api_preset():
            name = simpledialog.askstring(self.tr("dialog.save_preset"), self.tr("dialog.preset_name"), parent=win)
            if not name or not name.strip():
                return
            name = name.strip()
            preset_data = {
                "name": name,
                "api_url": api_url_entry.get().strip(),
                "api_key": api_key_entry.get().strip(),
                "model": model_entry.get().strip(),
            }
            existing_idx = next((i for i, p in enumerate(api_presets_local) if p["name"] == name), None)
            if existing_idx is not None:
                previous = api_presets_local[existing_idx]
                if "reasoning" in previous:
                    preset_data["reasoning"] = previous.get("reasoning", False)
                if "reasoning_max_tokens" in previous:
                    preset_data["reasoning_max_tokens"] = previous.get("reasoning_max_tokens", 1024)
                api_presets_local[existing_idx] = preset_data
            else:
                api_presets_local.append(preset_data)
            refresh_preset_menu(select_name=name)
            self.add_system_message(self.tr("msg.preset_saved", name=name))

        def delete_api_preset():
            choice = preset_var.get()
            if choice == MANUAL_PRESET:
                messagebox.showinfo(self.tr("dialog.delete_preset_info"), self.tr("dialog.delete_preset_pick"), parent=win)
                return
            if not messagebox.askyesno(self.tr("dialog.delete_preset"), self.tr("dialog.delete_preset_q", name=choice), parent=win):
                return
            api_presets_local[:] = [p for p in api_presets_local if p["name"] != choice]
            refresh_preset_menu()
            preset_var.set(MANUAL_PRESET)

        ctk.CTkButton(preset_btn_row, text=self.tr("btn.save_as"), width=140, command=save_api_preset).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ctk.CTkButton(
            preset_btn_row, text=self.tr("btn.delete_icon"), width=100, fg_color=COLORS["danger"], hover_color=COLORS["danger_hover"], command=delete_api_preset
        ).pack(side=tk.LEFT)

        ctk.CTkLabel(scroll, text=self.tr("dialog.api_url")).pack(anchor=tk.W, padx=10, pady=(5, 0))
        api_url_entry.pack(fill=ctk.X, padx=10, pady=(5, 10))
        api_url_entry.insert(0, self.api_url)

        ctk.CTkLabel(scroll, text=self.tr("dialog.api_key")).pack(anchor=tk.W, padx=10)
        api_key_entry.pack(fill=ctk.X, padx=10, pady=(5, 10))
        api_key_entry.insert(0, self.api_key)

        show_key_var = ctk.BooleanVar(value=False)

        def toggle_key_visibility():
            api_key_entry.configure(show="" if show_key_var.get() else "*")

        ctk.CTkCheckBox(scroll, text=self.tr("dialog.show_key"), variable=show_key_var, command=toggle_key_visibility).pack(
            anchor=tk.W, padx=10, pady=(0, 10)
        )

        ctk.CTkLabel(scroll, text=self.tr("dialog.model")).pack(anchor=tk.W, padx=10)
        model_entry.pack(fill=ctk.X, padx=10, pady=(5, 15))
        model_entry.insert(0, self.model)

        ctk.CTkLabel(scroll, text=self.tr("dialog.temperature")).pack(anchor=tk.W, padx=10)
        temp_val_lbl = ctk.CTkLabel(scroll, text=f"{self.temperature:.1f}", text_color=COLORS["accent"])
        temp_val_lbl.pack(anchor=tk.E, padx=10)

        def update_temp_lbl(val):
            temp_val_lbl.configure(text=f"{val:.1f}")

        temp_slider = ctk.CTkSlider(scroll, from_=0.0, to=2.0, number_of_steps=20, command=update_temp_lbl)
        temp_slider.set(self.temperature)
        temp_slider.pack(fill=ctk.X, padx=10, pady=(0, 15))

        ctk.CTkLabel(scroll, text=self.tr("dialog.context_size")).pack(anchor=tk.W, padx=10)
        ctx_val_lbl = ctk.CTkLabel(scroll, text=f"{self.context_size}", text_color=COLORS["accent"])
        ctx_val_lbl.pack(anchor=tk.E, padx=10)

        def update_ctx_lbl(val):
            ctx_val_lbl.configure(text=f"{int(val)}")

        ctx_slider = ctk.CTkSlider(scroll, from_=4096, to=131072, number_of_steps=31, command=update_ctx_lbl)
        ctx_slider.set(self.context_size)
        ctx_slider.pack(fill=ctk.X, padx=10, pady=(0, 15))

        ctk.CTkLabel(game, text=self.tr("dialog.gen_params"), font=("", 13, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 5))

        stream_var = ctk.BooleanVar(value=self.stream_mode)
        summary_enabled_var = ctk.BooleanVar(value=self.summary_enabled)
        memory_enabled_var = ctk.BooleanVar(value=self.memory_enabled)
        ctk.CTkCheckBox(game, text=self.tr("dialog.stream"), variable=stream_var).pack(anchor=tk.W, padx=10, pady=(5, 10))

        ctk.CTkLabel(game, text=self.tr("dialog.max_tokens")).pack(anchor=tk.W, padx=10)
        tokens_entry = ctk.CTkEntry(game)
        tokens_entry.pack(fill=ctk.X, padx=10, pady=(5, 15))
        tokens_entry.insert(0, str(self.max_tokens))

        ctk.CTkLabel(game, text=self.tr("dialog.section_summary"), font=("", 13, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 5))
        ctk.CTkCheckBox(game, text=self.tr("dialog.auto_summary"), variable=summary_enabled_var).pack(anchor=tk.W, padx=10, pady=5)

        ctk.CTkLabel(game, text=self.tr("dialog.summary_fill")).pack(anchor=tk.W, padx=10)
        fill_val_lbl = ctk.CTkLabel(game, text=f"{self.summary_fill_percent}%", text_color=COLORS["accent"])
        fill_val_lbl.pack(anchor=tk.E, padx=10)

        def update_fill_lbl(val):
            fill_val_lbl.configure(text=f"{int(round(float(val)))}%")

        fill_slider = ctk.CTkSlider(game, from_=50, to=95, number_of_steps=45, command=update_fill_lbl)
        fill_slider.set(self.summary_fill_percent)
        fill_slider.pack(fill=ctk.X, padx=10, pady=(0, 15))

        ctk.CTkLabel(game, text=self.tr("dialog.section_memory"), font=("", 13, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 5))
        ctk.CTkCheckBox(game, text=self.tr("dialog.memory_bank"), variable=memory_enabled_var).pack(anchor=tk.W, padx=10, pady=(0, 10))

        ctk.CTkLabel(game, text=self.tr("dialog.memory_every")).pack(anchor=tk.W, padx=10, pady=(10, 0))
        memory_interval_var = ctk.StringVar(value=str(self.memory_interval))
        ctk.CTkOptionMenu(game, variable=memory_interval_var, values=["3", "5", "10", "15"]).pack(
            anchor=tk.W, padx=10, pady=5
        )

        ctk.CTkLabel(game, text=self.tr("dialog.memory_top_k")).pack(anchor=tk.W, padx=10)
        memory_top_k_var = ctk.StringVar(value=str(self.memory_top_k))
        ctk.CTkOptionMenu(game, variable=memory_top_k_var, values=["3", "5", "7", "10"]).pack(anchor=tk.W, padx=10, pady=5)

        ctk.CTkLabel(game, text=self.tr("dialog.image_style")).pack(anchor=tk.W, padx=10, pady=(10, 5))
        image_style_var = ctk.StringVar(value=self.tr(f"image_style.{self.image_prompt_style}"))
        ctk.CTkOptionMenu(
            game,
            variable=image_style_var,
            values=[self.tr(f"image_style.{s}") for s in IMAGE_PROMPT_STYLES],
        ).pack(anchor=tk.W, padx=10, pady=5)

        ctk.CTkLabel(game, text=self.tr("dialog.image_look")).pack(anchor=tk.W, padx=10, pady=(10, 5))
        image_look_var = ctk.StringVar(value=self.tr(f"image_look.{self.image_look}"))
        ctk.CTkOptionMenu(
            game,
            variable=image_look_var,
            values=[self.tr(f"image_look.{name}") for name in IMAGE_LOOKS],
        ).pack(anchor=tk.W, padx=10, pady=5)

        prompt_drafts = {}
        limit_drafts = {}
        prompt_current = {"key": None}

        def stored_prompt(key):
            if key in prompt_drafts:
                return prompt_drafts[key]
            override = self.prompt_overrides.get(self.language, {}).get(key)
            if isinstance(override, str) and override.strip():
                return override
            return builtin_prompt(self.language, key)

        def flush_prompt_editor():
            key = prompt_current["key"]
            if key is None:
                return
            prompt_drafts[key] = prompt_editor.get("1.0", tk.END).strip()
            if key in DEFAULT_RESPONSE_LIMITS:
                limit_drafts[key] = limit_entry.get().strip()

        def show_prompt(key):
            flush_prompt_editor()
            prompt_current["key"] = key
            prompt_editor.delete("1.0", tk.END)
            prompt_editor.insert("1.0", stored_prompt(key))
            fields = prompt_placeholders(builtin_prompt(self.language, key))
            if fields:
                shown = ", ".join("{" + name + "}" for name in fields)
                prompt_hint.configure(text=self.tr("dialog.prompt_fields", fields=shown))
            else:
                prompt_hint.configure(text=self.tr("dialog.prompt_fields_none"))
            if key in DEFAULT_RESPONSE_LIMITS:
                raw = limit_drafts.get(key)
                if raw is None:
                    raw = str(self.response_limits.get(key, DEFAULT_RESPONSE_LIMITS[key]))
                limit_entry.delete(0, tk.END)
                limit_entry.insert(0, raw)
            reset_prompt_btn.pack_forget()
            if key in DEFAULT_RESPONSE_LIMITS:
                limit_row.pack(fill=tk.X, pady=(6, 0))
            else:
                limit_row.pack_forget()
            reset_prompt_btn.pack(anchor=tk.W, pady=(6, 0))

        def reset_prompt():
            key = prompt_current["key"]
            if key is None:
                return
            prompt_drafts[key] = builtin_prompt(self.language, key)
            prompt_editor.delete("1.0", tk.END)
            prompt_editor.insert("1.0", prompt_drafts[key])

        def on_prompt_selected(_event=None):
            sel = prompt_list.curselection()
            if not sel:
                return
            key = prompt_index_to_key[sel[0]]
            if key is None:
                return
            if key == prompt_current["key"]:
                return
            show_prompt(key)

        prompt_body = ctk.CTkFrame(prompt_tab, fg_color="transparent")
        prompt_body.pack(fill=tk.BOTH, expand=True)
        prompt_left = ctk.CTkFrame(prompt_body, width=220)
        prompt_left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8), pady=4)
        prompt_left.pack_propagate(False)
        prompt_list = tk.Listbox(
            prompt_left,
            bg=COLORS["listbox_bg"],
            fg="white",
            selectbackground=COLORS["listbox_sel"],
            relief=tk.FLAT,
            font=("Arial", 11),
            highlightthickness=0,
            borderwidth=0,
        )
        prompt_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        prompt_index_to_key = []
        first_prompt_key = None
        for group_key, keys in PROMPT_GROUPS:
            prompt_list.insert(tk.END, self.tr(group_key))
            prompt_index_to_key.append(None)
            for key in keys:
                suffix = key[len("prompt.") :]
                prompt_list.insert(tk.END, "  " + self.tr(f"prompt_name.{suffix}"))
                prompt_index_to_key.append(key)
                if first_prompt_key is None:
                    first_prompt_key = key
        prompt_list.bind("<<ListboxSelect>>", on_prompt_selected)

        prompt_right = ctk.CTkFrame(prompt_body, fg_color="transparent")
        prompt_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=4)
        prompt_editor = ctk.CTkTextbox(prompt_right, wrap=tk.WORD, font=ctk.CTkFont(size=13))
        prompt_editor.pack(fill=tk.BOTH, expand=True)
        prompt_editor.bind("<Button-3>", self.show_context_menu)
        prompt_hint = ctk.CTkLabel(prompt_right, text="", text_color="gray", anchor="w", justify=tk.LEFT)
        prompt_hint.pack(fill=tk.X, pady=(6, 0))
        limit_row = ctk.CTkFrame(prompt_right, fg_color="transparent")
        ctk.CTkLabel(limit_row, text=self.tr("dialog.response_limit")).pack(anchor=tk.W)
        limit_entry = ctk.CTkEntry(limit_row)
        limit_entry.pack(fill=tk.X, pady=(4, 0))
        reset_prompt_btn = ctk.CTkButton(prompt_right, text=self.tr("btn.reset_prompt"), width=120, command=reset_prompt)
        reset_prompt_btn.pack(anchor=tk.W, pady=(6, 0))
        if first_prompt_key is not None:
            show_prompt(first_prompt_key)
            prompt_list.selection_set(1)

        def prompt_problems():
            flush_prompt_editor()
            lines = []
            for key, text in prompt_drafts.items():
                issues = prompt_edit_issues(self.language, key, text)
                if not issues:
                    continue
                suffix = key[len("prompt.") :]
                name = self.tr(f"prompt_name.{suffix}")
                if issues["missing"]:
                    fields = ", ".join("{" + item + "}" for item in issues["missing"])
                    lines.append(self.tr("dialog.prompt_missing_fields", name=name, fields=fields))
                if issues["unknown"]:
                    fields = ", ".join("{" + item + "}" for item in issues["unknown"])
                    lines.append(self.tr("dialog.prompt_unknown_fields", name=name, fields=fields))
                if issues["broken"]:
                    lines.append(self.tr("dialog.prompt_broken", name=name))
            return lines

        def apply_prompt_drafts():
            lang = self.language
            current = dict(self.prompt_overrides.get(lang, {}))
            for key, text in prompt_drafts.items():
                if not text.strip() or text == builtin_prompt(lang, key):
                    current.pop(key, None)
                else:
                    current[key] = text
            overrides = {
                "ru": dict(self.prompt_overrides.get("ru", {})),
                "en": dict(self.prompt_overrides.get("en", {})),
            }
            overrides[lang] = current
            self.prompt_overrides = set_prompt_overrides(overrides)
            merged_limits = dict(self.response_limits)
            merged_limits.update(limit_drafts)
            self.response_limits = clamp_response_limits(merged_limits)

        def apply_settings():
            problems = prompt_problems()
            if problems:
                messagebox.showwarning(self.tr("dialog.prompt_invalid_title"), "\n".join(problems), parent=win)
                return
            apply_prompt_drafts()
            api_url = api_url_entry.get().strip()
            if api_url:
                self.api_url = api_url
            self.api_key = api_key_entry.get().strip()
            self.model = model_entry.get().strip()
            self.api_presets = [dict(p) for p in api_presets_local]
            selected_preset = preset_var.get()
            self.active_api_preset = selected_preset if selected_preset != MANUAL_PRESET else ""
            self.stream_mode = stream_var.get()
            self.summary_enabled = summary_enabled_var.get()
            self.memory_enabled = memory_enabled_var.get()
            self.temperature = temp_slider.get()
            self.context_size = int(ctx_slider.get())
            self.summary_fill_percent = int(round(fill_slider.get()))
            try:
                self.max_tokens = int(tokens_entry.get())
            except:
                pass
            try:
                self.memory_interval = int(memory_interval_var.get())
            except:
                pass
            try:
                self.memory_top_k = int(memory_top_k_var.get())
            except:
                pass
            # Обратный перевод подписи выбранного формата в ключ стиля
            selected_style = image_style_var.get()
            for style in IMAGE_PROMPT_STYLES:
                if self.tr(f"image_style.{style}") == selected_style:
                    self.image_prompt_style = style
                    break
            selected_look = image_look_var.get()
            for look in IMAGE_LOOKS:
                if self.tr(f"image_look.{look}") == selected_look:
                    self.image_look = look
                    break
            self.save_global_settings()
            self.update_toggle_buttons()
            self.update_summary_label()
            self.update_memory_label()
            self.update_context_indicator()
            model_info = self.tr("msg.model_part", model=self.model) if self.model else ""
            preset_info = self.tr("msg.preset_part", name=self.active_api_preset) if self.active_api_preset else ""
            self.add_system_message(
                self.tr(
                    "msg.settings_saved",
                    api=self.api_url,
                    model=model_info,
                    preset=preset_info,
                    stream=self.tr("on" if self.stream_mode else "off"),
                    summary=self.tr("on" if self.summary_enabled else "off"),
                    memory=self.tr("on" if self.memory_enabled else "off"),
                )
            )
            win.destroy()

        ctk.CTkButton(win, text=self.tr("btn.save"), command=apply_settings).pack(pady=10)

