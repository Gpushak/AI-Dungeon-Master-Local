import re

THINK_TAG_RE = re.compile(
    r"<(think|thinking|reasoning|reflection)>.*?</\1>",
    flags=re.DOTALL | re.IGNORECASE,
)
THINK_OPEN_RE = re.compile(r"<(think|thinking|reasoning|reflection)>", re.IGNORECASE)
THINK_CLOSE_RE = re.compile(r"</(think|thinking|reasoning|reflection)>", re.IGNORECASE)


def strip_reasoning_blocks(text: str) -> str:
    if not text:
        return text
    return THINK_TAG_RE.sub("", text).strip()


def extract_message_text(message):
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") in ("text", "output_text"):
                    parts.append(part.get("text") or "")
            elif isinstance(part, str):
                parts.append(part)
        content = "".join(parts)
    return strip_reasoning_blocks(content or "")


class StreamThinkFilter:
    """Отделяет <think>...</think> от рассказа, даже если теги разрезаны по чанкам.

    feed возвращает только видимый текст. Мысль забирается через take_reasoning.
    """

    def __init__(self):
        self.pending = ""
        self.in_think = False
        self._fresh = []

    def take_reasoning(self) -> str:
        if not self._fresh:
            return ""
        text = "".join(self._fresh)
        self._fresh.clear()
        return text

    def finish(self):
        """Добирает хвост мысли, если поток оборвался внутри тега."""
        if self.in_think and self.pending and not (self.pending.startswith("<") and len(self.pending) < 24):
            self._fresh.append(self.pending)
        if self.in_think:
            self.pending = ""

    def _hold_reasoning(self, leftover: str):
        lt = leftover.rfind("<")
        if lt != -1 and len(leftover) - lt < 24:
            if lt:
                self._fresh.append(leftover[:lt])
            self.pending = leftover[lt:]
            return
        if leftover:
            self._fresh.append(leftover)

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        text = self.pending + chunk
        self.pending = ""
        out = []
        i = 0
        while i < len(text):
            if self.in_think:
                close = THINK_CLOSE_RE.search(text, i)
                if not close:
                    self._hold_reasoning(text[i:])
                    return "".join(out)
                if close.start() > i:
                    self._fresh.append(text[i : close.start()])
                i = close.end()
                self.in_think = False
                continue
            open_match = THINK_OPEN_RE.search(text, i)
            if not open_match:
                leftover = text[i:]
                lt = leftover.rfind("<")
                if lt != -1 and len(leftover) - lt < 24 and not leftover[lt:].startswith("</"):
                    out.append(leftover[:lt])
                    self.pending = leftover[lt:]
                else:
                    out.append(leftover)
                break
            out.append(text[i : open_match.start()])
            self.in_think = True
            i = open_match.end()
        return "".join(out)


def fix_truncated_text(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[-1] in [".", "!", "?", "…", '"', "»", "*", ")", "]"]:
        return text

    punctuation_marks = [text.rfind("."), text.rfind("!"), text.rfind("?"), text.rfind("…")]
    last_pos = max(punctuation_marks)

    if last_pos != -1:
        cut_text = text[: last_pos + 1].strip()
        if text.count("*") % 2 == 0 and cut_text.count("*") % 2 != 0:
            cut_text += " *"
        if len(cut_text) > 15:
            return cut_text
    return text + "..."


def clean_dm_response(ai_text: str) -> str:
    ai_text = strip_reasoning_blocks(ai_text)
    ai_text = re.sub(r"^(Мастер|AI|Narrator|DM|ИИ|Master):\s*", "", ai_text, flags=re.IGNORECASE).strip()
    final_narration = ai_text
    final_narration = re.sub(r"\$\{?[^}]*\}?\$", "", final_narration)
    final_narration = final_narration.replace("$", "")
    final_narration = re.sub(r"[\uac00-\ud7a3\u4e00-\u9fff]", "", final_narration)
    final_narration = re.sub(r"\(\s*\)", "", final_narration).strip()
    return fix_truncated_text(final_narration)


def clean_stream_chunk(content: str) -> str:
    content = re.sub(r"[\uac00-\ud7a3\u4e00-\u9fff]", "", content)
    return content.replace("$", "").replace("{", "").replace("}", "")
