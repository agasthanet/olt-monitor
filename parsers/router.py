"""Vendor router: fetch_all_onts + restart helpers."""
from __future__ import annotations

from typing import List, Optional, Tuple

import config
from parsers.common import (
    OnuInfo,
    snmp_get,
    snmp_set_integer,
    restart_ont_snmp,
)
from parsers.zte import detect_firmware, _fetch_v1, _fetch_v2, _generate_demo_data
from parsers.hioso import fetch_hioso_onts
from parsers.hsairpo import fetch_hsairpo_onts
from parsers.cdata import fetch_cdata_onts

def fetch_all_onts(
    host: str = None,
    community: str = None,
    boards: List[int] = None,
    firmware: str = None,
    port: int = None,
    filter_pon: str = None,
    olt_id: str = "",
    olt_name: str = "",
    vendor: str = "zte",
) -> tuple:
    """
    Ambil ONT. Return (list[OnuInfo], vendor_yang_cocok|None).
    vendor: zte | hioso | hsairpo | auto
    """
    host = host or config.OLT_IP
    community = community or config.SNMP_COMMUNITY
    boards = boards or config.BOARDS
    port = port or config.SNMP_PORT
    vendor = (vendor or "zte").lower().strip()

    if config.DEMO_MODE:
        print("[SNMP] DEMO_MODE aktif → data dummy")
        onts = _generate_demo_data(boards)
        for o in onts:
            o.olt_id = olt_id or "demo"
            o.olt_name = olt_name or "DEMO"
        return onts, "demo"

    print(f"[SNMP] Connect ke {host}:{port} community={community} vendor={vendor} olt={olt_id or '-'}")
    sysdescr = snmp_get(host, community, "1.3.6.1.2.1.1.1.0", port=port, timeout=config.SNMP_TIMEOUT)
    if sysdescr is None:
        # coba sysName
        sysdescr = snmp_get(host, community, "1.3.6.1.2.1.1.5.0", port=port, timeout=config.SNMP_TIMEOUT)
    if sysdescr is None:
        print("[SNMP] GAGAL connect ke OLT.")
        return [], None
    print(f"[SNMP] OLT merespons: {sysdescr}")

    vendor_setting = (vendor or "auto").lower().strip()
    sd = str(sysdescr).lower()

    def _guess_vendor() -> str:
        if "hioso" in sd or "ha73" in sd or "ha72" in sd or "25355" in sd:
            return "hioso"
        if "airpo" in sd or "hsairpo" in sd or "vsol" in sd or "v-sol" in sd or "37950" in sd or "photon" in sd or "ept1004" in sd:
            return "hsairpo"
        if "c-data" in sd or "cdata" in sd or "c data" in sd or "fd11" in sd or "fd16" in sd or "34592" in sd:
            return "cdata"
        if "zte" in sd or "c320" in sd or "c300" in sd or "zxan" in sd:
            return "zte"
        # GPON OLT generik sering C-Data / clone
        if "gpon olt" in sd and "zte" not in sd:
            return "cdata"
        return "unknown"

    def _fetch_zte() -> List[OnuInfo]:
        fw_setting = (firmware or "auto").lower().strip()
        if fw_setting in ("", "auto", "none"):
            detected = detect_firmware(host, community, port)
        else:
            detected = fw_setting
        print(f"[SNMP] ZTE firmware setting={fw_setting!r} detected={detected!r}")
        if detected == "v1":
            order = ["v1", "v2"]
        elif detected == "v2":
            order = ["v2", "v1"]
        else:
            order = ["v2", "v1"]
        if fw_setting in ("v1", "v2"):
            order = [fw_setting, "v2" if fw_setting == "v1" else "v1"]
        last: List[OnuInfo] = []
        for fw in order:
            print(f"[SNMP] Fetch ZTE {fw.upper()} ...")
            if fw == "v2":
                last = _fetch_v2(host, community, boards, port, filter_pon=filter_pon, olt_id=olt_id, olt_name=olt_name)
            else:
                last = _fetch_v1(host, community, boards, port, filter_pon=filter_pon, olt_id=olt_id, olt_name=olt_name)
            print(f"[SNMP] ZTE {fw.upper()} → {len(last)} ONT")
            if last:
                return last
        return last

    def _fetch_hioso() -> List[OnuInfo]:
        variant = firmware if firmware in ("epon", "gpon") else "auto"
        return fetch_hioso_onts(
            host, community, port=port, variant=variant,
            olt_id=olt_id, olt_name=olt_name,
        )

    def _fetch_hsairpo() -> List[OnuInfo]:
        variant = firmware if firmware in ("epon", "gpon") else "auto"
        return fetch_hsairpo_onts(
            host, community, port=port, variant=variant,
            olt_id=olt_id, olt_name=olt_name,
        )

    def _fetch_cdata() -> List[OnuInfo]:
        variant = firmware if firmware in ("epon", "gpon") else "auto"
        return fetch_cdata_onts(
            host, community, port=port, variant=variant,
            olt_id=olt_id, olt_name=olt_name,
        )

    # Urutan percobaan vendor
    if vendor_setting in ("hioso",):
        chain = ["hioso", "zte", "cdata"]
    elif vendor_setting in ("hsairpo", "airpo", "vsol"):
        chain = ["hsairpo", "zte", "hioso", "cdata"]
    elif vendor_setting in ("cdata", "c-data", "fd"):
        chain = ["cdata", "hioso", "zte"]
    elif vendor_setting in ("zte", "c320", "c300"):
        chain = ["zte", "hioso", "cdata"]
    else:
        # AUTO: tebak dari sysDescr, lalu fallback vendor lain jika 0 ONT
        guessed = _guess_vendor()
        print(f"[SNMP] Auto guess dari sysDescr → {guessed}")
        if guessed == "hioso":
            chain = ["hioso", "zte", "hsairpo", "cdata"]
        elif guessed == "hsairpo":
            chain = ["hsairpo", "zte", "hioso", "cdata"]
        elif guessed == "cdata":
            chain = ["cdata", "hioso", "zte", "hsairpo"]
        elif guessed == "zte":
            chain = ["zte", "hioso", "hsairpo", "cdata"]
        else:
            chain = ["hioso", "cdata", "zte", "hsairpo"]
            print("[SNMP] Auto: sysDescr generik → coba hioso → cdata → zte → hsairpo")

    print(f"[SNMP] Vendor chain: {chain}")
    last: List[OnuInfo] = []
    used_vendor: Optional[str] = None
    for v in chain:
        print(f"[SNMP] === Coba vendor={v} ===")
        try:
            if v == "hioso":
                last = _fetch_hioso()
            elif v == "hsairpo":
                last = _fetch_hsairpo()
            elif v == "cdata":
                last = _fetch_cdata()
            else:
                last = _fetch_zte()
        except Exception as e:
            print(f"[SNMP] vendor {v} error: {e}")
            last = []
        print(f"[SNMP] vendor={v} → {len(last)} ONT")
        if last:
            used_vendor = v
            print(f"[SNMP] Vendor cocok: {v} ({len(last)} ONT)")
            break
    # second return value: vendor yang berhasil (untuk di-lock di olts.json)
    return last, used_vendor


# ============================================================
# Hioso OLT (enterprise 25355) — EPON & GPON
# ============================================================


