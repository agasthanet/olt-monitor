#!/usr/bin/env bash
# Update OLT MONITOR — ganti kode saja, data tetap aman
# Usage:
#   ./update.sh /path/to/zte_c320_monitor.zip
# atau extract zip ke folder sementara lalu:
#   ./update.sh --from /path/to/extracted_new_version

set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${APP_DIR}/.backup_$(date +%Y%m%d_%H%M%S)"

echo "=== OLT MONITOR Update ==="
echo "App dir : $APP_DIR"

# folder/file yang TIDAK boleh ditimpa
KEEP=(
  "data"
  ".env"
  "VERSION"
)

# backup data dulu
mkdir -p "$BACKUP_DIR"
for k in "${KEEP[@]}"; do
  if [ -e "$APP_DIR/$k" ]; then
    cp -a "$APP_DIR/$k" "$BACKUP_DIR/"
    echo "[backup] $k"
  fi
done
# backup file runtime di data jika ada di root
for f in olts.json onts_cache.json status_history.json license.json ping_history.json; do
  if [ -f "$APP_DIR/$f" ]; then
    cp -a "$APP_DIR/$f" "$BACKUP_DIR/"
    echo "[backup] $f"
  fi
done

SRC=""
if [ "${1:-}" = "--from" ]; then
  SRC="${2:-}"
elif [ -n "${1:-}" ]; then
  ZIP="$1"
  TMP=$(mktemp -d)
  unzip -q "$ZIP" -d "$TMP"
  # zip biasanya berisi folder zte_c320_monitor/
  if [ -d "$TMP/zte_c320_monitor" ]; then
    SRC="$TMP/zte_c320_monitor"
  else
    SRC="$TMP"
  fi
else
  echo "Usage: $0 /path/to/zte_c320_monitor.zip"
  echo "   or: $0 --from /path/to/new_extracted_folder"
  exit 1
fi

if [ ! -d "$SRC" ]; then
  echo "Source tidak ditemukan: $SRC"
  exit 1
fi

echo "[update] menyalin kode dari $SRC ..."
# salin semua kecuali data & .env
shopt -s dotglob
for item in "$SRC"/*; do
  name=$(basename "$item")
  case "$name" in
    data|.env|.backup_*|venv|__pycache__)
      echo "  skip $name"
      continue
      ;;
  esac
  if [ -d "$item" ]; then
    rm -rf "$APP_DIR/$name"
    cp -a "$item" "$APP_DIR/$name"
  else
    cp -a "$item" "$APP_DIR/$name"
  fi
  echo "  + $name"
done

# pastikan folder data ada; restore jika terhapus
mkdir -p "$APP_DIR/data"
for k in "${KEEP[@]}"; do
  if [ -e "$BACKUP_DIR/$k" ] && [ ! -e "$APP_DIR/$k" ]; then
    cp -a "$BACKUP_DIR/$k" "$APP_DIR/"
    echo "[restore] $k"
  fi
done
# merge: jangan timpa data yang sudah ada dengan kosong dari package
if [ -d "$BACKUP_DIR/data" ]; then
  cp -an "$BACKUP_DIR/data/." "$APP_DIR/data/" 2>/dev/null || true
fi
if [ -f "$BACKUP_DIR/.env" ] && [ ! -f "$APP_DIR/.env" ]; then
  cp -a "$BACKUP_DIR/.env" "$APP_DIR/.env"
fi

echo ""
echo "Selesai. Backup: $BACKUP_DIR"
echo "Jalankan ulang: python3 app.py"
echo "Cek versi: cat VERSION"
