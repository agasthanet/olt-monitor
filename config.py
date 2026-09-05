import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

OLT_IP = os.getenv("OLT_IP", "192.168.1.1")
SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "public")
SNMP_PORT = int(os.getenv("SNMP_PORT", "161"))
SNMP_TIMEOUT = int(os.getenv("SNMP_TIMEOUT", "10"))
SNMP_RETRIES = int(os.getenv("SNMP_RETRIES", "2"))
BOARDS = [int(x) for x in os.getenv("BOARDS", "1,2").split(",") if x.strip()]
MAX_PON = int(os.getenv("MAX_PON", "16"))
MAX_ONU = int(os.getenv("MAX_ONU", "128"))
FIRMWARE_MODE = os.getenv("FIRMWARE_MODE", "auto")

RX_GOOD = float(os.getenv("RX_GOOD", "-25.0"))
RX_WARNING = float(os.getenv("RX_WARNING", "-28.0"))

ODP_MAPPING_FILE = os.getenv("ODP_MAPPING_FILE", "data/odp_mapping.csv")
ODP_NAME_MAPPING_FILE = os.getenv("ODP_NAME_MAPPING_FILE", "data/odp_mapping_by_name.csv")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes")
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "300"))
AUTO_REFRESH_SECONDS = int(os.getenv("AUTO_REFRESH_SECONDS", "300"))
# Background service: refresh SEMUA OLT tiap N detik (default 30 menit)
BACKGROUND_REFRESH_SECONDS = int(os.getenv("BACKGROUND_REFRESH_SECONDS", "1800"))
BACKGROUND_REFRESH_ENABLED = os.getenv("BACKGROUND_REFRESH_ENABLED", "true").lower() in ("1", "true", "yes")


def _default_olts():
    p = Path(__file__).resolve().parent / "data" / "olts.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data  # boleh kosong []
        except Exception as e:
            print(f"[CONFIG] olts.json error: {e}")

    raw = os.getenv("OLTS_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception as e:
            print(f"[CONFIG] OLTS_JSON error: {e}")

    return []


OLTS = _default_olts()


def get_olt(olt_id: str):
    for o in OLTS:
        if str(o.get("id")) == str(olt_id):
            return o
    return OLTS[0] if OLTS else None
