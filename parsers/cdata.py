"""C-Data GPON/EPON SNMP OID parsers (enterprise 34592)."""
from __future__ import annotations

from typing import List, Optional, Tuple

import config
from parsers.common import (
    OnuInfo, parse_serial, snmp_bulk_walk, snmp_parallel_walk,
    snmp_probe_alive, snmp_text,
)
from parsers.hioso import _hioso_parse_power

def _parse_cdata_index(suffix: str) -> Tuple[int, int, int]:
    """Index C-Data: device.card.port.onu atau card.port.onu / port.onu."""
    parts = [p for p in str(suffix).strip(".").split(".") if p]
    nums = []
    for p in parts:
        try:
            nums.append(int(p))
        except Exception:
            continue
    if len(nums) >= 4:
        # device, card, port, onu
        return nums[1], nums[2], nums[3]
    if len(nums) == 3:
        return nums[0], nums[1], nums[2]
    if len(nums) == 2:
        return 0, nums[0], nums[1]
    if len(nums) == 1:
        return 0, 1, nums[0]
    return 0, 1, 0


def _cdata_status(code) -> str:
    try:
        c = int(code)
    except Exception:
        s = str(code or "").lower()
        if s in ("1", "up", "online", "active", "working"):
            return "Online"
        return "Offline"
    # runState: sering 1=online / 2=offline (varian firmware beda)
    if c in (1, 3, 5):
        return "Online"
    if c in (2, 4, 6, 0):
        return "Offline"
    return "Online" if c == 1 else "Offline"


def _fetch_cdata_gpon(host: str, community: str, port: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """
    C-Data GPON OLT — CDATA-GPON-MIB2 enterprise 34592.1.5.1
    Index: deviceId.cardId.portId.onuId
    """
    base = "1.3.6.1.4.1.34592.1.5.1.1.2.18"
    sn_oid = f"{base}.1.1.4"          # gponOnuSn
    desc_oid = f"{base}.1.1.8"        # gponOnuDescription
    status_oid = f"{base}.2.1.1"      # gponOnuRunState
    dist_oid = f"{base}.2.1.4"        # gponOnuDistance
    tx_oid = f"{base}.6.1.2"          # gponOnuOpticalTxPower
    rx_oid = f"{base}.6.1.4"          # gponOnuOpticalRxPower

    timeout = max(config.SNMP_TIMEOUT, 8)
    if not snmp_probe_alive(host, community, port=port, timeout=min(3.0, timeout)):
        print("[SNMP] C-Data GPON: host tidak merespon SNMP — skip")
        return []
    print("[SNMP] C-Data GPON (34592.1.5) parallel walk...")
    tables = snmp_parallel_walk(
        host, community,
        {
            "status": status_oid,
            "sn": sn_oid,
            "desc": desc_oid,
            "dist": dist_oid,
            "rx": rx_oid,
            "tx": tx_oid,
        },
        port=port, timeout=timeout, max_workers=6,
    )
    statuses = tables.get("status") or {}
    serials = tables.get("sn") or {}
    print(f"[SNMP] C-Data GPON status: {len(statuses)}")
    if not statuses:
        print(f"[SNMP] C-Data GPON serial seed: {len(serials)}")
        if not serials:
            return []
        statuses = {k: 1 for k in serials.keys()}
    descs = tables.get("desc") or {}
    dists = tables.get("dist") or {}
    rxs = tables.get("rx") or {}
    txs = tables.get("tx") or {}
    print(f"[SNMP] C-Data GPON sn={len(serials)} desc={len(descs)} rx={len(rxs)} tx={len(txs)}")

    keys = set(statuses.keys()) | set(serials.keys())
    onts: List[OnuInfo] = []
    for suffix in keys:
        try:
            board, pon, onu_id = _parse_cdata_index(suffix)
            st_raw = statuses.get(suffix)
            status = _cdata_status(st_raw) if st_raw is not None else "Unknown"
            try:
                status_code = int(st_raw) if st_raw is not None else -1
            except Exception:
                status_code = -1
            serial = parse_serial(serials.get(suffix, ""))
            name = snmp_text(descs.get(suffix, "")) or serial or f"ONU-{pon}:{onu_id}"
            rx_val = _hioso_parse_power(rxs.get(suffix))
            tx_val = _hioso_parse_power(txs.get(suffix))
            dist = None
            try:
                if dists.get(suffix) is not None:
                    dist = int(float(str(dists.get(suffix)).replace("m", "").strip()))
            except Exception:
                pass
            if rx_val is not None and rx_val > -32 and status != "Online":
                status = "Online"
            onts.append(OnuInfo(
                board=board, pon=pon, onu_id=onu_id,
                name=name, description=name, serial=serial,
                status=status, status_code=status_code,
                rx_power=rx_val, tx_power=tx_val, distance=dist,
                raw_index=str(suffix),
                olt_id=olt_id, olt_name=olt_name,
            ))
        except Exception as e:
            print(f"[parse cdata gpon] {suffix}: {e}")
    print(f"[SNMP] C-Data GPON → {len(onts)} ONT")
    return onts


def _fetch_cdata_epon(host: str, community: str, port: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """C-Data EPON — enterprise 34592.1.3 (legacy path)."""
    status_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.11"
    serial_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.3"
    type_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.2"
    dist_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.13"
    rx_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.36"
    tx_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.37"

    timeout = max(config.SNMP_TIMEOUT, 6)
    if not snmp_probe_alive(host, community, port=port, timeout=min(3.0, timeout)):
        print("[SNMP] C-Data EPON: host tidak merespon — skip")
        return []
    print("[SNMP] C-Data EPON (34592.1.3) parallel walk...")
    tables = snmp_parallel_walk(
        host, community,
        {
            "status": status_oid,
            "serial": serial_oid,
            "type": type_oid,
            "dist": dist_oid,
            "rx": rx_oid,
            "tx": tx_oid,
        },
        port=port, timeout=timeout, max_workers=6,
    )
    statuses = tables.get("status") or {}
    print(f"[SNMP] C-Data EPON status: {len(statuses)}")
    if not statuses:
        return []
    serials = tables.get("serial") or {}
    types = tables.get("type") or {}
    dists = tables.get("dist") or {}
    rxs = tables.get("rx") or {}
    txs = tables.get("tx") or {}

    onts: List[OnuInfo] = []
    for suffix, st_raw in statuses.items():
        board, pon, onu_id = _parse_cdata_index(suffix)
        try:
            try:
                status_code = int(st_raw)
            except Exception:
                status_code = -1
            status = "Online" if status_code in (1, 3) else "Offline"
            serial = parse_serial(serials.get(suffix, ""))
            name = snmp_text(types.get(suffix) or "")
            rx_val = _hioso_parse_power(rxs.get(suffix))
            tx_val = _hioso_parse_power(txs.get(suffix))
            dist = None
            try:
                if dists.get(suffix) is not None:
                    dist = int(float(str(dists.get(suffix))))
            except Exception:
                pass
            if rx_val is not None and rx_val > -32:
                status = "Online"
            onts.append(OnuInfo(
                board=board, pon=pon, onu_id=onu_id,
                name=name, serial=serial,
                status=status, status_code=status_code,
                rx_power=rx_val, tx_power=tx_val, distance=dist,
                raw_index=str(suffix),
                olt_id=olt_id, olt_name=olt_name,
            ))
        except Exception as e:
            print(f"[parse cdata epon] {suffix}: {e}")
    return onts


def fetch_cdata_onts(host: str, community: str, port: int = 161, olt_id: str = "", olt_name: str = "", variant: str = "auto") -> List[OnuInfo]:
    """C-Data: coba GPON dulu (umum V3.x), lalu EPON."""
    if variant == "epon":
        return _fetch_cdata_epon(host, community, port, olt_id=olt_id, olt_name=olt_name)
    if variant == "gpon":
        return _fetch_cdata_gpon(host, community, port, olt_id=olt_id, olt_name=olt_name)
    onts = _fetch_cdata_gpon(host, community, port, olt_id=olt_id, olt_name=olt_name)
    if onts:
        return onts
    return _fetch_cdata_epon(host, community, port, olt_id=olt_id, olt_name=olt_name)



