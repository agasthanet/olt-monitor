#!/usr/bin/env bash
# OLT MONITOR — install + auto-start untuk CONTAINER (MikroTik / Docker / LXC)
# Tanpa systemd. Cocok Ubuntu container di RouterOS.
set -euo pipefail

REPO="${REPO_URL:-https://github.com/agasthanet/olt-monitor.git}"
DIR="${INSTALL_DIR:-/root/olt-monitor}"
BRANCH="${BRANCH:-main}"
PORT="${APP_PORT:-5000}"

echo "=============================================="
echo "  OLT MONITOR — install CONTAINER"
echo "  Target : $DIR"
echo "  Repo   : $REPO"
echo "  Port   : $PORT"
echo "=============================================="

export DEBIAN_FRONTEND=noninteractive

# --- paket dasar ---
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv git curl ca-certificates \
    iputils-ping net-tools procps \
    || true
  # snmp client opsional (troubleshooting)
  apt-get install -y --no-install-recommends snmp || true
fi

if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 tidak tersedia"
  exit 1
fi
if ! command -v git >/dev/null; then
  echo "ERROR: git tidak tersedia"
  exit 1
fi

# --- clone / update ---
if [ -d "$DIR/.git" ]; then
  echo ">> Update repo existing..."
  cd "$DIR"
  git fetch origin || true
  git pull --ff-only origin "$BRANCH" 2>/dev/null || git pull origin "$BRANCH" || true
else
  if [ -d "$DIR" ] && [ ! -d "$DIR/.git" ]; then
    BAK="${DIR}_bak_$(date +%Y%m%d%H%M%S)"
    echo ">> Backup folder non-git ke $BAK"
    mv "$DIR" "$BAK"
    git clone -b "$BRANCH" "$REPO" "$DIR"
    mkdir -p "$DIR/data"
    if [ -d "$BAK/data" ]; then
      cp -an "$BAK/data/." "$DIR/data/" || true
      echo ">> Data dipulihkan dari backup"
    fi
  else
    git clone -b "$BRANCH" "$REPO" "$DIR"
  fi
fi

cd "$DIR"
mkdir -p data

# --- venv + pip ---
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt

APP_DIR="$(cd "$DIR" && pwd)"
PY="$APP_DIR/venv/bin/python"
LOG="$APP_DIR/olt-monitor.log"

# --- start script (foreground, cocok jadi CMD container) ---
cat > "$APP_DIR/start.sh" << EOS
#!/usr/bin/env bash
# Entry point OLT MONITOR (container)
cd "$APP_DIR"
export PYTHONUNBUFFERED=1
if [ -f "$APP_DIR/venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$APP_DIR/venv/bin/activate"
fi
exec "$PY" app.py
EOS
chmod +x "$APP_DIR/start.sh"

# --- helper: start background (nohup) ---
cat > "$APP_DIR/run-bg.sh" << EOS
#!/usr/bin/env bash
cd "$APP_DIR"
mkdir -p data
# stop instance lama (jika ada)
if [ -f "$APP_DIR/olt-monitor.pid" ]; then
  old=\$(cat "$APP_DIR/olt-monitor.pid" 2>/dev/null || true)
  if [ -n "\$old" ] && kill -0 "\$old" 2>/dev/null; then
    kill "\$old" 2>/dev/null || true
    sleep 1
  fi
fi
nohup "$PY" app.py >> "$LOG" 2>&1 &
echo \$! > "$APP_DIR/olt-monitor.pid"
echo "OLT MONITOR started PID=\$(cat "$APP_DIR/olt-monitor.pid")"
echo "Log: $LOG"
echo "UI : http://0.0.0.0:$PORT"
EOS
chmod +x "$APP_DIR/run-bg.sh"

cat > "$APP_DIR/stop.sh" << EOS
#!/usr/bin/env bash
if [ -f "$APP_DIR/olt-monitor.pid" ]; then
  pid=\$(cat "$APP_DIR/olt-monitor.pid")
  if kill -0 "\$pid" 2>/dev/null; then
    kill "\$pid" && echo "Stopped PID \$pid"
  else
    echo "Process tidak jalan"
  fi
  rm -f "$APP_DIR/olt-monitor.pid"
else
  pkill -f "$APP_DIR/venv/bin/python app.py" 2>/dev/null && echo "Stopped via pkill" || echo "Tidak ada proses"
fi
EOS
chmod +x "$APP_DIR/stop.sh"

# --- auto-start tanpa systemd ---
# 1) crontab @reboot (jika cron ada)
if command -v crontab >/dev/null 2>&1; then
  (crontab -l 2>/dev/null | grep -v "olt-monitor" || true
   echo "@reboot $APP_DIR/run-bg.sh"
  ) | crontab - 2>/dev/null && echo ">> crontab @reboot dipasang" || echo ">> crontab gagal (abaikan di container tanpa cron)"
fi

# 2) rc.local fallback
if [ -d /etc ]; then
  if [ ! -f /etc/rc.local ]; then
    printf '#!/bin/bash\nexit 0\n' > /etc/rc.local
    chmod +x /etc/rc.local 2>/dev/null || true
  fi
  if ! grep -q "olt-monitor/run-bg.sh" /etc/rc.local 2>/dev/null; then
    # sisipkan sebelum exit 0
    if grep -q "exit 0" /etc/rc.local; then
      sed -i "s|exit 0|$APP_DIR/run-bg.sh \&\nexit 0|" /etc/rc.local 2>/dev/null || true
    else
      echo "$APP_DIR/run-bg.sh &" >> /etc/rc.local
    fi
    echo ">> /etc/rc.local diisi (jika dipakai init container)"
  fi
fi

# 3) profile hint (login shell)
PROFILE_SNIP="# OLT MONITOR\n# start: $APP_DIR/run-bg.sh | stop: $APP_DIR/stop.sh | fg: $APP_DIR/start.sh"

# --- start sekarang ---
echo ""
echo ">> Menjalankan OLT MONITOR sekarang (background)..."
"$APP_DIR/run-bg.sh" || true
sleep 2
if [ -f "$APP_DIR/olt-monitor.pid" ] && kill -0 "$(cat "$APP_DIR/olt-monitor.pid")" 2>/dev/null; then
  echo ">> OK — process hidup"
else
  echo ">> Coba foreground: $APP_DIR/start.sh"
fi

echo ""
echo "=============================================="
echo "  SELESAI"
echo "=============================================="
echo "  Folder   : $APP_DIR"
echo "  Start FG : $APP_DIR/start.sh     (untuk CMD/entrypoint MikroTik)"
echo "  Start BG : $APP_DIR/run-bg.sh"
echo "  Stop     : $APP_DIR/stop.sh"
echo "  Log      : $LOG"
echo "  UI       : http://IP-CONTAINER:$PORT"
echo ""
echo "  MikroTik: set entrypoint/cmd container ke:"
echo "    $APP_DIR/start.sh"
echo "  Mount volume ke: $APP_DIR/data   (supaya data aman)"
echo "=============================================="
