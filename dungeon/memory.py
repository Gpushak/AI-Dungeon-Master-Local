import json
import re
from pathlib import Path

from .i18n import DM_PREFIX, PLAYER_PREFIX, t
from .storage import CorruptedDataError, atomic_write_json, read_json_with_backup

MEMORY_BANK_FILE = "memory_bank.json"


def load_memory_bank(world_path):
    path = Path(world_path) / MEMORY_BANK_FILE
    try:
        data, _ = read_json_with_backup(path, None)
    except CorruptedDataError:
        # Банк памяти восстанавливается индексацией, поэтому деградация здесь
        # допустима — в отличие от истории ходов.
        return {"last_indexed_turn": 0, "entries": []}
    if isinstance(data, dict) and "entries" in data:
        return data
    return {"last_indexed_turn": 0, "entries": []}


def save_memory_bank(world_path, bank):
    atomic_write_json(Path(world_path) / MEMORY_BANK_FILE, bank)


def count_completed_turns(history):
    turns = 0
    i = 0
    while i < len(history) - 1:
        if history[i].startswith(PLAYER_PREFIX) and history[i + 1].startswith(DM_PREFIX):
            turns += 1
            i += 2
        else:
            i += 1
    return turns


def get_turn_messages(history, turn_start, turn_end):
    """Возвращает сообщения для ходов turn_start..turn_end (1-based, включительно)."""
    messages = []
    current_turn = 0
    i = 0
    while i < len(history):
        if history[i].startswith(PLAYER_PREFIX):
            chunk = [history[i]]
            if i + 1 < len(history) and history[i + 1].startswith(DM_PREFIX):
                chunk.append(history[i + 1])
                current_turn += 1
                if turn_start <= current_turn <= turn_end:
                    messages.extend(chunk)
                i += 2
                continue
        i += 1
    return messages


def _completed_turns(history):
    turns = []
    i = 0
    while i < len(history):
        if str(history[i]).startswith(PLAYER_PREFIX):
            if i + 1 < len(history) and str(history[i + 1]).startswith(DM_PREFIX):
                turns.append((history[i], history[i + 1]))
                i += 2
                continue
        i += 1
    return turns


def get_recent_turn_messages(history, last_n):
    """Последние n завершённых ходов (ход игрока + ответ мастера), по порядку."""
    return [msg for turn in _completed_turns(history)[-last_n:] for msg in turn]


def recent_turns_within_tokens(history, token_budget, token_counter):
    """Последние завершённые ходы, пока оценка токенов не выйдет за бюджет.

    Новый ход входит даже один, если он сам больше бюджета: иначе кадр
    остался бы без текущей сцены.
    """
    try:
        budget = int(token_budget)
    except (TypeError, ValueError):
        budget = 1
    if budget < 1:
        budget = 1
    chosen = []
    used = 0
    for turn in reversed(_completed_turns(history)):
        cost = sum(int(token_counter(msg)) + 1 for msg in turn)
        if chosen and used + cost > budget:
            break
        chosen.append(turn)
        used += cost
    chosen.reverse()
    return [msg for turn in chosen for msg in turn]


def retrieve_relevant_memories(query, bank, top_k=5, min_score=1):
    query_lower = query.lower()
    query_words = set(re.findall(r"[\w\u0400-\u04ff]+", query_lower))
    scored = []
    for entry in bank.get("entries", []):
        score = 0
        for key in entry.get("keys", []):
            key_lower = key.lower()
            if key_lower in query_lower:
                score += 3
            elif key_lower in query_words:
                score += 2
        for npc in entry.get("npcs", []):
            if npc.lower() in query_lower:
                score += 2
        location = entry.get("location")
        if location and location.lower() in query_lower:
            score += 2
        if score >= min_score:
            scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]


def format_memory_block(memories, lang="ru"):
    if not memories:
        return ""
    block = t(lang, "prompt.memory_header")
    for mem in memories:
        keys = ", ".join(mem.get("keys", []))
        block += f"[{mem['id']}] ({keys}): {mem['summary']}\n"
    return block + "\n"


def parse_memory_index_response(raw, fallback_text):
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return {
                "summary": str(data.get("summary", fallback_text[:200])).strip(),
                "keys": [str(k).strip() for k in data.get("keys", []) if str(k).strip()],
                "location": data.get("location") or None,
                "npcs": [str(n).strip() for n in data.get("npcs", []) if str(n).strip()],
            }
        except:
            pass
    return {"summary": fallback_text[:200], "keys": [], "location": None, "npcs": []}


def sync_memory_bank_after_undo(history, memory_bank):
    current_turns = count_completed_turns(history)
    while memory_bank.get("entries") and memory_bank["entries"][-1].get("turn_end", 0) > current_turns:
        memory_bank["entries"].pop()
    if memory_bank.get("entries"):
        memory_bank["last_indexed_turn"] = memory_bank["entries"][-1]["turn_end"]
    else:
        memory_bank["last_indexed_turn"] = 0
    turns_since_memory = current_turns - memory_bank.get("last_indexed_turn", 0)
    return memory_bank, turns_since_memory
