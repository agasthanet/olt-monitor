#!/usr/bin/env python3
"""
OLT MONITOR - Web Dashboard sederhana
Dual firmware support + ODP mapping eksternal
"""

from __future__ import annotations

import csv
import io
import time
from collections import defaultdict
from datetime import datetime
from typing import List

import json
import threading
from pathlib import Path as _Path

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

import config
from odp_mapping import apply_odp_to_onts, load_odp_mapping, save_odp_mapping
from snmp_zte import OnuInfo, fetch_all_onts
from license_mod import (
    get_hwid,
    get_mode,
    max_olts,
    can_add_olt,
    activate as license_activate,
    deactivate as license_deactivate,
    load_license,
)

app = Flask(__name__)
app.secret_key = "zte-c320-monitor-secret-change-me"

# Cache memory + file (supaya filter tetap cepat walau Flask reload)
_cache = {"onts": [], "last_update": None, "firmware": None}
_CACHE_FILE = _Path(__file__).resolve().parent / "data" / "onts_cache.json"


def _onts_to_jsonable(onts):
    return [o.to_dict() if hasattr(o, "to_dict") else o for o in onts]


def _onts_from_jsonable(rows):
    out = []
    for r in rows:
        out.append(OnuInfo(
            board=int(r.get("board") or 0),
            pon=int(r.get("pon") or 0),
            onu_id=int(r.get("onu_id") or 0),
            name=r.get("name") or "",
            description=r.get("description") or "",
            serial=r.get("serial") or "",
            onu_type=r.get("onu_type") or "",
            status=r.get("status") or "Unknown",
            status_code=int(r.get("status_code") if r.get("status_code") is not None else -1),
            rx_power=r.get("rx_power"),
            tx_power=r.get("tx_power"),
            distance=r.get("distance"),
            odp=r.get("odp") or "Belum di-mapping",
            olt_id=r.get("olt_id") or "",
            olt_name=r.get("olt_name") or "",
            last_downtime=r.get("last_downtime") or "",
            last_online=r.get("last_online") or "",
        ))
    return out


def _load_file_cache():
    try:
        if not _CACHE_FILE.exists():
            return
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        _cache["last_update"] = data.get("last_update")
        _cache["onts"] = _onts_from_jsonable(data.get("onts") or [])
        print(f"[CACHE] Load file: {len(_cache['onts'])} ONT, ts={_cache['last_update']}")
    except Exception as e:
        print(f"[CACHE] load error: {e}")


def _save_file_cache():
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_update": _cache["last_update"],
            "onts": _onts_to_jsonable(_cache["onts"]),
        }
        _CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[CACHE] save error: {e}")


_load_file_cache()

_STATUS_HIST_FILE = _Path(__file__).resolve().parent / "data" / "status_history.json"


def _load_status_history() -> dict:
    try:
        if _STATUS_HIST_FILE.exists():
            return json.loads(_STATUS_HIST_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[HIST] load error: {e}")
    return {}


def _save_status_history(hist: dict) -> None:
    try:
        _STATUS_HIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATUS_HIST_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[HIST] save error: {e}")


def _is_online_status(status: str) -> bool:
    s = (status or "").lower()
    return s in ("online", "working")


def apply_downtime_tracking(onts: List[OnuInfo]) -> List[OnuInfo]:
    """
    Track last_online / last_downtime berdasarkan perubahan status antar refresh.
    Key = serial (fallback location).
    """
    hist = _load_status_history()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    offline_like = {"offline", "los", "dyinggasp", "authfailed", "poweroff", "unknown"}

    for o in onts:
        key = (o.serial or "").strip().upper() or f"{o.olt_id}:{o.board}/{o.pon}:{o.onu_id}"
        prev = hist.get(key) or {}
        prev_status = prev.get("status") or ""
        cur_online = _is_online_status(o.status)
        prev_online = _is_online_status(prev_status)

        last_online = prev.get("last_online") or ""
        last_downtime = prev.get("last_downtime") or ""

        if cur_online:
            last_online = now_str
            # tetap simpan last_downtime lama (riwayat)
        else:
            # baru offline (sebelumnya online) → catat downtime sekarang
            if prev_online or not last_downtime:
                if prev_online:
                    last_downtime = now_str
                elif not last_downtime:
                    # pertama kali lihat offline
                    last_downtime = now_str

        o.last_online = last_online
        o.last_downtime = last_downtime if not cur_online else (last_downtime or "")

        hist[key] = {
            "status": o.status,
            "last_online": o.last_online,
            "last_downtime": o.last_downtime,
            "name": o.name,
            "updated": now_str,
        }

    _save_status_history(hist)
    return onts




def get_onts(force: bool = False, olt_id: str = None, filter_pon: str = None) -> List[OnuInfo]:
    """
    Ambil ONT dari cache / OLT.
    - force=False: hanya cache (cepat untuk filter)
    - force=True + olt_id: refresh HANYA OLT itu
    - filter_pon: "board/pon" → hasil difilter ke PON itu
    """
    now = time.time()
    cache_ttl = getattr(config, "CACHE_SECONDS", 300)

    if not _cache["onts"] and not force:
        _load_file_cache()

    # Tanpa force: selalu dari cache (filter cepat)
    if not force:
        onts = list(_cache["onts"] or [])
        # lengkapi downtime dari history file
        hist = _load_status_history()
        for o in onts:
            key = (o.serial or "").strip().upper() or f"{o.olt_id}:{o.board}/{o.pon}:{o.onu_id}"
            h = hist.get(key) or {}
            if not o.last_downtime:
                o.last_downtime = h.get("last_downtime") or ""
            if not o.last_online:
                o.last_online = h.get("last_online") or ""
        if olt_id:
            onts = [o for o in onts if (o.olt_id or "") == olt_id or not o.olt_id]
        if filter_pon:
            try:
                fb, fp = filter_pon.split("/")
                onts = [o for o in onts if o.board == int(fb) and o.pon == int(fp)]
            except Exception:
                pass
        return onts

    # force=True → walk SNMP hanya OLT yang diminta
    targets = config.OLTS
    if olt_id:
        o = config.get_olt(olt_id)
        targets = [o] if o else targets

    fetched_all = []
    for olt in targets:
        if not olt:
            continue
        oid = str(olt.get("id", "olt1"))
        print(f"[APP] Refresh OLT {oid} ({olt.get('ip')}) pon={filter_pon or 'ALL'}")
        t0 = time.time()
        vendor = (olt.get("vendor") or "zte").lower().strip()
        if vendor in ("hsairpo-cli", "airpo-cli", "hs-ept", "hs-ept1004", "cli"):
            from cli_hsairpo import fetch_hsairpo_cli
            pons = list(range(1, 5))
            if filter_pon:
                try:
                    _b, _p = filter_pon.split("/")
                    pons = [int(_p)]
                except Exception:
                    pass
            proto = (olt.get("protocol") or "telnet").lower().strip()
            # JANGAN pakai port SNMP (161) untuk CLI
            raw_cli_port = olt.get("cli_port")
            try:
                cli_port = int(raw_cli_port) if raw_cli_port not in (None, "", 0, "0") else 0
            except Exception:
                cli_port = 0
            if not cli_port or cli_port == 161:
                cli_port = 23 if proto == "telnet" else 22
            print(f"[APP] CLI mode proto={proto} port={cli_port} user={olt.get('username') or 'admin'}")
            try:
                part = fetch_hsairpo_cli(
                    host=olt.get("ip"),
                    username=olt.get("username") or olt.get("user") or "admin",
                    password=olt.get("password") or olt.get("cli_password") or "",
                    protocol=proto,
                    port=cli_port,
                    pons=pons,
                    olt_id=oid,
                    olt_name=olt.get("name") or oid,
                )
            except Exception as e:
                print(f"[APP] CLI error: {e}")
                flash(f"CLI gagal ({oid}): {e}", "danger")
                part = []
        else:
            part = fetch_all_onts(
                host=olt.get("ip"),
                community=olt.get("community", config.SNMP_COMMUNITY),
                boards=olt.get("boards") or config.BOARDS,
                firmware=olt.get("firmware") or config.FIRMWARE_MODE,
                port=int(olt.get("port") or config.SNMP_PORT),
                filter_pon=filter_pon,
                olt_id=oid,
                olt_name=olt.get("name") or oid,
                vendor=vendor,
            )
        part = apply_odp_to_onts(part, load_odp_mapping())
        part = apply_downtime_tracking(part)
        print(f"[APP] OLT {oid}: {len(part)} ONT dalam {time.time()-t0:.1f}s")
        fetched_all.extend(part)

    # Merge ke cache: ganti data OLT yang di-refresh, pertahankan OLT lain
    refreshed_ids = {str(o.get("id")) for o in targets if o}
    old = [o for o in (_cache["onts"] or []) if (o.olt_id or "") not in refreshed_ids]
    # Jika filter_pon: hanya replace ONT di PON itu untuk OLT tsb
    if filter_pon and fetched_all is not None:
        try:
            fb, fp = filter_pon.split("/")
            fb, fp = int(fb), int(fp)
            kept = []
            for o in (_cache["onts"] or []):
                if (o.olt_id or "") in refreshed_ids and o.board == fb and o.pon == fp:
                    continue  # diganti
                kept.append(o)
            _cache["onts"] = kept + fetched_all
        except Exception:
            _cache["onts"] = old + fetched_all
    else:
        _cache["onts"] = old + fetched_all

    _cache["last_update"] = time.time()
    _save_file_cache()

    onts = list(_cache["onts"])
    if olt_id:
        onts = [o for o in onts if (o.olt_id or "") == olt_id or not o.olt_id]
    if filter_pon:
        try:
            fb, fp = filter_pon.split("/")
            onts = [o for o in onts if o.board == int(fb) and o.pon == int(fp)]
        except Exception:
            pass
    return onts


def signal_class(rx: float | None) -> str:
    if rx is None:
        return "secondary"
    if rx >= config.RX_GOOD:
        return "success"
    if rx >= config.RX_WARNING:
        return "warning"
    return "danger"


def status_badge(status: str) -> str:
    s = (status or "").lower()
    if s in ("online", "working"):
        return "success"
    if s in ("los", "dyinggasp", "offline"):
        return "danger"
    if s in ("logging", "syncmib"):
        return "warning"
    return "secondary"


@app.route("/")
def index():
    view = request.args.get("view", "pon")  # pon | odp
    filter_olt = request.args.get("olt") or (config.OLTS[0]["id"] if config.OLTS else None)
    filter_pon = request.args.get("pon") or None
    filter_odp = request.args.get("odp")
    search = request.args.get("q", "").strip().lower()
    # Baca cache saja (cepat)
    onts = get_onts(force=False, olt_id=filter_olt, filter_pon=None)

    # Filter
    filtered = onts
    if filter_pon:
        try:
            b, p = filter_pon.split("/")
            filtered = [o for o in filtered if o.board == int(b) and o.pon == int(p)]
        except Exception:
            pass
    if filter_odp:
        filtered = [o for o in filtered if o.odp == filter_odp]
    if search:
        filtered = [
            o
            for o in filtered
            if search in (o.name or "").lower()
            or search in (o.serial or "").lower()
            or search in (o.odp or "").lower()
            or search in (o.description or "").lower()
        ]

    # Group by PON
    by_pon = defaultdict(list)
    for o in filtered:
        key = f"{o.board}/{o.pon}"
        by_pon[key].append(o)

    # Group by ODP
    by_odp = defaultdict(list)
    for o in filtered:
        by_odp[o.odp or "Belum di-mapping"].append(o)

    # Stats
    total = len(onts)
    online = sum(1 for o in onts if (o.status or "").lower() in ("online", "working"))
    offline = total - online
    weak = sum(
        1
        for o in onts
        if o.rx_power is not None and o.rx_power < config.RX_WARNING
    )

    # Daftar PON & ODP untuk filter
    all_pons = sorted({f"{o.board}/{o.pon}" for o in onts})
    all_odps = sorted({o.odp or "Belum di-mapping" for o in onts})

    last_update = (
        datetime.fromtimestamp(_cache["last_update"]).strftime("%H:%M:%S")
        if _cache["last_update"]
        else "-"
    )

    cache_age = int(time.time() - _cache["last_update"]) if _cache["last_update"] else None
    return render_template(
        "index.html",
        onts=filtered,
        by_pon=dict(sorted(by_pon.items())),
        by_odp=dict(sorted(by_odp.items())),
        view=view,
        total=total,
        online=online,
        offline=offline,
        weak=weak,
        all_pons=all_pons,
        all_odps=all_odps,
        filter_pon=filter_pon,
        filter_odp=filter_odp,
        search=search,
        last_update=last_update,
        filter_olt=filter_olt,
        olts_list=config.OLTS,
        cache_age=cache_age,
        cache_ttl=getattr(config, "CACHE_SECONDS", 300),
        auto_refresh=getattr(config, "AUTO_REFRESH_SECONDS", 300),
        demo=config.DEMO_MODE,
        signal_class=signal_class,
        status_badge=status_badge,
        rx_good=config.RX_GOOD,
        rx_warning=config.RX_WARNING,
    )


@app.route("/api/onts")
def api_onts():
    force = request.args.get("refresh") == "1"
    onts = get_onts(force=force)
    return jsonify(
        {
            "count": len(onts),
            "last_update": _cache["last_update"],
            "data": [o.to_dict() for o in onts],
        }
    )


@app.route("/refresh")
def refresh():
    """Refresh HANYA OLT (dan opsional PON) yang sedang dilihat."""
    filter_olt = request.args.get("olt") or (config.OLTS[0]["id"] if config.OLTS else None)
    filter_pon = request.args.get("pon") or None
    t0 = time.time()
    onts = get_onts(force=True, olt_id=filter_olt, filter_pon=filter_pon)
    elapsed = time.time() - t0
    scope = f"OLT={filter_olt}" + (f" PON={filter_pon}" if filter_pon else " (semua PON)")
    flash(f"Refresh {scope}: {len(onts)} ONT dalam {elapsed:.1f}s", "success")
    args = {k: v for k, v in request.args.items() if k != "refresh"}
    if filter_olt and "olt" not in args:
        args["olt"] = filter_olt
    return redirect(url_for("index", **args))



@app.route("/odp", methods=["GET", "POST"])
def odp_page():
    mapping = load_odp_mapping()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            serial = request.form.get("serial", "").strip().upper()
            odp = request.form.get("odp", "").strip()
            if serial and odp:
                mapping[serial] = odp
                save_odp_mapping(mapping)
                flash(f"Mapping {serial} → {odp} ditambahkan", "success")
            else:
                flash("Serial dan ODP wajib diisi", "danger")
        elif action == "delete":
            serial = request.form.get("serial", "").strip().upper()
            if serial in mapping:
                del mapping[serial]
                save_odp_mapping(mapping)
                flash(f"Mapping {serial} dihapus", "success")
        elif action == "upload":
            f = request.files.get("file")
            if f and f.filename:
                try:
                    content = f.read().decode("utf-8")
                    if f.filename.lower().endswith(".json"):
                        import json
                        data = json.loads(content)
                        for k, v in data.items():
                            mapping[str(k).strip().upper()] = str(v).strip()
                    else:
                        reader = csv.DictReader(io.StringIO(content))
                        for row in reader:
                            serial = (
                                row.get("serial") or row.get("Serial") or row.get("sn") or ""
                            ).strip().upper()
                            odp = (
                                row.get("odp") or row.get("ODP") or row.get("odp_name") or ""
                            ).strip()
                            if serial and odp:
                                mapping[serial] = odp
                    save_odp_mapping(mapping)
                    flash(f"Upload berhasil. Total mapping: {len(mapping)}", "success")
                except Exception as e:
                    flash(f"Gagal parse file: {e}", "danger")
        return redirect(url_for("odp_page"))

    # Hitung berapa ONT yang sudah termapping
    onts = get_onts()
    mapped_count = sum(1 for o in onts if o.serial and o.serial.upper() in mapping)

    return render_template(
        "odp.html",
        mapping=mapping,
        mapped_count=mapped_count,
        total_ont=len(onts),
    )


@app.route("/download-mapping")
def download_mapping():
    mapping = load_odp_mapping()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["serial", "odp"])
    for s, o in sorted(mapping.items()):
        writer.writerow([s, o])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="odp_mapping.csv",
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    import json as _json
    olts_path = _Path(__file__).resolve().parent / "data" / "olts.json"

    def _save_olts(olts):
        olts_path.parent.mkdir(parents=True, exist_ok=True)
        olts_path.write_text(_json.dumps(olts, indent=2, ensure_ascii=False), encoding="utf-8")
        config.OLTS = olts

    def _load_olts():
        return list(config.OLTS or [])

    if request.method == "POST":
        action = request.form.get("action")
        olts = _load_olts()

        if action == "save_olt":
            oid = (request.form.get("id") or "").strip()
            edit_id = (request.form.get("edit_id") or "").strip()
            name = (request.form.get("name") or oid).strip()
            ip = (request.form.get("ip") or "").strip()
            community = (request.form.get("community") or "public").strip()
            port = int(request.form.get("port") or 161)
            boards_raw = request.form.get("boards") or "1,2"
            boards = [int(x) for x in boards_raw.replace(" ", "").split(",") if x]
            firmware = request.form.get("firmware") or "auto"
            vendor = (request.form.get("vendor") or "zte").strip().lower()
            username = (request.form.get("username") or "admin").strip()
            password = (request.form.get("password") or "").strip()
            protocol = (request.form.get("protocol") or "ssh").strip().lower()
            cli_port = int(request.form.get("cli_port") or (23 if protocol == "telnet" else 22))
            if not oid or not ip:
                flash("ID dan IP wajib diisi", "danger")
            else:
                entry = {
                    "id": oid,
                    "name": name,
                    "ip": ip,
                    "community": community,
                    "port": port,
                    "boards": boards or [1, 2],
                    "firmware": firmware,
                    "vendor": vendor,
                    "username": username,
                    "password": password,
                    "protocol": protocol,
                    "cli_port": cli_port,
                }
                # update existing or append
                found = False
                key = edit_id or oid
                for i, o in enumerate(olts):
                    if o.get("id") == key:
                        olts[i] = entry
                        found = True
                        break
                if not found:
                    if any(o.get("id") == oid for o in olts):
                        flash(f"ID {oid} sudah ada", "danger")
                    else:
                        ok, msg = can_add_olt(len(olts))
                        if not ok:
                            flash(msg, "danger")
                        else:
                            olts.append(entry)
                            found = True
                            flash(f"OLT {oid} ditambahkan", "success")
                            _save_olts(olts)
                else:
                    flash(f"OLT {oid} diupdate", "success")
                    _save_olts(olts)
            return redirect(url_for("settings"))

        if action == "activate_license":
            key = (request.form.get("license_key") or "").strip()
            ok, msg = license_activate(key)
            flash(msg, "success" if ok else "danger")
            return redirect(url_for("settings"))

        if action == "deactivate_license":
            license_deactivate()
            flash("Mode kembali ke Trial (max 1 OLT).", "warning")
            return redirect(url_for("settings"))

        if action == "delete_olt":
            oid = (request.form.get("id") or "").strip()
            olts = [o for o in olts if o.get("id") != oid]
            _save_olts(olts)
            flash(f"OLT {oid} dihapus", "success")
            return redirect(url_for("settings"))

        if action == "save_global":
            config.DEMO_MODE = request.form.get("demo_mode") == "on"
            flash("Opsi global disimpan (runtime)", "info")
            return redirect(url_for("settings"))

    edit = None
    edit_id = request.args.get("edit")
    if edit_id:
        edit = config.get_olt(edit_id)

    return render_template(
        "settings.html",
        olts=config.OLTS,
        edit=edit,
        demo=config.DEMO_MODE,
        license_mode=get_mode(),
        license_hwid=get_hwid(),
        license_info=load_license(),
        license_max_olts=max_olts(),
    )



@app.route("/api/set-odp", methods=["POST"])
def api_set_odp():
    """Update mapping ODP by serial (inline edit dari dashboard)."""
    data = request.get_json(silent=True) or request.form
    serial = (data.get("serial") or "").strip().upper()
    odp = (data.get("odp") or "").strip()
    if not serial:
        return jsonify({"ok": False, "error": "serial kosong"}), 400
    if not odp:
        odp = "Belum di-mapping"

    mapping = load_odp_mapping()
    mapping[serial] = odp
    save_odp_mapping(mapping)

    # update cache memory + file
    for o in _cache.get("onts") or []:
        if (o.serial or "").strip().upper() == serial:
            o.odp = odp
    _save_file_cache()

    return jsonify({"ok": True, "serial": serial, "odp": odp})




# ===== Background auto-refresh semua OLT =====
_bg_started = False
_bg_lock = threading.Lock()
_bg_status = {"last_run": None, "last_result": "", "running": False}


def _reload_olts_from_disk():
    """Reload olts.json supaya OLT baru ikut di-refresh tanpa restart."""
    try:
        path = _Path(__file__).resolve().parent / "data" / "olts.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                config.OLTS = data
    except Exception as e:
        print(f"[BG] reload olts error: {e}")


def background_refresh_all():
    """Refresh massal semua OLT yang terdaftar."""
    with _bg_lock:
        if _bg_status.get("running"):
            print("[BG] skip — masih running")
            return
        _bg_status["running"] = True
    try:
        _reload_olts_from_disk()
        olts = list(config.OLTS or [])
        if not olts:
            print("[BG] tidak ada OLT terdaftar")
            _bg_status["last_result"] = "no olt"
            return
        print(f"[BG] mulai refresh {len(olts)} OLT ...")
        total = 0
        for olt in olts:
            if not olt:
                continue
            oid = str(olt.get("id") or "")
            try:
                part = get_onts(force=True, olt_id=oid, filter_pon=None)
                total += len(part or [])
                print(f"[BG] {oid}: {len(part or [])} ONT OK")
            except Exception as e:
                print(f"[BG] {oid} GAGAL: {e}")
        from datetime import datetime as _dt
        _bg_status["last_run"] = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        _bg_status["last_result"] = f"{len(olts)} OLT, {total} ONT"
        print(f"[BG] selesai: {_bg_status['last_result']} @ {_bg_status['last_run']}")
    finally:
        _bg_status["running"] = False


def _bg_loop():
    import time as _time
    interval = int(getattr(config, "BACKGROUND_REFRESH_SECONDS", 1800) or 1800)
    # delay awal biar Flask siap dulu
    _time.sleep(15)
    print(f"[BG] worker aktif, interval={interval}s ({interval/60:.0f} menit)")
    while True:
        try:
            background_refresh_all()
        except Exception as e:
            print(f"[BG] loop error: {e}")
        _time.sleep(max(60, interval))


def start_background_refresh():
    global _bg_started
    if _bg_started:
        return
    if not getattr(config, "BACKGROUND_REFRESH_ENABLED", True):
        print("[BG] disabled via config")
        return
    _bg_started = True
    t = threading.Thread(target=_bg_loop, name="olt-bg-refresh", daemon=True)
    t.start()
    print("[BG] thread started")


# start saat module load (setelah Flask app siap)
try:
    start_background_refresh()
except Exception as e:
    print(f"[BG] start error: {e}")


if __name__ == "__main__":
    print("=" * 50)
    print("  OLT MONITOR")
    print("=" * 50)
    print(f"  OLTs        : {[(o.get('id'), o.get('ip')) for o in config.OLTS]}")
    print(f"  OLT IP      : {config.OLT_IP}")
    print(f"  Community   : {config.SNMP_COMMUNITY}")
    print(f"  Boards      : {config.BOARDS}")
    print(f"  Firmware    : {config.FIRMWARE_MODE}")
    print(f"  Demo Mode   : {config.DEMO_MODE}")
    print(f"  License     : {get_mode().upper()} (max {max_olts()} OLT) HWID={get_hwid()}")
    bg_iv = getattr(config, "BACKGROUND_REFRESH_SECONDS", 1800)
    print(f"  BG Refresh  : tiap {bg_iv}s ({bg_iv/60:.0f} menit) semua OLT")
    print("=" * 50)
    print("  Buka http://127.0.0.1:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
