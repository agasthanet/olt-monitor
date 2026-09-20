"""VSOL SNMP OID parsers."""
from __future__ import annotations

from typing import List, Optional, Tuple

import config
from parsers.common import OnuInfo, parse_serial, snmp_bulk_walk, snmp_text
from parsers.hioso import _parse_hioso_index, _hioso_parse_power

def _vsol_parse_power(raw) -> Optional[float]:
    """VSOL sering kirim string seperti '0.03 mW (-14.60 dBm)' atau '-14.60'."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.upper() in ("N/A", "NA", "--", "NULL"):
        return None
    # ambil dBm dalam kurung dulu
    m = re.search(r"\((-?\d+(?:\.\d+)?)\s*dBm\)", s, re.I)
    if m:
        return round(float(m.group(1)), 2)
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*dBm", s, re.I)
    if m:
        return round(float(m.group(1)), 2)
    try:
        v = float(s.replace("dBm", "").strip())
        if abs(v) > 100:
            v = v / 100.0
        elif abs(v) > 40:
            v = v / 10.0
        if -40 <= v <= 10:
            return round(v, 2)
    except Exception:
        pass
    return None


def _fetch_vsol_gpon(host: str, community: str, port: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """VSOL / HS Airpo GPON — MIB 37950.1.1.6"""
    # status, id, model, rx, tx, distance
    status_oid = "1.3.6.1.4.1.37950.1.1.6.1.1.1.1.5"
    onu_id_oid = "1.3.6.1.4.1.37950.1.1.6.1.1.2.1.5"
    model_oid = "1.3.6.1.4.1.37950.1.1.6.1.1.2.1.6"
    name_oid = "1.3.6.1.4.1.37950.1.1.6.1.1.2.1.2"  # description/name if exists
    serial_oid = "1.3.6.1.4.1.37950.1.1.6.1.1.2.1.3"
    rx_oid = "1.3.6.1.4.1.37950.1.1.6.1.1.3.1.7"
    tx_oid = "1.3.6.1.4.1.37950.1.1.6.1.1.3.1.6"
    dist_oid = "1.3.6.1.4.1.37950.1.1.6.1.1.12.1.3"

    timeout = max(config.SNMP_TIMEOUT, 6)
    print("[SNMP] HS Airpo/VSOL GPON walk...")
    statuses = snmp_bulk_walk(host, community, status_oid, port=port, timeout=timeout)
    print(f"[SNMP] VSOL status: {len(statuses)}")
    if not statuses:
        return []

    names = snmp_bulk_walk(host, community, name_oid, port=port, timeout=timeout)
    serials = snmp_bulk_walk(host, community, serial_oid, port=port, timeout=timeout)
    models = snmp_bulk_walk(host, community, model_oid, port=port, timeout=timeout)
    onu_ids = snmp_bulk_walk(host, community, onu_id_oid, port=port, timeout=timeout)
    rxs = snmp_bulk_walk(host, community, rx_oid, port=port, timeout=timeout)
    txs = snmp_bulk_walk(host, community, tx_oid, port=port, timeout=timeout)
    dists = snmp_bulk_walk(host, community, dist_oid, port=port, timeout=timeout)
    print(f"[SNMP] VSOL name={len(names)} sn={len(serials)} rx={len(rxs)}")

    onts: List[OnuInfo] = []
    for suffix, st_raw in statuses.items():
        board, pon, onu_id = _parse_hioso_index(suffix)
        try:
            if onu_ids.get(suffix) is not None:
                try:
                    onu_id = int(onu_ids.get(suffix))
                except Exception:
                    pass
            try:
                status_code = int(st_raw) if st_raw is not None else -1
            except Exception:
                status_code = -1
            # VSOL: 1=online sering, 0/2=offline
            if status_code == 1:
                status = "Online"
            elif status_code in (0, 2, 3):
                status = "Offline"
            else:
                status = HIOSO_STATUS.get(status_code, "Unknown")

            name = str(names.get(suffix) or models.get(suffix) or "").strip('"')
            serial = parse_serial(serials.get(suffix, ""))
            rx_val = _vsol_parse_power(rxs.get(suffix))
            tx_val = _vsol_parse_power(txs.get(suffix))
            dist = None
            try:
                if dists.get(suffix) is not None:
                    dist = int(float(str(dists.get(suffix))))
            except Exception:
                pass
            if rx_val is not None and rx_val > -32 and status != "Online":
                status = "Online"
            onts.append(OnuInfo(
                board=board, pon=pon, onu_id=onu_id,
                name=name,
                serial=serial,
                onu_type=str(models.get(suffix) or ""),
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
            print(f"[parse vsol] {suffix}: {e}")
    return onts


def _fetch_vsol_epon(host: str, community: str, port: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """VSOL EPON path 37950.1.1.5 — coba beberapa kandidat name/status."""
    candidates = [
        # (name, serial, status, rx, tx)
        (
            "1.3.6.1.4.1.37950.1.1.5.12.2.1.2",
            "1.3.6.1.4.1.37950.1.1.5.12.2.1.3",
            "1.3.6.1.4.1.37950.1.1.5.12.2.1.5",
            "1.3.6.1.4.1.37950.1.1.5.12.2.1.8.1.7",  # may need deeper
            "1.3.6.1.4.1.37950.1.1.5.12.2.1.8.1.6",
        ),
    ]
    # Optical often under 37950.1.1.5.10.13 / 12.2.1.8
    timeout = max(config.SNMP_TIMEOUT, 6)
    print("[SNMP] HS Airpo/VSOL EPON probe...")
    # Prefer status walk that returns data
    status_oids = [
        "1.3.6.1.4.1.37950.1.1.5.12.2.1.5",
        "1.3.6.1.4.1.37950.1.1.5.10.12.1.5",
    ]
    statuses = {}
    status_oid = status_oids[0]
    for so in status_oids:
        statuses = snmp_bulk_walk(host, community, so, port=port, timeout=timeout)
        if statuses:
            status_oid = so
            break
    print(f"[SNMP] VSOL EPON status via {status_oid}: {len(statuses)}")
    if not statuses:
        return []

    # Derive sibling OIDs from status parent
    # ...status.X -> try name/serial nearby
    names = snmp_bulk_walk(host, community, "1.3.6.1.4.1.37950.1.1.5.12.2.1.2", port=port, timeout=timeout)
    serials = snmp_bulk_walk(host, community, "1.3.6.1.4.1.37950.1.1.5.12.2.1.3", port=port, timeout=timeout)
    rxs = snmp_bulk_walk(host, community, "1.3.6.1.4.1.37950.1.1.5.12.2.1.8.1.7", port=port, timeout=timeout)
    if not rxs:
        rxs = snmp_bulk_walk(host, community, "1.3.6.1.4.1.37950.1.1.5.10.13.1.1.8", port=port, timeout=timeout)
    txs = snmp_bulk_walk(host, community, "1.3.6.1.4.1.37950.1.1.5.12.2.1.8.1.6", port=port, timeout=timeout)

    onts: List[OnuInfo] = []
    for suffix, st_raw in statuses.items():
        board, pon, onu_id = _parse_hioso_index(suffix)
        try:
            try:
                status_code = int(st_raw) if st_raw is not None else -1
            except Exception:
                status_code = -1
            status = "Online" if status_code == 1 else ("Offline" if status_code in (0, 2, 3) else "Unknown")
            name = str(names.get(suffix) or "").strip('"')
            serial = parse_serial(serials.get(suffix, ""))
            rx_val = _vsol_parse_power(rxs.get(suffix))
            tx_val = _vsol_parse_power(txs.get(suffix))
            if rx_val is not None and rx_val > -32 and status != "Online":
                status = "Online"
            onts.append(OnuInfo(
                board=board, pon=pon, onu_id=onu_id,
                name=name, serial=serial,
                status=status, status_code=status_code,
                rx_power=rx_val, tx_power=tx_val,
                raw_index=str(suffix),
                olt_id=olt_id, olt_name=olt_name,
            ))
        except Exception as e:
            print(f"[parse vsol epon] {suffix}: {e}")
    return onts



