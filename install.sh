#!/usr/bin/env bash
# Instalasi OLT MONITOR di Linux (Ubuntu/Debian)
set -euo pipefail

REPO="${REPO_URL:-https://github.com/agasthanet/olt-monitor.git}"
DIR="${INSTALL_DIR:-$HOME/olt-monitor}"
BRANCH="${BRANCH:-main}"

echo "=== OLT MONITOR — install Linux ==="
echo "Target: $DIR"
echo "Repo  : $REPO"

if ! command -v python3 >/dev/null; then
  echo "Menginstall python3..."
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-pip python3-venv git
fi
if ! command -v git >/dev/null; then
  sudo apt-get update -y
  sudo apt-get install -y git
fi

if [ -d "$DIR/.git" ]; then
  echo "Folder sudah ada, pull update..."
  cd "$DIR"
  git fetch origin
  git pull --ff-only origin "$BRANCH" || git pull origin "$BRANCH"
else
  if [ -d "$DIR" ] && [ ! -d "$DIR/.git" ]; then
    echo "Folder $DIR ada tanpa git. Backup data lalu clone..."
    BAK="${DIR}_bak_$(date +%Y%m%d%H%M%S)"
    mv "$DIR" "$BAK"
    git clone -b "$BRANCH" "$REPO" "$DIR"
    mkdir -p "$DIR/data"
    if [ -d "$BAK/data" ]; then
      cp -an "$BAK/data/." "$DIR/data/" || true
      echo "Data dipulihkan dari $BAK/data"
    fi
  else
    git clone -b "$BRANCH" "$REPO" "$DIR"
  fi
fi

cd "$DIR"
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt

echo ""
echo "=== Selesai ==="
echo "Jalankan:"
echo "  cd $DIR"
echo "  source venv/bin/activate"
echo "  python app.py"
echo "Lalu buka http://127.0.0.1:5000"
