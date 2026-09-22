import json

_FENCE = "```"


class LLMJsonError(ValueError):
    pass


def _strip_fence(text: str) -> str:
    if not text.startswith(_FENCE):
        return text
    body = text[len(_FENCE) :]
    body = body.split("\n", 1)[1] if "\n" in body else ""
    return body.rsplit(_FENCE, 1)[0].strip()


def parse_llm_json(raw: object) -> dict:
    text = str(raw).strip()
    if not text:
        raise LLMJsonError("модель вернула пустой ответ")

    candidates = [_strip_fence(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise LLMJsonError(f"JSON не найден в ответе модели: {text[:200]!r}")
