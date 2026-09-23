#!/usr/bin/env python3
"""
Contoh penerima telemetry sederhana (jalan di server admin).

  pip install flask
  python tools/telemetry_collector.py

Simpan ke data/telemetry_inbox.jsonl — satu baris JSON per ping.
Dashboard kasar: hitung install_id unik 7/30 hari.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)
INBOX = Path(__file__).resolve().parent.parent / "data" / "telemetry_inbox.jsonl"
INBOX.parent.mkdir(parents=True, exist_ok=True)


@app.post("/v1/ping")
def ping():
    data = request.get_json(silent=True) or {}
    if data.get("app") != "olt-monitor":
        return jsonify({"ok": False, "error": "unknown app"}), 400
    row = {
        "recv_at": datetime.utcnow().isoformat() + "Z",
        "remote": request.headers.get("X-Forwarded-For") or request.remote_addr,
        "body": data,
    }
    with INBOX.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return jsonify({"ok": True})


@app.get("/v1/stats")
def stats():
    """Agregat kasar: unik install_id dalam N hari."""
    days = int(request.args.get("days") or 30)
    cutoff = datetime.utcnow() - timedelta(days=days)
    seen = {}
    if INBOX.exists():
        for line in INBOX.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                row = json.loads(line)
                body = row.get("body") or {}
                iid = body.get("install_id") or body.get("hwid")
                ts = row.get("recv_at") or ""
                dt = datetime.fromisoformat(ts.replace("Z", ""))
                if dt < cutoff or not iid:
                    continue
                prev = seen.get(iid)
                if not prev or ts > prev["last"]:
                    seen[iid] = {
                        "last": ts,
                        "version": body.get("version"),
                        "mode": body.get("license_mode"),
                        "olt_count": body.get("olt_count"),
                    }
            except Exception:
                continue
    return jsonify({
        "days": days,
        "active_installs": len(seen),
        "installs": seen,
    })


if __name__ == "__main__":
    print("Telemetry collector on :5055  POST /v1/ping  GET /v1/stats")
    app.run(host="0.0.0.0", port=5055, debug=False, threaded=True)
