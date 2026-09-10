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

# Resolve absolute path + python for systemd
APP_DIR="$(cd "$DIR" && pwd)"
PY="$APP_DIR/venv/bin/python"
# User yang menjalankan install (hindari root di service jika mungkin)
SVC_USER="${SUDO_USER:-${USER:-root}}"
if [ "$SVC_USER" = "root" ] && [ -n "${SUDO_USER:-}" ]; then
  SVC_USER="$SUDO_USER"
fi

echo ""
echo "=== Selesai install paket ==="
echo "Folder : $APP_DIR"
echo ""

# ---- Auto-start systemd (opsional) ----
install_systemd() {
  local unit="/etc/systemd/system/olt-monitor.service"
  echo "Memasang systemd service (user=$SVC_USER) ..."
  sudo tee "$unit" > /dev/null << EOF
[Unit]
Description=OLT MONITOR
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
WorkingDirectory=$APP_DIR
ExecStart=$PY app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable olt-monitor
  sudo systemctl restart olt-monitor
  echo ""
  echo "Service aktif. Cek status:"
  echo "  sudo systemctl status olt-monitor"
  echo "Log:"
  echo "  sudo journalctl -u olt-monitor -f"
  echo "Stop / disable:"
  echo "  sudo systemctl stop olt-monitor"
  echo "  sudo systemctl disable olt-monitor"
}

if [ "${INSTALL_SYSTEMD:-}" = "1" ] || [ "${INSTALL_SYSTEMD:-}" = "yes" ]; then
  install_systemd
else
  echo "Auto-start systemd? [y/N]"
  read -r ans || ans=""
  case "${ans:-}" in
    y|Y|yes|YES)
      install_systemd
      ;;
    *)
      echo "Lewati systemd. Jalankan manual:"
      echo "  cd $APP_DIR"
      echo "  source venv/bin/activate"
      echo "  python app.py"
      echo ""
      echo "Atau pasang service nanti:"
      echo "  INSTALL_SYSTEMD=1 ./install.sh"
      ;;
  esac
fi

echo ""
echo "Buka http://IP-SERVER:5000"
