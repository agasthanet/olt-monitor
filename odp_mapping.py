"""
ODP Mapping helper
- serial -> odp  (odp_mapping.csv)
- name   -> odp  (odp_mapping_by_name.csv)  [dari Excel client]
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import config


def load_odp_mapping(filepath: str = None) -> Dict[str, str]:
    """Load mapping serial -> odp name."""
    filepath = filepath or config.ODP_MAPPING_FILE
    path = Path(filepath)

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".json":
            path.write_text("{}", encoding="utf-8")
        else:
            path.write_text("serial,odp\n", encoding="utf-8")
        return {}

    mapping: Dict[str, str] = {}

    try:
        if path.suffix.lower() == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    mapping = {str(k).strip().upper(): str(v).strip() for k, v in data.items()}
        else:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    serial = (
                        row.get("serial")
                        or row.get("Serial")
                        or row.get("sn")
                        or row.get("SN")
                        or row.get("serial_number")
                        or ""
                    ).strip().upper()
                    odp = (
                        row.get("odp")
                        or row.get("ODP")
                        or row.get("odp_name")
                        or row.get("nama_odp")
                        or ""
                    ).strip()
                    if serial and odp:
                        mapping[serial] = odp
    except Exception as e:
        print(f"[ODP] Gagal load mapping serial: {e}")

    return mapping


def load_name_mapping(filepath: str = None) -> List[Tuple[str, str]]:
    """
    Load list of (name_lower, odp) sorted by name length desc
    supaya match nama panjang lebih dulu.
    """
    filepath = filepath or getattr(config, "ODP_NAME_MAPPING_FILE", "data/odp_mapping_by_name.csv")
    path = Path(filepath)
    if not path.exists():
        return []

    pairs: List[Tuple[str, str]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or row.get("client") or row.get("CLIENT") or "").strip()
                odp = (row.get("odp") or row.get("ODP") or "").strip()
                if name and odp:
                    pairs.append((name.lower(), odp))
        pairs.sort(key=lambda x: len(x[0]), reverse=True)
    except Exception as e:
        print(f"[ODP] Gagal load name mapping: {e}")
    return pairs


def save_odp_mapping(mapping: Dict[str, str], filepath: str = None) -> bool:
    filepath = filepath or config.ODP_MAPPING_FILE
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if path.suffix.lower() == ".json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(mapping, f, indent=2, ensure_ascii=False)
        else:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["serial", "odp"])
                for serial, odp in sorted(mapping.items()):
                    writer.writerow([serial, odp])
        return True
    except Exception as e:
        print(f"[ODP] Gagal save: {e}")
        return False


def _match_name(text: str, name_pairs: List[Tuple[str, str]]) -> str | None:
    if not text or not name_pairs:
        return None
    t = text.lower()
    # exact / contains
    for name, odp in name_pairs:
        if len(name) < 3:
            continue
        if name in t or t in name:
            return odp
    return None


def apply_odp_to_onts(onts: list, mapping: Dict[str, str] = None) -> list:
    """Terapkan mapping ODP ke list OnuInfo (serial dulu, lalu nama)."""
    if mapping is None:
        mapping = load_odp_mapping()
    name_pairs = load_name_mapping()

    matched_serial = 0
    matched_name = 0

    for onu in onts:
        serial_key = (onu.serial or "").strip().upper()
        if serial_key and serial_key in mapping:
            onu.odp = mapping[serial_key]
            matched_serial += 1
            continue

        # match by name / description
        text = f"{onu.name or ''} {onu.description or ''}"
        odp = _match_name(text, name_pairs)
        if odp:
            onu.odp = odp
            matched_name += 1
            continue

        # parse ODP from description text
        m = re.search(r"ODP[-_\s]?([A-Z0-9\-]+)", text.upper())
        if m:
            onu.odp = f"ODP-{m.group(1)}"
        elif not onu.odp or onu.odp == "Belum di-mapping":
            onu.odp = "Belum di-mapping"

    print(f"[ODP] Match serial={matched_serial}, name={matched_name}, total_ont={len(onts)}")
    return onts
