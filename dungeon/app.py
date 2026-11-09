import customtkinter as ctk

import tkinter as tk

from .config import (
    BASE_DIR,
    COLORS,
    DEFAULT_IMAGE_LOOK,
    DEFAULT_IMAGE_STYLE,
    IMAGE_LOOKS,
    STORY_CARDS_KEY,
    WINDOW_SIZE,
    clamp_response_limits,
    normalize_image_settings,
)

from .i18n import (
    normalize_lang,
    set_prompt_overrides,
    t,
)

from .tokens import format_token_count

from .storage import (
    clamp_reasoning_max_tokens,
    flag_value,
    get_world_list,
    load_global_settings,
    read_world_language,
    save_global_settings,
    save_history,
)
from .ai_engine import AIEngineMixin
from .chat import ChatMixin
from .dialogs import DialogMixin
from .session import SessionMixin

class DungeonApp(DialogMixin, AIEngineMixin, ChatMixin, SessionMixin):
    def __init__(self, root):
        self.root = root
        settings = load_global_settings()
        self.language = normalize_lang(settings.get("language", "ru"))
        self.prompt_overrides = set_prompt_overrides(settings.get("prompt_overrides"))
        self.root.title(t(self.language, "window_title"))
        self.root.geometry(WINDOW_SIZE)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.current_world_path = None
        self.world_name = None
        self.history = []

        self.api_url = settings["api_url"]
        self.api_key = settings.get("api_key", "")
        self.model = settings.get("model", "")
        self.active_api_preset = settings.get("active_api_preset", "")
        self.api_presets = settings.get("api_presets", [])
        self.reasoning = flag_value(settings.get("reasoning", False))
        self.reasoning_max_tokens = clamp_reasoning_max_tokens(settings.get("reasoning_max_tokens", 1024))
        self.temperature = settings["temperature"]
        self.max_tokens = settings["max_tokens"]
        self.context_size = settings["context_size"]
        self.summary_fill_percent = settings["summary_fill_percent"]
        self.memory_interval = settings["memory_interval"]
        self.memory_top_k = settings["memory_top_k"]
        self.stream_mode = settings["stream_mode"]
        self.summary_enabled = settings.get("summary_enabled", True)
        self.memory_enabled = settings.get("memory_enabled", True)
        self.image_prompt_style = settings.get("image_prompt_style", DEFAULT_IMAGE_STYLE)
        self.image_look = settings.get("image_look", DEFAULT_IMAGE_LOOK)
        if self.image_look not in IMAGE_LOOKS:
            self.image_look = DEFAULT_IMAGE_LOOK
        image_settings = normalize_image_settings(settings)
        self.image_backend = image_settings["image_backend"]
        self.comfy_url = image_settings["comfy_url"]
        self.a1111_url = image_settings["a1111_url"]
        self.comfy_workflow = image_settings["comfy_workflow"]
        self.image_width = image_settings["image_width"]
        self.image_height = image_settings["image_height"]
        self.image_steps = image_settings["image_steps"]
        self.image_auto = image_settings["image_auto"]
        self.image_send_negative = image_settings["image_send_negative"]
        self.response_limits = clamp_response_limits(settings.get("response_limits"))
        self.covered_count = 0
        self.context_ratio = 0.0
        self.turns_since_memory = 0
        self.memory_bank = {"last_indexed_turn": 0, "entries": []}
        self.story_cards = {"cards": []}

        self.processing = False
        self.stream_start_index = None
        self.last_sent_prompt = None
        self.memory_indexing = False
        self.summary_indexing = False
        self.scene_prompt_running = False
        self._schedule_summary_after_turn = False
        self._schedule_memory_after_turn = False
        # Флаги отмены активных операций генерации
        self._cancel_events = {}

        self.create_widgets()
        self.initialize_world()
        self.update_toggle_buttons()
        self.update_summary_label()
        self.update_memory_label()

    def on_closing(self):
        if self.current_world_path:
            save_history(self.current_world_path, self.history)
        self.root.destroy()

    def tr(self, key, **kwargs):
        return t(self.language, key, **kwargs)

    def world_file_label(self, fname):
        if fname == STORY_CARDS_KEY:
            return self.tr("world_file.story_cards")
        return self.tr(f"world_file.{fname}")

    def on_language_selected(self, value):
        new_lang = "en" if str(value).upper().startswith("EN") else "ru"
        if new_lang == self.language:
            return
        self.language = new_lang
        self.save_global_settings()
        self.apply_language()
        self.add_system_message(self.tr("msg.language_changed", lang_name=self.tr(f"lang.{new_lang}")))

    def apply_language(self):
        self.root.title(self.tr("window_title"))
        if hasattr(self, "title_label"):
            self.title_label.configure(text=self.tr("app_title"))
        if hasattr(self, "lang_var"):
            self.lang_var.set("EN" if self.language == "en" else "RU")
        for btn, key in getattr(self, "top_command_buttons", []):
            btn.configure(text=self.tr(key))
        for btn, key in getattr(self, "action_buttons", []):
            btn.configure(text=self.tr(key))
        if hasattr(self, "send_button"):
            self.send_button.configure(text=self.tr("btn.send"))
        if hasattr(self, "update_toggle_buttons"):
            self.update_toggle_buttons()
        if hasattr(self, "update_summary_label"):
            self.update_summary_label()
        if hasattr(self, "update_memory_label"):
            self.update_memory_label()
        if hasattr(self, "refresh_busy_state"):
            self.refresh_busy_state()
        if hasattr(self, "refresh_world_combobox"):
            self.refresh_world_combobox()
        if hasattr(self, "update_context_indicator"):
            self.update_context_indicator()

    def save_global_settings(self):
        save_global_settings(
            {
                "api_url": self.api_url,
                "api_key": self.api_key,
                "model": self.model,
                "active_api_preset": self.active_api_preset,
                "api_presets": self.api_presets,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "context_size": self.context_size,
                "summary_fill_percent": self.summary_fill_percent,
                "memory_interval": self.memory_interval,
                "memory_top_k": self.memory_top_k,
                "stream_mode": self.stream_mode,
                "summary_enabled": self.summary_enabled,
                "memory_enabled": self.memory_enabled,
                "image_prompt_style": self.image_prompt_style,
                "image_look": self.image_look,
                "image_backend": self.image_backend,
                "comfy_url": self.comfy_url,
                "a1111_url": self.a1111_url,
                "comfy_workflow": self.comfy_workflow,
                "image_width": self.image_width,
                "image_height": self.image_height,
                "image_steps": self.image_steps,
                "image_auto": self.image_auto,
                "image_send_negative": self.image_send_negative,
                "response_limits": self.response_limits,
                "language": self.language,
                "prompt_overrides": self.prompt_overrides,
                "reasoning": bool(self.reasoning),
                "reasoning_max_tokens": self.reasoning_max_tokens,
            }
        )

    def refresh_world_combobox(self):
        names = get_world_list()
        self._world_by_label = {}
        labels = []
        for name in names:
            lang = read_world_language(BASE_DIR / name)
            label = f"{name}  ·  {lang.upper()}" if lang in ("ru", "en") else name
            self._world_by_label[label] = name
            labels.append(label)
        if not labels:
            labels = [self.tr("no_worlds")]

        self.world_combobox.configure(values=labels)
        current = ""
        if self.world_name:
            current = next((label for label, name in self._world_by_label.items() if name == self.world_name), "")

        if current:
            self.world_var.set(current)
        elif labels and labels[0] != self.tr("no_worlds"):
            self.world_var.set(labels[0])
            self.load_world(self._world_by_label[labels[0]])
        else:
            self.world_var.set(self.tr("no_worlds"))

    def on_world_selected(self, selected):
        name = getattr(self, "_world_by_label", {}).get(selected, selected)
        if name and name != self.tr("no_worlds") and name != self.world_name:
            if self.current_world_path:
                save_history(self.current_world_path, self.history)
            self.load_world(name)

    def create_widgets(self):
        main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        main_frame.pack(fill=ctk.BOTH, expand=True, padx=15, pady=15)

        title_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        title_frame.pack(pady=(0, 15))

        self.lang_var = ctk.StringVar(value="EN" if self.language == "en" else "RU")
        self.language_menu = ctk.CTkOptionMenu(
            title_frame,
            variable=self.lang_var,
            values=["RU", "EN"],
            command=self.on_language_selected,
            width=80,
        )
        self.language_menu.pack(side=ctk.RIGHT, padx=(10, 0))

        self.title_label = ctk.CTkLabel(
            title_frame,
            text=self.tr("app_title"),
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["accent"],
        )
        self.title_label.pack(side=ctk.LEFT)

        info_frame = ctk.CTkFrame(main_frame, height=40)
        info_frame.pack(fill=ctk.X, pady=(0, 10))

        self.world_var = ctk.StringVar()
        self.world_combobox = ctk.CTkOptionMenu(
            info_frame, variable=self.world_var, command=self.on_world_selected, width=200
        )
        self.world_combobox.pack(side=ctk.LEFT, padx=10, pady=5)

        add_world_btn = ctk.CTkButton(info_frame, text="+", width=30, command=self.create_world_dialog)
        add_world_btn.pack(side=ctk.LEFT, padx=5, pady=5)

        self.status_label = ctk.CTkLabel(info_frame, text=self.tr("ready"), text_color=COLORS["player_color"])
        self.status_label.pack(side=ctk.RIGHT, padx=10, pady=5)

        self.summary_toggle_btn = ctk.CTkButton(
            info_frame,
            text="",
            width=105,
            height=28,
            command=self.toggle_summary,
            font=ctk.CTkFont(size=11),
        )
        self.summary_toggle_btn.pack(side=ctk.RIGHT, padx=5, pady=5)

        self.summary_label = ctk.CTkLabel(info_frame, text=self.tr("summary_until"), text_color="gray")
        self.summary_label.pack(side=ctk.RIGHT, padx=5, pady=5)

        self.memory_toggle_btn = ctk.CTkButton(
            info_frame,
            text="",
            width=115,
            height=28,
            command=self.toggle_memory,
            font=ctk.CTkFont(size=11),
        )
        self.memory_toggle_btn.pack(side=ctk.RIGHT, padx=5, pady=5)

        self.memory_label = ctk.CTkLabel(info_frame, text=self.tr("memory_until"), text_color="gray")
        self.memory_label.pack(side=ctk.RIGHT, padx=5, pady=5)

        top_button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        top_button_frame.pack(fill=ctk.X, pady=(0, 10))

        self.top_command_buttons = []
        top_commands = [
            ("btn.world_files", self.open_world_files),
            ("btn.cards", self.open_story_cards_editor),
            ("btn.worlds", self.manage_worlds),
            ("btn.ai_settings", self.open_ai_settings),
            ("btn.quit", self.quit_app),
        ]
        for key, cmd in top_commands:
            btn = ctk.CTkButton(top_button_frame, text=self.tr(key), command=cmd, fg_color="transparent", border_width=1)
            btn.pack(side=ctk.LEFT, padx=5)
            self.top_command_buttons.append((btn, key))

        self.text_area = ctk.CTkTextbox(main_frame, wrap=tk.WORD, font=ctk.CTkFont(family="Arial", size=14))
        self.text_area.pack(fill=ctk.BOTH, expand=True, pady=(0, 10))
        self.text_area.bind("<Button-3>", self.show_context_menu)
        self.text_area.bind("<Control-KeyPress>", self.handle_text_shortcut)

        self.text_area._textbox.tag_config("player", foreground=COLORS["player_color"], font=("Arial", 14, "bold"))
        self.text_area._textbox.tag_config("dm", foreground=COLORS["dm_color"], font=("Arial", 14))
        self.text_area._textbox.tag_config("intro", foreground=COLORS["accent"], font=("Arial", 14, "italic"))
        self.text_area._textbox.tag_config("system", foreground=COLORS["system_color"], font=("Arial", 12, "italic"))
        self.text_area.configure(state="disabled")

        # Полоса показывает, сколько новой истории накопилось с последней
        # суммаризации — относительно места, которое для неё ещё есть в окне.
        context_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        context_frame.pack(fill=ctk.X, pady=(0, 8))
        self.context_label = ctk.CTkLabel(context_frame, text="", text_color="gray")
        self.context_label.pack(side=ctk.RIGHT, padx=(8, 0))
        self.context_bar = ctk.CTkProgressBar(context_frame, height=8)
        self.context_bar.pack(side=ctk.LEFT, fill=ctk.X, expand=True)
        self.context_bar.set(0)
        self.context_tokens = 0
        self.update_context_indicator()

        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill=ctk.X, pady=(0, 10))

        btn_args = {"height": 28, "font": ctk.CTkFont(size=11)}
        row1 = ctk.CTkFrame(button_frame, fg_color="transparent")
        row1.pack(fill=ctk.X, pady=(0, 4))
        row2 = ctk.CTkFrame(button_frame, fg_color="transparent")
        row2.pack(fill=ctk.X)

        self.action_buttons = []
        row1_commands = [
            ("btn.next", self.prompt_next_turn),
            ("btn.reroll", self.regenerate_action),
            ("btn.edit_last", self.edit_last_message),
            ("btn.prompt", self.show_last_prompt),
        ]
        row2_commands = [
            ("btn.summary", self.force_summary),
            ("btn.memory", self.show_memory_bank),
            ("btn.scene_prompt", self.generate_scene_prompt),
            ("btn.undo", self.undo_action),
        ]

        for key, cmd in row1_commands:
            btn = ctk.CTkButton(row1, text=self.tr(key), command=cmd, **btn_args)
            btn.pack(side=ctk.LEFT, padx=3, expand=True, fill=ctk.X)
            self.action_buttons.append((btn, key))

        for key, cmd in row2_commands:
            btn_kwargs = dict(btn_args)
            if cmd == self.undo_action:
                btn_kwargs.update(fg_color=COLORS["danger"], hover_color=COLORS["danger_hover"])
            btn = ctk.CTkButton(row2, text=self.tr(key), command=cmd, **btn_kwargs)
            btn.pack(side=ctk.LEFT, padx=3, expand=True, fill=tk.X)
            self.action_buttons.append((btn, key))

        input_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        input_frame.pack(fill=ctk.X)

        self.input_field = ctk.CTkTextbox(input_frame, height=70, wrap=tk.WORD, font=ctk.CTkFont(size=14))
        self.input_field.pack(side=ctk.LEFT, fill=ctk.X, expand=True, padx=(0, 10))
        self.input_field.bind("<Return>", self.handle_input_enter)
        self.input_field.bind("<Button-3>", self.show_context_menu)
        self.input_field.bind("<Control-KeyPress>", self.handle_text_shortcut)
        self.input_field.focus()

        self.send_button = ctk.CTkButton(
            input_frame,
            text=self.tr("btn.send"),
            command=self.on_send_or_stop,
            fg_color=COLORS["accent"],
            hover_color=COLORS["button_hover"],
            text_color="black",
            font=ctk.CTkFont(weight="bold"),
            width=120,
            height=70,
        )
        self.send_button.pack(side=ctk.RIGHT)

        # Esc останавливает генерацию — как в привычных чатах
        self.input_field.bind("<Escape>", self.handle_escape)
        self.text_area.bind("<Escape>", self.handle_escape)

    def update_toggle_buttons(self):
        if self.summary_enabled:
            self.summary_toggle_btn.configure(
                text=self.tr("toggle.summary_on"),
                fg_color=COLORS["player_color"],
                hover_color=COLORS["player_color"],
            )
        else:
            self.summary_toggle_btn.configure(text=self.tr("toggle.summary_off"), fg_color="gray40", hover_color="gray50")

        if self.memory_enabled:
            self.memory_toggle_btn.configure(
                text=self.tr("toggle.memory_on"),
                fg_color=COLORS["player_color"],
                hover_color=COLORS["player_color"],
            )
        else:
            self.memory_toggle_btn.configure(text=self.tr("toggle.memory_off"), fg_color="gray40", hover_color="gray50")

    def toggle_summary(self):
        self.summary_enabled = not self.summary_enabled
        self.save_global_settings()
        self.update_toggle_buttons()
        self.update_summary_label()
        state = self.tr("summary_enabled_word" if self.summary_enabled else "summary_disabled_word")
        self.add_system_message(self.tr("msg.summary_toggled", state=state))

    def toggle_memory(self):
        self.memory_enabled = not self.memory_enabled
        self.save_global_settings()
        self.update_toggle_buttons()
        self.update_memory_label()
        state = self.tr("memory_enabled_word" if self.memory_enabled else "memory_disabled_word")
        self.add_system_message(self.tr("msg.memory_toggled", state=state))

    def update_summary_label(self):
        if not hasattr(self, "summary_label"):
            return
        if not self.current_world_path:
            self.summary_label.configure(text=self.tr("summary_until"), text_color="gray")
            return
        if not self.summary_enabled:
            self.summary_label.configure(text=self.tr("summary.off"), text_color="gray")
            return
        percent = int(round(self.context_ratio * 100))
        self.summary_label.configure(
            text=self.tr("summary.fill", percent=percent),
            text_color=self._context_fill_color(self.context_ratio),
        )

    def update_memory_label(self):
        if not self.current_world_path:
            self.memory_label.configure(text=self.tr("memory_until"))
            return
        if not self.memory_enabled:
            entries_count = len(self.memory_bank.get("entries", []))
            self.memory_label.configure(text=self.tr("memory.off", n=entries_count), text_color="gray")
            return
        remaining = max(0, self.memory_interval - self.turns_since_memory)
        color = COLORS["accent"] if remaining <= 1 else "gray"
        entries_count = len(self.memory_bank.get("entries", []))
        self.memory_label.configure(text=self.tr("memory.until", n=entries_count, remaining=remaining), text_color=color)

    def _context_fill_color(self, ratio):
        """Зелёный далеко от порога, жёлтый при приближении, красный на пороге и выше."""
        threshold = max(1, int(self.summary_fill_percent)) / 100
        if ratio >= threshold:
            return COLORS["danger"]
        if ratio >= threshold * 0.75:
            return COLORS["accent"]
        return COLORS["player_color"]

    def update_context_indicator(self):
        """Показывает заполнение контекста новой историей с последней суммаризации."""
        used, budget, ratio = self.context_fill_state()
        self.context_tokens = used
        self.context_budget = max(1, int(budget))
        self.context_ratio = ratio
        color = self._context_fill_color(self.context_ratio)
        self.context_bar.set(min(1.0, self.context_ratio))
        self.context_bar.configure(progress_color=color)
        self.context_label.configure(
            text=self.tr(
                "context.since_summary",
                used=format_token_count(self.context_tokens),
                total=format_token_count(self.context_budget),
            ),
            text_color=color,
        )
        self.update_summary_label()
