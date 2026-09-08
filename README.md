# OLT MONITOR

> Dokumen panduan instalasi dan penggunaan **OLT MONITOR** untuk teknisi dan NOC (Network Operations Center).

**Versi aplikasi: `1.0.0`**

Aplikasi web berbasis Flask untuk memantau (*monitoring*) dan memetakan (*mapping*) ODP pada perangkat OLT secara terpusat.

---

## Daftar Isi

- [Fitur Utama](#fitur-utama)
- [Persyaratan Sistem](#persyaratan-sistem)
- [Instalasi Aplikasi](#instalasi-aplikasi)
- [Menjalankan Server](#menjalankan-server)
- [Aktivasi Lisensi Full](#aktivasi-lisensi-full)
- [Konfigurasi & Penambahan OLT](#konfigurasi--penambahan-olt)
  - [A. Menggunakan SNMP](#a-olt-zte-c320--hioso-snmp)
  - [B. Menggunakan CLI Telnet/SSH](#b-olt-hs-ept1004--airpo-cli-telnetssh)
  - [C. Hioso HA7302 (CLI)](#c-hioso-ha7302-cli-optical-ddm)
- [Dashboard & Pemantauan](#dashboard--pemantauan)
- [Mapping ODP](#mapping-odp)
- [Troubleshooting](#troubleshooting)
- [Versioning](#versioning)
- [Changelog](#changelog)
- [Update aplikasi (data tetap aman)](#update-aplikasi-data-tetap-aman)
- [Alur Singkat Penggunaan](#alur-singkat-penggunaan)

---

## Fitur Utama

- **Multi-Vendor Support:** ZTE C320 (SNMP), Hioso (SNMP), HS-EPT1004 / Airpo (CLI Telnet/SSH), Hioso HA7302 (CLI optical-ddm).
- **Monitoring Real-time:** Status Online/Offline, daya optik Rx/Tx (dBm), lokasi port, serta waktu *downtime* terakhir.
- **Ping & Health OLT:** Latency ping, grafik latency, CPU/Memory/Uptime/Suhu (jika MIB SNMP support).
- **ODP Mapping:** Pemetaan lokasi ODP berbasis nomor seri ONT/MAC address (inline edit + CSV).
- **Auto-Update & Background Refresh:** Frontend ~5 menit; background scan massal OLT tiap 30 menit; ping auto tiap 5 detik.
- **Lisensi:** Mode Trial (1 OLT) dan Mode Full (multi-OLT, key berbasis HWID).

---

## Persyaratan Sistem

- **Sistem Operasi:** Windows 10/11 atau Linux
- **Python:** Versi `3.10` s/d `3.14`
- **Konektivitas:** PC/Server dapat *ping* ke IP OLT
- **Akses OLT:**
  - **ZTE / Hioso (SNMP):** SNMP Community aktif
  - **HS-EPT1004:** Telnet/SSH (username & password CLI)
  - **Hioso HA7302:** Telnet (biasanya tanpa SNMP ONU)

### Verifikasi Python

```bash
python --version
# atau di Linux:
python3 --version
```

Jika belum terpasang, unduh dari [python.org](https://www.python.org/) dan centang **"Add Python to PATH"** (Windows).

---

## Instalasi Aplikasi

1. **Ekstrak arsip** `zte_c320_monitor.zip` ke folder pilihan, contoh:
   ```text
   C:\Users\...\Documents\zte_c320_monitor
   ```
   atau di Linux: `~/olt-monitor`

2. **Masuk ke direktori project:**
   ```bash
   cd C:\Users\...\Documents\zte_c320_monitor
   ```

3. **Install dependensi:**
   ```bash
   pip install -r requirements.txt
   ```
   Paket utama: `Flask`, `python-dotenv`, `paramiko` (SSH).

   Di Ubuntu disarankan pakai venv:
   ```bash
   sudo apt install -y python3 python3-pip python3-venv
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

---

## Menjalankan Server

```bash
python app.py
# Linux:
python3 app.py
```

**Contoh output:**
```text
==================================================
  OLT MONITOR
  License     : TRIAL (max 1 OLT) HWID=XXXX-XXXX-...
  BG Refresh  : tiap 1800s (30 menit)
==================================================
  Buka http://127.0.0.1:5000
```

Buka browser: **http://127.0.0.1:5000**  
Dari PC lain di jaringan: `http://<IP-SERVER>:5000`

---

## Aktivasi Lisensi Full

| Mode | Batas OLT | Syarat |
| :--- | :--- | :--- |
| **Trial** | Maksimal 1 OLT | Default, tanpa key |
| **Full** | Multi-OLT | License Key sesuai **HWID** mesin |

### Langkah aktivasi Full

1. Buka menu **Settings**.
2. Salin **HWID**.
3. Kirim HWID ke **agastha.net@gmail.com** dengan subject **Key OLT-MONITOR**.
4. Tempel **License Key** di Settings → **Aktivasi Full**.

> Keygen hanya untuk admin (folder terpisah, jangan dibagikan ke end-user).

---

## Konfigurasi & Penambahan OLT

Menu **Settings** → form **Tambah / Edit OLT**. Field menyesuaikan vendor (SNMP vs CLI).

### A. OLT ZTE C320 / Hioso (SNMP)

| Parameter | Contoh | Keterangan |
| :--- | :--- | :--- |
| **ID** | `Olt1` | ID unik |
| **Nama** | `OLT1-Main` | Nama tampilan |
| **IP OLT** | `192.168.0.88` | IP OLT |
| **Vendor** | `ZTE C320 (SNMP)` / `Hioso` | |
| **SNMP Community** | `public` | Sesuai OLT |
| **Port SNMP** | `161` | |
| **Boards (slot)** | `1,2` | Slot board aktif |
| **Firmware** | `Auto Detect` | |

### B. OLT HS-EPT1004 / Airpo (CLI Telnet/SSH)

| Parameter | Contoh | Keterangan |
| :--- | :--- | :--- |
| **ID** | `Olt2` | ID unik |
| **Nama** | `EPON-OLT-HSAIRPO` | |
| **IP OLT** | `192.168.1.88` | |
| **Vendor** | `HS-EPT1004 / Airpo (CLI Telnet/SSH)` | |
| **Protocol** | `Telnet` | Disarankan Telnet |
| **Port CLI** | `23` | SSH biasanya 22 |
| **Username / Password CLI** | `admin` / `******` | |

Uji dulu: `telnet <IP_OLT> 23`

### C. Hioso HA7302 (CLI optical-ddm)

| Parameter | Contoh | Keterangan |
| :--- | :--- | :--- |
| **Vendor** | `Hioso HA7302 (CLI Telnet optical-ddm)` | Tanpa SNMP ONU |
| **Protocol** | `Telnet` | Port **23** |
| **Username** | `root` | Sesuai OLT |
| **Boards** | `1` | Nomor PON fisik (jangan isi 1,2,3,4 jika cuma 1 PON) |

Perintah internal: `show optical-ddm onu 0/1/{pon}:{id}` (max 128 ONU).

---

## Dashboard & Pemantauan

1. Buka **Dashboard**.
2. Pilih OLT di dropdown.
3. Klik **Refresh OLT** untuk data optical/ONT terbaru.
4. Filter Per PON / ODP dan kotak pencarian nama/serial.

### Kolom data

| Kolom | Keterangan |
| :--- | :--- |
| **Lokasi** | Board / PON / ONU ID |
| **Nama** | Deskripsi ONT (Desc di HS-EPT) |
| **Serial** | MAC / Serial Number |
| **ODP** | Mapping ODP (edit via ikon pensil) |
| **Status** | Online / Offline |
| **Rx / Tx** | Daya optik (dBm) |
| **Downtime terakhir** | Saat terakhir offline |

### Panel atas

- **Ping OLT** — latency OLT yang dipilih (auto tiap 5 detik)
- **Health OLT** — CPU, Memory, Uptime, Suhu, Fan (N/A jika MIB tidak support)
- **Grafik latency** — history ping OLT terpilih

### Auto-update

- Browser: ~5 menit pada tab aktif
- Background ONT: massal tiap **30 menit**
- Ping: tiap **5 detik** (server)

---

## Mapping ODP

1. **Dashboard:** ikon pensil pada kolom ODP → isi nama → simpan.
2. **Menu Mapping ODP:** kelola / impor CSV.

```csv
serial,odp
AA:BB:CC:DD:EE:FF,ODP-Blok-A
ZTEGC1234567,ODP-Mawar-01
```

---

## Troubleshooting

| Gejala | Penanganan |
| :--- | :--- |
| SNMP tidak connect | Ping IP, community, port 161, firewall |
| SSH gagal di HS-EPT | Ganti **Telnet** port **23** |
| Telnet gagal | `telnet <IP> 23`; cek firewall/antivirus |
| Hioso CLI 0 ONT padahal ping OK | Boards = nomor PON benar; cek log `[HiosoCLI] sample` |
| Rx kembar antar PON (HS-EPT) | Gunakan versi ≥ 1.0.0 (merge by MAC) |
| Nama ONT kosong (HS-EPT) | Refresh OLT; pastikan `show ont info` jalan di CLI |
| Tidak bisa tambah OLT ke-2 | Masih Trial → aktivasi Full |
| Refresh lama | Normal jika ONT banyak |
| Server Ubuntu Python lama | Minimal Python 3.7+ (disarankan 3.10+) |
| `requirements.txt` invalid | Isi hanya: flask, python-dotenv, paramiko |

---

## Versioning

Skema versi: **`MAJOR.MINOR`** (ditulis `MAJOR.MINOR.PATCH` bila perlu patch kecil).

| Jenis perubahan | Naikkan | Contoh |
| :--- | :--- | :--- |
| Fitur baru / perubahan besar | **MAJOR** | `1.0.0` → `2.0.0` |
| Perbaikan bug / penyempurnaan kecil | **MINOR** | `1.0.0` → `1.1.0` |
| Patch sangat kecil (typo, docs) | **PATCH** | `1.1.0` → `1.1.1` |

Setiap rilis wajib dicatat di **Changelog** di bawah (dan file `CHANGELOG.md`).

---

## Changelog

### [1.0.0] — 2026-09-07

Rilis pertama stabil (baseline).

**Fitur**

- Dashboard multi-OLT: status ONT, Rx/Tx, ODP, downtime
- Vendor: ZTE C320 SNMP, Hioso SNMP, HS-EPT1004 CLI, Hioso HA7302 CLI
- Mapping ODP (inline + CSV)
- Lisensi Trial / Full berbasis HWID + keygen admin terpisah
- Background refresh ONT 30 menit
- Ping OLT auto 5 detik + grafik latency (OLT terpilih)
- Health OLT (CPU/Mem/Uptime/Suhu via SNMP bila tersedia)
- Dual firmware path ZTE; pure-Python SNMPv2c

**Perbaikan yang sudah termasuk di baseline**

- Merge optical HS-EPT by MAC (hindari Rx kembar antar PON)
- Telnet murni socket (Python 3.13+ tanpa telnetlib)
- Field Settings SNMP vs CLI sesuai vendor
- Port CLI tidak memakai 161 (SNMP)

---



---

## Update aplikasi (data tetap aman)

Data konfigurasi **tidak ikut di-overwrite** selama update:

| Tetap aman | Diganti (system) |
| :--- | :--- |
| Folder `data/` (`olts.json`, mapping ODP, cache, license, ping history) | `*.py`, `templates/`, `static/` |
| File `.env` | `requirements.txt`, `README.md`, `CHANGELOG.md`, `VERSION` |



### Update dari GitHub (disarankan)

Sumber resmi: **https://github.com/agasthanet/olt-monitor.git**

Dengan Git, setiap rilis cukup `git pull` — **folder `data/` dan file `.env` tidak ikut terhapus** karena dilindungi `.gitignore`.

#### A. Install baru dari GitHub

```bash
git clone https://github.com/agasthanet/olt-monitor.git
cd olt-monitor
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

Buka browser: `http://127.0.0.1:5000`

#### B. Server yang sudah jalan (ada data OLT) — sambungkan ke Git sekali

```bash
cd ~/olt-monitor                  # sesuaikan path folder app kamu
# JANGAN hapus folder data/

# Opsi 1 — script (backup data otomatis)
chmod +x update-from-git.sh
./update-from-git.sh
# sama dengan:
# ./update-from-git.sh https://github.com/agasthanet/olt-monitor.git main

# Opsi 2 — manual
git init
git remote add origin https://github.com/agasthanet/olt-monitor.git
git fetch origin
git checkout -b main
git pull origin main --allow-unrelated-histories
# jika ada konflik di file kode, pilih versi dari GitHub;
# pastikan folder data/ lokal tetap utuh

pip install -r requirements.txt
python3 app.py
```

#### C. Update rutin (setiap ada versi baru di GitHub)

```bash
cd ~/olt-monitor
# Stop app dulu (Ctrl+C)

./update-from-git.sh
# atau cukup:
git pull origin main

pip install -r requirements.txt   # hanya jika requirements berubah
python3 app.py

# cek versi
cat VERSION
```

#### D. Yang di-commit ke GitHub vs yang lokal

| Di GitHub (kode) | Hanya di server (jangan di-push) |
| :--- | :--- |
| `*.py`, `templates/`, `static/` | `data/olts.json` |
| `requirements.txt`, `VERSION` | `data/license.json` |
| `README.md`, `CHANGELOG.md` | `data/*_cache*`, `ping_history` |
| `.gitignore`, script `update*.sh` | `.env` |
| `data/*.example` (contoh kosong) | mapping ODP production |

> Admin yang push ke GitHub: jangan pernah commit password OLT, community SNMP, atau license key customer.

### Cara update dari zip (Linux)

```bash
# 1. Stop app (Ctrl+C)
# 2. Backup otomatis + ganti kode
chmod +x update.sh
./update.sh /path/ke/zte_c320_monitor.zip

# 3. (opsional) dependency baru
pip install -r requirements.txt

# 4. Jalankan lagi
python3 app.py
```

### Cara update (Windows)

```bat
update.bat C:\path\ke\zte_c320_monitor.zip
python app.py
```

### Cara manual (paling aman)

1. Stop `python app.py`
2. **Backup** folder `data/` dan file `.env`
3. Extract zip baru ke folder sementara
4. Salin **hanya** file sistem (`*.py`, `templates/`, `requirements.txt`, `VERSION`, docs) ke folder app
5. **Jangan** hapus/timpa `data/`
6. Jalankan lagi app

> Setelah update, cek `cat VERSION` / banner startup harus sesuai changelog.

## Alur Singkat Penggunaan

```text
Install Python
  └── Extract zte_c320_monitor.zip
        └── pip install -r requirements.txt
              └── python app.py
                    └── Browser http://127.0.0.1:5000
                          └── [Opsional] Aktivasi Full (HWID + Key)
                                └── Settings: Tambah OLT (SNMP / CLI)
                                      └── Dashboard: Refresh OLT
                                            └── Mapping ODP
```

---

*Simpan file ini bersama paket instalasi OLT MONITOR. Lihat juga `CHANGELOG.md` untuk riwayat rilis.*
