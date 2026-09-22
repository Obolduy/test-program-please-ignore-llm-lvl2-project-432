from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logging import get_logger
from app.guardrails.injection import detect_injection_llm, detect_injection_regex
from app.guardrails.pii import contains_pii, mask_pii

log = get_logger(__name__)

INJECTION_TRACES = ("1 рубль", "1 руб.", "promo@spammlot.example", "за 1 ₽")


@dataclass
class GuardReport:

    masked_pii: int = 0
    suspicious_chunks: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    output_issues: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return len(self.suspicious_chunks) > settings.suspicious_chunk_limit

    def as_dict(self) -> dict:
        return {
            "masked_pii": self.masked_pii,
            "suspicious_chunks": list(self.suspicious_chunks),
            "blocked_reasons": list(self.blocked_reasons),
            "output_issues": list(self.output_issues),
            "needs_review": self.needs_review,
        }


async def guard_context(chunks: list[dict]) -> tuple[list[dict], GuardReport]:
    report = GuardReport()
    safe: list[dict] = []

    for chunk in chunks:
        masked, entities = mask_pii(chunk["text"])
        if entities:
            report.masked_pii += len(entities)
            chunk = {**chunk, "text": masked}

        verdict = detect_injection_regex(masked)
        if verdict.suspicious:
            confirmed, reason = await _confirm(chunk["chunk_id"], masked, verdict)
            if confirmed:
                report.suspicious_chunks.append(chunk["chunk_id"])
                report.blocked_reasons.append(f"{chunk['chunk_id']}: {reason}")
                continue
        safe.append(chunk)

    if report.suspicious_chunks:
        log.warning(
            "guard_blocked_chunks",
            blocked=len(report.suspicious_chunks),
            needs_review=report.needs_review,
        )
    return safe, report


async def _confirm(chunk_id: str, text: str, rule_verdict) -> tuple[bool, str]:
    try:
        verdict = await detect_injection_llm(text)
    except Exception as exc:
        log.warning("injection_detector_unavailable", chunk=chunk_id, error=repr(exc))
        return True, rule_verdict.reason + " (точный уровень недоступен)"
    return verdict.suspicious, verdict.reason or rule_verdict.reason


def guard_output(card_json: str) -> tuple[str, list[str]]:
    issues: list[str] = []
    cleaned = card_json

    if contains_pii(card_json):
        cleaned, entities = mask_pii(card_json)
        issues.append(f"в карточке найдены и замаскированы персональные данные: {len(entities)}")

    for trace in INJECTION_TRACES:
        if trace in card_json:
            issues.append(f"в карточке след инъекции: {trace!r}")

    return cleaned, issues
