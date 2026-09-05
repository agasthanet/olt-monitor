# OLT MONITOR

> Dokumen panduan instalasi dan penggunaan **OLT MONITOR** untuk teknisi dan NOC (Network Operations Center).

Aplikasi web berbasis Flask untuk memantau (*monitoring*) dan memetakan (*mapping*) ODP pada perangkat OLT (ZTE, Hioso, HS-EPT1004 / Airpo) secara terpusat.

---

## 📋 Daftar Isi

- [Fitur Utama](#-fitur-utama)
- [Persyaratan Sistem](#-persyaratan-sistem)
- [Instalasi Aplikasi](#-instalasi-aplikasi)
- [Menjalankan Server](#-menjalankan-server)
- [Aktivasi Lisensi Full](#-aktivasi-lisensi-full)
- [Konfigurasi & Penambahan OLT](#-konfigurasi--penambahan-olt)
  - [A. OLT ZTE C320 / Hioso (SNMP)](#a-olt-zte-c320--hioso-snmp)
  - [B. OLT HS-EPT1004 / Airpo (CLI Telnet/SSH)](#b-olt-hs-ept1004--airpo-cli-telnetssh)
- [Dashboard & Pemantauan](#-dashboard--pemantauan)
- [Mapping ODP](#-mapping-odp)
- [Troubleshooting](#-troubleshooting)
- [Alur Singkat Penggunaan](#-alur-singkat-penggunaan)

---

## ⚡ Fitur Utama

- **Multi-Vendor Support:** Mendukung ZTE C320, Hioso (via SNMP), dan HS-EPT1004 / Airpo (via CLI Telnet/SSH).
- **Monitoring Real-time:** Status Online/Offline, daya optik Rx/Tx (dBm), lokasi port, serta waktu *downtime* terakhir.
- **ODP Mapping:** Pemetaan lokasi ODP berbasis nomor seri ONT/MAC address.
- **Auto-Update & Background Refresh:** Pembaruan otomatis halaman frontend setiap 5 menit dan pemindaian *background service* massal setiap 30 menit.
- **Skalabilitas Flexibel:** Mode Trial (1 OLT) dan Mode Full (multi-OLT berbasis lisensi HWID).

---

## 💻 Persyaratan Sistem

Sebelum melakukan instalasi, pastikan sistem memenuhi kriteria berikut:

- **Sistem Operasi:** Windows 10/11 atau Linux
- **Python:** Versi `3.10` s/d `3.14`
- **Konektivitas:** PC/Server dapat terhubung (*ping*) ke IP OLT
- **Akses OLT:**
  - **ZTE / Hioso:** SNMP Community aktif di OLT
  - **HS-EPT1004:** Akses Telnet/SSH (username & password CLI)

### Verifikasi Python
Buka Terminal / Command Prompt (CMD) / PowerShell, lalu ketik:
```bash
python --version
```
> **Catatan:** Jika Python belum terpasang, unduh melalui [python.org](https://www.python.org/) dan pastikan opsi **"Add Python to PATH"** dicentang saat proses instalasi.

---

## 🚀 Instalasi Aplikasi

1. **Ekstrak Arsip:**
   Ekstrak file `zte_c320_monitor.zip` ke direktori pilihan Anda, contoh:
   ```cmd
   C:\Users\...\Documents\zte_c320_monitor
   ```

2. **Masuk ke Direktori Project:**
   ```bash
   cd C:\Users\...\Documents\zte_c320_monitor
   ```

3. **Install Dependensi/Paket Pendukung:**
   ```bash
   pip install -r requirements.txt
   ```
   *Paket utama meliputi: `Flask`, `python-dotenv`, dan `paramiko` (untuk SSH).*

---

## 🖥️ Menjalankan Server

Jalankan perintah berikut pada terminal di direktori project:

```bash
python app.py
```

**Contoh Output Terminal:**
```text
==================================================
  OLT MONITOR
  License     : TRIAL (max 1 OLT) HWID=XXXX-XXXX-...
  BG Refresh  : tiap 1800s (30 menit)
==================================================
  Buka http://127.0.0.1:5000
```

Buka browser web dan akses alamat:
👉 **`http://127.0.0.1:5000`**

---

## 🔑 Aktivasi Lisensi Full

Aplikasi ini memiliki dua mode lisensi:

| Mode | Batas Maksimal OLT | Persyaratan |
| :--- | :--- | :--- |
| **Trial** | Maksimal 1 OLT | Mode default (tanpa kunci lisensi) |
| **Full** | Unlimited (Multi-OLT) | License Key resmi sesuai dengan **HWID** mesin |

### Langkah Aktivasi Mode Full:
1. Akses menu **Settings** pada dashboard web.
2. Salin kode **HWID** yang tertera pada layar.
3. Kirimkan HWID tersebut ke Admin untuk mendapatkan **License Key**.
4. Tempelkan **License Key** di kolom yang tersedia di menu **Settings**, lalu klik **Aktivasi Full**.

---

## ⚙️ Konfigurasi & Penambahan OLT

Akses menu **Settings** $ightarrow$ **Form Tambah / Edit OLT**. Form input akan disesuaikan secara otomatis berdasarkan vendor yang dipilih.

### A. OLT ZTE C320 / Hioso (SNMP)

| Parameter | Contoh Isian | Keterangan |
| :--- | :--- | :--- |
| **ID** | `Olt1` | ID Unik Sistem |
| **Nama** | `OLT1-Main` | Deskripsi / Nama OLT |
| **IP OLT** | `192.168.0.88` | IP Address OLT |
| **Vendor** | `ZTE C320 (SNMP)` / `Hioso` | Jenis Vendor OLT |
| **SNMP Community** | `public` | Sesuaikan dengan konfigurasi OLT |
| **Port SNMP** | `161` | Port default SNMP |
| **Boards (slot)** | `1,2` | Nomor slot board yang aktif |
| **Firmware** | `Auto Detect` | Deteksi otomatis firmware |

Klik **Tambah OLT** untuk menyimpan.

---

### B. OLT HS-EPT1004 / Airpo (CLI Telnet/SSH)

| Parameter | Contoh Isian | Keterangan |
| :--- | :--- | :--- |
| **ID** | `Olt2` | ID Unik Sistem |
| **Nama** | `EPON-OLT-HSAIRPO` | Deskripsi / Nama OLT |
| **IP OLT** | `192.168.1.88` | IP Address OLT |
| **Vendor** | `HS-EPT1004 / Airpo (CLI Telnet/SSH)` | Jenis Vendor OLT |
| **Protocol** | `Telnet` / `SSH` | Protokol komunikasi CLI |
| **Port CLI** | `23` | Port Telnet (23) atau SSH (22) |
| **Username CLI** | `admin` | Username login CLI |
| **Password CLI** | `******` | Password login CLI |

> **Tips:** Penguji dapat menguji koneksi Telnet terlebih dahulu menggunakan PuTTY/CMD:
> ```bash
> telnet 192.168.1.88 23
> ```
> Pastikan prompt login username berhasil muncul.

---

## 📊 Dashboard & Pemantauan

1. Buka menu **Dashboard**.
2. Pilih OLT target pada menu *dropdown*.
3. Klik tombol **Refresh OLT** untuk menarik data kondisi *optical & ONT/ONU* terbaru dari perangkat.
4. Gunakan fitur filter **Per PON / ODP** serta kotak pencarian untuk mencari pelanggan berdasarkan nama atau nomor seri (SN/MAC).

### Keterangan Kolom Data Dashboard:

| Kolom | Keterangan Informasi |
| :--- | :--- |
| **Lokasi** | Posisi fisik (`Board / PON / ONU ID`) |
| **Nama** | Deskripsi / Nama ONT (*kolom Desc pada HS-EPT*) |
| **Serial** | MAC Address atau Serial Number ONT |
| **ODP** | Mapping nama ODP (dapat diedit langsung via ikon pensil) |
| **Status** | Indikator status koneksi (`Online` / `Offline`) |
| **Rx / Tx** | Parameter daya penerimaan dan pemancaran optik (`dBm`) |
| **Downtime Terakhir** | Waktu pencatatan terakhir saat status berubah ke offline |

### Mekanisme Auto-Update:
- **Tampilan Browser:** Countdown refresh otomatis berkisar ~5 menit pada tab yang aktif.
- **Background Service:** Sistem melakukan scanning massal secara otomatis ke seluruh OLT setiap 30 menit selama proses `python app.py` berjalan.

---

## 📍 Mapping ODP

Fitur ini digunakan untuk menghubungkan Nomor Seri / MAC ONT ke nama ODP terkait:

1. **Via Dashboard:** Klik **Ikon Pensil** pada kolom ODP $ightarrow$ Ketik Nama ODP $ightarrow$ **Simpan**.
2. **Via Menu Mapping ODP (Impor CSV):** Pengelolaan data mapping secara massal dapat diunggah melalui file format CSV.

**Contoh Format CSV:**
```csv
serial,odp
AA:BB:CC:DD:EE:FF,ODP-Blok-A
ZTEGC1234567,ODP-Mawar-01
```

---

## 🛠️ Troubleshooting

| Gejala / Error | Penyebab & Solusi Penanganan |
| :--- | :--- |
| **SNMP Tidak Connect** | Cek koneksi IP (`ping`), pastikan *SNMP Community* sesuai, port `161` terbuka, dan tidak terblokir firewall. |
| **Error SSH pada HS-EPT** | Ubah konfigurasi **Protocol** ke `Telnet` dan gunakan **Port** `23`. |
| **Koneksi Telnet Gagal** | Uji koneksi via terminal `telnet <IP_OLT> 23`. Periksa aturan Firewall/Antivirus di Windows. |
| **Nama ONT Kosong (HS-EPT)** | Pastikan menggunakan versi aplikasi terbaru, lalu lakukan **Refresh OLT** kembali. |
| **Gagal Menambah OLT ke-2** | Aplikasi masih dalam mode **Trial** (Maks. 1 OLT). Lakukan **Aktivasi Full** menggunakan License Key. |
| **Proses Refresh Terlalu Lama** | Hal ini normal jika jumlah ONT sangat banyak (*proses pemindaian SNMP Walk / CLI memerlukan waktu*). |

---

## 🔄 Alur Singkat Penggunaan

```text
Install Python 
  └── Extract zte_c320_monitor.zip
        └── pip install -r requirements.txt
              └── python app.py
                    └── Akses Browser http://127.0.0.1:5000
                          └── [Opsional] Aktivasi License Full (HWID + Key)
                                └── Settings: Tambah OLT (SNMP / CLI)
                                      └── Dashboard: Refresh OLT & Pemantauan
                                            └── Mapping ODP
```

---
*Simpan file ini bersama paket instalasi repository aplikasi OLT MONITOR.*
