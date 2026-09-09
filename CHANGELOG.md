# Changelog — OLT MONITOR

Format berdasarkan [Keep a Changelog](https://keepachangelog.com/).  
Versioning: **MAJOR** = fitur baru; **MINOR** = perbaikan bug / penyempurnaan; **PATCH** = perbaikan kecil.

---

## [1.5.1] — 2026-09-09

### Fixed
- Hioso EPON: parser **classic** (nama dari OID 37 saja, seperti versi awal)
- Serial diformat MAC `aa:bb:cc:dd:ee:ff`
- Match Rx/Tx longgar jika index optical beda

## [1.5.0] — 2026-09-09

### Fixed
- **Hioso SNMP** dikembalikan ke logika stabil (seperti sebelum 1.4.1)
- Hapus filter ghost / rewrite board-PON yang merusak data
- Tidak scan banyak OID description (penyebab nama jadi `"1"` dan refresh lambat)

## [1.4.8] — 2026-09-09

### Fixed
- Nama ONT Hioso semua jadi `"1"`: abaikan nilai numerik/status sebagai description
- Fallback nama ke serial atau lokasi `board/pon:onu`

## [1.4.7] — 2026-09-09

### Fixed
- Tombol **Cek versi** / **Update dari GitHub** di Settings tidak bereaksi (script dijalankan sebelum DOM siap)
- Template `settings.html` dirapikan ulang (struktur HTML + event listener di `DOMContentLoaded`)

---

## [1.4.6] — 2026-09-09

### Fixed
- Feedback API cek versi / update lebih jelas (error GitHub, tanpa `.git`, `git` tidak terpasang)
- Coba URL `main` dan `master` untuk file `VERSION` remote

---

## [1.4.5] — 2026-09-09

### Fixed
- Spam log `[SNMP GET] ... timed out` di terminal (health probe / OID tidak support)
- Log error health probe di-quiet

---

## [1.4.4] — 2026-09-09

### Fixed
- Filter OLT di dashboard ikut menampilkan ONT tanpa `olt_id` (cache orphan) → total ONT “ngaco”
- Saat merge cache, ONT orphan dibuang

---

## [1.4.3] — 2026-09-09

### Fixed
- Access log Werkzeug untuk `/api/ping` dan `/api/health` disembunyikan (poll tiap detik)

---

## [1.4.2] — 2026-09-09

### Fixed
- Parsing PON Hioso dari label `ONU-x:y`
- Filter ghost ONU lebih ketat
- `olt_id` dipaksa terisi saat refresh

---

## [1.4.1] — 2026-09-09

### Fixed
- Log ping sukses tiap 5 detik tidak dicetak (hanya DOWN/error)
- Filter entry ghost Hioso EPON (offline tanpa serial/Rx)

---

## [1.4.0] — 2026-09-09

### Added
- Settings: tombol **Cek versi** dan **Update dari GitHub**
- `install.sh` instalasi Linux
- README: tutorial terpisah Windows vs Linux

---

## [1.3.2] — 2026-09-09

### Fixed
- Nama ONT Hioso: prioritaskan description SNMP, bukan label generik `ONU-x:y`
- Serial SNMP dibersihkan dari karakter garbage

---

## [1.3.1] — 2026-09-09

### Changed
- Ikon navbar diganti SVG chassis OLT + favicon

---

## [1.3.0] — 2026-09-09

### Added
- Tombol **Refresh All** di navbar (force refresh semua OLT)

### Fixed
- Template dashboard Chart.js — grafik latency tampil
- Canvas grafik tinggi tetap + tunggu Chart.js load

---

## [1.2.0] — 2026-09-08

### Added
- Mode **Auto** vendor: jika path pertama 0 ONT, coba Hioso → ZTE → HS-Airpo
- SysDescr generik: prioritaskan coba Hioso dulu

---

## [1.1.1] — 2026-09-08

### Fixed
- Mode Auto firmware: selalu coba V2 + V1 (GETBULK & GETNEXT)
- Jika filter boards menihilkan semua ONT, ulangi tanpa filter board

---

## [1.1.0] — 2026-09-08

### Fixed
- Deteksi firmware ZTE V1/V2 lebih robust
- Auto fallback V1 ↔ V2 jika kosong
- Script update menjaga folder `data/`

### Changed
- README dikurasi untuk end-user

---

## [1.0.0] — 2026-09-07

### Added
- Rilis pertama stabil
- Multi-OLT dashboard (status, Rx/Tx, ODP, downtime)
- Vendor: ZTE C320 SNMP, Hioso SNMP, HS-EPT1004 CLI, Hioso HA7302 CLI
- Mapping ODP inline + CSV
- Lisensi Trial (1 OLT) / Full (HWID)
- Background refresh ONT 30 menit
- Auto ping 5 detik + grafik latency
- Health OLT (CPU/Memory/Uptime via SNMP bila available)

### Fixed (baseline)
- Rx/Tx kembar antar PON HS-EPT (merge by MAC)
- Telnet tanpa `telnetlib` (Python 3.13+)
- Field Settings SNMP vs CLI sesuai vendor

---

## Unreleased

_Perubahan berikutnya dicatat di sini sebelum rilis berikutnya._
