"""
SNMP helper untuk ZTE C320 / C300
Dual support V1 (base 1012) dan V2 (base 1082)

Menggunakan pure-Python SNMPv2c (tanpa pysnmp) —
kompatibel Python 3.10 s/d 3.14 di Windows/Linux.
"""

from __future__ import annotations

import random
import socket
import re
import struct
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import config


# ============================================================
# Pure Python SNMPv2c (minimal GET / GETBULK)
# ============================================================

class SnmpError(Exception):
    pass


def _encode_length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x100:
        return bytes([0x81, n])
    return bytes([0x82, (n >> 8) & 0xFF, n & 0xFF])


def _encode_oid(oid: str) -> bytes:
    parts = [int(x) for x in oid.strip(".").split(".") if x != ""]
    if len(parts) < 2:
        raise ValueError(f"OID terlalu pendek: {oid}")
    # first two combined
    body = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        if p < 0:
            raise ValueError("OID negatif")
        # base-128
        stack = []
        stack.append(p & 0x7F)
        p >>= 7
        while p:
            stack.append(0x80 | (p & 0x7F))
            p >>= 7
        body += bytes(reversed(stack))
    return b"\x06" + _encode_length(len(body)) + body


def _encode_octet_string(s: str) -> bytes:
    b = s.encode("latin-1", errors="replace")
    return b"\x04" + _encode_length(len(b)) + b


def _encode_integer(n: int) -> bytes:
    if n == 0:
        body = b"\x00"
    else:
        # signed big-endian, minimal
        neg = n < 0
        if neg:
            n = -n
        raw = []
        while n:
            raw.append(n & 0xFF)
            n >>= 8
        body = bytes(reversed(raw))
        if body[0] & 0x80:
            body = b"\x00" + body
        if neg:
            # two's complement roughly for small values
            body = bytes((~x) & 0xFF for x in body)
    return b"\x02" + _encode_length(len(body)) + body


def _encode_null() -> bytes:
    return b"\x05\x00"


def _encode_sequence(content: bytes) -> bytes:
    return b"\x30" + _encode_length(len(content)) + content


def _encode_get_pdu(request_id: int, oid: str, pdu_type: int = 0xA0) -> bytes:
    """0xA0 = GetRequest, 0xA1 = GetNext, 0xA5 = GetBulk"""
    varbind = _encode_sequence(_encode_oid(oid) + _encode_null())
    varbind_list = _encode_sequence(varbind)
    pdu_body = (
        _encode_integer(request_id)
        + _encode_integer(0)  # error-status
        + _encode_integer(0)  # error-index
        + varbind_list
    )
    return bytes([pdu_type]) + _encode_length(len(pdu_body)) + pdu_body


def _encode_getbulk_pdu(request_id: int, oid: str, non_repeaters: int = 0, max_repetitions: int = 25) -> bytes:
    varbind = _encode_sequence(_encode_oid(oid) + _encode_null())
    varbind_list = _encode_sequence(varbind)
    pdu_body = (
        _encode_integer(request_id)
        + _encode_integer(non_repeaters)
        + _encode_integer(max_repetitions)
        + varbind_list
    )
    return b"\xa5" + _encode_length(len(pdu_body)) + pdu_body


def _encode_message(community: str, pdu: bytes) -> bytes:
    version = _encode_integer(1)  # SNMPv2c
    community_enc = _encode_octet_string(community)
    return _encode_sequence(version + community_enc + pdu)


def _decode_length(data: bytes, idx: int) -> Tuple[int, int]:
    if idx >= len(data):
        raise SnmpError("truncated length")
    first = data[idx]
    if first < 0x80:
        return first, idx + 1
    n = first & 0x7F
    if idx + n >= len(data):
        raise SnmpError("truncated length bytes")
    val = 0
    for i in range(n):
        val = (val << 8) | data[idx + 1 + i]
    return val, idx + 1 + n


def _decode_oid(data: bytes, idx: int) -> Tuple[str, int]:
    if data[idx] != 0x06:
        raise SnmpError(f"expected OID tag, got {data[idx]:02x}")
    length, idx = _decode_length(data, idx + 1)
    end = idx + length
    body = data[idx:end]
    if not body:
        return "", end
    first = body[0]
    parts = [first // 40, first % 40]
    i = 1
    while i < len(body):
        val = 0
        while i < len(body):
            b = body[i]
            i += 1
            val = (val << 7) | (b & 0x7F)
            if not (b & 0x80):
                break
        parts.append(val)
    return ".".join(str(p) for p in parts), end


def _decode_value(data: bytes, idx: int) -> Tuple[object, int]:
    if idx >= len(data):
        raise SnmpError("truncated value")
    tag = data[idx]
    length, idx = _decode_length(data, idx + 1)
    end = idx + length
    body = data[idx:end]

    if tag == 0x02:  # INTEGER
        if not body:
            return 0, end
        val = 0
        for b in body:
            val = (val << 8) | b
        # signed
        if body[0] & 0x80:
            bits = len(body) * 8
            val -= 1 << bits
        return val, end
    if tag == 0x04:  # OCTET STRING
        try:
            return body.decode("utf-8"), end
        except Exception:
            return body.hex(" ").upper(), end
    if tag == 0x05:  # NULL
        return None, end
    if tag == 0x06:  # OID
        oid, _ = _decode_oid(data, idx - (end - idx) - 1)  # re-parse
        # simpler: decode from body
        if not body:
            return "", end
        first = body[0]
        parts = [first // 40, first % 40]
        i = 1
        while i < len(body):
            val = 0
            while i < len(body):
                b = body[i]
                i += 1
                val = (val << 7) | (b & 0x7F)
                if not (b & 0x80):
                    break
            parts.append(val)
        return ".".join(str(p) for p in parts), end
    if tag == 0x40:  # IpAddress
        if len(body) == 4:
            return ".".join(str(b) for b in body), end
        return body.hex(), end
    if tag in (0x41, 0x42, 0x43, 0x46):  # Counter, Gauge, TimeTicks, Counter64
        val = 0
        for b in body:
            val = (val << 8) | b
        return val, end
    if tag == 0x44:  # Opaque
        return body.hex(), end
    # fallback
    return body.hex(" ").upper() if body else None, end


def _decode_varbinds(data: bytes, idx: int) -> Tuple[List[Tuple[str, object]], int]:
    if idx >= len(data) or data[idx] != 0x30:
        raise SnmpError("expected sequence for varbind list")
    length, idx = _decode_length(data, idx + 1)
    end = min(idx + length, len(data))
    results = []
    while idx < end:
        if data[idx] != 0x30:
            break
        vb_len, vb_idx = _decode_length(data, idx + 1)
        vb_end = min(vb_idx + vb_len, end)
        try:
            oid, vb_idx = _decode_oid(data, vb_idx)
            val, vb_idx = _decode_value(data, vb_idx)
            results.append((oid, val))
        except Exception:
            # skip malformed varbind
            pass
        idx = vb_end
    return results, end


def _decode_response(data: bytes) -> List[Tuple[str, object]]:
    if not data or data[0] != 0x30:
        raise SnmpError("invalid SNMP response")
    length, idx = _decode_length(data, 1)
    # version
    if data[idx] != 0x02:
        raise SnmpError("expected version")
    _, idx = _decode_value(data, idx)
    # community
    if data[idx] != 0x04:
        raise SnmpError("expected community")
    _, idx = _decode_value(data, idx)
    # PDU (GetResponse = 0xA2)
    pdu_tag = data[idx]
    if pdu_tag not in (0xA2, 0xA1, 0xA0, 0xA5):
        # still try
        pass
    pdu_len, idx = _decode_length(data, idx + 1)
    pdu_end = idx + pdu_len
    # request-id, error-status, error-index
    _, idx = _decode_value(data, idx)
    err_status, idx = _decode_value(data, idx)
    _, idx = _decode_value(data, idx)
    if err_status and err_status != 0:
        # partial results still useful
        pass
    varbinds, _ = _decode_varbinds(data, idx)
    return varbinds


def snmp_get(host: str, community: str, oid: str, port: int = 161, timeout: float = 5.0) -> Optional[object]:
    req_id = random.randint(1, 0x7FFFFFFF)
    pdu = _encode_get_pdu(req_id, oid)
    msg = _encode_message(community, pdu)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(msg, (host, port))
        data, _ = sock.recvfrom(65535)
        sock.close()
        vbs = _decode_response(data)
        if vbs:
            return vbs[0][1]
    except Exception as e:
        print(f"[SNMP GET] {oid}: {e}")
    return None


def snmp_getnext_walk(
    host: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 5.0,
    max_oids: int = 5000,
) -> Dict[str, object]:
    """SNMPv2c GETNEXT walk — fallback kalau GETBULK tidak didukung / kosong."""
    base = oid.strip(".")
    result: Dict[str, object] = {}
    current_oid = base
    retries = 0

    while len(result) < max_oids:
        req_id = random.randint(1, 0x7FFFFFFF)
        pdu = _encode_get_pdu(req_id, current_oid, pdu_type=0xA1)  # GetNext
        msg = _encode_message(community, pdu)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(msg, (host, port))
            data, _ = sock.recvfrom(65535)
            sock.close()
            vbs = _decode_response(data)
            retries = 0
        except socket.timeout:
            retries += 1
            if retries >= 3:
                break
            continue
        except Exception as e:
            print(f"[SNMP GETNEXT] {current_oid}: {e}")
            break

        if not vbs:
            break

        full_oid, val = vbs[0]
        full = str(full_oid).strip(".")
        if not full.startswith(base + ".") and full != base:
            break
        suffix = full[len(base) :].lstrip(".")
        if not suffix:
            current_oid = full
            continue
        if suffix in result:
            break
        result[suffix] = val
        current_oid = full

    return result


def snmp_bulk_walk(
    host: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 5.0,
    max_repetitions: int = 40,
    max_oids: int = 5000,
) -> Dict[str, object]:
    """
    SNMPv2c GETBULK walk, auto-fallback ke GETNEXT jika hasil kosong / gagal.
    Return dict: suffix_after_base -> value
    """
    base = oid.strip(".")
    result: Dict[str, object] = {}
    current_oid = base
    retries = 0
    bulk_failed = False

    while len(result) < max_oids:
        req_id = random.randint(1, 0x7FFFFFFF)
        pdu = _encode_getbulk_pdu(req_id, current_oid, 0, max_repetitions)
        msg = _encode_message(community, pdu)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(msg, (host, port))
            data, _ = sock.recvfrom(65535)
            sock.close()
            vbs = _decode_response(data)
            retries = 0
        except socket.timeout:
            retries += 1
            if retries >= 2:
                bulk_failed = True
                break
            continue
        except Exception as e:
            print(f"[SNMP BULK] {current_oid}: {e}")
            bulk_failed = True
            break

        if not vbs:
            bulk_failed = True
            break

        advanced = False
        left_subtree = False
        for full_oid, val in vbs:
            full = str(full_oid).strip(".")
            if not full.startswith(base):
                left_subtree = True
                break
            suffix = full[len(base) :].lstrip(".")
            if not suffix:
                continue
            if suffix in result:
                left_subtree = True
                break
            result[suffix] = val
            current_oid = full
            advanced = True

        if left_subtree or not advanced:
            break

    # Fallback GETNEXT jika bulk kosong (banyak OLT ZTE: Get-bulk=0 di show snmp)
    if not result:
        result = snmp_getnext_walk(
            host, community, oid, port=port, timeout=timeout, max_oids=max_oids
        )
        if result:
            print(f"[SNMP] GETNEXT fallback OK untuk {oid}: {len(result)} entry")

    return result


def snmp_get_rx_for_suffixes(
    host: str,
    community: str,
    suffixes: list,
    port: int = 161,
    timeout: float = 4.0,
) -> Dict[str, object]:
    """
    Ambil Rx Power per-ONT dengan GET (lebih andal kalau GETBULK optical kosong).
    Coba beberapa OID + bentuk index: suffix dan suffix.1
    """
    bases = [
        "1.3.6.1.4.1.3902.1082.500.20.2.2.2.1.10",
        "1.3.6.1.4.1.3902.1082.500.20.2.2.1.1.10",
        "1.3.6.1.4.1.3902.1012.3.50.12.1.1.10",
    ]
    out: Dict[str, object] = {}
    if not suffixes:
        return out

    # Batasi biar tidak terlalu lama: max 200 ONT GET
    sample = list(suffixes)[:200]
    print(f"[SNMP] GET Rx per-ONT untuk {len(sample)} index...")

    for base in bases:
        got = 0
        for suf in sample:
            for candidate in (f"{base}.{suf}.1", f"{base}.{suf}"):
                val = snmp_get(host, community, candidate, port=port, timeout=timeout)
                if val is None:
                    continue
                # simpan di key yang dipakai parser (suf dan suf.1)
                out[str(suf)] = val
                out[f"{suf}.1"] = val
                got += 1
                break
        if got:
            print(f"[SNMP] GET Rx OK via {base} → {got} nilai")
            return out
        print(f"[SNMP] GET Rx via {base}: 0")
    return out



# ============================================================
# ZTE C320 data model
# ============================================================

@dataclass
class OnuInfo:
    board: int
    pon: int
    onu_id: int
    name: str = ""
    description: str = ""
    serial: str = ""
    onu_type: str = ""
    status: str = "Unknown"
    status_code: int = -1
    rx_power: Optional[float] = None
    tx_power: Optional[float] = None
    distance: Optional[int] = None
    odp: str = "Belum di-mapping"
    raw_index: str = ""
    olt_id: str = ""
    olt_name: str = ""
    last_downtime: str = ""   # waktu mulai offline terakhir (ISO / display)
    last_online: str = ""     # waktu terakhir terdeteksi online

    def to_dict(self) -> dict:
        return {
            "olt_id": self.olt_id,
            "olt_name": self.olt_name,
            "board": self.board,
            "pon": self.pon,
            "onu_id": self.onu_id,
            "name": self.name,
            "description": self.description,
            "serial": self.serial,
            "onu_type": self.onu_type,
            "status": self.status,
            "status_code": self.status_code,
            "rx_power": self.rx_power,
            "tx_power": self.tx_power,
            "distance": self.distance,
            "odp": self.odp,
            "last_downtime": self.last_downtime,
            "last_online": self.last_online,
            "location": f"{self.board}/{self.pon}:{self.onu_id}",
        }


STATUS_MAP = {
    # Hasil observasi C320 V2.1.0 (1082): code 4 = ONT hidup (ada Rx)
    0: "Logging",
    1: "Offline",
    2: "SyncMib",
    3: "Online",
    4: "Online",      # BUKAN LOS di firmware ini
    5: "DyingGasp",
    6: "PowerOff",
    7: "AuthFailed",
    8: "Offline",
    9: "Offline",
}

STATUS_DISPLAY = {
    "Working": "Online",
    "Online": "Online",
    "Logging": "Logging",
    "LOS": "LOS",
    "SyncMib": "SyncMib",
    "DyingGasp": "DyingGasp",
    "AuthFailed": "AuthFailed",
    "PowerOff": "Offline",
    "Offline": "Offline",
    "Unknown": "Unknown",
}


def convert_rx_power(raw) -> Optional[float]:
    if raw is None:
        return None
    try:
        raw = int(float(str(raw).strip()))
    except Exception:
        return None
    # N/A / offline markers
    if raw in (65535, 65535000, -80000, 0xFFFF, 2147483647, -2147483648):
        return None
    # Sudah dalam dBm * 100 (contoh -2234 = -22.34)
    if -4000 <= raw <= -500:
        return round(raw / 100.0, 2)
    # Sudah dalam dBm * 1000
    if -40000 <= raw <= -5000:
        return round(raw / 1000.0, 2)
    # Formula klasik ZTE: value * 0.002 - 30
    if 0 <= raw <= 30000:
        return round(raw * 0.002 - 30, 2)
    # 2's complement 16-bit style
    if 30000 < raw <= 65535:
        return round((raw - 65536) * 0.002 - 30, 2)
    # Nilai negatif langsung (sudah dBm-ish)
    if -40 <= raw <= 10:
        return float(raw)
    # dBuW 0.002 resolution -> dBm = val*0.002 - 30
    if -20000 <= raw < 0:
        return round(raw * 0.002 - 30, 2)
    return None


def convert_tx_power(raw) -> Optional[float]:
    if raw is None:
        return None
    try:
        raw = int(raw)
    except Exception:
        return None
    if raw in (65535, 0xFFFF):
        return None
    if 0 <= raw <= 30000:
        return round(raw * 0.002 - 30, 2)
    if raw > 30000:
        return round((raw - 65536) * 0.002 - 30, 2)
    if -100 < raw < 100:
        return round(raw * 0.1, 2)
    return round(raw / 1000.0, 2) if abs(raw) > 50 else None


def parse_serial(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (bytes, bytearray)):
        # vendor (4) + hex serial
        try:
            if len(raw) >= 8:
                # often first 4 bytes vendor ascii or binary
                s = raw.decode("ascii", errors="ignore").strip()
                if len(s) >= 8:
                    return re.sub(r"^\d+,", "", s).strip().upper()
            return raw.hex().upper()
        except Exception:
            return raw.hex().upper()
    raw = str(raw).strip().strip('"')
    # decoder kadang hasilkan "1,ZTEGXXXX" atau "1.ZTEGXXXX"
    if "," in raw:
        raw = raw.split(",")[-1].strip()
    if re.match(r"^\d+\.", raw):
        raw = raw.split(".", 1)[-1].strip()
    raw = raw.replace("0x", "").replace(" ", "")
    # hex string panjang → coba decode vendor
    if len(raw) >= 16 and all(c in "0123456789ABCDEFabcdef" for c in raw):
        try:
            b = bytes.fromhex(raw[:24] if len(raw) >= 24 else raw)
            vendor = b[:4].decode("ascii", errors="ignore")
            if vendor.isprintable() and len(vendor) >= 3:
                rest = b[4:].hex().upper()
                return (vendor + rest).upper()
            return raw.upper()
        except Exception:
            return raw.upper()
    return raw.upper()



def detect_firmware(host: str, community: str, port: int = 161) -> str:
    """Coba deteksi V1 vs V2."""
    # V2 name table
    v2 = snmp_bulk_walk(host, community, "1.3.6.1.4.1.3902.1082.500.10.2.3.3.1.2", port=port, timeout=config.SNMP_TIMEOUT, max_oids=5)
    if v2:
        print("[SNMP] Firmware terdeteksi: V2 (1082)")
        return "v2"
    v1 = snmp_bulk_walk(host, community, "1.3.6.1.4.1.3902.1012.3.28.1.1.3", port=port, timeout=config.SNMP_TIMEOUT, max_oids=5)
    if v1:
        print("[SNMP] Firmware terdeteksi: V1 (1012)")
        return "v1"
    print("[SNMP] Tidak bisa deteksi firmware, default V1")
    return "v1"


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
    serial_oid = "1.3.6.1.4.1.3902.1012.3.28.1.1.5"
    status_oid = "1.3.6.1.4.1.3902.1012.3.28.2.1.4"
    rx_oid = "1.3.6.1.4.1.3902.1012.3.50.12.1.1.10"

    timeout = max(config.SNMP_TIMEOUT, 6)
    print("[SNMP] Parallel walk V1 tables...")
    def _w(oid):
        return snmp_bulk_walk(host, community, oid, port=port, timeout=timeout, max_repetitions=40)
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_name = ex.submit(_w, name_oid)
        f_ser = ex.submit(_w, serial_oid)
        f_st = ex.submit(_w, status_oid)
        f_rx = ex.submit(_w, rx_oid)
        names = f_name.result()
        serials = f_ser.result()
        statuses = f_st.result()
        rxs = f_rx.result()
    print(f"[SNMP] Ditemukan {len(names)} entry name")

    for suffix, name in names.items():
        try:
            parts = str(suffix).strip(".").split(".")
            if len(parts) < 2:
                continue
            if_index = int(parts[0])
            onu_id = int(parts[1])
            board, pon = _guess_board_pon_v1(if_index)
            if board not in boards:
                continue

            serial = parse_serial(serials.get(suffix, ""))
            try:
                status_code = int(statuses.get(suffix, -1))
            except Exception:
                status_code = -1
            status = STATUS_MAP.get(status_code, "Unknown")

            rx_raw = rxs.get(suffix, rxs.get(suffix + ".1"))
            rx_val = convert_rx_power(rx_raw)

            onts.append(
                OnuInfo(
                    board=board,
                    pon=pon,
                    onu_id=onu_id,
                    name=str(name).strip('"') if name else "",
                    serial=serial,
                    status=STATUS_DISPLAY.get(status, status),
                    status_code=status_code,
                    rx_power=rx_val,
                    raw_index=str(suffix),
                )
            )
        except Exception as e:
            print(f"[parse v1] {suffix}: {e}")
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
            desc = str(_lookup(descs, suffix) or "").strip('"')
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
                    name=str(name).strip('"') if name else "",
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
) -> List[OnuInfo]:
    """
    Ambil ONT.
    vendor: zte | hioso | auto
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
        return onts

    print(f"[SNMP] Connect ke {host}:{port} community={community} vendor={vendor} olt={olt_id or '-'}")
    sysdescr = snmp_get(host, community, "1.3.6.1.2.1.1.1.0", port=port, timeout=config.SNMP_TIMEOUT)
    if sysdescr is None:
        print("[SNMP] GAGAL connect ke OLT.")
        return []
    print(f"[SNMP] OLT merespons: {sysdescr}")

    # Auto vendor dari sysDescr
    if vendor in ("auto", ""):
        sd = str(sysdescr).lower()
        if "hioso" in sd or "ha73" in sd or "ha72" in sd or "25355" in sd:
            vendor = "hioso"
        elif "airpo" in sd or "hsairpo" in sd or "vsol" in sd or "v-sol" in sd or "37950" in sd or "photon" in sd or "ept1004" in sd:
            vendor = "hsairpo"
        else:
            vendor = "zte"
        print(f"[SNMP] Auto vendor → {vendor}")

    if vendor in ("hioso",):
        variant = firmware if firmware in ("epon", "gpon") else "auto"
        return fetch_hioso_onts(
            host, community, port=port, variant=variant,
            olt_id=olt_id, olt_name=olt_name,
        )

    if vendor in ("hsairpo", "airpo", "vsol"):
        variant = firmware if firmware in ("epon", "gpon") else "auto"
        return fetch_hsairpo_onts(
            host, community, port=port, variant=variant,
            olt_id=olt_id, olt_name=olt_name,
        )

    if firmware is None or firmware == "auto":
        firmware = detect_firmware(host, community, port)

    if firmware == "v2":
        return _fetch_v2(host, community, boards, port, filter_pon=filter_pon, olt_id=olt_id, olt_name=olt_name)
    return _fetch_v1(host, community, boards, port, filter_pon=filter_pon, olt_id=olt_id, olt_name=olt_name)


# ============================================================
# Hioso OLT (enterprise 25355) — EPON & GPON
# ============================================================

HIOSO_STATUS = {
    1: "Online",
    2: "Offline",
    3: "Offline",
    0: "Unknown",
}


def _hioso_parse_power(raw) -> Optional[float]:
    if raw is None:
        return None
    try:
        s = str(raw).strip().replace("dBm", "").replace(" ", "")
        if s in ("", "N/A", "NA", "--", "null"):
            return None
        v = float(s)
        # integer mentah 0.01 dBm atau 0.1 dBm
        if abs(v) > 100:
            v = v / 100.0
        elif abs(v) > 40 and abs(v) <= 100:
            v = v / 10.0
        if v < -40 or v > 10:
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
    """Hioso EPON / HA73xx style — MIB 25355.3.2.6"""
    name_oid = "1.3.6.1.4.1.25355.3.2.6.3.2.1.37"
    serial_oid = "1.3.6.1.4.1.25355.3.2.6.3.2.1.11"
    status_oid = "1.3.6.1.4.1.25355.3.2.6.3.2.1.39"
    dist_oid = "1.3.6.1.4.1.25355.3.2.6.3.2.1.25"
    rx_oid = "1.3.6.1.4.1.25355.3.2.6.14.2.1.8"
    tx_oid = "1.3.6.1.4.1.25355.3.2.6.14.2.1.4"

    timeout = max(config.SNMP_TIMEOUT, 6)
    print("[SNMP] Hioso EPON walk...")
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
            dist = None
            try:
                if dists.get(suffix) is not None:
                    dist = int(dists.get(suffix))
            except Exception:
                pass
            if rx_val is not None and rx_val > -32 and status != "Online":
                status = "Online"
            onts.append(OnuInfo(
                board=board, pon=pon, onu_id=onu_id,
                name=str(name).strip('"') if name else "",
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
                name=str(name).strip('"') if name else "",
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


def _fetch_cdata_epon(host: str, community: str, port: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """C-Data FD-ONU — enterprise 34592."""
    status_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.11"
    serial_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.3"
    type_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.2"
    dist_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.13"
    rx_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.36"
    tx_oid = "1.3.6.1.4.1.34592.1.3.4.1.1.37"

    timeout = max(config.SNMP_TIMEOUT, 6)
    print("[SNMP] C-Data EPON (34592) walk...")
    statuses = snmp_bulk_walk(host, community, status_oid, port=port, timeout=timeout)
    print(f"[SNMP] C-Data status: {len(statuses)}")
    if not statuses:
        return []
    serials = snmp_bulk_walk(host, community, serial_oid, port=port, timeout=timeout)
    types = snmp_bulk_walk(host, community, type_oid, port=port, timeout=timeout)
    dists = snmp_bulk_walk(host, community, dist_oid, port=port, timeout=timeout)
    rxs = snmp_bulk_walk(host, community, rx_oid, port=port, timeout=timeout)
    txs = snmp_bulk_walk(host, community, tx_oid, port=port, timeout=timeout)

    onts: List[OnuInfo] = []
    for suffix, st_raw in statuses.items():
        board, pon, onu_id = _parse_hioso_index(suffix)
        try:
            try:
                status_code = int(st_raw)
            except Exception:
                status_code = -1
            status = "Online" if status_code in (1, 3) else "Offline"
            serial = parse_serial(serials.get(suffix, ""))
            name = str(types.get(suffix) or "").strip('"')
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
            print(f"[parse cdata] {suffix}: {e}")
    return onts



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
                name=str(names.get(suffix) or "").strip('"'),
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
