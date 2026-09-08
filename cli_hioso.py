"""
Hioso HA7302CSM (dan sejenis) — monitor via Telnet CLI.
SNMP tidak tersedia; show pon ... onu memutus koneksi.
Pakai: show optical-ddm onu 0/1/{pon}:{onu_id}
"""
from __future__ import annotations

import re
import socket
import time
from typing import List, Optional

from snmp_zte import OnuInfo

_RX_RE = re.compile(r"RxPower\s*:\s*([-\d.]+)\s*dBm", re.I)
_TX_RE = re.compile(r"TxPower\s*:\s*([-\d.]+)\s*dBm", re.I)
_ONU_HDR = re.compile(r"ONU\s+(\d+)/(\d+)/(\d+):(\d+)\s+optical", re.I)


def _telnet_session(host: str, port: int, username: str, password: str,
                    access_password: str = "", enable_password: str = "",
                    timeout: int = 20):
    """Login Hioso multi-step, return connected socket at EPON(epon)# prompt."""
    access_password = access_password or password
    enable_password = enable_password or password

    sock = socket.create_connection((host, port), timeout=max(timeout, 25))
    sock.settimeout(timeout)

    def recv_wait(seconds: float = 1.0) -> str:
        sock.settimeout(seconds)
        buf = b""
        end = time.time() + seconds
        while time.time() < end:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                # strip rough telnet IAC
                cleaned = bytearray()
                i = 0
                while i < len(chunk):
                    if chunk[i] == 255 and i + 1 < len(chunk):
                        cmd = chunk[i + 1]
                        if cmd in (251, 252, 253, 254) and i + 2 < len(chunk):
                            opt = chunk[i + 2]
                            if cmd in (251, 252):
                                sock.sendall(bytes([255, 254, opt]))
                            else:
                                sock.sendall(bytes([255, 252, opt]))
                            i += 3
                        else:
                            i += 2
                    else:
                        cleaned.append(chunk[i])
                        i += 1
                buf += bytes(cleaned)
                if len(chunk) < 4096:
                    time.sleep(0.05)
                    sock.settimeout(0.25)
            except socket.timeout:
                break
            except Exception:
                break
        return buf.decode("utf-8", errors="ignore")

    def wait_for(keys, max_wait=15.0) -> str:
        buf = ""
        end = time.time() + max_wait
        while time.time() < end:
            buf += recv_wait(0.7)
            low = buf.lower()
            for k in keys:
                if k.lower() in low:
                    return buf
            if buf.rstrip().endswith(("#", ">")):
                return buf
        return buf

    def send(s: str):
        sock.sendall((s + "\r\n").encode("ascii", errors="ignore"))

    # banner / login
    buf = wait_for(["login", "password", "access password", "username", "#", ">"], max_wait=timeout)
    print(f"[HiosoCLI] banner: {buf[-150:]!r}")
    low = buf.lower()

    if "login" in low or "username" in low:
        send(username)
        buf = wait_for(["password"], max_wait=timeout)
        send(password)
        buf = wait_for(["access password", ">", "#", "password"], max_wait=timeout)

    if "access password" in buf.lower():
        send(access_password)
        buf = wait_for([">", "#"], max_wait=timeout)

    # already at EPON> or need password again
    if "password" in buf.lower() and ">" not in buf[-5:] and "#" not in buf[-5:]:
        send(password)
        buf = wait_for([">", "#"], max_wait=timeout)

    # enable
    if not buf.rstrip().endswith("#"):
        send("en")
        buf = wait_for(["password", "#", ">"], max_wait=8)
        if "password" in buf.lower():
            send(enable_password)
            wait_for(["#"], max_wait=timeout)

    # enter epon node
    send("configure terminal")
    wait_for(["(config)", "#"], max_wait=8)
    send("epon")
    wait_for(["(epon)", "#"], max_wait=8)
    print("[HiosoCLI] entered EPON(epon)#")
    return sock, recv_wait, send


def _run_cmd(send, recv_wait, cmd: str, wait: float = 2.5) -> str:
    try:
        recv_wait(0.15)
    except Exception:
        pass
    send(cmd)
    time.sleep(0.4)
    return recv_wait(wait)


def parse_optical_ddm(text: str) -> tuple:
    """Return (rx, tx) or (None, None)."""
    rx = tx = None
    m = _RX_RE.search(text)
    if m:
        try:
            rx = float(m.group(1))
        except ValueError:
            pass
    m = _TX_RE.search(text)
    if m:
        try:
            tx = float(m.group(1))
        except ValueError:
            pass
    return rx, tx


def fetch_hioso_cli(
    host: str,
    username: str = "root",
    password: str = "",
    *,
    port: int = 23,
    pons: Optional[List[int]] = None,
    max_onu: int = 128,
    access_password: str = "",
    enable_password: str = "",
    olt_id: str = "",
    olt_name: str = "",
) -> List[OnuInfo]:
    """
    Loop show optical-ddm onu 0/1/{pon}:{n} untuk tiap PON.
    Chassis/slot fixed 0/1 (HA7302 typical).
    """
    pons = pons or [1]
    print(f"[HiosoCLI] {host}:{port} user={username} pons={pons} max_onu={max_onu}")
    t0 = time.time()
    sock = None
    try:
        sock, recv_wait, send = _telnet_session(
            host, port, username, password,
            access_password=access_password,
            enable_password=enable_password,
        )
        onts: List[OnuInfo] = []
        # drain
        recv_wait(0.8)

        # pastikan masih di (epon)#
        send("")
        prompt_chk = recv_wait(1.0)
        if "(epon)" not in prompt_chk.lower() and "epon" not in prompt_chk.lower():
            print(f"[HiosoCLI] re-enter epon, prompt was: {prompt_chk[-80:]!r}")
            send("configure terminal")
            recv_wait(1.0)
            send("epon")
            recv_wait(1.0)

        debug_left = 5
        for pon in pons:
            empty_streak = 0
            for onu_id in range(1, max_onu + 1):
                # Format HA7302: 0/1/{pon}:{onu_id}
                cmd = f"show optical-ddm onu 0/1/{pon}:{onu_id}"
                raw = _run_cmd(send, recv_wait, cmd, wait=3.0)
                if debug_left > 0:
                    print(f"[HiosoCLI] sample cmd={cmd!r} out={raw[-300:]!r}")
                    debug_left -= 1

                rx, tx = parse_optical_ddm(raw)
                # Terima jika ada Rx/Tx numerik (header kadang beda format)
                has_optical = rx is not None or tx is not None
                if not has_optical:
                    # coba format alternatif sekali di onu 1: 0/{pon}/1:id  (jarang)
                    empty_streak += 1
                    if empty_streak >= 10 and onu_id > 12:
                        print(f"[HiosoCLI] stop early pon={pon} after {onu_id} empty")
                        break
                    continue

                empty_streak = 0
                status = "Online"
                if rx is not None and rx < -35:
                    status = "Offline"
                onts.append(OnuInfo(
                    board=1,
                    pon=pon,
                    onu_id=onu_id,
                    name=f"ONU-{pon}-{onu_id}",
                    description="",
                    serial="",
                    status=status,
                    status_code=1 if status == "Online" else 0,
                    rx_power=rx,
                    tx_power=tx,
                    raw_index=f"hioso-{pon}-{onu_id}",
                    olt_id=olt_id,
                    olt_name=olt_name,
                ))
                print(f"[HiosoCLI] 0/1/{pon}:{onu_id} rx={rx} tx={tx}")

                print(f"[HiosoCLI] total {len(uniq)} ONT in {time.time()-t0:.1f}s")
        return uniq
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass
