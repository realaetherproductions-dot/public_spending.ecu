from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text


def normalize_tax_id(value: str | None) -> str | None:
    """Normalize an OCDS supplier identifier without inventing missing digits.

    Ecuadorian identifiers are commonly published with punctuation or spaces.
    Numeric identifiers are reduced to digits; foreign/alphanumeric identifiers
    keep letters and digits in uppercase form.
    """
    if not value:
        return None
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    compact = re.sub(r"[^0-9A-Za-z]", "", text).upper()
    return compact or None


def parse_amount(value: str | int | float | Decimal | None) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_iso_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
