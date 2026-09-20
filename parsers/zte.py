"""ZTE C320/C300 SNMP OID parsers (V1 / V2)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

import config
from parsers.common import (
    OnuInfo,
    convert_rx_power,
    convert_tx_power,
    parse_serial,
    prefer_ont_name,
    snmp_bulk_walk,
    snmp_get,
    snmp_text,
)

def detect_firmware(host: str, community: str, port: int = 161) -> str:
    """
    Deteksi V1 vs V2. Pakai GETBULK + fallback GETNEXT.
    Return 'v2' | 'v1' | 'auto' (coba keduanya saat fetch).
    """
    timeout = max(getattr(config, "SNMP_TIMEOUT", 5), 10)

    def _probe(oid: str) -> int:
        try:
            d = snmp_bulk_walk(host, community, oid, port=port, timeout=timeout, max_oids=15)
            n = len(d or {})
            if n:
                return n
        except Exception as e:
            print(f"[SNMP] bulk probe {oid}: {e}")
        try:
            d = snmp_getnext_walk(host, community, oid, port=port, timeout=timeout, max_oids=15)
            n = len(d or {})
            if n:
                return n
        except Exception as e:
            print(f"[SNMP] next probe {oid}: {e}")
        return 0

    probes_v2 = [
        "1.3.6.1.4.1.3902.1082.500.10.2.3.3.1.2",
        "1.3.6.1.4.1.3902.1082.500.10.2.3.3.1.18",
        "1.3.6.1.4.1.3902.1082.500.10.2.3.8.1.4",
        "1.3.6.1.4.1.3902.1082.500.20.2.2.2.1.10",
    ]
    probes_v1 = [
        "1.3.6.1.4.1.3902.1012.3.28.1.1.3",
        "1.3.6.1.4.1.3902.1012.3.28.1.1.5",
        "1.3.6.1.4.1.3902.1012.3.28.2.1.4",
        "1.3.6.1.4.1.3902.1012.3.50.12.1.1.10",
    ]
    score_v2 = score_v1 = 0
    for oid in probes_v2:
        n = _probe(oid)
        if n:
            print(f"[SNMP] V2 hit {n} via {oid}")
            score_v2 += n
            break
    for oid in probes_v1:
        n = _probe(oid)
        if n:
            print(f"[SNMP] V1 hit {n} via {oid}")
            score_v1 += n
            break
    if score_v2 and not score_v1:
        print("[SNMP] Firmware → V2")
        return "v2"
    if score_v1 and not score_v2:
        print("[SNMP] Firmware → V1")
        return "v1"
    if score_v2 >= score_v1 and score_v2:
        print("[SNMP] Firmware → V2 (score lebih tinggi)")
        return "v2"
    if score_v1:
        print("[SNMP] Firmware → V1 (score lebih tinggi)")
        return "v1"
    print("[SNMP] Probe kosong — mode AUTO (fetch V2+V1)")
    return "auto"


def _guess_board_pon_v1(if_index: int) -> Tuple[int, int]:
    known = {
        268501248: (1, 1), 268501504: (1, 2), 268501760: (1, 3), 268502016: (1, 4),
        268502272: (1, 5), 268502528: (1, 6), 268502784: (1, 7), 268503040: (1, 8),
        268566784: (2, 1), 268567040: (2, 2), 268567296: (2, 3), 268567552: (2, 4),
        268567808: (2, 5), 268568064: (2, 6), 268568320: (2, 7), 268568576: (2, 8),
    }
    if if_index in known:
        return known[if_index]
    base = 0x10000000
    diff = if_index - base
    slot = (diff // 0x10000) or 1
    pon = ((diff % 0x10000) // 0x100) or 1
    return max(1, min(slot, 4)), max(1, min(pon, 16))


def _guess_board_pon_v2(if_index: int) -> Tuple[int, int]:
    """
    V2 ifIndex (ONU-ID space):
      ifIndex = 0x11010000 + slot*0x100 + pon
    Contoh: slot1 pon1 = 285278465 (0x11010101)
    """
    base = 0x11010000  # 285278208
    if if_index >= base:
        diff = if_index - base
        slot = diff // 0x100
        pon = diff % 0x100
        if slot < 1:
            slot = 1
        if pon < 1:
            pon = 1
        return max(1, min(slot, 8)), max(1, min(pon, 16))

    # Fallback TYPE-space style (0x10000000 + slot*0x10000 + pon*0x100)
    base2 = 0x10000000
    diff = if_index - base2
    slot = (diff // 0x10000) or 1
    pon = ((diff % 0x10000) // 0x100) or 1
    return max(1, min(slot, 8)), max(1, min(pon, 16))


def _fetch_v1(host: str, community: str, boards: List[int], port: int, filter_pon: str | None = None, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    onts: List[OnuInfo] = []
    name_oid = "1.3.6.1.4.1.3902.1012.3.28.1.1.3"
    desc_oid = "1.3.6.1.4.1.3902.1012.3.28.1.1.2"  # description / label
    serial_oid = "1.3.6.1.4.1.3902.1012.3.28.1.1.5"
    status_oid = "1.3.6.1.4.1.3902.1012.3.28.2.1.4"
    rx_oid = "1.3.6.1.4.1.3902.1012.3.50.12.1.1.10"

    timeout = max(config.SNMP_TIMEOUT, 6)
    print("[SNMP] Parallel walk V1 tables...")
    def _w(oid):
        return snmp_bulk_walk(host, community, oid, port=port, timeout=timeout, max_repetitions=40)
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_name = ex.submit(_w, name_oid)
        f_desc = ex.submit(_w, desc_oid)
        f_ser = ex.submit(_w, serial_oid)
        f_st = ex.submit(_w, status_oid)
        f_rx = ex.submit(_w, rx_oid)
        names = f_name.result()
        descs = f_desc.result()
        serials = f_ser.result()
        statuses = f_st.result()
        rxs = f_rx.result()
    print(f"[SNMP] Ditemukan {len(names)} entry name")
    skipped_board = 0

    for suffix, name in names.items():
        try:
            parts = str(suffix).strip(".").split(".")
            if len(parts) < 2:
                continue
            if_index = int(parts[0])
            onu_id = int(parts[1])
            board, pon = _guess_board_pon_v1(if_index)
            if boards and board not in boards:
                skipped_board += 1
                continue

            serial = parse_serial(serials.get(suffix, ""))
            try:
                status_code = int(statuses.get(suffix, -1))
            except Exception:
                status_code = -1
            status = STATUS_MAP.get(status_code, "Unknown")

            rx_raw = rxs.get(suffix, rxs.get(suffix + ".1"))
            rx_val = convert_rx_power(rx_raw)

            desc = snmp_text(descs.get(suffix, ""))
            onts.append(
                OnuInfo(
                    board=board,
                    pon=pon,
                    onu_id=onu_id,
                    name=prefer_ont_name(name, desc),
                    description=desc,
                    serial=serial,
                    status=STATUS_DISPLAY.get(status, status),
                    status_code=status_code,
                    rx_power=rx_val,
                    raw_index=str(suffix),
                )
            )
        except Exception as e:
            print(f"[parse v1] {suffix}: {e}")
    if skipped_board:
        print(f"[SNMP] V1: {skipped_board} entry dilewati filter boards={boards}")
        if not onts and names:
            print("[SNMP] V1: coba tanpa filter board...")
            # re-parse without board filter
            for suffix, name in names.items():
                try:
                    parts = str(suffix).strip(".").split(".")
                    if len(parts) < 2:
                        continue
                    if_index = int(parts[0])
                    onu_id = int(parts[1])
                    board, pon = _guess_board_pon_v1(if_index)
                    serial = parse_serial(serials.get(suffix, ""))
                    try:
                        status_code = int(statuses.get(suffix, -1))
                    except Exception:
                        status_code = -1
                    status = STATUS_MAP.get(status_code, "Unknown")
                    rx_raw = rxs.get(suffix, rxs.get(suffix + ".1"))
                    rx_val = convert_rx_power(rx_raw)
                    onts.append(OnuInfo(
                        board=board, pon=pon, onu_id=onu_id,
                        name=snmp_text(name),
                        serial=serial,
                        status=STATUS_DISPLAY.get(status, status),
                        status_code=status_code,
                        rx_power=rx_val,
                        raw_index=str(suffix),
                        olt_id=olt_id, olt_name=olt_name,
                    ))
                except Exception:
                    pass
            print(f"[SNMP] V1 tanpa filter board → {len(onts)} ONT")
    return onts


def _fetch_v2(host: str, community: str, boards: List[int], port: int, filter_pon: str | None = None, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    onts: List[OnuInfo] = []
    name_oid = "1.3.6.1.4.1.3902.1082.500.10.2.3.3.1.2"
    serial_oid = "1.3.6.1.4.1.3902.1082.500.10.2.3.3.1.18"
    status_oid = "1.3.6.1.4.1.3902.1082.500.10.2.3.8.1.4"
    rx_oid = "1.3.6.1.4.1.3902.1082.500.20.2.2.2.1.10"
    desc_oid = "1.3.6.1.4.1.3902.1082.500.10.2.3.3.1.3"
    tx_oid = "1.3.6.1.4.1.3902.1082.500.20.2.2.2.1.14"

    timeout = max(config.SNMP_TIMEOUT, 6)
    tables = {
        "name": name_oid,
        "serial": serial_oid,
        "status": status_oid,
        "rx": rx_oid,
        "desc": desc_oid,
        "tx": tx_oid,
    }
    results = {}
    print(f"[SNMP] Parallel walk {len(tables)} tabel (timeout={timeout}s)...")

    def _walk_one(item):
        key, oid = item
        data = snmp_bulk_walk(host, community, oid, port=port, timeout=timeout, max_repetitions=40)
        return key, data

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(_walk_one, it): it[0] for it in tables.items()}
        for fut in as_completed(futs):
            key, data = fut.result()
            results[key] = data
            print(f"[SNMP]   {key}: {len(data)} entry")

    names = results.get("name", {})
    serials = results.get("serial", {})
    statuses = results.get("status", {})
    rxs = results.get("rx", {})
    descs = results.get("desc", {})
    txs = results.get("tx", {})
    print(f"[SNMP] Total name entry: {len(names)}")

    # OID optical alternatif jika kosong (beda sub-firmware C320)
    if not rxs:
        alt_rx = [
            "1.3.6.1.4.1.3902.1082.500.20.2.2.1.1.10",
            "1.3.6.1.4.1.3902.1082.500.20.2.2.2.1.10",
            "1.3.6.1.4.1.3902.1082.500.1.2.2.1.10",
            "1.3.6.1.4.1.3902.1082.500.20.2.1.1.1.10",
            "1.3.6.1.4.1.3902.1012.3.50.12.1.1.10",
            "1.3.6.1.4.1.3902.1012.3.50.11.2.1.3",
        ]
        for oid in alt_rx:
            print(f"[SNMP] Coba Rx OID alternatif: {oid}")
            alt = snmp_bulk_walk(host, community, oid, port=port, timeout=timeout, max_repetitions=40)
            if alt:
                rxs = alt
                print(f"[SNMP]   Rx alternatif OK: {len(alt)} entry")
                break
        if not rxs:
            print("[SNMP] Rx Power tetap 0 — biasanya ONT offline / optical table kosong di OLT ini")
    if not rxs and names:
        rxs = snmp_get_rx_for_suffixes(
            host, community, list(names.keys()), port=port, timeout=min(timeout, 5)
        )
        print(f"[SNMP] Rx setelah GET per-ONT: {len(rxs)}")

    if not txs:
        alt_tx = [
            "1.3.6.1.4.1.3902.1082.500.20.2.2.1.1.14",
            "1.3.6.1.4.1.3902.1012.3.50.12.1.1.14",
        ]
        for oid in alt_tx:
            alt = snmp_bulk_walk(host, community, oid, port=port, timeout=timeout, max_repetitions=40)
            if alt:
                txs = alt
                print(f"[SNMP] Tx alternatif OK: {len(alt)} entry")
                break

    for suffix, name in names.items():
        try:
            parts = [p for p in str(suffix).strip(".").split(".") if p]
            if len(parts) < 2:
                continue
            if_index = int(parts[0])
            onu_id = int(parts[1])
            board, pon = _guess_board_pon_v2(if_index)
            if filter_pon:
                try:
                    fb, fp = filter_pon.split("/")
                    if board != int(fb) or pon != int(fp):
                        continue
                except Exception:
                    pass

            def _lookup(d, suf):
                suf = str(suf)
                if suf in d:
                    return d[suf]
                # Rx power ZTE sering: ifIndex.onuId.1
                if suf + ".1" in d:
                    return d[suf + ".1"]
                if suf.endswith(".1") and suf[:-2] in d:
                    return d[suf[:-2]]
                parts = suf.split(".")
                if len(parts) >= 2:
                    tail2 = ".".join(parts[-2:])
                    for k, v in d.items():
                        ks = str(k)
                        if ks == suf or ks == tail2 or ks == tail2 + ".1":
                            return v
                        if ks.endswith("." + tail2) or ks.endswith("." + tail2 + ".1"):
                            return v
                return None

            serial = parse_serial(_lookup(serials, suffix) or "")
            # bersihkan prefix aneh "1," dari decoder
            if "," in serial:
                serial = serial.split(",")[-1].strip()
            st_raw = _lookup(statuses, suffix)
            try:
                status_code = int(st_raw) if st_raw is not None else -1
            except Exception:
                status_code = -1
            status = STATUS_MAP.get(status_code, "Unknown")
            rx_raw = _lookup(rxs, suffix)
            rx_val = convert_rx_power(rx_raw)
            tx_val = convert_tx_power(_lookup(txs, suffix))
            desc = snmp_text(_lookup(descs, suffix) or "")
            # Heuristik: sinyal bagus → Online; sinyal hilang + status Online → LOS
            if rx_val is not None and rx_val > -32 and status not in ("Online", "Working"):
                status = "Online"
            if (rx_val is None or rx_val <= -35) and status == "Online" and status_code in (1, 5, 6, 7):
                status = STATUS_MAP.get(status_code, "Offline")

            onts.append(
                OnuInfo(
                    board=board,
                    pon=pon,
                    onu_id=onu_id,
                    name=prefer_ont_name(name, desc),
                    description=desc,
                    serial=serial,
                    status=STATUS_DISPLAY.get(status, status),
                    status_code=status_code,
                    rx_power=rx_val,
                    tx_power=tx_val,
                    raw_index=str(suffix),
                    olt_id=olt_id,
                    olt_name=olt_name,
                )
            )
        except Exception as e:
            print(f"[parse v2] {suffix}: {e}")

    # Debug index samples + raw keys
    if names:
        sample_keys = list(names.keys())[:3]
        print("[SNMP] Sample keys name/status/rx:")
        for k in sample_keys:
            print(f"  key={k!r}")
            print(f"    status_raw={statuses.get(k)!r}  rx_raw={rxs.get(k)!r}  serial_raw={str(serials.get(k))[:40]!r}")
            # also show nearby keys in rxs
        rx_keys = list(rxs.keys())[:3]
        st_keys = list(statuses.keys())[:3]
        print(f"  first rx keys: {rx_keys}")
        print(f"  first status keys: {st_keys}")

    if onts:
        samples = onts[:5]
        print("[SNMP] Sample parsed:")
        for o in samples:
            print(f"  index={o.raw_index} -> {o.board}/{o.pon}:{o.onu_id} name={o.name!r} status={o.status}({o.status_code}) rx={o.rx_power} sn={o.serial}")
        boards_found = sorted({o.board for o in onts})
        status_count = {}
        for o in onts:
            status_count[o.status] = status_count.get(o.status, 0) + 1
        print(f"[SNMP] Board terdeteksi: {boards_found}")
        print(f"[SNMP] Status count: {status_count}")
        rx_ok = sum(1 for o in onts if o.rx_power is not None)
        print(f"[SNMP] ONT dengan Rx Power valid: {rx_ok}/{len(onts)}")

    filtered = [o for o in onts if o.board in boards]
    if filtered:
        print(f"[SNMP] Setelah filter boards {boards}: {len(filtered)} ONT")
        return filtered
    print(f"[SNMP] Filter boards {boards} kosong, tampilkan semua {len(onts)} ONT")
    return onts


def _generate_demo_data(boards: List[int]) -> List[OnuInfo]:
    import random as rnd

    demo = []
    names = [
        "Budi Santoso", "Siti Aminah", "Agus Wijaya", "Dewi Lestari",
        "Rudi Hartono", "Maya Sari", "Eko Prasetyo", "Lina Marlina",
        "Hadi Susilo", "Rina Wati", "Joko Widodo", "Ani Yulianti",
    ]
    odps = ["ODP-BLOKA-01", "ODP-BLOKA-02", "ODP-BLOKB-01", "ODP-BLOKC-03", "ODP-BLOKD-01"]
    statuses = ["Online", "Online", "Online", "Offline", "LOS", "DyingGasp"]

    for board in boards:
        for pon in range(1, 5):
            for i in range(1, rnd.randint(4, 9)):
                status = rnd.choice(statuses)
                rx = None
                if status == "Online":
                    rx = round(rnd.uniform(-27.5, -18.0), 2)
                elif status in ("LOS", "DyingGasp"):
                    rx = round(rnd.uniform(-32.0, -28.5), 2)

                serial = f"ZTEG{rnd.randint(0x10000000, 0xFFFFFFFF):08X}"
                name = rnd.choice(names)
                odp = rnd.choice(odps)

                demo.append(
                    OnuInfo(
                        board=board,
                        pon=pon,
                        onu_id=i,
                        name=name,
                        description=f"{odp} - {name}",
                        serial=serial,
                        onu_type=rnd.choice(["F670L", "F660V6", "F601"]),
                        status=status,
                        status_code=3 if status == "Online" else 6,
                        rx_power=rx,
                        tx_power=round(rnd.uniform(1.5, 3.5), 2) if rx else None,
                        odp=odp,
                    )
                )
    return demo


