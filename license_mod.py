"""
License: Trial (max 1 OLT) vs Full (multi-OLT, key bound to HWID).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import platform
import re
import uuid
from pathlib import Path

# Secret untuk sign key — ganti di production kalau mau
_SECRET = b"OLT-MONITOR-xAI-2026-CyberPlus-HWID-KEY"

_DATA = Path(__file__).resolve().parent / "data"
_LICENSE_FILE = _DATA / "license.json"


def get_hwid() -> str:
    """Hardware ID stabil per mesin (Windows/Linux)."""
    parts = []
    try:
        parts.append(str(uuid.getnode()))  # MAC-based
    except Exception:
        pass
    parts.append(platform.node() or "")
    parts.append(platform.system() or "")
    parts.append(platform.machine() or "")
    # Windows: machine guid if available
    try:
        if platform.system() == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            parts.append(str(guid))
    except Exception:
        pass
    raw = "|".join(parts)
    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest().upper()
    # format groups: XXXX-XXXX-XXXX-XXXX
    return "-".join(digest[i : i + 4] for i in range(0, 16, 4))


def generate_key(hwid: str) -> str:
    """Generate full license key untuk HWID tertentu (dipakai keygen)."""
    h = _normalize_hwid(hwid)
    sig = hmac.new(_SECRET, h.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    # 20 hex chars grouped
    body = sig[:20]
    return "FULL-" + "-".join(body[i : i + 5] for i in range(0, 20, 5))


def _normalize_hwid(hwid: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", (hwid or "")).upper()


def validate_key(key: str, hwid: str | None = None) -> bool:
    if not key:
        return False
    key = key.strip().upper()
    hwid = hwid or get_hwid()
    expected = generate_key(hwid).upper()
    # allow with/without FULL- prefix noise
    return key.replace(" ", "") == expected.replace(" ", "")


def load_license() -> dict:
    default = {"mode": "trial", "key": "", "activated_at": ""}
    try:
        if _LICENSE_FILE.exists():
            data = json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                default.update(data)
    except Exception as e:
        print(f"[LICENSE] load error: {e}")
    return default


def save_license(data: dict) -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    _LICENSE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_mode() -> str:
    """trial | full"""
    lic = load_license()
    key = (lic.get("key") or "").strip()
    if key and validate_key(key):
        return "full"
    return "trial"


def max_olts() -> int:
    return 999 if get_mode() == "full" else 1


def can_add_olt(current_count: int) -> tuple[bool, str]:
    limit = max_olts()
    if current_count >= limit:
        if get_mode() == "trial":
            return False, "Mode Trial hanya boleh 1 OLT. Aktivasi Full dengan license key (HWID)."
        return False, f"Batas OLT tercapai ({limit})."
    return True, ""


def activate(key: str) -> tuple[bool, str]:
    key = (key or "").strip()
    hwid = get_hwid()
    if not validate_key(key, hwid):
        return False, "Key tidak valid untuk HWID mesin ini."
    from datetime import datetime
    save_license({
        "mode": "full",
        "key": key.strip().upper(),
        "activated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hwid": hwid,
    })
    return True, "Aktivasi Full berhasil."


def deactivate() -> None:
    save_license({"mode": "trial", "key": "", "activated_at": ""})
