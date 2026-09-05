"""
HS-EPT1004 / HS Airpo — ambil data ONT via SSH atau Telnet CLI.
Perintah: sh ont optical-info ponN all
"""

from __future__ import annotations

import re
import time
from typing import List, Optional

from snmp_zte import OnuInfo

# MAC di CLI: 689F.F009.3829  atau  689F.F009.3829
_MAC_RE = re.compile(
    r"^(\d+)\s+([0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})\s+"
    r"([\d.]+)\s+([-\d.]+)\s+([-\d.]+)"
)


def _norm_mac(mac: str) -> str:
    h = mac.replace(".", "").replace(":", "").replace("-", "").upper()
    if len(h) == 12:
        return ":".join(h[i : i + 2] for i in range(0, 12, 2))
    return mac.upper()


def parse_optical_info(text: str, pon: int, olt_id: str = "", olt_name: str = "") -> List[OnuInfo]:
    """Parse output `sh ont optical-info ponN all`."""
    onts: List[OnuInfo] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("-") or line.startswith("=") or "ONT" in line and "MAC" in line:
            continue
        if "More" in line or line.startswith("PON-") or line.startswith("EPON-"):
            continue
        m = _MAC_RE.match(line)
        if not m:
            # fallback: split whitespace
            parts = line.split()
            if len(parts) < 5:
                continue
            if not parts[0].isdigit():
                continue
            try:
                onu_id = int(parts[0])
                mac = parts[1]
                if "." not in mac and len(mac) < 8:
                    continue
                rx = float(parts[4]) if len(parts) > 4 else None
                tx = float(parts[3]) if len(parts) > 3 else None
            except (ValueError, IndexError):
                continue
        else:
            onu_id = int(m.group(1))
            mac = m.group(2)
            try:
                tx = float(m.group(4))
            except ValueError:
                tx = None
            try:
                rx = float(m.group(5))
            except ValueError:
                rx = None

        serial = _norm_mac(mac)
        status = "Online"
        if rx is not None and rx < -35:
            status = "Offline"
        name_fallback = mac.upper()
        onts.append(
            OnuInfo(
                board=1,
                pon=pon,
                onu_id=onu_id,
                name=name_fallback,
                description="",
                serial=serial,
                status=status,
                status_code=1 if status == "Online" else 0,
                rx_power=rx,
                tx_power=tx,
                raw_index=f"cli-pon{pon}-{onu_id}",
                olt_id=olt_id,
                olt_name=olt_name,
            )
        )
    return onts




def parse_ont_info_table(text: str) -> dict:
    """
    Parse: show ont info ponN all
    PORT ONT MAC Control Run Config Match Desc
    pon1 1 689F.F009.3829 active online success match 14105_Wida
    Return: { (pon, onu_id): {name, status, mac, serial} }
    """
    out = {}
    # line like: pon1  5  D05F.AF83.4CA6 active online success match 14105_Wida
    row_re = re.compile(
        r"^(pon\s*(\d+))\s+(\d+)\s+"
        r"([0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})\s+"
        r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*(.*)$",
        re.I,
    )
    for line in text.splitlines():
        line = line.strip()
        if not line.lower().startswith("pon"):
            continue
        m = row_re.match(line)
        if not m:
            # looser split
            parts = line.split()
            if len(parts) < 6:
                continue
            try:
                pon_s = parts[0].lower().replace("pon", "").strip()
                pon = int(pon_s)
                onu_id = int(parts[1])
                mac = parts[2]
                run_state = parts[4].lower() if len(parts) > 4 else ""
                desc = " ".join(parts[8:]).strip() if len(parts) > 8 else (parts[-1] if len(parts) > 7 else "")
            except Exception:
                continue
        else:
            pon = int(m.group(2))
            onu_id = int(m.group(3))
            mac = m.group(4)
            run_state = m.group(6).lower()
            desc = (m.group(9) or "").strip()
        status = "Online" if run_state in ("online", "up", "active") else "Offline"
        serial = _norm_mac(mac)
        name = desc if desc and desc.lower() not in ("-", "n/a", "none", "") else mac.upper()
        out[(pon, onu_id)] = {
            "name": name,
            "description": desc,
            "status": status,
            "mac": mac,
            "serial": serial,
        }
    return out


def parse_ont_names(text: str) -> dict:
    """Legacy helper: onu_id -> name from info table."""
    info = parse_ont_info_table(text)
    return {onu_id: v["name"] for (pon, onu_id), v in info.items()}


def _ssh_run(host: str, user: str, password: str, commands: List[str], port: int = 22, timeout: int = 20) -> str:
    try:
        import paramiko
    except ImportError as e:
        raise RuntimeError(
            "Library paramiko belum terpasang. Jalankan: pip install paramiko"
        ) from e

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            port=port,
            username=user,
            password=password,
            timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        # Prefer interactive shell — banyak OLT butuh enable
        chan = client.invoke_shell(width=200, height=50)
        time.sleep(0.8)
        _drain(chan)
        out_all = []
        for cmd in commands:
            chan.send(cmd + "\n")
            time.sleep(0.3)
            chunk = _read_until_prompt(chan, timeout=timeout)
            out_all.append(chunk)
            # handle --More-- pagination
            while "--More--" in chunk or "---- More ----" in chunk:
                chan.send(" ")
                time.sleep(0.4)
                more = _read_until_prompt(chan, timeout=8)
                out_all.append(more)
                chunk = more
        return "\n".join(out_all)
    finally:
        try:
            client.close()
        except Exception:
            pass


def _drain(chan, wait: float = 0.5) -> str:
    time.sleep(wait)
    data = ""
    while chan.recv_ready():
        data += chan.recv(65535).decode("utf-8", errors="ignore")
        time.sleep(0.05)
    return data


def _read_until_prompt(chan, timeout: float = 15) -> str:
    buf = ""
    end = time.time() + timeout
    while time.time() < end:
        if chan.recv_ready():
            buf += chan.recv(65535).decode("utf-8", errors="ignore")
            # prompt tipikal: ends with # or >
            if buf.rstrip().endswith(("#", ">")) and "\n" in buf:
                # pastikan bukan di tengah --More--
                if "--More--" not in buf[-80:] and "---- More" not in buf[-80:]:
                    break
        else:
            time.sleep(0.15)
    return buf



def _telnet_run(host: str, user: str, password: str, commands: List[str], port: int = 23, timeout: int = 20) -> str:
    """Telnet murni via socket — kompatibel Python 3.13+ (tanpa telnetlib)."""
    import socket
    import select

    print(f"[CLI] Connecting Telnet {host}:{port} ...")
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as e:
        raise RuntimeError(
            f"Tidak bisa connect Telnet {host}:{port} — {e}. "
            "Cek: OLT hidup, port 23 open, firewall Windows/antivirus, "
            "dan PC ini bisa Telnet ke OLT (uji di CMD: telnet {host} {port})"
        ) from e
    sock.settimeout(timeout)
    try:
        def recv_some(wait: float = 1.0) -> str:
            sock.settimeout(wait)
            chunks = []
            endt = time.time() + wait
            while time.time() < endt:
                try:
                    data = sock.recv(4096)
                    if not data:
                        break
                    # strip IAC telnet negotiation roughly
                    cleaned = bytearray()
                    i = 0
                    while i < len(data):
                        if data[i] == 255 and i + 1 < len(data):  # IAC
                            cmd = data[i + 1]
                            if cmd in (251, 252, 253, 254) and i + 2 < len(data):  # WILL/WONT/DO/DONT
                                # reply WONT/DONT
                                opt = data[i + 2]
                                if cmd in (251, 252):  # WILL/WONT -> DONT
                                    sock.sendall(bytes([255, 254, opt]))
                                else:  # DO/DONT -> WONT
                                    sock.sendall(bytes([255, 252, opt]))
                                i += 3
                            elif cmd == 250:  # SB
                                i += 2
                                while i < len(data) and not (data[i] == 255 and i + 1 < len(data) and data[i + 1] == 240):
                                    i += 1
                                i += 2
                            else:
                                i += 2
                        else:
                            cleaned.append(data[i])
                            i += 1
                    chunks.append(bytes(cleaned).decode("utf-8", errors="ignore"))
                    if len(data) < 4096:
                        # short pause for more
                        time.sleep(0.05)
                        sock.settimeout(0.2)
                except socket.timeout:
                    break
                except Exception:
                    break
            return "".join(chunks)

        def wait_for(patterns, max_wait: float = 15) -> str:
            buf = ""
            endt = time.time() + max_wait
            while time.time() < endt:
                buf += recv_some(0.8)
                low = buf.lower()
                for pat in patterns:
                    if pat.lower() in low:
                        return buf
                # also prompt
                if buf.rstrip().endswith(("#", ">")):
                    return buf
            return buf

        def send_line(s: str):
            sock.sendall((s + "\r\n").encode("ascii", errors="ignore"))

        # banner + login
        buf = wait_for(["username", "login", "password", "#", ">"], max_wait=timeout)
        print(f"[CLI] telnet banner: {buf[-120:]!r}")
        low = buf.lower()
        if "password" in low and "username" not in low and "login" not in low:
            send_line(password)
        elif "#" in buf[-3:] or ">" in buf[-3:]:
            pass
        else:
            send_line(user)
            buf = wait_for(["password", "#", ">"], max_wait=timeout)
            if "password" in buf.lower():
                send_line(password)
                buf = wait_for(["#", ">"], max_wait=timeout)

        # enable
        send_line("enable")
        buf = wait_for(["password", "#", ">"], max_wait=5)
        if "password" in buf.lower():
            send_line(password)
            wait_for(["#", ">"], max_wait=timeout)

        send_line("terminal length 0")
        time.sleep(0.3)
        recv_some(0.5)

        out_all = []
        for cmd in commands:
            send_line(cmd)
            time.sleep(0.4)
            chunk = ""
            endt = time.time() + timeout
            while time.time() < endt:
                piece = recv_some(0.6)
                if not piece:
                    if chunk.rstrip().endswith(("#", ">")) and "\n" in chunk:
                        if "--More--" not in chunk[-100:] and "---- More" not in chunk[-100:]:
                            break
                    continue
                chunk += piece
                # pagination
                while "--More--" in chunk or "---- More" in chunk:
                    sock.sendall(b" ")
                    time.sleep(0.35)
                    chunk += recv_some(0.8)
                if chunk.rstrip().endswith(("#", ">")) and cmd.split()[0][:2].lower() in chunk.lower() or chunk.rstrip().endswith(("#", ">")):
                    # got prompt back
                    if "\n" in chunk:
                        break
            out_all.append(chunk)
        return "\n".join(out_all)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def fetch_hsairpo_cli(
    host: str,
    username: str,
    password: str,
    *,
    protocol: str = "telnet",
    port: int = 22,
    pons: Optional[List[int]] = None,
    enable_password: str = "",
    olt_id: str = "",
    olt_name: str = "",
) -> List[OnuInfo]:
    """
    Ambil semua ONT optical-info per PON via CLI.
    protocol: ssh | telnet
    """
    pons = pons or [1, 2, 3, 4]
    protocol = (protocol or "ssh").lower().strip()
    if protocol == "telnet" and port == 22:
        port = 23
    if protocol == "ssh" and port == 23:
        port = 22

    cmds = ["terminal length 0"]
    # UTAMA: info (ada Desc + status), lalu optical (Rx/Tx)
    for p in pons:
        cmds.append(f"show ont info pon{p} all")
    for p in pons:
        cmds.append(f"show ont optical-info pon{p} all")

    print(f"[CLI] HS-EPT1004 {protocol}://{host}:{port} user={username} pons={pons}")
    t0 = time.time()
    raw = ""
    if protocol == "telnet":
        try:
            raw = _telnet_run(host, username, password, cmds, port=port or 23)
        except Exception as e:
            print(f"[CLI] Telnet gagal: {e}")
            raise
    else:
        try:
            raw = _ssh_run(host, username, password, cmds, port=port or 22)
        except Exception as e:
            print(f"[CLI] SSH gagal: {e}")
            print("[CLI] Coba fallback Telnet port 23...")
            try:
                raw = _telnet_run(host, username, password, cmds, port=23)
                print("[CLI] Fallback Telnet berhasil")
            except Exception as e2:
                raise RuntimeError(
                    f"SSH gagal ({e}). Telnet juga gagal ({e2}). "
                    "Set Protocol=Telnet, Port=23 di Settings."
                ) from e2
    print(f"[CLI] raw output {len(raw)} chars in {time.time()-t0:.1f}s")

    # 1) Build ONT dari show ont info (Desc = name)
    info_map = parse_ont_info_table(raw)
    print(f"[CLI] info table: {len(info_map)} rows")

    # 2) Optical Rx/Tx by (pon, onu_id)
    optical_by_key = {}
    for p in pons:
        part = parse_optical_info(raw, pon=p, olt_id=olt_id, olt_name=olt_name)
        for o in part:
            optical_by_key[(o.pon, o.onu_id)] = o
            # also by serial
            if o.serial:
                optical_by_key[("mac", o.serial)] = o
    print(f"[CLI] optical keys: {len(optical_by_key)}")

    uniq: List[OnuInfo] = []
    seen = set()

    if info_map:
        for (pon, onu_id), v in sorted(info_map.items()):
            key = (pon, onu_id)
            if key in seen:
                continue
            seen.add(key)
            opt = optical_by_key.get(key) or optical_by_key.get(("mac", v.get("serial") or ""))
            rx = opt.rx_power if opt else None
            tx = opt.tx_power if opt else None
            # Desc → Name
            name = (v.get("name") or v.get("description") or "").strip()
            if not name or name in ("-",):
                name = (v.get("mac") or "").upper()
            status = v.get("status") or "Unknown"
            if rx is not None and rx < -35:
                status = "Offline"
            uniq.append(OnuInfo(
                board=1,
                pon=pon,
                onu_id=onu_id,
                name=name,
                description=v.get("description") or name,
                serial=v.get("serial") or (opt.serial if opt else ""),
                status=status,
                status_code=1 if status == "Online" else 0,
                rx_power=rx,
                tx_power=tx,
                raw_index=f"cli-{pon}-{onu_id}",
                olt_id=olt_id,
                olt_name=olt_name,
            ))
    else:
        # fallback optical only
        for o in optical_by_key.values():
            if isinstance(o, OnuInfo):
                k = (o.pon, o.onu_id)
                if k in seen:
                    continue
                seen.add(k)
                if not o.name:
                    o.name = (o.serial or "").upper()
                uniq.append(o)

    print(f"[CLI] total {len(uniq)} ONT dari HS-EPT1004 (name dari Desc)")
    return uniq
