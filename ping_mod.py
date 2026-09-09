"""Ping OLT hosts — status + history untuk grafik."""
from __future__ import annotations

import json
import platform
import re
import subprocess
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, List, Optional

_DATA = Path(__file__).resolve().parent / "data"
_HISTORY_FILE = _DATA / "ping_history.json"
_LOCK = threading.Lock()

# olt_id -> deque of {ts, ms, ok}
_HISTORY: Dict[str, Deque[dict]] = defaultdict(lambda: deque(maxlen=120))
# olt_id -> last result
_LAST: Dict[str, dict] = {}

_MAX_POINTS = 120  # ~1 jam jika tiap 30 dtk


def _load():
    global _HISTORY, _LAST
    try:
        if not _HISTORY_FILE.exists():
            return
        data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        for oid, points in (data.get("history") or {}).items():
            dq = deque(maxlen=_MAX_POINTS)
            for p in points[-_MAX_POINTS:]:
                dq.append(p)
            _HISTORY[oid] = dq
        _LAST.update(data.get("last") or {})
    except Exception as e:
        print(f"[PING] load error: {e}")


def _save():
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        payload = {
            "history": {k: list(v) for k, v in _HISTORY.items()},
            "last": _LAST,
        }
        _HISTORY_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as e:
        print(f"[PING] save error: {e}")


_load()


def ping_host(ip: str, count: int = 3, timeout_sec: int = 2) -> dict:
    """
    Return {ok, ms, loss, raw_error}.
    ms = average RTT, None if all failed.
    """
    ip = (ip or "").strip()
    if not ip:
        return {"ok": False, "ms": None, "loss": 100, "error": "no ip"}

    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout_sec * 1000), ip]
    else:
        # Linux: -c count, -W timeout per probe (seconds)
        cmd = ["ping", "-c", str(count), "-W", str(timeout_sec), ip]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec * count + 5,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except Exception as e:
        return {"ok": False, "ms": None, "loss": 100, "error": str(e)}

    # Parse avg latency
    ms = None
    # Linux: rtt min/avg/max/mdev = 1.2/3.4/5.6/0.1 ms
    m = re.search(r"=\s*[\d.]+/([\d.]+)/", out)
    if not m:
        # Windows: Average = 12ms
        m = re.search(r"Average\s*=\s*([\d.]+)\s*ms", out, re.I)
    if not m:
        # time=12.3 ms individual
        times = re.findall(r"time[=<]\s*([\d.]+)\s*ms", out, re.I)
        if times:
            vals = [float(x) for x in times]
            ms = sum(vals) / len(vals)
    else:
        try:
            ms = float(m.group(1))
        except ValueError:
            ms = None

    # loss
    loss = 100
    mloss = re.search(r"(\d+)%\s*(packet\s*)?loss", out, re.I)
    if mloss:
        loss = int(mloss.group(1))
    elif ms is not None:
        loss = 0

    ok = ms is not None and loss < 100
    return {"ok": ok, "ms": round(ms, 1) if ms is not None else None, "loss": loss, "error": "" if ok else "timeout/unreachable"}


def record_ping(olt_id: str, ip: str) -> dict:
    result = ping_host(ip)
    point = {
        "ts": int(time.time()),
        "ms": result.get("ms"),
        "ok": bool(result.get("ok")),
        "loss": result.get("loss", 100),
    }
    with _LOCK:
        _HISTORY[olt_id].append(point)
        _LAST[olt_id] = {
            **point,
            "ip": ip,
            "error": result.get("error") or "",
        }
        _save()
    return _LAST[olt_id]


def get_last(olt_id: str) -> Optional[dict]:
    return _LAST.get(olt_id)


def get_history(olt_id: str, limit: int = 60) -> List[dict]:
    with _LOCK:
        pts = list(_HISTORY.get(olt_id) or [])
    return pts[-limit:]


def get_all_last() -> Dict[str, dict]:
    return dict(_LAST)


def ping_all_olts(olts: list) -> dict:
    results = {}
    for o in olts or []:
        if not o:
            continue
        oid = str(o.get("id") or "")
        ip = o.get("ip") or ""
        if not oid or not ip:
            continue
        try:
            results[oid] = record_ping(oid, ip)
            # log hanya jika DOWN (jangan spam terminal tiap 5 detik)
            r = results[oid]
            if not r.get("ok"):
                print(f"[PING] DOWN {oid} {ip}: {r.get('error') or 'timeout'}")
        except Exception as e:
            print(f"[PING] {oid} error: {e}")
    return results
