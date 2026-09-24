"""Indian States / UTs with ISO-3166-2:IN codes.

Source status: the code list is a stable public standard. State-specific
*regulatory* facts are never inferred from this table — they live in
`approval_data.py` / `portal_data.py` with their own verification metadata.
"""
from __future__ import annotations

STATES: list[dict[str, str]] = [
    {"code": "AP", "name": "Andhra Pradesh"},
    {"code": "AR", "name": "Arunachal Pradesh"},
    {"code": "AS", "name": "Assam"},
    {"code": "BR", "name": "Bihar"},
    {"code": "CT", "name": "Chhattisgarh"},
    {"code": "GA", "name": "Goa"},
    {"code": "GJ", "name": "Gujarat"},
    {"code": "HR", "name": "Haryana"},
    {"code": "HP", "name": "Himachal Pradesh"},
    {"code": "JH", "name": "Jharkhand"},
    {"code": "KA", "name": "Karnataka"},
    {"code": "KL", "name": "Kerala"},
    {"code": "MP", "name": "Madhya Pradesh"},
    {"code": "MH", "name": "Maharashtra"},
    {"code": "MN", "name": "Manipur"},
    {"code": "ML", "name": "Meghalaya"},
    {"code": "MZ", "name": "Mizoram"},
    {"code": "NL", "name": "Nagaland"},
    {"code": "OD", "name": "Odisha"},
    {"code": "PB", "name": "Punjab"},
    {"code": "RJ", "name": "Rajasthan"},
    {"code": "SK", "name": "Sikkim"},
    {"code": "TN", "name": "Tamil Nadu"},
    {"code": "TG", "name": "Telangana"},
    {"code": "TR", "name": "Tripura"},
    {"code": "UP", "name": "Uttar Pradesh"},
    {"code": "UT", "name": "Uttarakhand"},
    {"code": "WB", "name": "West Bengal"},
    {"code": "AN", "name": "Andaman and Nicobar Islands"},
    {"code": "CH", "name": "Chandigarh"},
    {"code": "DN", "name": "Dadra and Nagar Haveli and Daman and Diu"},
    {"code": "DL", "name": "Delhi"},
    {"code": "JK", "name": "Jammu and Kashmir"},
    {"code": "LA", "name": "Ladakh"},
    {"code": "LD", "name": "Lakshadweep"},
    {"code": "PY", "name": "Puducherry"},
]

STATE_BY_CODE: dict[str, str] = {s["code"]: s["name"] for s in STATES}


def state_name(code: str | None) -> str | None:
    if not code:
        return None
    return STATE_BY_CODE.get(code.upper())
