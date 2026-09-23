"""
Telemetry opt-in untuk OLT MONITOR.

Default: MATI. Tidak mengirim data kecuali user mengaktifkan di Settings.

Yang DIKIRIM (anonim / agregat):
  - install_id (UUID instalasi, bukan data pelanggan)
  - hwid (sudah hash format license)
  - app_version, license_mode, license_max_olts
  - olt_count (jumlah OLT terdaftar — angka saja)
  - platform (os/arch)
  - ts (waktu kirim)

Yang TIDAK dikirim:
  - IP OLT, community, password, serial ONU, nama pelanggan, ODP, cache ONT
"""
from __future__ import annotations

import json
import platform
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

_DATA = Path(__file__).resolve().parent / "data"
_CFG_FILE = _DATA / "telemetry.json"

# Endpoint default — ganti di Settings / env TELEMETRY_URL
DEFAULT_ENDPOINT = "https://olt-monitor-telemetry.agastha-net.workers.dev/v1/ping"

_DEFAULT_CFG = {
    "enabled": True,
    "endpoint": DEFAULT_ENDPOINT,
    "interval_hours": 24,
    "last_sent": None,
    "last_ok": None,
    "last_error": "",
    "last_payload": None,
}


def load_cfg() -> dict:
    cfg = dict(_DEFAULT_CFG)
    try:
        if _CFG_FILE.exists():
            data = json.loads(_CFG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # pertahankan endpoint/last_* dari file; enabled dikontrol di bawah
                for k in ("endpoint", "interval_hours", "last_sent", "last_ok", "last_error"):
                    if k in data:
                        cfg[k] = data[k]
    except Exception as e:
        print(f"[TELEMETRY] load cfg: {e}")
    import os
    env_url = (os.getenv("TELEMETRY_URL") or "").strip()
    if env_url:
        cfg["endpoint"] = env_url
    # Selalu aktif kecuali TELEMETRY_DISABLED=1
    disabled = (os.getenv("TELEMETRY_DISABLED") or "").strip().lower() in ("1", "true", "yes")
    cfg["enabled"] = not disabled
    return cfg


def save_cfg(cfg: dict) -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    # jangan simpan payload besar terus-menerus
    out = {
        "enabled": bool(cfg.get("enabled")),
        "endpoint": (cfg.get("endpoint") or DEFAULT_ENDPOINT).strip(),
        "interval_hours": int(cfg.get("interval_hours") or 24),
        "last_sent": cfg.get("last_sent"),
        "last_ok": cfg.get("last_ok"),
        "last_error": (cfg.get("last_error") or "")[:500],
    }
    _CFG_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def build_payload(
    *,
    app_version: str,
    install_id: str,
    hwid: str,
    license_mode: str,
    license_max_olts: int,
    olt_count: int,
    email: str = "",
    full_name: str = "",
    company: str = "",
    whatsapp: str = "",
) -> dict:
    return {
        "schema": 3,
        "app": "olt-monitor",
        "version": app_version,
        "install_id": install_id,
        "hwid": hwid,
        "email": (email or "").strip().lower()[:120],
        "full_name": (full_name or "").strip()[:80],
        "company": (company or "").strip()[:80],
        "whatsapp": (whatsapp or "").strip()[:32],
        "license_mode": license_mode,
        "license_max_olts": int(license_max_olts or 0),
        "olt_count": int(olt_count or 0),
        "platform": {
            "system": platform.system() or "",
            "release": platform.release() or "",
            "machine": platform.machine() or "",
            "python": platform.python_version(),
        },
        "ts": int(time.time()),
    }


def send_ping(payload: dict, endpoint: str, timeout: float = 8.0) -> tuple[bool, str, dict]:
    """Return (ok, msg, response_json)."""
    url = (endpoint or "").strip()
    if not url.startswith("http"):
        return False, "endpoint tidak valid", {}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"OLT-MONITOR/{payload.get('version', '?')}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            raw = resp.read()[:4000]
            data = {}
            try:
                data = json.loads(raw.decode("utf-8", errors="ignore") or "{}")
            except Exception:
                data = {}
            if 200 <= int(code) < 300:
                return True, f"HTTP {code}", data if isinstance(data, dict) else {}
            return False, f"HTTP {code}: {raw[:200]!r}", {}
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}", {}
    except Exception as e:
        return False, str(e), {}


def _endpoint_base(ping_url: str) -> str:
    u = (ping_url or "").rstrip("/")
    if u.endswith("/v1/ping"):
        return u[: -len("/v1/ping")]
    if u.endswith("/ping"):
        return u.rsplit("/", 1)[0]
    return u


def fetch_remote_license(ping_url: str, install_id: str, hwid: str, timeout: float = 8.0) -> dict:
    """GET /v1/license?install_id=&hwid= → {mode, max_olts} atau {}."""
    base = _endpoint_base(ping_url)
    if not base.startswith("http"):
        return {}
    q = f"install_id={urllib.parse.quote(install_id or '')}&hwid={urllib.parse.quote(hwid or '')}"
    url = f"{base}/v1/license?{q}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "OLT-MONITOR"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()[:2000]
            data = json.loads(raw.decode("utf-8", errors="ignore") or "{}")
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[TELEMETRY] fetch license: {e}")
        return {}


def maybe_report(
    *,
    app_version: str,
    install_id: str,
    hwid: str,
    license_mode: str,
    license_max_olts: int,
    olt_count: int,
    email: str = "",
    full_name: str = "",
    company: str = "",
    whatsapp: str = "",
    force: bool = False,
) -> dict:
    """
    Kirim telemetry jika enabled dan interval lewat (atau force=True).
    Return status dict untuk UI.
    """
    cfg = load_cfg()
    if not cfg.get("enabled") and not force:
        return {"skipped": True, "reason": "disabled"}

    if not cfg.get("enabled") and force:
        return {"skipped": True, "reason": "disabled (aktifkan dulu di Settings)"}

    endpoint = (cfg.get("endpoint") or DEFAULT_ENDPOINT).strip()
    interval_h = max(1, int(cfg.get("interval_hours") or 24))
    now = time.time()
    last = cfg.get("last_sent")
    try:
        last_ts = float(last) if last is not None else 0.0
    except Exception:
        last_ts = 0.0

    if not force and last_ts and (now - last_ts) < interval_h * 3600:
        return {
            "skipped": True,
            "reason": "interval",
            "next_in_sec": int(interval_h * 3600 - (now - last_ts)),
        }

    payload = build_payload(
        app_version=app_version,
        install_id=install_id or "",
        hwid=hwid or "",
        license_mode=license_mode or "trial",
        license_max_olts=license_max_olts,
        olt_count=olt_count,
        email=email or "",
        full_name=full_name or "",
        company=company or "",
        whatsapp=whatsapp or "",
    )
    ok, msg, resp = send_ping(payload, endpoint)
    cfg["last_sent"] = now
    cfg["last_ok"] = ok
    cfg["last_error"] = "" if ok else msg
    save_cfg(cfg)
    print(f"[TELEMETRY] {'OK' if ok else 'FAIL'}: {msg}")

    # Terapkan license remote jika server mengirim
    lic_info = {}
    if ok and isinstance(resp, dict):
        lic_info = resp.get("license") if isinstance(resp.get("license"), dict) else {}
    if not lic_info:
        try:
            lic_info = fetch_remote_license(endpoint, payload.get("install_id") or "", payload.get("hwid") or "")
            if lic_info.get("license"):
                lic_info = lic_info["license"]
        except Exception:
            lic_info = {}
    if lic_info and lic_info.get("mode"):
        try:
            from license_mod import apply_remote_license
            apply_remote_license(
                str(lic_info.get("mode") or "trial"),
                int(lic_info.get("max_olts") or 1),
                note="telemetry_sync",
            )
        except Exception as e:
            print(f"[LICENSE] apply remote: {e}")

    return {"skipped": False, "ok": ok, "msg": msg, "payload": payload, "license": lic_info}


def set_enabled(enabled: bool, endpoint: Optional[str] = None) -> dict:
    cfg = load_cfg()
    cfg["enabled"] = bool(enabled)
    if endpoint is not None and str(endpoint).strip():
        cfg["endpoint"] = str(endpoint).strip()
    save_cfg(cfg)
    return cfg
