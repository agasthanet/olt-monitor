"""
License: Trial (max 1 OLT) vs Full (kelipatan 5 OLT: 5/10/15/..., key + HWID).
Format key: FULL-05-XXXXX-XXXXX-XXXXX-XXXXX  (05 = limit OLT)
Key lama FULL-XXXXX-... (tanpa angka) dihitung max 5 OLT.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import platform
import re
import uuid
from pathlib import Path

_SECRET = b"OLT-MONITOR-xAI-2026-CyberPlus-HWID-KEY"

_DATA = Path(__file__).resolve().parent / "data"
_LICENSE_FILE = _DATA / "license.json"

TRIAL_MAX_OLTS = 1
DEFAULT_FULL_MAX = 5  # key legacy / fallback


def get_hwid() -> str:
    parts = []
    try:
        parts.append(str(uuid.getnode()))
    except Exception:
        pass
    parts.append(platform.node() or "")
    parts.append(platform.system() or "")
    parts.append(platform.machine() or "")
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
    return "-".join(digest[i : i + 4] for i in range(0, 16, 4))


def _normalize_hwid(hwid: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", (hwid or "")).upper()


def normalize_limit(n: int) -> int:
    """Paksa kelipatan 5, minimum 5."""
    try:
        n = int(n)
    except Exception:
        n = DEFAULT_FULL_MAX
    if n < 5:
        n = 5
    # bulatkan ke atas ke kelipatan 5
    if n % 5:
        n = ((n // 5) + 1) * 5
    return n


def generate_key(hwid: str, max_olts: int = 5) -> str:
    """Generate Full key untuk HWID + limit OLT (kelipatan 5)."""
    h = _normalize_hwid(hwid)
    if len(h) < 8:
        raise ValueError("HWID terlalu pendek / tidak valid")
    limit = normalize_limit(max_olts)
    payload = f"{h}:{limit}".encode("utf-8")
    sig = hmac.new(_SECRET, payload, hashlib.sha256).hexdigest().upper()
    body = sig[:20]
    groups = "-".join(body[i : i + 5] for i in range(0, 20, 5))
    return f"FULL-{limit:02d}-{groups}"


def parse_key(key: str) -> tuple[int | None, str]:
    """
    Return (limit, signature_part).
    limit None = format tidak dikenal.
    Legacy FULL-XXXXX-XXXXX-XXXXX-XXXXX → limit 5.
    """
    key = (key or "").strip().upper().replace(" ", "")
    if not key.startswith("FULL-"):
        return None, ""
    parts = key.split("-")
    # FULL-05-AAAAA-BBBBB-CCCCC-DDDDD → ['FULL','05','AAAAA',...]
    if len(parts) >= 6 and parts[1].isdigit():
        limit = int(parts[1])
        sig = "-".join(parts[2:])
        return limit, sig
    # Legacy FULL-AAAAA-BBBBB-CCCCC-DDDDD
    if len(parts) >= 5 and not parts[1].isdigit():
        return DEFAULT_FULL_MAX, "-".join(parts[1:])
    return None, ""


def validate_key(key: str, hwid: str | None = None) -> bool:
    key = (key or "").strip().upper()
    if not key:
        return False
    hwid = hwid or get_hwid()
    limit, _ = parse_key(key)
    if limit is None:
        return False
    # legacy: also accept old hmac(hwid only) for limit 5
    expected = generate_key(hwid, limit).upper().replace(" ", "")
    got = key.replace(" ", "")
    if got == expected:
        return True
    # legacy key without limit digit in format
    if limit == DEFAULT_FULL_MAX:
        h = _normalize_hwid(hwid)
        sig = hmac.new(_SECRET, h.encode("utf-8"), hashlib.sha256).hexdigest().upper()[:20]
        legacy = "FULL-" + "-".join(sig[i : i + 5] for i in range(0, 20, 5))
        if got == legacy.upper():
            return True
    return False


def key_limit(key: str) -> int:
    limit, _ = parse_key(key)
    if limit is None:
        return TRIAL_MAX_OLTS
    return normalize_limit(limit)


def load_license() -> dict:
    default = {"mode": "trial", "key": "", "activated_at": "", "max_olts": TRIAL_MAX_OLTS}
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
    lic = load_license()
    key = (lic.get("key") or "").strip()
    if key and validate_key(key):
        return "full"
    return "trial"


def max_olts() -> int:
    if get_mode() != "full":
        return TRIAL_MAX_OLTS
    lic = load_license()
    # prefer stored limit, else parse from key
    stored = lic.get("max_olts")
    try:
        if stored is not None and int(stored) > 1:
            return normalize_limit(int(stored))
    except Exception:
        pass
    key = (lic.get("key") or "").strip()
    if key:
        return key_limit(key)
    return DEFAULT_FULL_MAX


def can_add_olt(current_count: int) -> tuple[bool, str]:
    limit = max_olts()
    if current_count >= limit:
        if get_mode() == "trial":
            return (
                False,
                "Mode Trial max 1 OLT. Aktivasi Full (kelipatan 5 OLT) dengan license key.",
            )
        return (
            False,
            f"Mode Full max {limit} OLT. Minta key dengan limit lebih tinggi (10/15/20…).",
        )
    return True, ""


def activate(key: str) -> tuple[bool, str]:
    key = (key or "").strip()
    hwid = get_hwid()
    if not validate_key(key, hwid):
        return False, "Key tidak valid untuk HWID mesin ini."
    from datetime import datetime

    limit = key_limit(key)
    save_license({
        "mode": "full",
        "key": key.strip().upper(),
        "activated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hwid": hwid,
        "max_olts": limit,
    })
    return True, f"Aktivasi Full berhasil (max {limit} OLT)."


def deactivate() -> None:
    save_license({
        "mode": "trial",
        "key": "",
        "activated_at": "",
        "max_olts": TRIAL_MAX_OLTS,
    })
