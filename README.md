# 🐉 AI Dungeon Master

English | [Russian](README.ru.md)

A local Game Master for text role-playing games, played in the browser. You describe an action, and the model answers as the Game Master. It works with any LLM through an OpenAI-compatible API (by default — [LM Studio](http://localhost:1234)).

The page can be opened on this computer, on a phone on the same Wi-Fi, or on a device on the same Tailscale network.

If you play in Russian, Gemma 4 models are a good fit. They write Russian well and offer a reasonable size-to-quality ratio. The 31B and 26B A4B sizes are enough for most games.

The old desktop program is in [AIDM_Desktop](AIDM_Desktop/README.md). This browser build is the current version.

## Features

- **Text sessions** — a player turn and a Game Master reply, streamed as they are generated
- **Worlds** — one folder per campaign, with its files, history, cards, and memory
- **Story cards** — notes with triggers; matching cards are added to the prompt on their own
- **Memory bank** — the model indexes past turns and brings back the memories that fit the scene
- **Summarization** — compresses the chronicle into `summary.txt` once new story fills the context
- **Stop** — interrupt a reply, a summary, memory indexing, a scene prompt, or a card description
- **Scene prompt** — a prompt and a negative prompt for an image of the current scene
- **Model configurations** — several APIs can be saved and switched from **Models**
- **Two interface languages** — Russian and English; the world list is split by campaign language
- **World export** — a zip of one campaign's files, without program settings

## Release

1. From the repository root, run `build_web.ps1`.
2. The script writes `App_web/` with `AIDM.exe`, an empty `worlds/` folder, and the samples from `Demo worlds`.
3. Zip `App_web` and unpack that archive into any folder.
4. Run `AIDM.exe`.
5. Choose where the game should open: this computer, home Wi-Fi, or Tailscale.
6. Leave the console window open. Closing it stops the server.
7. Start the local model. By default the game expects [LM Studio](http://localhost:1234).

Campaigns created in the program are saved in `worlds` next to `AIDM.exe`. That folder travels with the zip. The build does not copy existing campaigns or API keys: `worlds/settings.json` in the archive is an empty template.

## From source

```text
pip install -r requirements.txt
python run_web.py
```

A source launch keeps worlds in `worlds` at the repository root. Only the packaged exe keeps them beside the program.

## Network

The first window asks how to open the game. The choice is stored in `worlds/settings.json` as `bind_mode`.

| Choice | Who can open the page |
|--------|------------------------|
| This computer only | This PC, at `http://127.0.0.1:8765` |
| Home Wi-Fi | Devices on the same Wi-Fi. The window shows the address. |
| Tailscale | Devices on the same Tailscale network. Tailscale has to be running before you press Start. Shared Wi-Fi is not required. |

The server uses port **8765**. If a phone does not open the page, allow inbound TCP 8765 in Windows Firewall. The computer has to stay on.

The same addresses are shown in **Settings**: this computer, the phone, and Tailscale when that network is found. The checkbox **Open the game to the local network** is stored there. The server has to be restarted before a newly opened address starts accepting connections. Tailscale is chosen in the first window at startup.

## Quick start

1. Start the model and the game server.
2. On the page, open **Worlds** and create a world. The repository already has samples in `Demo worlds`.
3. In **Files**, fill in the AI instructions, plot basics, author notes, and the introduction.
4. Add **Cards** if you want them.
5. Write an action and press **Send**. On a narrow screen, **Take a turn** opens the input.
6. In **Settings**, adjust the API address, temperature, context size, and intervals.

The language button in the header switches the interface between RU and EN. New worlds remember the language they were created in and show up in that group.

## Interface

On a wide screen the menu and the input are on the page. Below 720px the menu sits behind **Menu**, and the turn field sits behind **Take a turn**. The buttons under the log scroll sideways.

### Header

| Element | Purpose |
|---------|---------|
| **Menu** | On a narrow screen, opens the title, the world picker, and the section buttons |
| **Models** | Switch between saved API configurations |
| World picker | Campaign list, split into Russian and English |
| **RU / EN** | Interface language |
| **Worlds** | Create, open, delete, export, and import a world |
| **Files** | The world's text files |
| **Cards** | Story card editor |
| **Memory** | Memory bank and manual indexing |
| **Settings** | API, generation, game options, and prompt text |
| **Prompt** | The last request sent to the model |
| **Scene** | An image prompt for the current scene |
| **Summary: ON/OFF** | Automatic summarization |
| **Memory: ON/OFF** | Memory bank |

Next to the toggles you can see how much new story has accumulated since the last summary, and how many turns remain until the next memory index.

### Under the log

| Button | Purpose |
|--------|---------|
| **Take a turn** | On a narrow screen, shows the input |
| **Send** | Send the action. While the model is working, this becomes **Stop** |
| **What's next?** | Describe what should happen and continue the scene |
| **Undo** | Delete the last message |
| **Reroll** | Generate the last Game Master reply again |
| **Edit** | Change the latest line |
| **Summarize** | Update `summary.txt` now, before the threshold |

The bar under the log shows how much new story has accumulated since the last summary, relative to the room still left for it in the context window. It turns yellow as that fill approaches the auto-summary threshold and red once the threshold is reached: past that point, older unsummarized lines start falling out of the prompt.

## Stopping generation

While the model is working, **Send** turns into **Stop**.

- **Game Master reply** — the text received so far is saved into the story. You can edit it or remove it with **Undo**. Background summary and memory indexing do not start after a stopped reply.
- **Summary and memory** — the operation is cancelled, and `summary.txt` and `memory_bank.json` stay as they were. Summarization retries on the next turn while the bar is still at the threshold. Memory indexing retries after the next few turns.
- **Scene prompt and card description** — generation is cancelled and the result is not applied.

## Scene prompt

**Scene** builds an image prompt for the current scene. The request to the model contains:

- `plot_basics.txt`, the AI instructions, and the author notes
- the **last 5 completed turns** — each Game Master reply together with the player's turn before it
- **relevant story cards** matched by words in those turns, plus every card that has no triggers

The model returns JSON with `prompt` and `negative_prompt`. Each can be copied on its own. If the JSON cannot be parsed, the raw response is used as the prompt.

The format and the visual look are chosen in the scene window and in **Settings → Game settings**.

| Format | What the prompt looks like |
|--------|----------------------------|
| **Stable Diffusion** | comma-separated tags, weights as `(tag:1.2)`, quality tags at the end |
| **Midjourney** | one English paragraph plus `--ar 16:9 --style raw --v 7` |
| **Flux** | 2–4 English sentences, no weights and no quality tags |
| **Generic** | 2–4 English sentences, no weights |

The image look is appended to the finished prompt: no style, anime, realism, painting, or cinematic. Midjourney keeps its `--` parameters at the end of the line.

The keys in `worlds/settings.json` are `image_prompt_style` (`sd`, `midjourney`, `flux`, `generic`) and `image_look` (`none`, `anime`, `realism`, `painting`, `cinematic`).

## Worlds

Each world is a folder inside `worlds/`:

```text
worlds/
├── settings.json              # Program settings, shared by every world
└── World Name/
    ├── language.txt           # ru or en — the language the world was created in
    ├── ai_instructions.txt    # How the Game Master should behave
    ├── plot_basics.txt        # Setting and opening situation
    ├── author_notes.txt       # Tone, style, and the author's preferences
    ├── introduction.txt       # Where the story starts
    ├── summary.txt            # Compressed chronicle
    ├── summary_state.json     # How many history messages are already in the summary
    ├── story_cards.json       # Story cards
    ├── memory_bank.json       # Memory bank
    └── history.json           # Session history
```

**Worlds** can create a campaign, open it, delete it, export a zip, and import a zip. The archive holds that world's files. `settings.json` with the API keys is left out. An import needs a zip of those world files.

Sample worlds live in `Demo worlds`, split into `Ru` and `En`.

### Safe saving

Files are written atomically: the data goes to a temporary file, the previous version is copied to `<file>.bak`, and only then the temporary file takes its place. An interrupted write leaves the previous file intact.

If a file cannot be read, the program tries `<file>.bak`. When the backup is broken too, a world with a damaged `history.json` does not open: the campaign does not silently become empty. The memory bank and the cards can be built again. The history cannot.

## Story cards

A card has a title, a description, and comma-separated triggers. Cards whose words appear in the input and the recent history are included in the turn prompt. Empty triggers mean the card is always active.

You can write the description yourself, or ask the model to generate one from the title.

Example `story_cards.json`:

```json
{
  "cards": [
    {
      "id": "card_001",
      "title": "Arion",
      "description": "Arion is an adventurer and a warrior. He wears leather armor...",
      "triggers": ["arion", "hero", "warrior"]
    },
    {
      "id": "card_002",
      "title": "The Drunken Dragon Tavern",
      "description": "A noisy place on the edge of the city...",
      "triggers": ["tavern", "dragon", "bartender"]
    }
  ]
}
```

## Memory bank

Every N turns (5 by default) the model reads the new part of the session and saves an entry: a short account, keywords, the location, and the NPCs who were mentioned.

On later turns, memories that match the current scene are added to the prompt. **Memory** shows the whole bank and can index it immediately.

## Summarization

When the new story since the last summary fills a configured share of the remaining context (80% by default, allowed range 50–95%), the model rewrites `summary.txt`. The boundary is stored in `summary_state.json` and moves only after a successful write, so stopping a summary does not reset the bar.

**Summarize** updates the chronicle at any time. The **Summary** toggle turns off only the automatic run.

## Settings

All of this lives in `worlds/settings.json`. The window has three tabs: **AI settings**, **Game settings**, and **Prompt settings**.

The AI tab sets the Chat Completions address, the key, the model name, and saved configurations. **Models** in the header switches a saved configuration without opening the whole window.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `temperature` | `0.7` | Reply creativity, from 0.0 to 2.0 |
| `max_tokens` | `300` | How many tokens the Game Master reply may use |
| `context_size` | `16384` | The model's context window |
| `stream_mode` | `true` | Show the reply as it is generated |
| `summary_enabled` | `true` | Automatic summarization |
| `summary_fill_percent` | `80` | Auto-summary threshold, 50–95 |
| `memory_enabled` | `true` | Memory bank |
| `memory_interval` | `5` | Index memory every N turns |
| `memory_top_k` | `5` | How many memories and cards to put in the prompt |
| `image_prompt_style` | `sd` | Scene prompt format |
| `image_look` | `none` | Visual style appended to the prompt |
| `language` | `ru` | Interface language |
| `bind_mode` | `lan` | `local`, `lan`, or `tailscale` |

The prompts tab holds the texts the request is built from: the turn, the summary, memory, cards, and the scene. Each text has required `{fields}`. If a field is missing or the braces do not match, the setting is not saved. **Reset** restores the built-in text. That tab also sets the token limit for that prompt's own reply. Custom texts are stored in `prompt_overrides`, separately for `ru` and `en`. The limits are stored in `response_limits`.

## Tips

- For a long campaign, keep summarization and the memory bank on.
- Put places, characters, and rules that should come back on a word into cards. Leave the triggers empty when something should be in every turn.
- **Prompt** shows exactly what the model received on the last turn: system, user, and an approximate token count.
- Save one API configuration per local model and per outside service, then switch them with **Models**.
