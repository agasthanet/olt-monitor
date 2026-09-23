"""
License: Trial (max 3 OLT) vs Full (kelipatan 5 OLT: 5/10/15/..., key + HWID).
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

TRIAL_MAX_OLTS = 3
DEFAULT_FULL_MAX = 5  # key legacy / fallback


def _read_machine_id() -> str:
    """Linux machine-id (bisa sama antar VM yang di-clone)."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            p = Path(path)
            if p.is_file():
                val = p.read_text(encoding="utf-8", errors="ignore").strip()
                if val and len(val) >= 8:
                    return val
        except Exception:
            continue
    return ""


def _read_stable_mac() -> str:
    """MAC dari interface non-virtual (bisa sama di template clone)."""
    skip_prefix = ("lo", "docker", "veth", "br-", "virbr", "cni", "flannel", "tun", "tap", "wg")
    base = Path("/sys/class/net")
    if not base.is_dir():
        return ""
    try:
        names = sorted(p.name for p in base.iterdir() if p.is_dir())
    except Exception:
        return ""
    for name in names:
        if name == "lo" or name.startswith(skip_prefix):
            continue
        try:
            mac = (base / name / "address").read_text(encoding="utf-8", errors="ignore").strip().lower()
            if not mac or mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
                continue
            return mac.replace(":", "")
        except Exception:
            continue
    return ""


def _windows_machine_guid() -> str:
    try:
        if platform.system() != "Windows":
            return ""
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return str(guid or "")
    except Exception:
        return ""


def _format_hwid(digest_hex: str) -> str:
    digest_hex = re.sub(r"[^0-9A-Fa-f]", "", digest_hex).upper()
    if len(digest_hex) < 16:
        digest_hex = (digest_hex + "0" * 16)[:16]
    return "-".join(digest_hex[i : i + 4] for i in range(0, 16, 4))


def _get_or_create_install_id() -> str:
    """
    ID unik per instalasi app (bukan per hardware template).
    Disimpan di data/install_id.txt — stabil reboot, beda antar mesin
    meski VM di-clone (asal folder data/ tidak di-copy).
    """
    path = _DATA / "install_id.txt"
    try:
        if path.is_file():
            val = path.read_text(encoding="utf-8", errors="ignore").strip().lower()
            if re.match(r"^[0-9a-f]{16,64}$", val):
                return val
    except Exception:
        pass
    import secrets
    val = secrets.token_hex(16)
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        path.write_text(val + "\n", encoding="utf-8")
    except Exception as e:
        print(f"[LICENSE] gagal simpan install_id: {e}")
    return val


def _compute_hwid_raw() -> str:
    """
    Campur:
    - install_id (unik per install — cegah kembar antar mesin clone)
    - machine-id / MachineGuid / MAC (ikatan mesin)
    - hostname + arch
    """
    parts = [
        "iid:" + _get_or_create_install_id(),
        "host:" + (platform.node() or ""),
        "sys:" + (platform.system() or ""),
        "arch:" + (platform.machine() or ""),
    ]
    win = _windows_machine_guid()
    if win:
        parts.append("win:" + win)
    mid = _read_machine_id()
    if mid:
        parts.append("mid:" + mid)
    mac = _read_stable_mac()
    if mac:
        parts.append("mac:" + mac)
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest().upper()


def get_hwid() -> str:
    """
    HWID stabil antar reboot, unik per instalasi.
    Freeze di data/machine_hwid.txt setelah dihitung sekali.
    Jangan copy folder data/ antar server — ikut ke-copy HWID + license.
    """
    freeze = _DATA / "machine_hwid.txt"
    try:
        if freeze.is_file():
            saved = freeze.read_text(encoding="utf-8", errors="ignore").strip().upper()
            if re.match(r"^[0-9A-F]{4}(-[0-9A-F]{4}){3}$", saved):
                return saved
            norm = _normalize_hwid(saved)
            if len(norm) >= 16:
                return _format_hwid(norm)
    except Exception:
        pass

    hwid = _format_hwid(_compute_hwid_raw())
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        freeze.write_text(hwid + "\n", encoding="utf-8")
    except Exception as e:
        print(f"[LICENSE] gagal simpan machine_hwid: {e}")
    return hwid


def reset_hwid() -> str:
    """Hapus freeze + install_id, buat HWID baru (untuk migrasi / bentrok)."""
    for name in ("machine_hwid.txt", "install_id.txt"):
        try:
            (_DATA / name).unlink(missing_ok=True)
        except Exception:
            pass
    return get_hwid()


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



def apply_remote_license(mode: str, max_olts: int = 5, note: str = "") -> None:
    """Terapkan license dari server telemetry (tanpa keygen)."""
    from datetime import datetime
    mode = (mode or "trial").strip().lower()
    if mode not in ("trial", "full"):
        mode = "trial"
    try:
        n = int(max_olts)
    except Exception:
        n = TRIAL_MAX_OLTS if mode == "trial" else DEFAULT_FULL_MAX
    if mode == "trial":
        n = TRIAL_MAX_OLTS
    else:
        try:
            n = int(n)
        except Exception:
            n = DEFAULT_FULL_MAX
        if n < 5:
            n = 5
        n = normalize_limit(n)
    lic = load_license()
    lic["mode"] = mode
    lic["max_olts"] = n
    lic["source"] = "remote"
    # remote grant mengalahkan key lokal
    if mode == "full":
        lic["key"] = lic.get("key") or "REMOTE"
    lic["remote_synced_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if note:
        lic["remote_note"] = str(note)[:120]
    if mode == "full":
        lic["activated_at"] = lic["remote_synced_at"]
    else:
        lic["activated_at"] = ""
        lic["key"] = ""
    save_license(lic)
    print(f"[LICENSE] remote → {mode} max_olts={n} source=remote")


def clear_remote_to_trial() -> None:
    apply_remote_license("trial", TRIAL_MAX_OLTS, note="server_trial")


def get_mode() -> str:
    lic = load_license()
    # Prioritas: grant dari server telemetry
    src = (lic.get("source") or "").strip().lower()
    mode = (lic.get("mode") or "").strip().lower()
    if src == "remote":
        return "full" if mode == "full" else "trial"
    key = (lic.get("key") or "").strip()
    if key and key != "REMOTE" and validate_key(key):
        return "full"
    if mode == "full" and int(lic.get("max_olts") or 0) > 1:
        return "full"
    return "trial"


def max_olts() -> int:
    if get_mode() != "full":
        return TRIAL_MAX_OLTS
    lic = load_license()
    stored = lic.get("max_olts")
    try:
        if stored is not None and int(stored) > 1:
            return normalize_limit(int(stored))
    except Exception:
        pass
    if (lic.get("source") or "") == "remote":
        return DEFAULT_FULL_MAX
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
                "Mode Trial max 3 OLT. Aktivasi Full (kelipatan 5 OLT) dengan license key.",
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
