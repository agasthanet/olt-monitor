"""
Health OLT: CPU, Memory, Uptime, Temperature, Fan (jika MIB support).
SNMP untuk ZTE/Hioso; CLI partial untuk vendor CLI.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from snmp_zte import snmp_get, snmp_bulk_walk

# Standard
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"

# HOST-RESOURCES
OID_HR_PROCESSOR_LOAD = "1.3.6.1.2.1.25.3.3.1.2"  # walk
OID_HR_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"
OID_HR_STORAGE_SIZE = "1.3.6.1.2.1.25.2.3.1.5"
OID_HR_STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6"

# ZTE C300/C320 equipment
OID_ZTE_CARD_CPU = "1.3.6.1.4.1.3902.1015.2.1.1.3.1.9"   # walk zxAnCardCpuLoad
OID_ZTE_CARD_MEM = "1.3.6.1.4.1.3902.1015.2.1.1.3.1.11"  # walk zxAnCardMemUsage
OID_ZTE_TEMP = "1.3.6.1.4.1.3902.1015.2.1.3.2"           # chassis temp (scalar-ish)
OID_ZTE_TEMP_ALT = "1.3.6.1.4.1.3902.1015.2.1.3.2.0"

# Common fan / env (UCD / ENTITY - best effort)
OID_UCD_SS_CPU_USER = "1.3.6.1.4.1.2021.11.9.0"
OID_UCD_MEM_AVAIL = "1.3.6.1.4.1.2021.4.6.0"
OID_UCD_MEM_TOTAL = "1.3.6.1.4.1.2021.4.5.0"


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        if isinstance(v, bytes):
            v = v.decode("utf-8", errors="ignore")
        return int(float(str(v).strip()))
    except Exception:
        return None


def _format_uptime(ticks) -> str:
    """SNMP TimeTicks = hundredths of a second."""
    n = _to_int(ticks)
    if n is None:
        return "—"
    sec = n // 100
    days, sec = divmod(sec, 86400)
    hours, sec = divmod(sec, 3600)
    mins, sec = divmod(sec, 60)
    if days:
        return f"{days}d {hours}h {mins}m"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m {sec}s"


def _avg(nums: List[int]) -> Optional[float]:
    if not nums:
        return None
    return round(sum(nums) / len(nums), 1)


def fetch_olt_health_snmp(host: str, community: str, port: int = 161) -> Dict[str, Any]:
    """Ambil health via SNMP. Field None = tidak tersedia di OLT ini."""
    out: Dict[str, Any] = {
        "ok": False,
        "source": "snmp",
        "sys_name": None,
        "sys_descr": None,
        "uptime": None,
        "uptime_raw": None,
        "cpu_percent": None,
        "mem_percent": None,
        "temperature_c": None,
        "fan": None,
        "details": {},
        "error": "",
        "ts": int(time.time()),
    }
    try:
        sys_name = snmp_get(host, community, OID_SYS_NAME, port=port, timeout=4)
        uptime = snmp_get(host, community, OID_SYS_UPTIME, port=port, timeout=4)
        descr = snmp_get(host, community, OID_SYS_DESCR, port=port, timeout=4)
        out["sys_name"] = str(sys_name) if sys_name is not None else None
        out["sys_descr"] = str(descr)[:120] if descr is not None else None
        out["uptime_raw"] = _to_int(uptime)
        out["uptime"] = _format_uptime(uptime)
        out["ok"] = uptime is not None or sys_name is not None
    except Exception as e:
        out["error"] = f"sys: {e}"
        return out

    # --- CPU ---
    cpu_vals: List[int] = []
    try:
        for _sfx, val in (snmp_bulk_walk(host, community, OID_ZTE_CARD_CPU, port=port, timeout=5, max_repetitions=20) or {}).items():
            n = _to_int(val)
            if n is not None and 0 <= n <= 100:
                cpu_vals.append(n)
    except Exception as e:
        print(f"[HEALTH] cpu zte: {e}")
    if not cpu_vals:
        try:
            for _sfx, val in (snmp_bulk_walk(host, community, OID_HR_PROCESSOR_LOAD, port=port, timeout=5, max_repetitions=10) or {}).items():
                n = _to_int(val)
                if n is not None and 0 <= n <= 100:
                    cpu_vals.append(n)
        except Exception as e:
            print(f"[HEALTH] cpu hr: {e}")
    if not cpu_vals:
        try:
            v = snmp_get(host, community, OID_UCD_SS_CPU_USER, port=port, timeout=3)
            n = _to_int(v)
            if n is not None:
                cpu_vals.append(n)
        except Exception:
            pass
    out["cpu_percent"] = _avg(cpu_vals)
    if cpu_vals:
        out["details"]["cpu_samples"] = cpu_vals

    # --- Memory ---
    mem_vals: List[int] = []
    try:
        for _sfx, val in (snmp_bulk_walk(host, community, OID_ZTE_CARD_MEM, port=port, timeout=5, max_repetitions=20) or {}).items():
            n = _to_int(val)
            if n is not None and 0 <= n <= 100:
                mem_vals.append(n)
    except Exception as e:
        print(f"[HEALTH] mem zte: {e}")
    if not mem_vals:
        try:
            sizes, used, descrs = {}, {}, {}
            for sfx, val in (snmp_bulk_walk(host, community, OID_HR_STORAGE_DESCR, port=port, timeout=4, max_repetitions=15) or {}).items():
                descrs[str(sfx).rsplit(".", 1)[-1]] = str(val).lower()
            for sfx, val in (snmp_bulk_walk(host, community, OID_HR_STORAGE_SIZE, port=port, timeout=4, max_repetitions=15) or {}).items():
                sizes[str(sfx).rsplit(".", 1)[-1]] = _to_int(val)
            for sfx, val in (snmp_bulk_walk(host, community, OID_HR_STORAGE_USED, port=port, timeout=4, max_repetitions=15) or {}).items():
                used[str(sfx).rsplit(".", 1)[-1]] = _to_int(val)
            for idx, d in descrs.items():
                if "memory" in d or "ram" in d or "real" in d:
                    s, u = sizes.get(idx), used.get(idx)
                    if s and u is not None and s > 0:
                        mem_vals.append(int(100 * u / s))
        except Exception as e:
            print(f"[HEALTH] mem hr: {e}")
    out["mem_percent"] = _avg(mem_vals)
    if mem_vals:
        out["details"]["mem_samples"] = mem_vals

    # --- Temperature ---
    try:
        for candidate in (OID_ZTE_TEMP_ALT, OID_ZTE_TEMP):
            v = snmp_get(host, community, candidate, port=port, timeout=3)
            n = _to_int(v)
            if n is not None and -20 < n < 120:
                out["temperature_c"] = n
                break
        if out["temperature_c"] is None:
            # walk short tree
            for _sfx, val in (snmp_bulk_walk(host, community, "1.3.6.1.4.1.3902.1015.2.1.3", port=port, timeout=4, max_repetitions=10) or {}).items():
                n = _to_int(val)
                if n is not None and 0 < n < 100:
                    out["temperature_c"] = n
                    break
    except Exception:
        pass

    # Fan: rarely exposed — mark N/A unless we find something obvious
    out["fan"] = None  # UI shows "N/A" if None
    return out


def fetch_olt_health(olt: dict) -> Dict[str, Any]:
    """Dispatch by vendor. CLI OLT: limited (uptime/sys via snmp if community works)."""
    if not olt:
        return {"ok": False, "error": "no olt", "ts": int(time.time())}
    vendor = (olt.get("vendor") or "").lower()
    host = olt.get("ip") or ""
    community = olt.get("community") or "public"
    port = int(olt.get("port") or 161)

    # CLI vendors still may answer sysDescr if SNMP agent minimal exists
    if vendor in ("hsairpo-cli", "hioso-cli", "ha7302", "cli"):
        # try SNMP first for sys uptime; if fail return partial
        h = fetch_olt_health_snmp(host, community, port)
        if not h.get("ok"):
            h["error"] = h.get("error") or "SNMP terbatas pada OLT CLI — CPU/Mem/Fan mungkin tidak tersedia"
            h["source"] = "cli-limited"
        return h

    return fetch_olt_health_snmp(host, community, port)


# cache per olt_id
_CACHE: Dict[str, Dict[str, Any]] = {}


def get_cached_health(olt_id: str) -> Optional[Dict[str, Any]]:
    return _CACHE.get(olt_id)


def refresh_health(olt: dict) -> Dict[str, Any]:
    oid = str(olt.get("id") or "")
    h = fetch_olt_health(olt)
    if oid:
        _CACHE[oid] = h
    return h
