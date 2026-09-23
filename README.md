# OLT MONITOR

> Panduan instalasi dan penggunaan untuk teknisi / NOC.

**Versi stabil: `1.10.2`**

Aplikasi web untuk memantau ONT/ONU dari OLT (status, Rx/Tx, mapping ODP) secara terpusat.

Repo: https://github.com/agasthanet/olt-monitor

---

## Fitur Utama

- Multi-vendor: ZTE C320 (SNMP), Hioso (SNMP), HS-EPT1004 / Airpo (CLI), Hioso HA7302 (CLI)
- Status ONT, Rx/Tx, downtime, mapping ODP
- Ping OLT + grafik latency, health (CPU/Mem bila SNMP support)
- Background refresh, mode Trial (1 OLT) / Full (multi-OLT)

---

## Persyaratan

- Python **3.10 – 3.14** (disarankan)
- Jaringan: PC/server dapat **ping** ke IP OLT
- SNMP community **atau** akses Telnet/SSH (tergantung vendor)

---


## Spesifikasi sistem (rekomendasi)

Untuk memonitor **±10 OLT** (asumsi ~50–100 ONU per OLT, total ~500–1000 ONU):

### Nyaman (disarankan)

| Komponen | Spec |
|----------|------|
| **CPU** | 2–4 vCPU (x86_64) |
| **RAM** | **2–4 GB** |
| **Storage** | 10–20 GB (SSD lebih enak) |
| **OS** | Ubuntu 22.04 / Debian 12 (atau setara) |
| **Jaringan** | Latency ke OLT stabil; port **UDP/161** (SNMP) tidak di-filter |

### Minimum (masih bisa jalan)

| Komponen | Spec |
|----------|------|
| CPU | 1–2 vCPU |
| RAM | **1 GB** (lebih longgar 2 GB) |
| Storage | 5 GB |

### Yang membebani aplikasi

1. **Refresh SNMP** (paling berat) — walk paralel per OLT  
2. **Background refresh** (~30 menit) × jumlah OLT  
3. **Ping** tiap 5 detik (ringan)  
4. **Health SNMP** sesekali  

Dengan optimasi walk paralel, **10 OLT di 2 vCPU / 2 GB** biasanya cukup. Jika tiap OLT 100+ ONU dan sering force-refresh bersamaan, naikkan ke **4 GB RAM**.

### Estimasi waktu refresh

| Kondisi | Estimasi |
|---------|----------|
| 1 OLT ~60 ONU | ~20–40 detik |
| 10 OLT (background berurutan) | ~5–15 menit total |
| Refresh 1 OLT dari UI | ~20–40 detik |

### Tips deploy

- Jangan taruh di host yang sama dengan OLT jika CPU OLT sudah penuh  
- Pastikan server monitor → OLT **routing/latency bagus** (timeout SNMP = UI terasa lambat)  
- Mode license **Full** untuk multi-OLT (Trial max 1 OLT)  
- Container LXC / MikroTik: disarankan **≥ 2 GB RAM** (jangan 512 MB)


## Instalasi di Linux (Ubuntu/Debian)

### Cara cepat (script)

```bash
curl -fsSL https://raw.githubusercontent.com/agasthanet/olt-monitor/main/install.sh -o install.sh
# atau salin install.sh dari paket
chmod +x install.sh
./install.sh
```

Script akan: install `python3`/`git` bila perlu, `git clone`, buat `venv`, `pip install`.

### Manual

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

git clone https://github.com/agasthanet/olt-monitor.git
cd olt-monitor

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python app.py
```

Buka browser: **http://127.0.0.1:5000**  
Dari PC lain: `http://<IP-SERVER>:5000`

### Update di Linux

```bash
cd ~/olt-monitor
source venv/bin/activate
./update-from-git.sh
# atau: git pull
pip install -r requirements.txt
# stop app (Ctrl+C) lalu jalankan lagi:
python app.py
```

Atau dari menu **Settings** di web: **Cek versi** / **Update dari GitHub**, lalu restart app.

---

## Instalasi di Windows

1. Install Python dari [python.org](https://www.python.org/downloads/)  
   Centang **“Add python.exe to PATH”**.
2. Install **Git for Windows** dari [git-scm.com](https://git-scm.com/) (opsional, untuk update via Git).
3. Buka **Command Prompt** atau **PowerShell**:

```bat
git clone https://github.com/agasthanet/olt-monitor.git
cd olt-monitor

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

python app.py
```

Tanpa Git: extract ZIP → `cd` ke folder → buat venv & `pip install` sama seperti di atas.

Buka browser: **http://127.0.0.1:5000**

### Update di Windows

```bat
cd olt-monitor
venv\Scripts\activate
git pull
pip install -r requirements.txt
python app.py
```

Atau `update.bat path\ke\zte_c320_monitor.zip` jika update dari file ZIP.

---

## Menjalankan Server

```bash
# Linux
source venv/bin/activate
python app.py

# Windows
venv\Scripts\activate
python app.py
```

---

## Aktivasi Lisensi Full

| Mode | Batas |
|------|--------|
| Trial | 1 OLT |
| Full | Multi-OLT |

1. Settings → salin **HWID**
2. Kirim ke **agastha.net@gmail.com** (subject: `Key OLT-MONITOR`)
3. Tempel license key → Aktivasi Full

---

## Menambahkan OLT

Settings → form OLT (field menyesuaikan vendor).

| Vendor | Akses |
|--------|--------|
| ZTE C320 / Hioso SNMP | Community + port 161 |
| HS-EPT1004 CLI | Telnet port 23 + user/pass |
| Hioso HA7302 CLI | Telnet + user/pass, Boards = nomor PON |

Dashboard → pilih OLT → **Refresh OLT**.

---

## Mapping ODP

Ikon pensil di kolom ODP, atau impor CSV di menu Mapping ODP:

```csv
serial,odp
AABBCCDDEEFF,ODP-Blok-A
```

---

## Update & versi (Settings)

Di **Settings** tersedia:

- **Cek versi** — bandingkan versi lokal dengan GitHub  
- **Update dari GitHub** — `git pull` / script update (folder `data/` aman)

Setelah update, **restart** `python app.py`.

---

## Telemetry

App mengirim data agregat otomatis (versi, mode license, jumlah OLT, HWID/install_id, platform).
Tidak mengirim IP OLT, community, password, serial ONU, atau nama pelanggan.

Nonaktifkan (opsional): set env `TELEMETRY_DISABLED=1`.
Endpoint: env `TELEMETRY_URL` atau default Cloudflare Worker.


## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| SNMP gagal | Ping IP, community, port 161, firewall |
| Telnet gagal | `telnet <IP> 23`, cek user/password |
| 0 ONT | Vendor & Boards benar? Refresh lagi |
| Tidak bisa OLT ke-2 | Masih Trial → aktivasi Full |
| Update gagal di web | Jalankan `./update-from-git.sh` di terminal |

---

## Alur singkat

```text
Install (Linux: install.sh / Windows: clone + venv)
  → python app.py
  → http://127.0.0.1:5000
  → Settings: tambah OLT
  → Dashboard: Refresh
```

## Container (MikroTik / Docker)

Tanpa systemd. Pakai skrip khusus:

```bash
curl -fsSL https://raw.githubusercontent.com/agasthanet/olt-monitor/main/install-container.sh -o install-container.sh
chmod +x install-container.sh
./install-container.sh
```

- Start foreground (entrypoint): `/root/olt-monitor/start.sh`
- Start background: `/root/olt-monitor/run-bg.sh`
- Stop: `/root/olt-monitor/stop.sh`
- Mount volume ke `data/` agar config tidak hilang.

