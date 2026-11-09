import re

PLAYER_PREFIX = "Игрок:"
DM_PREFIX = "Мастер:"
INTRO_PREFIX = "Вступление:"

TRANSLATIONS = {
    "ru": {
        "lang.ru": "Русский",
        "lang.en": "English",
        "window_title": "AI Dungeon Master",
        "app_title": "AI DUNGEON MASTER",
        "no_worlds": "Нет миров",
        "worlds.lang.ru": "Русские",
        "worlds.lang.en": "Английские",
        "ready": "Готов",
        "summary_until": "До суммаризации: -",
        "memory_until": "До памяти: -",
        "btn.world_files": "Файлы мира",
        "btn.cards": "Карточки",
        "btn.worlds": "Миры",
        "btn.ai_settings": "Настройки",
        "btn.quit": "Выйти",
        "btn.next": "Дальше?",
        "btn.reroll": "Реролл",
        "btn.edit_last": "Редактировать",
        "btn.prompt": "Промпт",
        "btn.scene_prompt": "Промпт сцены",
        "btn.scene_image": "Сгенерировать изображение",
        "btn.gallery": "Библиотека",
        "btn.summary": "Суммаризация",
        "btn.memory": "Память",
        "btn.undo": "Отменить ход",
        "btn.send": "Отправить",
        "btn.make_move": "Сделать ход",
        "btn.menu": "Меню",
        "btn.models": "Модели",
        "btn.modes": "Режимы",
        "mode.sandbox": "Песочница",
        "mode.adventure": "Приключение",
        "models.empty": "Нет сохранённых конфигураций",
        "dialog.section_sandbox_mechanics": "Механики приключения",
        "dialog.sandbox_d20": "Проверка d20",
        "dialog.sandbox_hero": "Карточка героя",
        "dialog.sandbox_npc": "Автокарточки встреч",
        "hero.title": "Карточка героя",
        "hero.name": "Имя",
        "hero.appearance": "Внешность",
        "hero.equipment": "Снаряжение",
        "hero.strength": "Сила",
        "hero.dexterity": "Ловкость",
        "hero.constitution": "Телосложение",
        "hero.intelligence": "Интеллект",
        "hero.wisdom": "Мудрость",
        "hero.charisma": "Харизма",
        "hero.required": "Заполните карточку героя, чтобы начать ход.",
        "hero.confirm_title": "Изменить характеристики?",
        "hero.confirm_hint": "Сцена предлагает изменить характеристики. Снаряжение и внешность уже записаны.",
        "hero.confirm": "Применить",
        "hero.reject": "Оставить как есть",
        "check.success": "успех",
        "check.fail": "провал",
        "check.fact": "Проверка «{name}» (сложность {dc}): выпало {roll} — {result}.",
        "check.cue.critical_success": "Игрок критически успешно сделал ход. Описывай это как блестящий, безоговорочный успех.",
        "check.cue.success": "Игрок успешно сделал ход. Описывай соответствующим образом.",
        "check.cue.failure": "Игрок неудачно сделал ход. Описывай соответствующим образом.",
        "check.cue.critical_failure": "Игрок критически провалил ход. Описывай это как тяжёлый, явный провал.",
        "btn.create": "Создать",
        "btn.create_ok": "Создать",
        "btn.cancel": "Отмена",
        "btn.cancel_plain": "Отмена",
        "btn.close": "Закрыть",
        "btn.close_x": "Закрыть",
        "btn.save": "Сохранить",
        "btn.save_ok": "Сохранить",
        "btn.save_as": "Сохранить как...",
        "btn.delete": "Удалить",
        "btn.delete_icon": "Удалить",
        "btn.load": "Загрузить",
        "btn.export": "Экспорт",
        "btn.import": "Импорт",
        "btn.add": "Добавить",
        "btn.copy": "Копировать",
        "btn.index_now": "Индексировать сейчас",
        "toggle.summary_on": "Сумм.: ВКЛ",
        "toggle.summary_off": "Сумм.: ВЫКЛ",
        "toggle.memory_on": "Память: ВКЛ",
        "toggle.memory_off": "Память: ВЫКЛ",
        "summary.off": "Сумм.: выкл",
        "summary.fill": "Сумм.: {percent}%",
        "memory.off": "Память: {n} | выкл",
        "memory.until": "Память: {n} | до инд.: {remaining}",
        "context.since_summary": "С суммаризации: {used} / {total}",
        "btn.stop": "Стоп",
        "status.generating": "Генерация...",
        "status.scene_prompt": "Промпт сцены...",
        "status.scene_image": "Изображение сцены...",
        "status.summary_memory": "Суммаризация и память...",
        "status.summary": "Суммаризация...",
        "status.memory": "Индексация памяти...",
        "menu.select_all": "Выделить всё",
        "menu.copy": "Копировать",
        "menu.paste": "Вставить",
        "menu.cut": "Вырезать",
        "dialog.manage_worlds": "Управление мирами",
        "dialog.your_worlds": "Ваши миры:",
        "dialog.delete_world": "Удалить мир",
        "dialog.delete_world_q": "Удалить мир '{name}' безвозвратно?",
        "dialog.create_world": "Создать новый мир",
        "dialog.world_name": "Название мира (папка):",
        "dialog.default_world_name": "Новый мир",
        "dialog.bad_name": "Ошибка",
        "dialog.bad_name_msg": "Некорректное или занятое имя",
        "dialog.busy": "Дождитесь окончания текущего действия.",
        "dialog.import_failed": "Архив мира не подошёл. Нужен zip с файлами этого мира.",
        "log.earlier": "Раньше",
        "dialog.world_files": "Файлы мира",
        "dialog.choose_file": "Выберите файл:",
        "dialog.unsaved": "Есть несохранённые изменения",
        "dialog.attention": "Внимание",
        "dialog.file_unsaved": "В файле «{label}» есть изменения. Сохранить?",
        "dialog.close_unsaved": "Есть несохранённые изменения. Сохранить перед закрытием?",
        "dialog.cards_title": "Карточки историй",
        "dialog.cards_need_world": "Сначала выберите или создайте мир.",
        "dialog.next_title": "Дальше?",
        "dialog.next_hint": "Опишите, что должно произойти в следующем ходу.\nИИ реализует это в повествовании.",
        "dialog.empty_input": "Пустой ввод",
        "dialog.empty_next": "Опишите, что должно произойти дальше.",
        "dialog.ai_settings": "Настройки",
        "dialog.tab_ai": "Настройки ИИ",
        "dialog.tab_game": "Настройки игры",
        "dialog.lan_title": "Телефон в той же сети",
        "dialog.lan_access": "Открыть игру для локальной сети",
        "dialog.lan_hint": "Оставьте компьютер включённым и откройте на телефоне адрес ниже. Телефон должен быть в той же сети Wi-Fi. Страницу увидят устройства в этой сети. Новое значение заработает после сохранения и перезапуска сервера.",
        "dialog.lan_restart": "Сохраните настройки и перезапустите сервер, чтобы адрес начал открываться.",
        "dialog.lan_this_computer": "Этот компьютер",
        "dialog.lan_phone": "Телефон",
        "dialog.lan_tailscale": "Tailscale",
        "dialog.lan_none": "Адрес в сети не найден. Подключите компьютер к Wi-Fi и перезапустите сервер.",
        "dialog.tab_prompts": "Настройки промптов",
        "dialog.section_summary": "Суммаризация",
        "dialog.section_memory": "Банк памяти",
        "dialog.prompt_fields": "Обязательные поля: {fields}",
        "dialog.prompt_fields_none": "Обязательных полей нет.",
        "dialog.prompt_missing_fields": "В промпте «{name}» не хватает полей: {fields}.",
        "dialog.prompt_unknown_fields": "В промпте «{name}» есть неизвестные поля: {fields}.",
        "dialog.prompt_broken": "Промпт «{name}» нельзя подставить: проверьте фигурные скобки.",
        "dialog.prompt_invalid_title": "Промпт",
        "prompt_group.turn": "Ход",
        "prompt_group.summary": "Суммаризация",
        "prompt_group.memory": "Память",
        "prompt_group.cards": "Карточки",
        "prompt_group.scene": "Сцена",
        "prompt_name.continue": "Продолжение хода",
        "prompt_name.direction": "Направление автора",
        "prompt_name.no_reasoning": "Без размышлений",
        "prompt_name.history_header": "Заголовок истории",
        "prompt_name.summary": "Суммаризация",
        "prompt_name.summary_compress": "Сжатие содержания",
        "prompt_name.summary_header": "Заголовок хроники",
        "prompt_name.none": "Пустое значение",
        "prompt_name.memory_index": "Индексация памяти",
        "prompt_name.memory_header": "Заголовок памяти",
        "prompt_name.card_desc_gen": "Описание карточки",
        "prompt_name.cards_header": "Заголовок карточек",
        "prompt_name.card_triggers": "Триггеры карточки",
        "prompt_name.card_always": "Всегда активная карточка",
        "prompt_name.cards_missing": "Нет карточек",
        "prompt_name.scene_image": "Промпт сцены",
        "prompt_name.scene_style.sd": "Стиль Stable Diffusion",
        "prompt_name.scene_style.midjourney": "Стиль Midjourney",
        "prompt_name.scene_style.flux": "Стиль Flux",
        "prompt_name.scene_style.generic": "Универсальный стиль",
        "prompt_name.scene_look.anime": "Стиль: аниме",
        "prompt_name.scene_look.realism": "Стиль: реализм",
        "prompt_name.scene_look.painting": "Стиль: живопись",
        "prompt_name.scene_look.cinematic": "Стиль: кино",
        "btn.reset_prompt": "Сбросить",
        "dialog.api_config": "Конфигурация API",
        "dialog.manual_preset": "— Вручную —",
        "dialog.save_preset": "Сохранить конфигурацию",
        "dialog.preset_name": "Название конфигурации:",
        "dialog.delete_preset_info": "Удаление",
        "dialog.delete_preset_pick": "Выберите сохранённую конфигурацию для удаления.",
        "dialog.delete_preset": "Удалить конфигурацию",
        "dialog.delete_preset_q": "Удалить конфигурацию «{name}»?",
        "dialog.api_url": "URL API (Chat Completions):",
        "dialog.api_key": "API-ключ (необязательно):",
        "dialog.show_key": "Показать ключ",
        "dialog.model": "Модель (необязательно):",
        "dialog.reasoning": "Рассуждение",
        "dialog.reasoning_max_tokens": "Макс. токенов рассуждения:",
        "log.reasoning": "Рассуждение",
        "log.reasoning_hidden": "Модель рассуждала, но не прислала текст.",
        "dialog.gen_params": "Параметры генерации",
        "dialog.stream": "Показывать ответ по мере генерации",
        "dialog.auto_summary": "Автосуммаризация",
        "dialog.memory_bank": "Банк памяти",
        "dialog.temperature": "Температура (0.0 - 2.0):",
        "dialog.max_tokens": "Макс. токенов в ответе:",
        "dialog.response_limit": "Макс. токенов в ответе этого промпта:",
        "dialog.context_size": "Размер контекста:",
        "dialog.summary_fill": "Автосуммаризация при заполнении (%):",
        "dialog.memory_every": "Банк памяти (индексация каждые N ходов):",
        "dialog.memory_top_k": "Макс. воспоминаний в промпте:",
        "dialog.image_style": "Формат промпта для изображений:",
        "dialog.image_look": "Стиль изображения:",
        "image_style.sd": "Stable Diffusion (теги, веса)",
        "image_style.midjourney": "Midjourney (--параметры)",
        "image_style.flux": "Flux (естественный текст)",
        "image_style.generic": "Универсальный (текст)",
        "image_look.none": "Без стиля",
        "image_look.anime": "Аниме",
        "image_look.realism": "Реализм",
        "image_look.painting": "Живопись",
        "image_look.cinematic": "Кино",
        "dialog.section_image": "Генератор изображений",
        "dialog.image_backend": "Куда отправлять промпт:",
        "image_backend.off": "Не отправлять",
        "image_backend.comfy": "ComfyUI",
        "image_backend.a1111": "Automatic1111 / Forge",
        "dialog.comfy_url": "Адрес ComfyUI:",
        "dialog.a1111_url": "Адрес Automatic1111 / Forge:",
        "dialog.comfy_workflow": "Файл workflow (API format):",
        "dialog.workflow_empty": "В папке workflows нет файлов JSON.",
        "dialog.workflow_hint": "Положите экспорт Save (API Format) в папку workflows рядом с worlds.",
        "dialog.image_width": "Ширина:",
        "dialog.image_height": "Высота:",
        "dialog.image_steps": "Шаги:",
        "dialog.image_auto": "Сразу отправлять готовый промпт в генератор",
        "dialog.image_send_negative": "Отправлять антипромпт",
        "dialog.image_test": "Проверить подключение",
        "dialog.language": "Язык интерфейса:",
        "dialog.quit": "Выход",
        "dialog.quit_q": "Действительно выйти из игры?",
        "dialog.edit_dm": "Редактировать ответ",
        "dialog.edit_dm_label": "Редактирование ответа:",
        "dialog.edit_player": "Редактировать ход",
        "dialog.edit_player_label": "Редактирование вашего действия:",
        "dialog.edit_prev": "Пред.",
        "dialog.edit_next": "След. ",
        "dialog.prompt_title": "Последний промпт",
        "dialog.no_prompt": "Нет данных о запросе.",
        "dialog.prompt_time": "=== ВРЕМЯ ЗАПРОСА ===\n{time}\n\n=== ПРИМЕРНОЕ КОЛ-ВО ТОКЕНОВ ===\n{tokens}\n\n",
        "dialog.prompt_body": "=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n",
        "dialog.memory_title": "Банк памяти",
        "dialog.no_world": "Мир не выбран.",
        "dialog.memory_empty": "Банк памяти пуст. Записи появятся после нескольких ходов.",
        "dialog.memory_stats": "Записей: {n} | Проиндексировано ходов: {turns}",
        "dialog.memory_entry": "=== {id} | ходы {start}-{end} ===\nКлючи: {keys}\nNPC: {npcs} | Локация: {location}\n{summary}\n",
        "dialog.no_worlds_title": "Нет миров",
        "dialog.no_worlds_q": "У вас нет ни одного мира. Создать новый?",
        "cards.list": "Карточки:",
        "cards.search": "Поиск карточек...",
        "cards.title": "Название:",
        "cards.desc": "Описание:",
        "cards.triggers": "Триггеры (через запятую — ключевые слова для подтягивания карточки):",
        "cards.triggers_ph": "арион, таверна, меч",
        "cards.empty_triggers": "Пустые триггеры = карточка всегда активна в промпте",
        "cards.untitled": "Без названия",
        "cards.new": "Новая карточка",
        "cards.delete": "Удалить",
        "cards.delete_q": "Удалить выбранную карточку?",
        "cards.save_with_world": "Сохранятся вместе с миром",
        "cards.generate_desc": "Сгенерировать описание",
        "cards.generating": "Генерация описания...",
        "cards.generate_desc_title": "Генерация описания карточки",
        "cards.enter_title_first": "Сначала введите название карточки",
        "scene.prompt_label": "Промпт",
        "scene.negative_label": "Антипромпт",
        "scene.wish": "Что показать",
        "scene.wish_hint": "Пустое поле — кадр по последней сцене.",
        "scene.format": "Формат модели",
        "scene.look": "Стиль",
        "scene.copy_prompt": "Копировать промпт",
        "scene.copy_negative": "Копировать антипромпт",
        "scene.copied_prompt": "Промпт сцены скопирован.",
        "scene.copied_negative": "Антипромпт скопирован.",
        "scene.generating": "Создание промпта...",
        "scene.stop": "Стоп",
        "scene.needs_world": "Сначала загрузите мир.",
        "scene.needs_history": "Нужна хотя бы одна реплика мастера в истории.",
        "scene.needs_prompt": "Сначала нужен промпт сцены.",
        "scene.image_alt": "Изображение сцены",
        "scene.image_off": "Генератор изображений выключен. Включите его в настройках.",
        "gallery.empty": "В этом мире ещё нет изображений.",
        "gallery.delete": "Удалить",
        "gallery.delete_q": "Удалить это изображение?",
        "scene.image_test_ok": "Генератор отвечает.",
        "scene.image_missing_workflow": "Не найден файл workflow: {msg}",
        "scene.image_ui_workflow": "Это обычный файл ComfyUI. Нужен экспорт Save (API Format).",
        "scene.image_bad_workflow": "Файл workflow не читается: {msg}",
        "scene.image_no_nodes": "В workflow не найдены узлы положительного промпта.",
        "scene.image_offline": "Генератор изображений не запущен или адрес неверный.",
        "scene.image_rejected": "Генератор отклонил запрос: {msg}",
        "scene.image_empty": "Генератор не вернул изображение.",
        "scene.image_timeout": "Генератор не успел закончить изображение.",
        "dialog.corrupt_title": "Повреждённые данные",
        "dialog.corrupt_history": "Мир «{name}» не загружен: файл {file} повреждён и не читается даже из резервной копии.\n\nИстория не изменена — её можно починить вручную.\nПодробности: {detail}\n\nРезервная копия лежит рядом: {file}.bak",
        "on": "ВКЛ",
        "off": "ВЫКЛ",
        "summary_enabled_word": "включена",
        "summary_disabled_word": "выключена",
        "memory_enabled_word": "включён",
        "memory_disabled_word": "выключён",
        "msg.cards_saved": "Карточки историй сохранены",
        "msg.file_saved": "Файл {name} сохранён",
        "msg.preset_saved": "Конфигурация API «{name}» сохранена.",
        "msg.settings_saved": "Настройки сохранены. API: {api}{model}{preset}. Стриминг: {stream}. Суммаризация: {summary}. Память: {memory}.",
        "msg.model_part": ", модель: {model}",
        "msg.preset_part": ", конфиг: {name}",
        "msg.dm_edited": "Ответ Мастера изменен.",
        "msg.player_edited": "Ваш ход изменен.",
        "msg.force_summary": "Принудительное обновление краткого содержания...",
        "msg.prompt_copied": "Промпт скопирован.",
        "msg.force_memory": "Принудительная индексация памяти...",
        "msg.summary_toggled": "Автосуммаризация {state}.",
        "msg.memory_toggled": "Банк памяти {state}.",
        "msg.welcome": "Добро пожаловать! Создайте новый мир через кнопку «Миры».",
        "msg.world_loaded": "Мир '{name}' загружен.",
        "msg.undone": "Последнее сообщение удалено.",
        "msg.no_memory_turns": "Нет новых ходов для индексации.",
        "msg.memory_entry": "Память [{id}]: {summary}... (ключи: {keys})",
        "msg.memory_offline": "Банк памяти: сервер ИИ недоступен.",
        "msg.memory_error": "Ошибка индексации памяти: {msg}",
        "msg.empty_model": "Модель вернула пустой ответ.",
        "msg.tokens": "Токены: Контекст: {p} | Ответ: {c} | Всего: {t}/{ctx}",
        "msg.reviewing": "ИИ пересматривает хронологию...",
        "msg.no_server": "Ошибка: Локальный сервер ИИ не запущен!",
        "msg.error": "Ошибка: {msg}",
        "msg.summary_ok": "Краткое содержание мира успешно синхронизировано!",
        "msg.summary_fail": "Не удалось автоматически обновить саммари: {msg}",
        "msg.history_restored": "История восстановлена из резервной копии (файл был повреждён).",
        "msg.stop_requested": "Останавливаю генерацию...",
        "msg.scene_prompt_done": "Промпт сцены готов.",
        "msg.scene_prompt_fail": "Не удалось создать промпт сцены: {msg}",
        "msg.scene_image_done": "Изображение сцены готово.",
        "msg.scene_image_fail": "Не удалось создать изображение: {msg}",
        "msg.image_stopped": "Генерация изображения остановлена.",
        "msg.action_stopped": "Генерация остановлена. Ответ сохранён частично — его можно отредактировать или удалить.",
        "msg.summary_stopped": "Суммаризация остановлена.",
        "msg.memory_stopped": "Индексация памяти остановлена.",
        "msg.language_changed": "Язык интерфейса: {lang_name}",
        "world_file.introduction.txt": "Вступление",
        "world_file.ai_instructions.txt": "Инструкции ИИ",
        "world_file.plot_basics.txt": "Основы сюжета",
        "world_file.author_notes.txt": "Авторские пометки",
        "world_file.summary.txt": "Краткое содержание",
        "world_file.story_cards": "Карточки историй",
        "hist.player": "Игрок:",
        "hist.dm": "Мастер:",
        "hist.intro": "Вступление:",
        "prompt.continue": "(Продолжай повествование.)",
        "prompt.check": """Нужна ли проверка d20 для этого действия игрока?
Осмотр и спокойный разговор без риска — без проверки.
Если проверка нужна, назови её и выбери сложность только из 10, 13, 16, 19.
Ответь только JSON:
{{"needed": false}}
или
{{"needed": true, "name": "название проверки", "dc": 13}}

Действие:
{action}""",
        "prompt.followup": """По последнему ходу реши, изменились ли герой и список важных персонажей.
Снаряжение и внешность указывай только если сцена реально их меняет. Иначе пустая строка.
Характеристики предлагай только при реальном изменении. Иначе пустой объект.
Ключи характеристик: strength, dexterity, constitution, intelligence, wisdom, charisma.
В characters включай только персонажа с именем, который либо вернётся в сюжете (returns), либо участвует в конфликте (conflict).
Безымянную стражу не включай.

Герой:
{hero}

Действие игрока:
{action}

Ответ мастера:
{reply}

Только JSON:
{{"equipment": "", "appearance": "", "stats": {{}}, "characters": [{{"name": "", "description": "", "triggers": [], "returns": false, "conflict": false}}]}}""",
        "prompt.hero_block": """=== ГЕРОЙ ===
Имя: {name}
Внешность: {appearance}
Снаряжение: {equipment}
Сила: {strength}; Ловкость: {dexterity}; Телосложение: {constitution}; Интеллект: {intelligence}; Мудрость: {wisdom}; Харизма: {charisma}
""",
        "prompt.direction": "Автор задаёт направление следующего хода:\n{hint}\n\nРеализуй это в повествовании органично, сохраняя стиль, контекст и правила мира. Не упоминай, что это «задание от автора» — просто развивай сюжет.",
        "prompt.no_reasoning": "ВАЖНО: Отвечай сразу, без размышлений, анализа или внутренних монологов. Не используй теги <think>, <thinking>, <reasoning> или подобные. Начинай ответ сразу с повествования.",
        "prompt.summary_header": "=== Сжатая хроника прошлых событий (summary.txt) ===\n{text}\n",
        "prompt.history_header": "ИСТОРИЯ ТЕКУЩЕЙ ИГРОВОЙ СЕССИИ:",
        "prompt.memory_header": "=== РЕЛЕВАНТНЫЕ ВОСПОМИНАНИЯ (банк памяти) ===\n",
        "prompt.cards_header": "=== РЕЛЕВАНТНЫЕ КАРТОЧКИ ИСТОРИИ ===\n",
        "prompt.card_triggers": "(триггеры: {triggers})",
        "prompt.card_always": "(всегда активна)",
        "prompt.cards_missing": "Информация отсутствует.",
        "prompt.none": "Отсутствует.",
        "prompt.memory_index": """Проанализируй фрагмент текстовой RPG-сессии.
Сделай:
1. summary — 2-4 предложения, только ключевые события и факты (имена, предметы, решения)
2. keys — до 3 ключевых СЛОВ (не словосочетаний) для поиска, только самые важные! (имена NPC, локации, предметы, события)
3. location — текущая локация или null
4. npcs — список упомянутых NPC

ФРАГМЕНТ:
{fragment}

Ответь ТОЛЬКО валидным JSON:
{{"summary": "...", "keys": ["...", "..."], "location": "...", "npcs": ["..."]}}""",
        "prompt.summary": """Перед тобой история текстовой ролевой игры и её старое содержание.
Твоя задача: составить обновленное, чистое и емкое КРАТКОЕ СОДЕРЖАНИЕ (summary).
ПРАВИЛА:
1. Сформируй краткую историю в хронологическом порядке.
2. Игнорируй мелкую рутину.
3. Пиши лаконично, тезисно.
4. Учти СТАРОЕ краткое содержание.

СТАРОЕ КРАТКОЕ СОДЕРЖАНИЕ:
{old_summary}

АКТУАЛЬНАЯ ИСТОРИЯ ИГРЫ:
{history}

Выдай только текст нового краткого содержания простым текстом без лишних *, вступлений и Markdown.""",
        "prompt.summary_compress": "Краткое содержание слишком большое, сожми его: убери повторы и мелкие детали, оставь важное. Новый текст должен быть короче старого.",
        "prompt.card_desc_gen": """Ты помогаешь пользователю создать описание для карточки истории в текстовой RPG.

Контекст мира:
{world_context}

Название карточки: {card_title}

Базовая информация (plot_basics):
{plot_basics}

Авторские пометки:
{author_notes}

Фрагмент истории для контекста:
{history_fragment}

Создай подробное описание карточки (~5 предложений) в контексте этого мира. Опиши персонажа, локацию или объект, его характеристики, роль в мире. Не используй Markdown, пиши обычным текстом.
Описание:""",
        "prompt.scene_image": """Ты составляешь промпт для генерации изображения текущей сцены текстовой RPG.

Основы сюжета:
{plot_basics}

Недавние события (последние ходы):
{history_fragment}

Релевантные карточки истории:
{cards_block}

{style_rules}

Ограничения по содержанию снимаются: NSFW, насилие, кровь и эротические элементы разрешены и должны описываться прямо и без цензуры, если они соответствуют сцене.

Верни СТРОГО один JSON-объект без пояснений и без Markdown, с двумя полями:
{{"prompt": "<текст промпта>", "negative_prompt": "<анти-промпт: что НЕ должно быть на изображении>"}}""",
        "prompt.scene_wish": """Пожелание игрока к кадру:
{wish}

Изобрази это пожелание. Сохрани формат и стиль промпта выше. Не подменяй пожеланием всю сцену, если оно только уточняет кадр.""",
        "prompt.scene_style.sd": """Создай один подробный визуальный промпт для текущей сцены в формате Stable Diffusion / SDXL.

ФОРМАТ: теги через запятую, как в тегах бустимилков (Danbooru). Порядок тегов: количество людей на рисунке (например 2girls, 1boy), главный объект, детали внешности, одежда и снаряжение, действие и поза, окружение, время суток и освещение, стиль и качество. Активно используй веса тегов. Вес тега указывай скобками: (красные волосы:1.2). Не используй точки, связные предложения и слова вроде «изображение», «фото», «рисунок».

Делай предпочтение изображению от первого лица главного героя (если композиция позваляет).
В промт добавляй детали окружения, детали которые бы отражали характер персонажей, даже если они не указаны.

Теги качества добавь в конец промпта: masterpiece, best quality, highly detailed, sharp focus.

Анти-промпт пиши теми же тегами через запятую и не включай в него NSFW и насилие: lowres, worst quality, low quality, jpeg artifacts, blurry, bad anatomy, bad hands, extra fingers, extra limbs, fused fingers, malformed limbs, deformed, disfigured, extra digits, fewer digits, cropped, out of frame, text, signature, watermark, logo.""",
        "prompt.scene_style.midjourney": """Создай один подробный визуальный промпт для текущей сцены в формате Midjourney.

ФОРМАТ: связное естественное описание на английском языке, одним абзацем. Описывай только то, что видно: персонажей (внешность, одежду, позы), окружение, время суток, освещение, настроение, ракурс и композицию. Не используй теги через запятую, веса в скобках и технические термины вроде «8k».

В конце добавь параметры Midjourney: --ar 16:9 --style raw --v 7

Анти-промпт опиши словами, а не тегами: перечисли, чего не должно быть на изображении (например: extra fingers, text, watermark, distorted anatomy). Не включай в него NSFW и насилие.""",
        "prompt.scene_style.flux": """Создай один подробный визуальный промпт для текущей сцены в формате Flux / естественный текст.

ФОРМАТ: связное описание на английском языке, 2-4 предложения, в порядке: кто и что в кадре, внешность и одежда персонажей, действие, окружение, освещение, стиль и настроение. Не используй теги через запятую, веса в скобках и служебные слова вроде «negative prompt», «quality».

Теги качества в конце не нужны — Flux их игнорирует.

Анти-промпт — отдельное связное предложение, описывающее, чего не должно быть на изображении (например: «artifacts, extra fingers, text, watermark, distorted anatomy»). Не включай в него NSFW и насилие.""",
        "prompt.scene_style.generic": """Создай один подробный визуальный промпт для текущей сцены.

ФОРМАТ: связное описание на английском языке, 2-4 предложения. Описывай только то, что видно: персонажей (внешность, одежду, позы), окружение, время суток, освещение, стиль, настроение, ракурс и композицию. Не используй теги через запятую и веса в скобках.

Анти-промпт — отдельное связное предложение, описывающее, чего не должно быть на изображении. Не включай в него NSFW и насилие.""",
        "prompt.scene_look.anime": """СТИЛЬ ИЗОБРАЖЕНИЯ: аниме.
Впиши это описание стиля в поле prompt, в том же формате, что и остальной промпт: anime style, cel shading, clean lineart, expressive eyes, vibrant colors.
Не делай сцену фотореалистичной.""",
        "prompt.scene_look.realism": """СТИЛЬ ИЗОБРАЖЕНИЯ: реализм.
Впиши это описание стиля в поле prompt, в том же формате, что и остальной промпт: photorealistic, realistic skin, natural lighting, lifelike proportions, detailed materials.
Не используй аниме, мультяшность и рисованный контур.""",
        "prompt.scene_look.painting": """СТИЛЬ ИЗОБРАЖЕНИЯ: живопись.
Впиши это описание стиля в поле prompt, в том же формате, что и остальной промпт: oil painting, visible brushstrokes, painterly light, fine art.""",
        "prompt.scene_look.cinematic": """СТИЛЬ ИЗОБРАЖЕНИЯ: кино.
Впиши это описание стиля в поле prompt, в том же формате, что и остальной промпт: cinematic still, dramatic lighting, shallow depth of field, film color grade.""",
    },
    "en": {
        "lang.ru": "Русский",
        "lang.en": "English",
        "window_title": "AI Dungeon Master",
        "app_title": "AI DUNGEON MASTER",
        "no_worlds": "No worlds",
        "worlds.lang.ru": "Russian",
        "worlds.lang.en": "English",
        "ready": "Ready",
        "summary_until": "Until summary: -",
        "memory_until": "Until memory: -",
        "btn.world_files": "World files",
        "btn.cards": "Cards",
        "btn.worlds": "Worlds",
        "btn.ai_settings": "Settings",
        "btn.quit": "Quit",
        "btn.next": "What next?",
        "btn.reroll": "Reroll",
        "btn.edit_last": "Edit last",
        "btn.prompt": "Prompt",
        "btn.scene_prompt": "Scene Prompt",
        "btn.scene_image": "Generate image",
        "btn.gallery": "Library",
        "btn.summary": "Summarize",
        "btn.memory": "Memory",
        "btn.undo": "Undo turn",
        "btn.send": "Send",
        "btn.make_move": "Take a turn",
        "btn.menu": "Menu",
        "btn.models": "Models",
        "btn.modes": "Modes",
        "mode.sandbox": "Sandbox",
        "mode.adventure": "Adventure",
        "models.empty": "No saved configurations",
        "dialog.section_sandbox_mechanics": "Adventure mechanics",
        "dialog.sandbox_d20": "d20 check",
        "dialog.sandbox_hero": "Hero card",
        "dialog.sandbox_npc": "Automatic encounter cards",
        "hero.title": "Hero card",
        "hero.name": "Name",
        "hero.appearance": "Appearance",
        "hero.equipment": "Equipment",
        "hero.strength": "Strength",
        "hero.dexterity": "Dexterity",
        "hero.constitution": "Constitution",
        "hero.intelligence": "Intelligence",
        "hero.wisdom": "Wisdom",
        "hero.charisma": "Charisma",
        "hero.required": "Fill in the hero card before taking a turn.",
        "hero.confirm_title": "Change ability scores?",
        "hero.confirm_hint": "The scene suggests new ability scores. Equipment and appearance are already saved.",
        "hero.confirm": "Apply",
        "hero.reject": "Keep current scores",
        "check.success": "success",
        "check.fail": "failure",
        "check.fact": "Check \"{name}\" (difficulty {dc}): rolled {roll} — {result}.",
        "check.cue.critical_success": "The player critically succeeded at the action. Narrate it as a brilliant, unmistakable success.",
        "check.cue.success": "The player succeeded at the action. Narrate it accordingly.",
        "check.cue.failure": "The player failed the action. Narrate it accordingly.",
        "check.cue.critical_failure": "The player critically failed the action. Narrate it as a severe, unmistakable failure.",
        "btn.create": "Create",
        "btn.create_ok": "Create",
        "btn.cancel": "Cancel",
        "btn.cancel_plain": "Cancel",
        "btn.close": "Close",
        "btn.close_x": "Close",
        "btn.save": "Save",
        "btn.save_ok": "Save",
        "btn.save_as": "Save as...",
        "btn.delete": "Delete",
        "btn.delete_icon": "Delete",
        "btn.load": "Load",
        "btn.export": "Export",
        "btn.import": "Import",
        "btn.add": "Add",
        "btn.copy": "Copy",
        "btn.index_now": "Index now",
        "toggle.summary_on": "Summ.: ON",
        "toggle.summary_off": "Summ.: OFF",
        "toggle.memory_on": "Memory: ON",
        "toggle.memory_off": "Memory: OFF",
        "summary.off": "Summ.: off",
        "summary.fill": "Summ.: {percent}%",
        "memory.off": "Memory: {n} | off",
        "memory.until": "Memory: {n} | until idx.: {remaining}",
        "context.since_summary": "Since summary: {used} / {total}",
        "btn.stop": "Stop",
        "status.generating": "Generating...",
        "status.scene_prompt": "Scene prompt...",
        "status.scene_image": "Scene image...",
        "status.summary_memory": "Summary and memory...",
        "status.summary": "Summarizing...",
        "status.memory": "Indexing memory...",
        "menu.select_all": "Select all",
        "menu.copy": "Copy",
        "menu.paste": "Paste",
        "menu.cut": "Cut",
        "dialog.manage_worlds": "Manage worlds",
        "dialog.your_worlds": "Your worlds:",
        "dialog.delete_world": "Delete world",
        "dialog.delete_world_q": "Delete world '{name}' permanently?",
        "dialog.create_world": "Create a new world",
        "dialog.world_name": "World name (folder):",
        "dialog.default_world_name": "New World",
        "dialog.bad_name": "Error",
        "dialog.bad_name_msg": "Invalid or already used name",
        "dialog.busy": "Wait until the current action finishes.",
        "dialog.import_failed": "This world archive could not be imported. Use a zip of the world files.",
        "log.earlier": "Earlier",
        "dialog.world_files": "World files",
        "dialog.choose_file": "Choose a file:",
        "dialog.unsaved": "Unsaved changes",
        "dialog.attention": "Warning",
        "dialog.file_unsaved": "File “{label}” has unsaved changes. Save?",
        "dialog.close_unsaved": "There are unsaved changes. Save before closing?",
        "dialog.cards_title": "Story cards",
        "dialog.cards_need_world": "Select or create a world first.",
        "dialog.next_title": "What next?",
        "dialog.next_hint": "Describe what should happen on the next turn.\nThe AI will write it into the story.",
        "dialog.empty_input": "Empty input",
        "dialog.empty_next": "Describe what should happen next.",
        "dialog.ai_settings": "Settings",
        "dialog.tab_ai": "AI settings",
        "dialog.tab_game": "Game settings",
        "dialog.lan_title": "Phone on the same network",
        "dialog.lan_access": "Open the game to the local network",
        "dialog.lan_hint": "Leave this computer on and open the address below on the phone. The phone has to be on the same Wi-Fi. Devices on that network can open the page. The new value starts working after you save and restart the server.",
        "dialog.lan_restart": "Save the settings and restart the server before the address will open.",
        "dialog.lan_this_computer": "This computer",
        "dialog.lan_phone": "Phone",
        "dialog.lan_tailscale": "Tailscale",
        "dialog.lan_none": "No network address found. Connect the computer to Wi-Fi and restart the server.",
        "dialog.tab_prompts": "Prompt settings",
        "dialog.section_summary": "Summary",
        "dialog.section_memory": "Memory bank",
        "dialog.prompt_fields": "Required fields: {fields}",
        "dialog.prompt_fields_none": "No required fields.",
        "dialog.prompt_missing_fields": "Prompt “{name}” is missing fields: {fields}.",
        "dialog.prompt_unknown_fields": "Prompt “{name}” has unknown fields: {fields}.",
        "dialog.prompt_broken": "Prompt “{name}” cannot be filled in: check the braces.",
        "dialog.prompt_invalid_title": "Prompt",
        "prompt_group.turn": "Turn",
        "prompt_group.summary": "Summary",
        "prompt_group.memory": "Memory",
        "prompt_group.cards": "Cards",
        "prompt_group.scene": "Scene",
        "prompt_name.continue": "Continue the turn",
        "prompt_name.direction": "Author direction",
        "prompt_name.no_reasoning": "No reasoning",
        "prompt_name.history_header": "History header",
        "prompt_name.summary": "Summarization",
        "prompt_name.summary_compress": "Compress the summary",
        "prompt_name.summary_header": "Chronicle header",
        "prompt_name.none": "Empty value",
        "prompt_name.memory_index": "Memory indexing",
        "prompt_name.memory_header": "Memory header",
        "prompt_name.card_desc_gen": "Card description",
        "prompt_name.cards_header": "Cards header",
        "prompt_name.card_triggers": "Card triggers",
        "prompt_name.card_always": "Always-active card",
        "prompt_name.cards_missing": "No cards",
        "prompt_name.scene_image": "Scene prompt",
        "prompt_name.scene_style.sd": "Stable Diffusion style",
        "prompt_name.scene_style.midjourney": "Midjourney style",
        "prompt_name.scene_style.flux": "Flux style",
        "prompt_name.scene_style.generic": "Generic style",
        "prompt_name.scene_look.anime": "Look: anime",
        "prompt_name.scene_look.realism": "Look: realism",
        "prompt_name.scene_look.painting": "Look: painting",
        "prompt_name.scene_look.cinematic": "Look: cinematic",
        "btn.reset_prompt": "Reset",
        "dialog.api_config": "API configuration",
        "dialog.manual_preset": "— Manual —",
        "dialog.save_preset": "Save configuration",
        "dialog.preset_name": "Configuration name:",
        "dialog.delete_preset_info": "Delete",
        "dialog.delete_preset_pick": "Select a saved configuration to delete.",
        "dialog.delete_preset": "Delete configuration",
        "dialog.delete_preset_q": "Delete configuration “{name}”?",
        "dialog.api_url": "API URL (Chat Completions):",
        "dialog.api_key": "API key (optional):",
        "dialog.show_key": "Show key",
        "dialog.model": "Model (optional):",
        "dialog.reasoning": "Reasoning",
        "dialog.reasoning_max_tokens": "Max reasoning tokens:",
        "log.reasoning": "Reasoning",
        "log.reasoning_hidden": "The model reasoned, but did not send the text.",
        "dialog.gen_params": "Generation settings",
        "dialog.stream": "Show the reply as it is generated",
        "dialog.auto_summary": "Auto-summary",
        "dialog.memory_bank": "Memory bank",
        "dialog.temperature": "Temperature (0.0 - 2.0):",
        "dialog.max_tokens": "Max response tokens:",
        "dialog.response_limit": "Max tokens for this prompt's reply:",
        "dialog.context_size": "Context size:",
        "dialog.summary_fill": "Auto-summary when this full (%):",
        "dialog.memory_every": "Memory bank (index every N turns):",
        "dialog.memory_top_k": "Max memories in the prompt:",
        "dialog.image_style": "Image prompt format:",
        "dialog.image_look": "Image look:",
        "image_style.sd": "Stable Diffusion (tags, weights)",
        "image_style.midjourney": "Midjourney (--parameters)",
        "image_style.flux": "Flux (natural text)",
        "image_style.generic": "Generic (text)",
        "image_look.none": "No style",
        "image_look.anime": "Anime",
        "image_look.realism": "Realism",
        "image_look.painting": "Painting",
        "image_look.cinematic": "Cinematic",
        "dialog.section_image": "Image generator",
        "dialog.image_backend": "Where to send the prompt:",
        "image_backend.off": "Do not send",
        "image_backend.comfy": "ComfyUI",
        "image_backend.a1111": "Automatic1111 / Forge",
        "dialog.comfy_url": "ComfyUI address:",
        "dialog.a1111_url": "Automatic1111 / Forge address:",
        "dialog.comfy_workflow": "Workflow file (API format):",
        "dialog.workflow_empty": "The workflows folder has no JSON files.",
        "dialog.workflow_hint": "Put a Save (API Format) export in the workflows folder next to worlds.",
        "dialog.image_width": "Width:",
        "dialog.image_height": "Height:",
        "dialog.image_steps": "Steps:",
        "dialog.image_auto": "Send the finished prompt to the generator immediately",
        "dialog.image_send_negative": "Send the negative prompt",
        "dialog.image_test": "Test connection",
        "dialog.language": "Interface language:",
        "dialog.quit": "Quit",
        "dialog.quit_q": "Really quit the game?",
        "dialog.edit_dm": "Edit reply",
        "dialog.edit_dm_label": "Edit the DM reply:",
        "dialog.edit_player": "Edit your turn",
        "dialog.edit_player_label": "Edit your action:",
        "dialog.edit_prev": "Prev",
        "dialog.edit_next": "Next ",
        "dialog.prompt_title": "Last prompt",
        "dialog.no_prompt": "No prompt data yet.",
        "dialog.prompt_time": "=== REQUEST TIME ===\n{time}\n\n=== APPROXIMATE TOKEN COUNT ===\n{tokens}\n\n",
        "dialog.prompt_body": "=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n",
        "dialog.memory_title": "Memory bank",
        "dialog.no_world": "No world selected.",
        "dialog.memory_empty": "Memory bank is empty. Entries appear after a few turns.",
        "dialog.memory_stats": "Entries: {n} | Indexed turns: {turns}",
        "dialog.memory_entry": "=== {id} | turns {start}-{end} ===\nKeys: {keys}\nNPCs: {npcs} | Location: {location}\n{summary}\n",
        "dialog.no_worlds_title": "No worlds",
        "dialog.no_worlds_q": "You have no worlds yet. Create one?",
        "cards.list": "Cards:",
        "cards.search": "Search cards...",
        "cards.title": "Title:",
        "cards.desc": "Description:",
        "cards.triggers": "Triggers (comma-separated keywords that pull this card into the prompt):",
        "cards.triggers_ph": "arion, tavern, sword",
        "cards.empty_triggers": "Empty triggers = the card is always included in the prompt",
        "cards.untitled": "Untitled",
        "cards.new": "New card",
        "cards.delete": "Delete",
        "cards.delete_q": "Delete the selected card?",
        "cards.save_with_world": "Saved together with the world",
        "cards.generate_desc": "Generate Description",
        "cards.generating": "Generating description...",
        "cards.generate_desc_title": "Generate Card Description",
        "cards.enter_title_first": "Please enter a card title first",
        "scene.prompt_label": "Prompt",
        "scene.negative_label": "Negative prompt",
        "scene.wish": "What to show",
        "scene.wish_hint": "Leave this empty to frame the latest scene.",
        "scene.format": "Model format",
        "scene.look": "Style",
        "scene.copy_prompt": "Copy prompt",
        "scene.copy_negative": "Copy negative prompt",
        "scene.copied_prompt": "Scene prompt copied.",
        "scene.copied_negative": "Negative prompt copied.",
        "scene.generating": "Generating prompt...",
        "scene.stop": "Stop",
        "scene.needs_world": "Please load a world first.",
        "scene.needs_history": "The history needs at least one Game Master reply.",
        "scene.needs_prompt": "A scene prompt is needed first.",
        "scene.image_alt": "Scene image",
        "scene.image_off": "The image generator is off. Turn it on in settings.",
        "gallery.empty": "This world has no images yet.",
        "gallery.delete": "Delete",
        "gallery.delete_q": "Delete this image?",
        "scene.image_test_ok": "The generator is responding.",
        "scene.image_missing_workflow": "Workflow file was not found: {msg}",
        "scene.image_ui_workflow": "This is a regular ComfyUI file. Export it with Save (API Format).",
        "scene.image_bad_workflow": "The workflow file cannot be read: {msg}",
        "scene.image_no_nodes": "The workflow has no positive prompt nodes.",
        "scene.image_offline": "The image generator is not running, or the address is wrong.",
        "scene.image_rejected": "The generator rejected the request: {msg}",
        "scene.image_empty": "The generator did not return an image.",
        "scene.image_timeout": "The generator did not finish the image in time.",
        "dialog.corrupt_title": "Corrupted data",
        "dialog.corrupt_history": "World \"{name}\" was not loaded: file {file} is corrupted and cannot be read, including from the backup.\n\nHistory was left untouched — you can repair it manually.\nDetails: {detail}\n\nThe backup is next to it: {file}.bak",
        "on": "ON",
        "off": "OFF",
        "summary_enabled_word": "enabled",
        "summary_disabled_word": "disabled",
        "memory_enabled_word": "enabled",
        "memory_disabled_word": "disabled",
        "msg.cards_saved": "Story cards saved",
        "msg.file_saved": "File {name} saved",
        "msg.preset_saved": "API configuration “{name}” saved.",
        "msg.settings_saved": "Settings saved. API: {api}{model}{preset}. Streaming: {stream}. Summary: {summary}. Memory: {memory}.",
        "msg.model_part": ", model: {model}",
        "msg.preset_part": ", preset: {name}",
        "msg.dm_edited": "DM reply updated.",
        "msg.player_edited": "Your turn updated.",
        "msg.force_summary": "Forcing a summary update...",
        "msg.prompt_copied": "Prompt copied.",
        "msg.force_memory": "Forcing memory indexing...",
        "msg.summary_toggled": "Auto-summary {state}.",
        "msg.memory_toggled": "Memory bank {state}.",
        "msg.welcome": "Welcome! Create a new world with the “Worlds” button.",
        "msg.world_loaded": "World '{name}' loaded.",
        "msg.undone": "Last message removed.",
        "msg.no_memory_turns": "No new turns to index.",
        "msg.memory_entry": "Memory [{id}]: {summary}... (keys: {keys})",
        "msg.memory_offline": "Memory bank: AI server is unavailable.",
        "msg.memory_error": "Memory indexing error: {msg}",
        "msg.empty_model": "The model returned an empty reply.",
        "msg.tokens": "Tokens: Context: {p} | Reply: {c} | Total: {t}/{ctx}",
        "msg.reviewing": "The AI is reviewing the chronicle...",
        "msg.no_server": "Error: local AI server is not running!",
        "msg.error": "Error: {msg}",
        "msg.summary_ok": "World summary updated!",
        "msg.summary_fail": "Could not auto-update the summary: {msg}",
        "msg.history_restored": "History restored from backup (the file was corrupted).",
        "msg.stop_requested": "Stopping generation...",
        "msg.scene_prompt_done": "Scene prompt is ready.",
        "msg.scene_prompt_fail": "Could not create the scene prompt: {msg}",
        "msg.scene_image_done": "The scene image is ready.",
        "msg.scene_image_fail": "Could not create the image: {msg}",
        "msg.image_stopped": "Image generation stopped.",
        "msg.action_stopped": "Generation stopped. The partial reply was kept — you can edit or undo it.",
        "msg.summary_stopped": "Summarization stopped.",
        "msg.memory_stopped": "Memory indexing stopped.",
        "msg.language_changed": "Interface language: {lang_name}",
        "world_file.introduction.txt": "Introduction",
        "world_file.ai_instructions.txt": "AI instructions",
        "world_file.plot_basics.txt": "Plot basics",
        "world_file.author_notes.txt": "Author notes",
        "world_file.summary.txt": "Summary",
        "world_file.story_cards": "Story cards",
        "hist.player": "Player:",
        "hist.dm": "DM:",
        "hist.intro": "Introduction:",
        "prompt.continue": "(Continue the narrative.)",
        "prompt.check": """Does this player action need a d20 check?
Looking around and a conversation without risk need no check.
If a check is needed, name it and choose a difficulty only from 10, 13, 16, 19.
Reply with JSON only:
{{"needed": false}}
or
{{"needed": true, "name": "check name", "dc": 13}}

Action:
{action}""",
        "prompt.followup": """From the latest turn, decide whether the hero changed and which new characters matter.
Set equipment and appearance only if the scene really changes them. Otherwise use an empty string.
Propose ability scores only for a real change. Otherwise use an empty object.
Ability keys: strength, dexterity, constitution, intelligence, wisdom, charisma.
Include a character only when they have a name and will either return later (returns) or take part in a conflict (conflict).
Skip unnamed guards.

Hero:
{hero}

Player action:
{action}

Narration:
{reply}

JSON only:
{{"equipment": "", "appearance": "", "stats": {{}}, "characters": [{{"name": "", "description": "", "triggers": [], "returns": false, "conflict": false}}]}}""",
        "prompt.hero_block": """=== HERO ===
Name: {name}
Appearance: {appearance}
Equipment: {equipment}
Strength: {strength}; Dexterity: {dexterity}; Constitution: {constitution}; Intelligence: {intelligence}; Wisdom: {wisdom}; Charisma: {charisma}
""",
        "prompt.direction": "The author sets the direction for the next turn:\n{hint}\n\nRealize this organically in the narration, keeping the style, context, and world rules. Do not mention that this is an author instruction — just advance the story.",
        "prompt.no_reasoning": "IMPORTANT: Respond immediately without reasoning, analysis, or internal monologue. Do not use , <thinking>, <reasoning>, or similar tags. Start your response directly with the narrative.",
        "prompt.summary_header": "=== Compressed chronicle of past events (summary.txt) ===\n{text}\n",
        "prompt.history_header": "CURRENT SESSION HISTORY:",
        "prompt.memory_header": "=== RELEVANT MEMORIES (memory bank) ===\n",
        "prompt.cards_header": "=== RELEVANT STORY CARDS ===\n",
        "prompt.card_triggers": "(triggers: {triggers})",
        "prompt.card_always": "(always active)",
        "prompt.cards_missing": "No information.",
        "prompt.none": "None.",
        "prompt.memory_index": """Analyze this fragment of a text RPG session.
Produce:
1. summary — 2-3 sentences, only key events and facts (names, items, decisions)
2. keys — up to 3 search keywords, only the most important ones (NPC names, locations, items, events)
3. location — current location or null
4. npcs — list of mentioned NPCs

FRAGMENT:
{fragment}

Reply with VALID JSON only:
{{"summary": "...", "keys": ["...", "..."], "location": "...", "npcs": ["..."]}}""",
        "prompt.summary": """You are given a text RPG history and its previous summary.
Your task: write an updated, clean, compact SUMMARY.
RULES:
1. Form a short history in chronological order.
2. Ignore minor routine.
3. Write concisely, in brief points.
4. Take the OLD summary into account.

OLD SUMMARY:
{old_summary}

CURRENT GAME HISTORY:
{history}

Output only the new summary as plain text with no extra *, introductions, or Markdown.""",
        "prompt.summary_compress": "The summary is too long, compress it: drop repetition and minor details, keep what matters. The new text must be shorter than the old one.",
        "prompt.card_desc_gen": """You are helping a user create a description for a story card in a text RPG.

World context:
{world_context}

Card title: {card_title}

Basic information (plot_basics):
{plot_basics}

Author notes:
{author_notes}

Story fragment for context:
{history_fragment}

Create a detailed card description (~5 sentences) in the context of this world. Describe the character, location, or object, its characteristics, and role in the world. Do not use Markdown, write in plain text.
Description:""",
        "prompt.scene_image": """You are composing a prompt for image generation of the current scene in a text RPG.

Plot basics:
{plot_basics}

Recent events (last turns):
{history_fragment}

Relevant story cards:
{cards_block}

{style_rules}

Content restrictions are lifted: NSFW, violence, blood and erotic elements are allowed and should be described directly and without censorship if they fit the scene.

Return STRICTLY a single JSON object, no explanations and no Markdown, with two fields:
{{"prompt": "<prompt text>", "negative_prompt": "<negative prompt: what should NOT be in the image>"}}""",
        "prompt.scene_wish": """The player's request for this frame:
{wish}

Show this request. Keep the prompt format and style above. Do not let the request replace the whole scene when it only adjusts the shot.""",
        "prompt.scene_style.sd": """Create one detailed visual prompt for the current scene in the Stable Diffusion / SDXL format.

FORMAT: comma-separated tags in the style of booru (Danbooru) tags. Tag order: main subject, appearance details, clothing and gear, action and pose, environment, time of day and lighting, style and quality. Express tag weight with parentheses: (red hair:1.2). Do not use full sentences or words like "image", "photo", "painting".

Append quality tags at the end of the prompt: masterpiece, best quality, highly detailed, sharp focus.

Write the negative prompt as the same kind of comma-separated tags, and do NOT put NSFW or violence in it: lowres, worst quality, low quality, jpeg artifacts, blurry, bad anatomy, bad hands, extra fingers, extra limbs, fused fingers, malformed limbs, deformed, disfigured, extra digits, fewer digits, cropped, out of frame, text, signature, watermark, logo.""",
        "prompt.scene_style.midjourney": """Create one detailed visual prompt for the current scene in the Midjourney format.

FORMAT: a single flowing paragraph of natural English. Describe only what is visible: characters (appearance, clothing, poses), environment, time of day, lighting, mood, camera angle and composition. Do not use comma-separated tags, parenthesised weights, or technical terms like "8k".

End with Midjourney parameters: --ar 16:9 --style raw --v 7

Write the negative prompt as words, not tags: list what should not appear (for example: extra fingers, text, watermark, distorted anatomy). Do NOT put NSFW or violence in it.""",
        "prompt.scene_style.flux": """Create one detailed visual prompt for the current scene for Flux / natural text models.

FORMAT: 2-4 sentences of natural English, ordered as: who and what is in frame, character appearance and clothing, action, environment, lighting, style and mood. Do not use comma-separated tags, parenthesised weights, or service words like "negative prompt" or "quality".

Do NOT append quality tags — Flux ignores them.

The negative prompt is one separate sentence describing what should not be in the image (for example: "artifacts, extra fingers, text, watermark, distorted anatomy"). Do NOT put NSFW or violence in it.""",
        "prompt.scene_style.generic": """Create one detailed visual prompt for the current scene.

FORMAT: 2-4 sentences of natural English. Describe only what is visible: characters (appearance, clothing, poses), environment, time of day, lighting, style, mood, camera angle and composition. Do not use comma-separated tags or parenthesised weights.

The negative prompt is one separate sentence describing what should not be in the image. Do NOT put NSFW or violence in it.""",
        "prompt.scene_look.anime": """IMAGE LOOK: anime.
Write this style into the prompt field, in the same format as the rest of the prompt: anime style, cel shading, clean lineart, expressive eyes, vibrant colors.
Do not make the scene photorealistic.""",
        "prompt.scene_look.realism": """IMAGE LOOK: realism.
Write this style into the prompt field, in the same format as the rest of the prompt: photorealistic, realistic skin, natural lighting, lifelike proportions, detailed materials.
Do not use anime, cartoon, or drawn outlines.""",
        "prompt.scene_look.painting": """IMAGE LOOK: painting.
Write this style into the prompt field, in the same format as the rest of the prompt: oil painting, visible brushstrokes, painterly light, fine art.""",
        "prompt.scene_look.cinematic": """IMAGE LOOK: cinematic.
Write this style into the prompt field, in the same format as the rest of the prompt: cinematic still, dramatic lighting, shallow depth of field, film color grade.""",
    },
}

TEMPLATES = {
    "ru": {
        "introduction.txt": (
            "Вы — искатель приключений в мире фэнтези. История начинается здесь: "
            "опишите стартовую сцену, обстановку и с чего начинается приключение."
        ),
        "ai_instructions.txt": """Ты - ИИ мастер, который предоставляет любой контент для ролевых игр.
Инструкции, которые ты (Мастер) обязан соблюдать при написании:
- '!!' Двигай сюжет, не зацикливайся на одной сцене.
- '!' Отдавайте предпочтение действиям и диалогам, а не описаниям.
- '!' Не описывайте окружающую обстановку, освещение, погоду, звуки или жестикуляцию персонажей, если это напрямую не влияет на текущее действие.
- '!' Избегайте повторяющегося эмоционального повествования.
- '!' Пишите скорее как сценарий фильма, чем как роман.
- Будьте конкретны, описательны и изобретательны.
- Избегайте повторений и обобщений.
- Старайтесь развивать историю, даже если пользователь бездействует.
- Обычно говорите от второго лица (например, "О смотрит на вас"). Но используйте слова от третьего лица, если вам кажется, что история развивается именно так.
- Если ввод заканчивается на середине предложения, продолжайте с того места, где он был прерван.
- Подробно опишите внешность и характерные черты персонажей.

Разрешено принимать решения и писать за пользователя!
""",
        "plot_basics.txt": "Мир фэнтези.\nВы искатель приключений.\nУ вас есть меч и щит.\nВы носите легкую кожаную броню.",
        "author_notes.txt": "Стиль написания: Приключение, комедия, фэнтези.",
        "summary.txt": "",
    },
    "en": {
        "introduction.txt": (
            "You are an adventurer in a fantasy world. The story starts here: "
            "describe the opening scene, the setting, and how the adventure begins."
        ),
        "ai_instructions.txt": """You are an AI game master who provides any content for tabletop role-playing games.
Instructions you (the DM) must follow when writing:
- '!!' Drive the plot forward; do not loop on a single scene.
- '!' Prefer actions and dialogue over description.
- '!' Do not describe surroundings, lighting, weather, sounds, or character gestures unless they directly affect the current action.
- '!' Avoid repetitive emotional narration.
- '!' Write more like a film script than a novel.
- Be specific, descriptive, and inventive.
- Avoid repetition and generalizations.
- Keep the story moving even if the user does nothing.
- Usually write in the second person (e.g. "She looks at you"). Use third person when the story calls for it.
- If input ends mid-sentence, continue from where it was interrupted.
- Describe characters' appearance and distinctive traits in detail.

You may make decisions and write for the user!
""",
        "plot_basics.txt": "A fantasy world.\nYou are an adventurer.\nYou have a sword and a shield.\nYou wear light leather armor.",
        "author_notes.txt": "Writing style: Adventure, comedy, fantasy.",
        "summary.txt": "",
    },
}

STORY_CARD_DEMOS = {
    "ru": {
        "cards": [
            {
                "id": "card_001",
                "title": "Арион",
                "description": "Арион - мужчина, 21 год.\nОн воин, орудует длинным мечом и щитом.\nИмеет красные волосы среднего размера, одет в кожанную броню",
                "triggers": ["арион", "воин"],
            }
        ]
    },
    "en": {
        "cards": [
            {
                "id": "card_001",
                "title": "Arion",
                "description": "Arion is a man, 21 years old.\nHe is a warrior, wields a long sword and a shield.\nHe has medium‑length red hair and is dressed in leather armor.",
                "triggers": ["arion", "warrior",],
            }
        ]
    },
}


def normalize_lang(value):
    value = str(value or "ru").lower()
    return "en" if value.startswith("en") else "ru"


# Тексты, которые уходят модели или вставляются в её контекст.
# Группы задают порядок во вкладке «Настройки промптов».
PROMPT_GROUPS = (
    (
        "prompt_group.turn",
        (
            "prompt.continue",
            "prompt.direction",
            "prompt.no_reasoning",
            "prompt.history_header",
        ),
    ),
    (
        "prompt_group.summary",
        (
            "prompt.summary",
            "prompt.summary_compress",
            "prompt.summary_header",
            "prompt.none",
        ),
    ),
    (
        "prompt_group.memory",
        (
            "prompt.memory_index",
            "prompt.memory_header",
        ),
    ),
    (
        "prompt_group.cards",
        (
            "prompt.card_desc_gen",
            "prompt.cards_header",
            "prompt.card_triggers",
            "prompt.card_always",
            "prompt.cards_missing",
        ),
    ),
    (
        "prompt_group.scene",
        (
            "prompt.scene_image",
            "prompt.scene_style.sd",
            "prompt.scene_style.midjourney",
            "prompt.scene_style.flux",
            "prompt.scene_style.generic",
            "prompt.scene_look.anime",
            "prompt.scene_look.realism",
            "prompt.scene_look.painting",
            "prompt.scene_look.cinematic",
        ),
    ),
)

PROMPT_KEYS = tuple(key for _group, keys in PROMPT_GROUPS for key in keys)

# Правки из настроек. Пустой словарь — встроенные тексты.
_PROMPT_OVERRIDES = {"ru": {}, "en": {}}

# Имя поля {history}. Удвоенные скобки {{ }} — это литерал для format и не поле.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def builtin_prompt(lang, key):
    """Встроенный текст без пользовательских правок."""
    lang = normalize_lang(lang)
    table = TRANSLATIONS.get(lang, TRANSLATIONS["ru"])
    text = table.get(key)
    if text is None:
        text = TRANSLATIONS["ru"].get(key, key)
    return text


def prompt_placeholders(text):
    """Имена полей в порядке появления. Удвоенные скобки пропускаются."""
    if not isinstance(text, str):
        return []
    masked = text.replace("{{", "").replace("}}", "")
    return list(dict.fromkeys(_PLACEHOLDER.findall(masked)))


def prompt_edit_issues(lang, key, text):
    """Проверяет правку промпта.

    Пустой текст и точное совпадение со встроенным — это сброс, не ошибка.
    Иначе возвращает словарь missing/unknown/broken, либо None, если текст можно хранить.
    """
    text = text if isinstance(text, str) else ""
    if not text.strip() or text == builtin_prompt(lang, key):
        return None
    required = prompt_placeholders(builtin_prompt(lang, key))
    present = prompt_placeholders(text)
    missing = [name for name in required if name not in present]
    unknown = [name for name in present if name not in required]
    broken = False
    if not missing and not unknown:
        try:
            text.format(**{name: "x" for name in required})
        except (ValueError, KeyError, IndexError):
            broken = True
    if not missing and not unknown and not broken:
        return None
    return {"missing": missing, "unknown": unknown, "broken": broken}


def normalize_prompt_overrides(raw):
    """Оставляет только непустые правки известных промптов, отличные от встроенного текста."""
    cleaned = {"ru": {}, "en": {}}
    if not isinstance(raw, dict):
        return cleaned
    allowed = set(PROMPT_KEYS)
    for lang in ("ru", "en"):
        bucket = raw.get(lang)
        if not isinstance(bucket, dict):
            continue
        for key, value in bucket.items():
            if key not in allowed or not isinstance(value, str) or not value.strip():
                continue
            if value == builtin_prompt(lang, key):
                continue
            if prompt_edit_issues(lang, key, value):
                continue
            cleaned[lang][key] = value
    return cleaned


def set_prompt_overrides(raw):
    """Подставляет сохранённые правки. Вызывается при запуске и при сохранении настроек."""
    global _PROMPT_OVERRIDES
    _PROMPT_OVERRIDES = normalize_prompt_overrides(raw)
    return {"ru": dict(_PROMPT_OVERRIDES["ru"]), "en": dict(_PROMPT_OVERRIDES["en"])}


def t(lang, key, **kwargs):
    lang = normalize_lang(lang)
    override = _PROMPT_OVERRIDES.get(lang, {}).get(key)
    if isinstance(override, str) and override.strip():
        text = override
    else:
        text = builtin_prompt(lang, key)
    if kwargs:
        return text.format(**kwargs)
    return text


def default_templates(lang):
    lang = normalize_lang(lang)
    return dict(TEMPLATES.get(lang, TEMPLATES["ru"]))


def default_story_cards(lang=None):
    lang = normalize_lang(lang if lang is not None else "ru")
    demo = STORY_CARD_DEMOS.get(lang, STORY_CARD_DEMOS["ru"])
    return {"cards": [dict(card, triggers=list(card.get("triggers", []))) for card in demo["cards"]]}


def is_player_msg(msg):
    return isinstance(msg, str) and msg.startswith(PLAYER_PREFIX)


def is_dm_msg(msg):
    return isinstance(msg, str) and msg.startswith(DM_PREFIX)


def is_intro_msg(msg):
    return isinstance(msg, str) and msg.startswith(INTRO_PREFIX)


def player_text(msg):
    return msg[len(PLAYER_PREFIX) :].strip() if is_player_msg(msg) else msg


def dm_text(msg):
    return msg[len(DM_PREFIX) :].strip() if is_dm_msg(msg) else msg


def intro_text(msg):
    return msg[len(INTRO_PREFIX) :].strip() if is_intro_msg(msg) else msg


def localize_history_line(lang, msg):
    if is_player_msg(msg):
        return f"{t(lang, 'hist.player')} {player_text(msg)}"
    if is_dm_msg(msg):
        return f"{t(lang, 'hist.dm')} {dm_text(msg)}"
    if is_intro_msg(msg):
        return f"{t(lang, 'hist.intro')} {intro_text(msg)}"
    return msg


def localize_history(lang, messages):
    return [localize_history_line(lang, msg) for msg in messages]
