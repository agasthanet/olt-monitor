"""Shared SNMP helpers & OnuInfo model."""
from __future__ import annotations

import random
import re
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import config

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
    if tag == 0x04:  # OCTET STRING — selalu bytes; caller pakai snmp_text / parse_serial
        return body, end
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


def snmp_get(host: str, community: str, oid: str, port: int = 161, timeout: float = 5.0, quiet: bool = True) -> Optional[object]:
    """quiet=True: jangan spam log saat timeout (default)."""
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
    except socket.timeout:
        return None
    except Exception as e:
        if not quiet:
            print(f"[SNMP GET] {oid}: {e}")
    return None



def _encode_set_pdu(request_id: int, oid: str, value_bytes: bytes) -> bytes:
    """SNMPv2c SetRequest (0xA3). value_bytes = already BER-encoded value."""
    varbind = _encode_sequence(_encode_oid(oid) + value_bytes)
    varbind_list = _encode_sequence(varbind)
    pdu_body = (
        _encode_integer(request_id)
        + _encode_integer(0)
        + _encode_integer(0)
        + varbind_list
    )
    return bytes([0xA3]) + _encode_length(len(pdu_body)) + pdu_body


def snmp_set_integer(
    host: str,
    community: str,
    oid: str,
    value: int,
    port: int = 161,
    timeout: float = 8.0,
) -> tuple:
    """
    SET integer. Return (ok: bool, message: str).
    Butuh community write (sering 'private' / sama dengan read jika tidak dipisah).
    """
    req_id = random.randint(1, 0x7FFFFFFF)
    pdu = _encode_set_pdu(req_id, oid, _encode_integer(int(value)))
    msg = _encode_message(community, pdu)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(msg, (host, port))
        data, _ = sock.recvfrom(65535)
        sock.close()
        # decode error-status from response roughly
        try:
            vbs = _decode_response(data)
            return True, f"SET OK {oid}={value}"
        except Exception:
            return True, f"SET sent {oid}={value} (response parse soft-ok)"
    except socket.timeout:
        return False, f"SET timeout {oid}"
    except Exception as e:
        return False, f"SET error: {e}"


def restart_ont_snmp(
    host: str,
    community: str,
    board: int,
    pon: int,
    onu_id: int,
    port: int = 161,
    vendor: str = "auto",
) -> tuple:
    """
    Best-effort restart ONT via SNMP SET.
    Return (ok, message).
    """
    vendor = (vendor or "auto").lower()
    # kandidat OID + nilai aksi reset (biasanya 1)
    # Index bervariasi antar firmware: board.pon.onu | 1.board.pon.onu | 0.board.pon.onu
    idxs = [
        f"{board}.{pon}.{onu_id}",
        f"1.{board}.{pon}.{onu_id}",
        f"0.{board}.{pon}.{onu_id}",
        f"1.1.{board}.{pon}.{onu_id}",
        f"{pon}.{onu_id}",
        f"1.{pon}.{onu_id}",
        f"0.{pon}.{onu_id}",
    ]
    oid_bases = []
    if vendor in ("zte", "c320", "c300", "auto", ""):
        oid_bases += [
            # ZTE C300/C320 common mgmt action (1=reset)
            "1.3.6.1.4.1.3902.1012.3.28.3.1.4",
            "1.3.6.1.4.1.3902.1012.3.28.2.1.20",
            "1.3.6.1.4.1.3902.1082.1.3.2.2.1.10",
            "1.3.6.1.4.1.3902.1082.1.1.2.4.1.4",
        ]
    if vendor in ("hioso", "auto", ""):
        oid_bases += [
            "1.3.6.1.4.1.25355.3.2.6.3.2.1.50",  # speculative action
        ]
    if vendor in ("hsairpo", "vsol", "airpo", "auto", ""):
        oid_bases += [
            "1.3.6.1.4.1.37950.1.1.5.10.3.1.4",
        ]

    errors = []
    for base in oid_bases:
        for idx in idxs:
            oid = f"{base}.{idx}"
            ok, msg = snmp_set_integer(host, community, oid, 1, port=port, timeout=5)
            if ok:
                return True, f"Restart command sent ({oid})"
            errors.append(msg)
    # last try value=2 (some vendors use 2=reboot)
    for base in oid_bases[:3]:
        for idx in idxs[:3]:
            oid = f"{base}.{idx}"
            ok, msg = snmp_set_integer(host, community, oid, 2, port=port, timeout=5)
            if ok:
                return True, f"Restart command sent value=2 ({oid})"
            errors.append(msg)
    return False, "Restart SNMP gagal. Cek community WRITE, atau OLT tidak expose OID reset. " + (errors[0] if errors else "")


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
            # jangan spam; GETNEXT gagal → stop walk
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
    last_rx_power: Optional[float] = None  # Rx terakhir saat masih online

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
            "last_rx_power": self.last_rx_power,
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



def _snmp_number(raw):
    """Normalisasi nilai SNMP (int/float/bytes/str) ke float, atau None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, (bytes, bytearray)):
        b = bytes(raw).strip(b"\x00").strip()
        if not b:
            return None
        # teks ASCII: "-22.50", "2250"
        try:
            t = b.decode("ascii", errors="ignore").strip().replace("dBm", "").replace(" ", "")
            if t and t not in ("N/A", "NA", "--", "null"):
                return float(t)
        except Exception:
            pass
        # integer big-endian (1–4 byte)
        try:
            if 1 <= len(b) <= 4:
                return float(int.from_bytes(b, "big", signed=True))
        except Exception:
            pass
        return None
    s = str(raw).strip()
    # hindari repr bytes
    if s.startswith("b'") or s.startswith('b"'):
        return None
    s = s.replace("dBm", "").replace(" ", "")
    if s in ("", "N/A", "NA", "--", "null", "None"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def convert_rx_power(raw) -> Optional[float]:
    if raw is None:
        return None
    try:
        n = _snmp_number(raw)
        if n is None:
            return None
        raw = int(n)
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
        n = _snmp_number(raw)
        if n is None:
            return None
        raw = int(n)
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




def prefer_ont_name(name, description="") -> str:
    """Pilih label tampilan: prioritaskan description jika name generik ONU-x:y."""
    n = snmp_text(name)
    d = snmp_text(description)
    generic = False
    if not n:
        generic = True
    elif re.match(r"^ONU[-_]?\d+[:./]\d+$", n, re.I):
        generic = True
    elif re.match(r"^ONU\d+$", n, re.I):
        generic = True
    elif n.upper() in ("NA", "N/A", "NULL", "-"):
        generic = True
    if generic and d and d.upper() not in ("NA", "N/A", "NULL", "-"):
        return d
    return n or d or ""


def snmp_text(val) -> str:
    """Octet string → teks aman untuk nama/desc (bukan serial)."""
    if val is None:
        return ""
    if isinstance(val, (bytes, bytearray)):
        b = bytes(val).split(b"\x00")[0]
        # trim trailing NULs already done
        for enc in ("utf-8", "latin-1"):
            try:
                s = b.decode(enc)
                s = "".join(ch for ch in s if ch.isprintable() or ch in " \t").strip().strip('"')
                return s
            except Exception:
                continue
        return ""
    s = str(val).strip().strip('"')
    # jangan tampilkan repr bytes
    if s.startswith("b'") or s.startswith('b"'):
        return ""
    return "".join(ch for ch in s if ch.isprintable() or ch in " \t").strip()


def parse_serial(raw) -> str:
    """
    Format serial ONT:
    - ZTE 8 byte: vendor ASCII (ZTEG) + 4 byte hex → ZTEGC69C61EF
    - MAC 6 byte → AA:BB:CC:DD:EE:FF
    - String hex "52 54 45 47 ..." → decode dulu
    """
    if raw is None:
        return ""

    def _from_bytes(raw_b: bytes) -> str:
        if not raw_b:
            return ""
        # MAC 6 bytes
        if len(raw_b) == 6:
            return ":".join(f"{b:02X}" for b in raw_b)
        # ZTE-style: 4 ascii vendor + binary
        if len(raw_b) >= 8:
            vendor = raw_b[:4]
            rest = raw_b[4:]
            # vendor printable ASCII letters (ZTEG, HWTC, ...)
            if all(65 <= b <= 90 or 97 <= b <= 122 for b in vendor):
                try:
                    v = vendor.decode("ascii")
                    # sisa tampilkan hex (standar SN ZTE)
                    return v + rest[:4].hex().upper() if len(rest) >= 4 else v + rest.hex().upper()
                except Exception:
                    pass
            # full printable
            try:
                s = raw_b.decode("ascii")
                if s.isprintable() and len(s) >= 4:
                    return re.sub(r"^\d+,", "", s).strip()
            except Exception:
                pass
        # continuous hex uppercase
        return raw_b.hex().upper()

    if isinstance(raw, (bytes, bytearray)):
        return _from_bytes(bytes(raw))

    s = str(raw).strip().strip('"')
    s = "".join(ch for ch in s if ch.isprintable() or ch in " :").strip()
    s = re.sub(r"^\d+,", "", s).strip()

    # "52 54 45 47 C6 9C 61 EF" atau "52:54:45:47:..."
    if re.fullmatch(r"[0-9A-Fa-f]{2}([ :\-][0-9A-Fa-f]{2}){3,}", s):
        hexpart = re.sub(r"[^0-9A-Fa-f]", "", s)
        try:
            return _from_bytes(bytes.fromhex(hexpart))
        except Exception:
            return hexpart.upper()

    # continuous hex 12–16+ chars without separator
    if re.fullmatch(r"[0-9A-Fa-f]{12,32}", s):
        try:
            return _from_bytes(bytes.fromhex(s))
        except Exception:
            return s.upper()

    return s


