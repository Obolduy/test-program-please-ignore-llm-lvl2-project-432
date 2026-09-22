import re
from dataclasses import dataclass

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+7|8)[\s(-]?\d{3}[\s)-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b")
_INN = re.compile(r"\b\d{10}\b|\b\d{12}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

_INN_WEIGHTS_10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN_WEIGHTS_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN_WEIGHTS_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


@dataclass(frozen=True)
class MaskedEntity:

    kind: str
    placeholder: str


def _check_digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(weight * int(digit) for weight, digit in zip(weights, digits)) % 11 % 10


def _inn_checksum(digits: str) -> bool:
    if len(digits) == 10:
        return int(digits[9]) == _check_digit(digits, _INN_WEIGHTS_10)
    if len(digits) == 12:
        return int(digits[10]) == _check_digit(digits, _INN_WEIGHTS_11) and int(
            digits[11]
        ) == _check_digit(digits, _INN_WEIGHTS_12)
    return False


def _luhn(digits: str) -> bool:
    total = 0
    for index, digit in enumerate(reversed(digits)):
        value = int(digit)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


_DETECTORS = (
    ("email", _EMAIL, None),
    ("phone", _PHONE, None),
    ("inn", _INN, lambda match: _inn_checksum(_digits(match))),
    ("card", _CARD, lambda match: len(_digits(match)) >= 13 and _luhn(_digits(match))),
)


def mask_pii(text: str) -> tuple[str, list[MaskedEntity]]:
    found: list[MaskedEntity] = []
    counters: dict[str, int] = {}
    masked = text

    for kind, pattern, is_real in _DETECTORS:

        def replace(match: re.Match, kind=kind, is_real=is_real) -> str:
            value = match.group(0)
            if is_real and not is_real(value):
                return value
            counters[kind] = counters.get(kind, 0) + 1
            placeholder = f"[{kind.upper()}_{counters[kind]}]"
            found.append(MaskedEntity(kind=kind, placeholder=placeholder))
            return placeholder

        masked = pattern.sub(replace, masked)

    return masked, found


def contains_pii(text: str) -> bool:
    masked, found = mask_pii(text)
    return bool(found) and masked != text
