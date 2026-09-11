# OLT MONITOR

> Panduan instalasi dan penggunaan untuk teknisi / NOC.

**Versi stabil: `1.6.4`**

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
