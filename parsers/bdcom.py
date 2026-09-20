"""BDCOM / NMS EPON SNMP OID parsers (enterprise 3320)."""
from __future__ import annotations

from typing import List, Optional

import config
from parsers.common import OnuInfo, parse_serial, snmp_bulk_walk, snmp_text
from parsers.hioso import _parse_hioso_index, _hioso_parse_power

def _fetch_bdcom_epon(host: str, community: str, port: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """BDCOM / NMS EPON — enterprise 3320 (OLT 'EPON-OLT Series Software')."""
    status_oid = "1.3.6.1.4.1.3320.101.11.4.1.5"
    status_oid2 = "1.3.6.1.4.1.3320.101.10.1.1.26"
    desc_oid = "1.3.6.1.4.1.3320.101.11.4.1.2"
    mac_oid = "1.3.6.1.4.1.3320.101.10.1.1.3"
    vendor_oid = "1.3.6.1.4.1.3320.101.10.1.1.1"
    dist_oid = "1.3.6.1.4.1.3320.101.10.1.1.27"
    rx_oid = "1.3.6.1.4.1.3320.101.10.5.1.5"
    tx_oid = "1.3.6.1.4.1.3320.101.10.5.1.6"

    timeout = max(config.SNMP_TIMEOUT, 6)
    print("[SNMP] BDCOM/NMS EPON (3320) walk...")
    statuses = snmp_bulk_walk(host, community, status_oid, port=port, timeout=timeout)
    if not statuses:
        statuses = snmp_bulk_walk(host, community, status_oid2, port=port, timeout=timeout)
        print(f"[SNMP] BDCOM status alt: {len(statuses)}")
    else:
        print(f"[SNMP] BDCOM status: {len(statuses)}")
    if not statuses:
        return []

    descs = snmp_bulk_walk(host, community, desc_oid, port=port, timeout=timeout)
    macs = snmp_bulk_walk(host, community, mac_oid, port=port, timeout=timeout)
    vendors = snmp_bulk_walk(host, community, vendor_oid, port=port, timeout=timeout)
    dists = snmp_bulk_walk(host, community, dist_oid, port=port, timeout=timeout)
    rxs = snmp_bulk_walk(host, community, rx_oid, port=port, timeout=timeout)
    txs = snmp_bulk_walk(host, community, tx_oid, port=port, timeout=timeout)
    print(f"[SNMP] BDCOM desc={len(descs)} mac={len(macs)} rx={len(rxs)}")

    st_map = {0: "Online", 1: "Online", 2: "Offline", 3: "SyncMib", 4: "Offline", 5: "Online"}
    onts: List[OnuInfo] = []
    for suffix, st_raw in statuses.items():
        board, pon, onu_id = _parse_hioso_index(suffix)
        try:
            try:
                status_code = int(st_raw)
            except Exception:
                status_code = -1
            status = st_map.get(status_code, "Unknown")
            name = str(descs.get(suffix) or vendors.get(suffix) or "").strip('"')
            serial = parse_serial(macs.get(suffix, ""))
            rx_val = _hioso_parse_power(rxs.get(suffix))
            if rx_val is None:
                rx_val = _vsol_parse_power(rxs.get(suffix))
            tx_val = _hioso_parse_power(txs.get(suffix))
            if tx_val is None:
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
                name=name, serial=serial,
                status=status, status_code=status_code,
                rx_power=rx_val, tx_power=tx_val, distance=dist,
                raw_index=str(suffix),
                olt_id=olt_id, olt_name=olt_name,
            ))
        except Exception as e:
            print(f"[parse bdcom] {suffix}: {e}")
    return onts



