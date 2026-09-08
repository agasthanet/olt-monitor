# OLT MONITOR

> Panduan instalasi dan penggunaan **OLT MONITOR** untuk teknisi / NOC.

**Versi: `1.0.0`**

Aplikasi web untuk memantau ONT/ONU dari OLT (status, Rx/Tx, mapping ODP) secara terpusat.

---

## Daftar Isi

- [Fitur Utama](#fitur-utama)
- [Persyaratan Sistem](#persyaratan-sistem)
- [Instalasi](#instalasi)
- [Menjalankan Server](#menjalankan-server)
- [Aktivasi Lisensi Full](#aktivasi-lisensi-full)
- [Menambahkan OLT](#menambahkan-olt)
- [Dashboard](#dashboard)
- [Mapping ODP](#mapping-odp)
- [Update Aplikasi](#update-aplikasi)
- [Troubleshooting](#troubleshooting)
- [Alur Singkat](#alur-singkat)

---

## Fitur Utama

- Multi-vendor: ZTE C320 (SNMP), Hioso (SNMP), HS-EPT1004 / Airpo (CLI), Hioso HA7302 (CLI)
- Status ONT Online/Offline, Rx/Tx (dBm), downtime terakhir
- Mapping ODP (edit di dashboard atau impor CSV)
- Ping OLT + grafik latency
- Health OLT (CPU/Memory/Uptime/Suhu bila SNMP support)
- Auto refresh background tiap 30 menit; ping otomatis
- Mode **Trial** (1 OLT) dan **Full** (multi-OLT)

---

## Persyaratan Sistem

- Windows 10/11 atau Linux
- Python **3.10 – 3.14** (minimal 3.7+)
- Server/PC dapat **ping** ke IP OLT
- Akses sesuai vendor:
  - ZTE / Hioso SNMP → community SNMP aktif
  - HS-EPT / HA7302 → Telnet atau SSH (user & password)

Cek Python:

```bash
python --version
# Linux:
python3 --version
```

---

## Instalasi

### Dari GitHub (disarankan)

```bash
git clone https://github.com/agasthanet/olt-monitor.git
cd olt-monitor
python3 -m venv venv
source venv/bin/activate
# Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Dari file ZIP

1. Extract `zte_c320_monitor.zip` / isi repo ke folder pilihan
2. Masuk folder tersebut
3. `pip install -r requirements.txt`

**Ubuntu** (jika belum ada venv):

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Menjalankan Server

```bash
python app.py
# atau
python3 app.py
```

Buka browser: **http://127.0.0.1:5000**  
Dari PC lain: `http://<IP-SERVER>:5000`

---

## Aktivasi Lisensi Full

| Mode | Batas OLT |
| :--- | :--- |
| **Trial** | 1 OLT (default) |
| **Full** | Multi-OLT |

1. Buka menu **Settings**
2. Salin **HWID**
3. Kirim HWID ke **agastha.net@gmail.com** (subject: `Key OLT-MONITOR`)
4. Tempel **License Key** yang diterima → **Aktivasi Full**

---

## Menambahkan OLT

Menu **Settings** → form tambah OLT. Field menyesuaikan vendor.

### ZTE C320 / Hioso (SNMP)

| Field | Contoh |
| :--- | :--- |
| ID / Nama | `olt1` / `OLT-Main` |
| IP | `192.168.0.88` |
| Vendor | ZTE C320 (SNMP) atau Hioso |
| Community | `public` (sesuai OLT) |
| Port | `161` |
| Boards | `1,2` |

### HS-EPT1004 / Airpo (CLI)

| Field | Contoh |
| :--- | :--- |
| Vendor | HS-EPT1004 / Airpo (CLI Telnet/SSH) |
| Protocol | Telnet (port **23**) |
| Username / Password | sesuai login CLI |

### Hioso HA7302 (CLI)

| Field | Contoh |
| :--- | :--- |
| Vendor | Hioso HA7302 (CLI Telnet optical-ddm) |
| Protocol | Telnet, port **23** |
| Username | biasanya `root` |
| Boards | nomor PON saja, mis. `1` (jangan `1,2,3,4` jika hanya 1 PON) |

Uji Telnet: `telnet <IP_OLT> 23`

---

## Dashboard

1. Pilih OLT di dropdown
2. Klik **Refresh OLT** untuk ambil data terbaru
3. Filter PON / ODP / pencarian nama atau serial

| Kolom | Isi |
| :--- | :--- |
| Lokasi | Board / PON / ONU |
| Nama | Deskripsi ONT |
| Serial | MAC / SN |
| ODP | Bisa diedit (ikon pensil) |
| Status | Online / Offline |
| Rx / Tx | dBm |
| Downtime | Terakhir offline |

**Ping** dan **Health** menampilkan data OLT yang sedang dipilih.  
Background: data ONT di-scan massal tiap ~30 menit selama app berjalan.

---

## Mapping ODP

- Di dashboard: klik ikon pensil pada kolom ODP → isi nama → simpan
- Atau menu **Mapping ODP** / impor CSV:

```csv
serial,odp
AA:BB:CC:DD:EE:FF,ODP-Blok-A
```

---

## Update Aplikasi

Data OLT, mapping ODP, dan license **tidak hilang** saat update (tersimpan di folder `data/`).

### Update dari GitHub

```bash
cd olt-monitor
# stop app dulu (Ctrl+C)

./update-from-git.sh
# atau:
git pull

pip install -r requirements.txt
python3 app.py
```

Cek versi: `cat VERSION`

### Update dari ZIP

```bash
./update.sh /path/ke/zte_c320_monitor.zip
# Windows: update.bat path\ke\file.zip
python app.py
```

---

## Troubleshooting

| Masalah | Solusi |
| :--- | :--- |
| SNMP tidak connect | Ping IP OLT, cek community & port 161, firewall |
| CLI/Telnet gagal | `telnet <IP> 23`, cek user/password, firewall |
| 0 ONT padahal OLT hidup | Vendor benar? Boards/PON sesuai? Refresh lagi |
| Tidak bisa tambah OLT ke-2 | Masih Trial → aktivasi Full |
| Refresh lama | Normal jika ONT banyak |
| Python error `annotations` | Upgrade Python (minimal 3.7, disarankan 3.10+) |

---

## Alur Singkat

```text
Install (git clone / extract zip)
  → pip install -r requirements.txt
  → python app.py
  → Browser http://127.0.0.1:5000
  → (opsional) Aktivasi Full via HWID
  → Settings: Tambah OLT
  → Dashboard: Refresh & monitor
  → Mapping ODP bila perlu
```

---

*OLT MONITOR v1.0.0 — simpan panduan ini bersama instalasi.*
