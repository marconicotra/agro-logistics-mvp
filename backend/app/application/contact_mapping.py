import re


class PhoneNormalizationError(ValueError):
    pass


def normalize_phone_number(phone_number: str | None) -> str | None:
    if phone_number is None:
        return None
    value = phone_number.strip()
    if not value:
        return None

    has_plus = value.startswith("+")
    digits = re.sub(r"\D", "", value)
    if not digits:
        raise PhoneNormalizationError("phone_number must contain digits")

    if has_plus:
        return f"+{digits}"
    if digits.startswith("00"):
        return f"+{digits[2:]}"
    if digits.startswith("54"):
        return f"+{digits}"

    return _normalize_argentina_local_number(digits)


def _normalize_argentina_local_number(digits: str) -> str:
    local = digits[1:] if digits.startswith("0") else digits
    if local.startswith("11") and local[2:4] == "15":
        return f"+54911{local[4:]}"
    if local.startswith("11") and len(local) == 10:
        return f"+549{local}"
    if len(local) == 12 and local[3:5] == "15":
        return f"+549{local[:3]}{local[5:]}"
    if len(local) == 13 and local[4:6] == "15":
        return f"+549{local[:4]}{local[6:]}"
    if len(local) < 8:
        raise PhoneNormalizationError("phone_number is too short")
    return f"+54{local}"
