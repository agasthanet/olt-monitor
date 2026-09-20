"""Hioso HA73xx SNMP OID parsers (EPON / GPON)."""
from __future__ import annotations

from typing import List, Optional, Tuple

import config
from parsers.common import (
    OnuInfo,
    _snmp_number,
    parse_serial,
    snmp_bulk_walk,
    snmp_text,
)

def _clean_display(val) -> str:
    """Buang karakter non-printable / garbage dari SNMP string."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        # MAC 6 byte
        if len(val) == 6:
            return "".join(f"{b:02X}" for b in val)
        try:
            val = val.decode("utf-8", errors="ignore")
        except Exception:
            val = val.decode("latin-1", errors="ignore")
    s = str(val).strip().strip('"')
    # filter control chars
    s = "".join(ch for ch in s if ch.isprintable())
    s = s.strip()
    if s.lower() in ("n/a", "na", "null", "none", "--", "-"):
        return ""
    return s


def _is_generic_onu_name(name: str) -> bool:
    """True jika bukan nama pelanggan yang berguna."""
    import re
    if not name:
        return True
    s = str(name).strip()
    if not s:
        return True
    # angka saja / status code / index
    if re.fullmatch(r"\d+", s):
        return True
    if len(s) <= 2 and not re.search(r"[A-Za-z]{2,}", s):
        return True
    if re.match(r"^ONU[-:_\s]?\d", s, re.I) or re.match(r"^ONU\d*$", s, re.I):
        return True
    if s.lower() in ("online", "offline", "up", "down", "active", "inactive", "yes", "no"):
        return True
    return False


HIOSO_STATUS = {
    1: "Online",   # Up
    2: "Offline",  # Down / PwrDown
    3: "Offline",
    4: "Offline",
    5: "Offline",
    0: "Unknown",
}


def _hioso_parse_power(raw) -> Optional[float]:
    """Parse Rx/Tx Hioso — support int Gauge, ASCII string, dan bytes."""
    v = _snmp_number(raw)
    if v is None:
        return None
    try:
        # integer mentah 0.01 dBm atau 0.1 dBm
        if abs(v) > 100:
            v = v / 100.0
        elif abs(v) > 40 and abs(v) <= 100:
            v = v / 10.0
        # longgarkan batas (sinyal lemah masih valid)
        if v < -50 or v > 15:
            return None
        return round(v, 2)
    except Exception:
        return None


def _parse_hioso_index(suffix: str) -> Tuple[int, int, int]:
    """Index Hioso biasanya board.pon.onu_id"""
    parts = [p for p in str(suffix).strip(".").split(".") if p]
    nums = []
    for p in parts:
        try:
            nums.append(int(p))
        except Exception:
            continue
    if len(nums) >= 3:
        return nums[0], nums[1], nums[2]
    if len(nums) == 2:
        return 1, nums[0], nums[1]
    if len(nums) == 1:
        return 1, 1, nums[0]
    return 1, 1, 0


def _fetch_hioso_epon(host: str, community: str, port: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """
    Hioso EPON — parser sederhana (versi awal yang stabil).
    OID: name.37, serial.11, status.39, dist.25, rx/tx optical table.
    """
    name_oid = "1.3.6.1.4.1.25355.3.2.6.3.2.1.37"
    serial_oid = "1.3.6.1.4.1.25355.3.2.6.3.2.1.11"
    status_oid = "1.3.6.1.4.1.25355.3.2.6.3.2.1.39"
    dist_oid = "1.3.6.1.4.1.25355.3.2.6.3.2.1.25"
    rx_oid = "1.3.6.1.4.1.25355.3.2.6.14.2.1.8"
    tx_oid = "1.3.6.1.4.1.25355.3.2.6.14.2.1.4"

    timeout = max(config.SNMP_TIMEOUT, 6)
    print("[SNMP] Hioso EPON walk (classic)...")
    names = snmp_bulk_walk(host, community, name_oid, port=port, timeout=timeout)
    print(f"[SNMP] Hioso name: {len(names)}")
    if not names:
        return []

    serials = snmp_bulk_walk(host, community, serial_oid, port=port, timeout=timeout)
    statuses = snmp_bulk_walk(host, community, status_oid, port=port, timeout=timeout)
    dists = snmp_bulk_walk(host, community, dist_oid, port=port, timeout=timeout)
    rxs = snmp_bulk_walk(host, community, rx_oid, port=port, timeout=timeout)
    txs = snmp_bulk_walk(host, community, tx_oid, port=port, timeout=timeout)
    print(f"[SNMP] Hioso serial={len(serials)} status={len(statuses)} rx={len(rxs)} tx={len(txs)}")

    def _fmt_mac(s: str) -> str:
        s = (s or "").strip().replace(":", "").replace("-", "").replace(".", "")
        if len(s) == 12 and all(c in "0123456789abcdefABCDEF" for c in s):
            s = s.lower()
            return ":".join(s[i:i+2] for i in range(0, 12, 2))
        return s

    onts: List[OnuInfo] = []
    for suffix, name in names.items():
        board, pon, onu_id = _parse_hioso_index(suffix)
        # Web Hioso HA7304 menampilkan slot 0-based (0/2:1), SNMP sering 1-based (1.2.1)
        if board >= 1:
            board = board - 1
        try:
            st_raw = statuses.get(suffix)
            try:
                status_code = int(st_raw) if st_raw is not None else -1
            except Exception:
                status_code = -1
            status = HIOSO_STATUS.get(status_code, "Unknown")
            # string status dari SNMP
            if status == "Unknown" and st_raw is not None:
                s = str(st_raw).strip().lower()
                if s in ("1", "up", "online", "active"):
                    status = "Online"
                elif s in ("2", "3", "4", "5", "down", "offline", "pwrdown", "los"):
                    status = "Offline"

            serial = _fmt_mac(parse_serial(serials.get(suffix, "")))
            # name dari OID 37; kosong/"NA" → biarkan NA atau serial
            display = snmp_text(name)
            display = "".join(ch for ch in display if ch.isprintable()).strip()
            if not display or display.isdigit():
                display = "NA"
            if display.upper() == "NA" and serial:
                # tetap tampilkan NA seperti web Hioso, serial di kolom sendiri
                display = "NA"

            rx_val = _hioso_parse_power(rxs.get(suffix))
            # optical table kadang index beda — coba tanpa suffix match longgar
            if rx_val is None:
                for k, v in (rxs or {}).items():
                    if str(k).endswith(str(suffix)) or str(suffix).endswith(str(k)):
                        rx_val = _hioso_parse_power(v)
                        if rx_val is not None:
                            break
            tx_val = _hioso_parse_power(txs.get(suffix))
            if tx_val is None:
                for k, v in (txs or {}).items():
                    if str(k).endswith(str(suffix)) or str(suffix).endswith(str(k)):
                        tx_val = _hioso_parse_power(v)
                        if tx_val is not None:
                            break

            dist = None
            try:
                if dists.get(suffix) is not None:
                    dist = int(dists.get(suffix))
            except Exception:
                pass

            if rx_val is not None and rx_val > -32 and status != "Online":
                status = "Online"

            onts.append(OnuInfo(
                board=board,
                pon=pon,
                onu_id=onu_id,
                name=display,
                description=display,
                serial=serial,
                status=status,
                status_code=status_code,
                rx_power=rx_val,
                tx_power=tx_val,
                distance=dist,
                raw_index=str(suffix),
                olt_id=olt_id,
                olt_name=olt_name,
            ))
        except Exception as e:
            print(f"[parse hioso epon] {suffix}: {e}")

    print(f"[SNMP] Hioso EPON classic result: {len(onts)} ONT")
    return onts


def _fetch_hioso_gpon(host: str, community: str, port: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """Hioso / C-Data style GPON — MIB 25355.3.3"""
    name_oid = "1.3.6.1.4.1.25355.3.3.1.1.1.2"
    serial_oid = "1.3.6.1.4.1.25355.3.3.1.1.1.5"
    status_oid = "1.3.6.1.4.1.25355.3.3.1.1.1.11"
    rx_oid = "1.3.6.1.4.1.25355.3.3.1.1.4.1.1"
    tx_oid = "1.3.6.1.4.1.25355.3.3.1.1.4.1.2"

    timeout = max(config.SNMP_TIMEOUT, 6)
    print("[SNMP] Hioso GPON walk...")
    names = snmp_bulk_walk(host, community, name_oid, port=port, timeout=timeout)
    print(f"[SNMP] Hioso GPON name: {len(names)}")
    if not names:
        return []

    serials = snmp_bulk_walk(host, community, serial_oid, port=port, timeout=timeout)
    statuses = snmp_bulk_walk(host, community, status_oid, port=port, timeout=timeout)
    rxs = snmp_bulk_walk(host, community, rx_oid, port=port, timeout=timeout)
    txs = snmp_bulk_walk(host, community, tx_oid, port=port, timeout=timeout)

    onts: List[OnuInfo] = []
    for suffix, name in names.items():
        board, pon, onu_id = _parse_hioso_index(suffix)
        try:
            st_raw = statuses.get(suffix)
            try:
                status_code = int(st_raw) if st_raw is not None else -1
            except Exception:
                status_code = -1
            status = HIOSO_STATUS.get(status_code, "Unknown")
            serial = parse_serial(serials.get(suffix, ""))
            rx_val = _hioso_parse_power(rxs.get(suffix))
            tx_val = _hioso_parse_power(txs.get(suffix))
            if rx_val is not None and rx_val > -32 and status != "Online":
                status = "Online"
            onts.append(OnuInfo(
                board=board, pon=pon, onu_id=onu_id,
                name=snmp_text(name),
                serial=serial,
                status=status,
                status_code=status_code,
                rx_power=rx_val,
                tx_power=tx_val,
                raw_index=str(suffix),
                olt_id=olt_id,
                olt_name=olt_name,
            ))
        except Exception as e:
            print(f"[parse hioso gpon] {suffix}: {e}")
    return onts


def detect_hioso_type(host: str, community: str, port: int = 161) -> Optional[str]:
    """Return 'epon', 'gpon', or None"""
    epon = snmp_bulk_walk(host, community, "1.3.6.1.4.1.25355.3.2.6.3.2.1.37", port=port, timeout=config.SNMP_TIMEOUT, max_oids=3)
    if epon:
        print("[SNMP] Hioso type: EPON (25355.3.2)")
        return "epon"
    gpon = snmp_bulk_walk(host, community, "1.3.6.1.4.1.25355.3.3.1.1.1.2", port=port, timeout=config.SNMP_TIMEOUT, max_oids=3)
    if gpon:
        print("[SNMP] Hioso type: GPON (25355.3.3)")
        return "gpon"
    return None


def fetch_hioso_onts(
    host: str,
    community: str,
    port: int = 161,
    variant: str = "auto",
    olt_id: str = "",
    olt_name: str = "",
) -> List[OnuInfo]:
    if variant in ("auto", "", None):
        variant = detect_hioso_type(host, community, port) or "epon"
    if variant == "gpon":
        return _fetch_hioso_gpon(host, community, port, olt_id=olt_id, olt_name=olt_name)
    return _fetch_hioso_epon(host, community, port, olt_id=olt_id, olt_name=olt_name)


# ============================================================
# HS Airpo / VSOL-style OLT (enterprise 37950) + fallback Hioso
# ============================================================

