#!/usr/bin/env bash
# Update OLT MONITOR dari GitHub — data/ dan .env tidak di-overwrite
# Repo default: https://github.com/agasthanet/olt-monitor.git

set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

REPO_URL="${1:-https://github.com/agasthanet/olt-monitor.git}"
BRANCH="${2:-main}"

echo "=== OLT MONITOR — update dari Git ==="
echo "Dir   : $APP_DIR"
echo "Repo  : $REPO_URL"
echo "Branch: $BRANCH"

# Backup data
BACKUP=".backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP"
for k in data .env; do
  if [ -e "$k" ]; then
    cp -a "$k" "$BACKUP/"
    echo "[backup] $k -> $BACKUP/"
  fi
done

if [ -d .git ]; then
  echo "[git] repo sudah ada, pull..."
  git remote set-url origin "$REPO_URL" 2>/dev/null || git remote add origin "$REPO_URL"
  git fetch origin
  # jangan biarkan data lokal tertimpa
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" "origin/$BRANCH"
  git pull --rebase --autostash origin "$BRANCH" || git pull origin "$BRANCH"
else
  echo "[git] init + clone sparse (kode saja, jaga data lokal)..."
  # jika folder sudah berisi app tanpa .git: init dan fetch
  git init
  git remote add origin "$REPO_URL"
  git fetch origin
  # stash local untracked data before reset
  git checkout -f "origin/$BRANCH" 2>/dev/null || git checkout -f main 2>/dev/null || true
  git branch -M "$BRANCH"
  git reset --hard "origin/$BRANCH"
fi

# Restore data jika terhapus/tertimpa
if [ -d "$BACKUP/data" ]; then
  mkdir -p data
  cp -an "$BACKUP/data/." data/ 2>/dev/null || true
  # prioritaskan file data lokal yang sudah ada isinya
  for f in olts.json license.json onts_cache.json status_history.json ping_history.json odp_mapping.csv odp_mapping_by_name.csv; do
    if [ -f "$BACKUP/data/$f" ]; then
      cp -a "$BACKUP/data/$f" "data/$f"
      echo "[restore] data/$f"
    fi
  done
fi
if [ -f "$BACKUP/.env" ]; then
  cp -a "$BACKUP/.env" .env
  echo "[restore] .env"
fi

echo ""
echo "Versi sekarang:"
cat VERSION 2>/dev/null || echo "(tidak ada file VERSION)"
echo ""
echo "Selesai. Backup: $BACKUP"
echo "Jalankan: python3 app.py"
echo "Opsional: pip install -r requirements.txt"
