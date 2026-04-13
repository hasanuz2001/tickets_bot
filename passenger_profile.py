"""Yo'lovchi profilida chipta xaridi uchun zarur maydonlarni tekshirish (server, bot, testlar uchun)."""

from __future__ import annotations

import re
from typing import Any, Dict

_BIRTH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PASSPORT_MIN_LEN = 6

# eticket forma + DB: barcha maydonlar to'ldirilishi kerak
REQUIRED_PASSENGER_KEYS = (
    "full_name",
    "passport",
    "phone",
    "birth_date",
    "gender",
    "citizenship",
)

FIELD_LABELS_UZ: Dict[str, str] = {
    "full_name": "To'liq ism (pasport bo'yicha)",
    "passport": "Passport seriya va raqami",
    "phone": "Telefon (+998...)",
    "birth_date": "Tug'ilgan sana (YYYY-MM-DD)",
    "gender": "Jins (erkak/ayol)",
    "citizenship": "Fuqarolik (masalan UZB)",
}


def _row_to_dict(p: Any) -> dict:
    if p is None:
        return {}
    if isinstance(p, dict):
        return dict(p)
    try:
        return dict(p)
    except Exception:
        return {}


def passenger_missing_fields(passenger: Any) -> list[str]:
    """
    Yetishmayotgan majburiy maydon kalitlari tartibda qaytariladi.
    Yo'lovchi yo'q bo'lsa — barcha kalitlar.
    """
    p = _row_to_dict(passenger)
    if not p:
        return list(REQUIRED_PASSENGER_KEYS)

    missing: list[str] = []

    name = (p.get("full_name") or "").strip()
    if not name:
        missing.append("full_name")

    passport = (p.get("passport") or "").strip()
    if len(passport) < _PASSPORT_MIN_LEN:
        missing.append("passport")

    phone = (p.get("phone") or "").strip()
    if not phone.startswith("+"):
        missing.append("phone")

    birth = (p.get("birth_date") or "").strip()
    if not birth or not _BIRTH_RE.match(birth):
        missing.append("birth_date")

    gender = (p.get("gender") or "").strip().lower()
    if gender not in ("male", "female"):
        missing.append("gender")

    citizen = (p.get("citizenship") or "").strip().upper()
    if not citizen or len(citizen) != 3 or not citizen.isalpha():
        missing.append("citizenship")

    return missing


def passenger_profile_complete(passenger: Any) -> bool:
    return len(passenger_missing_fields(passenger)) == 0


def is_valid_birth_date_iso(s: str) -> bool:
    raw = (s or "").strip()
    return bool(_BIRTH_RE.match(raw))


def missing_fields_message_uz(missing: list[str]) -> str:
    if not missing:
        return ""
    parts = [FIELD_LABELS_UZ.get(k, k) for k in missing]
    return "Quyidagilar kerak: " + "; ".join(parts) + "."
