"""HS-Airpo / multi-probe SNMP (BDCOM, VSOL, C-Data, Hioso, 12170)."""
from __future__ import annotations

from typing import List, Optional

import config
from parsers.common import OnuInfo, parse_serial, snmp_bulk_walk, snmp_get, snmp_text
from parsers.bdcom import _fetch_bdcom_epon
from parsers.vsol import _fetch_vsol_epon, _fetch_vsol_gpon
from parsers.cdata import fetch_cdata_onts
from parsers.hioso import fetch_hioso_onts, _parse_hioso_index, _hioso_parse_power

def _fetch_ent12170(host: str, community: str, port: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """
    HS Airpo enterprise 12170.
    Walk tree dalam, cari tabel yang mirip status/MAC/Rx ONU.
    """
    base = "1.3.6.1.4.1.12170"
    timeout = max(config.SNMP_TIMEOUT, 8)
    print("[SNMP] Enterprise 12170 deep walk...")
    # walk lebih dalam
    all_data = snmp_bulk_walk(host, community, base, port=port, timeout=timeout, max_oids=2000)
    print(f"[SNMP] 12170 total entries: {len(all_data)}")
    if not all_data:
        return []

    # group by parent path (tanpa index terakhir)
    # print sample paths untuk debug
    parents = {}
    for suffix, val in all_data.items():
        parts = str(suffix).split(".")
        if len(parts) < 2:
            continue
        # parent = semua kecuali last index component(s)
        parent = ".".join(parts[:-1])
        parents.setdefault(parent, []).append((parts[-1], val))

    # tampilkan parent dengan banyak row (kandidat tabel)
    big = sorted(((p, len(rows)) for p, rows in parents.items()), key=lambda x: -x[1])
    print("[SNMP] 12170 top tables:")
    for p, n in big[:15]:
        sample = parents[p][0][1] if parents[p] else None
        print(f"       .{p} rows={n} sample={str(sample)[:60]!r}")

    # Heuristik: cari kolom status (nilai 0/1/2/3/4 kecil integer)
    # dan kolom MAC (hex / string 12 char)
    # Index pattern sering: pon.onu atau ifIndex-like

    # Coba pola umum di bawah 12170:
    # 12170.x.y.z.1.<col>.<index...>
    candidate_status = []
    candidate_mac = []
    candidate_name = []
    candidate_rx = []
    candidate_tx = []
    candidate_dist = []

    for suffix, val in all_data.items():
        s = str(val).strip() if val is not None else ""
        # MAC-like
        if isinstance(val, str):
            hexish = s.replace(" ", "").replace(":", "").replace("-", "")
            if len(hexish) == 12 and all(c in "0123456789abcdefABCDEF" for c in hexish):
                candidate_mac.append((suffix, s))
            elif 3 <= len(s) <= 64 and not s.replace(".", "").replace(" ", "").isdigit():
                # possible name/descr
                if any(c.isalpha() for c in s):
                    candidate_name.append((suffix, s))
        if isinstance(val, int):
            if val in (0, 1, 2, 3, 4, 5):
                candidate_status.append((suffix, val))
            # Rx power often -400..100 as 0.1 dBm or raw
            if -4000 <= val <= 100 and val not in (0, 1, 2, 3, 4, 5):
                # could be power*10 or power*100
                if -400 <= val <= 50:
                    candidate_rx.append((suffix, val))
            if 0 < val < 100000 and val > 10:
                # distance meters
                if val < 60000:
                    candidate_dist.append((suffix, val))

    print(f"[SNMP] 12170 candidates status={len(candidate_status)} mac={len(candidate_mac)} name={len(candidate_name)} rx={len(candidate_rx)}")

    # Jika ada MAC table, pakai index MAC sebagai kunci ONU
    onts: List[OnuInfo] = []
    if candidate_mac:
        # group MAC by index suffix (last 1-3 numbers)
        for suf, mac in candidate_mac:
            parts = str(suf).split(".")
            # index = last component or last 2
            try:
                onu_id = int(parts[-1])
            except Exception:
                onu_id = abs(hash(suf)) % 10000
            # try find matching status with same index tail
            st = None
            st_code = -1
            for ss, sv in candidate_status:
                if ss.endswith("." + parts[-1]) or ss.split(".")[-1] == parts[-1]:
                    st_code = int(sv)
                    break
            status = "Online" if st_code in (1, 3, 5) else ("Offline" if st_code in (0, 2, 4) else "Unknown")
            # name
            name = ""
            for ns, nv in candidate_name:
                if ns.endswith("." + parts[-1]):
                    name = str(nv).strip('"')
                    break
            # rx
            rx_val = None
            for rs, rv in candidate_rx:
                if rs.endswith("." + parts[-1]):
                    rx_val = _hioso_parse_power(rv)
                    if rx_val is None:
                        try:
                            f = float(rv)
                            if abs(f) > 100:
                                f = f / 100.0
                            elif abs(f) > 40:
                                f = f / 10.0
                            if -40 <= f <= 10:
                                rx_val = round(f, 2)
                        except Exception:
                            pass
                    break
            if rx_val is not None and rx_val > -32:
                status = "Online"
            # pon from ifDescr-like: default pon 1
            pon = 1
            board = 1
            if len(parts) >= 2:
                try:
                    maybe_pon = int(parts[-2])
                    if 1 <= maybe_pon <= 16:
                        pon = maybe_pon
                except Exception:
                    pass
            onts.append(OnuInfo(
                board=board, pon=pon, onu_id=onu_id,
                name=name, serial=parse_serial(mac),
                status=status, status_code=st_code,
                rx_power=rx_val,
                raw_index=str(suf),
                olt_id=olt_id, olt_name=olt_name,
            ))
        if onts:
            print(f"[SNMP] 12170 parsed {len(onts)} ONT via MAC table")
            return onts

    # Fallback: parse ifDescr for ONU-like interfaces (pon1:1 etc)
    if_names = snmp_bulk_walk(host, community, "1.3.6.1.2.1.2.2.1.2", port=port, timeout=timeout, max_oids=500)
    if_oper = snmp_bulk_walk(host, community, "1.3.6.1.2.1.2.2.1.8", port=port, timeout=timeout, max_oids=500)
    print(f"[SNMP] ifDescr={len(if_names)} ifOper={len(if_oper)}")
    for idx, descr in if_names.items():
        d = str(descr).lower()
        # match onu / pon1:3 / epon0/1:2 patterns
        if "onu" in d or ":" in d and ("pon" in d or "epon" in d or "gpon" in d):
            try:
                oper = int(if_oper.get(idx, 2))
            except Exception:
                oper = 2
            status = "Online" if oper == 1 else "Offline"
            # parse pon/onu from descr
            board, pon, onu_id = 1, 1, int(str(idx)) if str(idx).isdigit() else 0
            import re as _re
            m = _re.search(r"(?:pon|epon|gpon)[^\d]*(\d+)[^\d]+(\d+)", d)
            if m:
                pon, onu_id = int(m.group(1)), int(m.group(2))
            onts.append(OnuInfo(
                board=board, pon=pon, onu_id=onu_id,
                name=str(descr), serial="",
                status=status, status_code=oper,
                raw_index=str(idx),
                olt_id=olt_id, olt_name=olt_name,
            ))
    if onts:
        print(f"[SNMP] 12170/ifDescr parsed {len(onts)} ONT")
    return onts


def fetch_hsairpo_onts(
    host: str,
    community: str,
    port: int = 161,
    variant: str = "auto",
    olt_id: str = "",
    olt_name: str = "",
) -> List[OnuInfo]:
    """
    HS Airpo / EPON-OLT Series Software:
    probe BDCOM 3320 → VSOL 37950 → C-Data 34592 → Hioso 25355
    + discovery enterprise roots (bantu debug OID).
    """
    print("[SNMP] HS Airpo: probe BDCOM/VSOL/C-Data/Hioso...")
    tmo = max(config.SNMP_TIMEOUT, 5)

    # Test walk standard MIB dulu (buktikan parser & akses SNMP)
    sys_walk = snmp_bulk_walk(host, community, "1.3.6.1.2.1.1", port=port, timeout=tmo, max_oids=15)
    print(f"[SNMP] system MIB walk: {len(sys_walk)} entry")
    for k, v in list(sys_walk.items())[:5]:
        print(f"       system.{k} = {v!r}")

    if_walk = snmp_bulk_walk(host, community, "1.3.6.1.2.1.2.2.1.2", port=port, timeout=tmo, max_oids=10)
    print(f"[SNMP] ifDescr walk: {len(if_walk)} entry")
    for k, v in list(if_walk.items())[:5]:
        print(f"       ifDescr.{k} = {v!r}")

    # Discovery enterprise: walk 1.3.6.1.4.1 dan ambil enterprise ID unik
    ent_root = snmp_bulk_walk(host, community, "1.3.6.1.4.1", port=port, timeout=tmo, max_oids=80)
    print(f"[SNMP] enterprises root walk: {len(ent_root)} entry")
    ents = set()
    for k in ent_root.keys():
        parts = str(k).split(".")
        if parts and parts[0].isdigit():
            ents.add(parts[0])
    if ents:
        print(f"[SNMP] enterprise IDs ditemukan: {sorted(ents, key=lambda x: int(x))}")
        for k, v in list(ent_root.items())[:8]:
            print(f"       enterprises.{k} = {str(v)[:80]!r}")
    else:
        print("[SNMP] enterprises root KOSONG — SNMP view kemungkinan tidak allow private MIB")

    # Probe spesifik
    for ent, label in [
        ("1.3.6.1.4.1.3320", "BDCOM/3320"),
        ("1.3.6.1.4.1.34592", "C-Data/34592"),
        ("1.3.6.1.4.1.37950", "VSOL/37950"),
        ("1.3.6.1.4.1.25355", "Hioso/25355"),
        ("1.3.6.1.4.1.17409", "NSCRTV/17409"),
        ("1.3.6.1.4.1.3902", "ZTE/3902"),
    ]:
        sample = snmp_bulk_walk(host, community, ent, port=port, timeout=tmo, max_oids=3)
        print(f"[SNMP] probe {label}: {len(sample)} entry")

    try:
        soid = snmp_get(host, community, "1.3.6.1.2.1.1.2.0", port=port, timeout=tmo)
        print(f"[SNMP] sysObjectID: {soid}")
    except Exception as e:
        print(f"[SNMP] sysObjectID error: {e}")

    # Enterprise 12170 (HS Airpo deteksi dari walk)
    onts12170 = _fetch_ent12170(host, community, port, olt_id=olt_id, olt_name=olt_name)
    if onts12170:
        return onts12170

    # 1) BDCOM 3320 — beberapa kandidat status
    bdcom_status_oids = [
        "1.3.6.1.4.1.3320.101.11.4.1.5",   # llidOnlineInfoStatus
        "1.3.6.1.4.1.3320.101.10.1.1.26",  # onuStatus
        "1.3.6.1.4.1.3320.101.11.1.1.5",   # alt
        "1.3.6.1.4.1.3320.101.10.1.1.28",  # onuBindStatus
    ]
    for so in bdcom_status_oids:
        probe = snmp_bulk_walk(host, community, so, port=port, timeout=tmo, max_oids=8)
        print(f"[SNMP] BDCOM try {so}: {len(probe)}")
        if probe:
            onts = _fetch_bdcom_epon(host, community, port, olt_id=olt_id, olt_name=olt_name)
            if onts:
                return onts
            break

    # 2) VSOL GPON
    probe = snmp_bulk_walk(host, community, "1.3.6.1.4.1.37950.1.1.6.1.1.1.1.5", port=port, timeout=tmo, max_oids=5)
    print(f"[SNMP] VSOL GPON probe: {len(probe)}")
    if probe or variant == "gpon":
        onts = _fetch_vsol_gpon(host, community, port, olt_id=olt_id, olt_name=olt_name)
        if onts:
            return onts

    # 3) VSOL EPON
    for so in [
        "1.3.6.1.4.1.37950.1.1.5.12.2.1.5",
        "1.3.6.1.4.1.37950.1.1.5.10.12.1.5",
        "1.3.6.1.4.1.37950.1.1.5.12.2.1.8",
    ]:
        probe = snmp_bulk_walk(host, community, so, port=port, timeout=tmo, max_oids=5)
        print(f"[SNMP] VSOL EPON try {so}: {len(probe)}")
        if probe:
            onts = _fetch_vsol_epon(host, community, port, olt_id=olt_id, olt_name=olt_name)
            if onts:
                return onts
            break

    # 4) C-Data 34592
    for so in [
        "1.3.6.1.4.1.34592.1.3.4.1.1.11",
        "1.3.6.1.4.1.34592.1.3.4.1.1.3",
        "1.3.6.1.4.1.34592.1.3.3.1.1.3",
    ]:
        probe = snmp_bulk_walk(host, community, so, port=port, timeout=tmo, max_oids=5)
        print(f"[SNMP] C-Data try {so}: {len(probe)}")
        if probe:
            onts = _fetch_cdata_epon(host, community, port, olt_id=olt_id, olt_name=olt_name)
            if onts:
                return onts
            break

    # 5) NSCRTV 17409 (beberapa OLT EPON China)
    probe = snmp_bulk_walk(host, community, "1.3.6.1.4.1.17409.2.3.4.1.1.8", port=port, timeout=tmo, max_oids=5)
    print(f"[SNMP] NSCRTV status probe: {len(probe)}")
    if probe:
        # parse simple
        names = snmp_bulk_walk(host, community, "1.3.6.1.4.1.17409.2.3.4.1.1.2", port=port, timeout=tmo)
        macs = snmp_bulk_walk(host, community, "1.3.6.1.4.1.17409.2.3.4.1.1.7", port=port, timeout=tmo)
        rxs = snmp_bulk_walk(host, community, "1.3.6.1.4.1.17409.2.3.4.2.1.4", port=port, timeout=tmo)
        txs = snmp_bulk_walk(host, community, "1.3.6.1.4.1.17409.2.3.4.2.1.5", port=port, timeout=tmo)
        onts = []
        for suffix, st_raw in probe.items():
            board, pon, onu_id = _parse_hioso_index(suffix)
            try:
                sc = int(st_raw)
            except Exception:
                sc = -1
            status = "Online" if sc == 1 else "Offline"
            rx_val = _hioso_parse_power(rxs.get(suffix))
            if rx_val is None:
                rx_val = _vsol_parse_power(rxs.get(suffix))
            onts.append(OnuInfo(
                board=board, pon=pon, onu_id=onu_id,
                name=snmp_text(names.get(suffix)),
                serial=parse_serial(macs.get(suffix, "")),
                status=status, status_code=sc,
                rx_power=rx_val,
                tx_power=_hioso_parse_power(txs.get(suffix)),
                raw_index=str(suffix),
                olt_id=olt_id, olt_name=olt_name,
            ))
        if onts:
            return onts

    # 6) Hioso
    print("[SNMP] HS Airpo: fallback ke Hioso OID...")
    onts = fetch_hioso_onts(host, community, port=port, variant="auto", olt_id=olt_id, olt_name=olt_name)
    if onts:
        return onts

    print("[SNMP] HS Airpo: semua tree kosong — cek SNMP community/view di OLT")
    print("[SNMP] Tip: jalankan snmpwalk enterprises dari PC, kirim hasil probe di log di atas")
    return []
