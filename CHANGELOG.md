## [1.4.0] — 2026-09-09

### Added
- Settings: Cek versi & Update dari GitHub
- install.sh Linux
- README terpisah Windows/Linux

# Changelog — OLT MONITOR

Format berdasarkan [Keep a Changelog](https://keepachangelog.com/).  
Versioning: **MAJOR** = fitur baru; **MINOR** = perbaikan bug; **PATCH** = perbaikan sangat kecil.

## [1.3.2] — 2026-09-09

### Fixed
- Nama ONT Hioso: prioritaskan description, bukan `ONU-x:y`
- Serial dibersihkan dari karakter garbage

## [1.3.0] — 2026-09-09

### Added
- Tombol **Refresh All** di navbar: force refresh semua OLT

### Fixed
- Struktur template dashboard (script Chart.js) — grafik latency tampil
- Canvas grafik tinggi tetap + wait Chart.js load

## [1.2.0] — 2026-09-08

### Added
- Mode **Auto** vendor: jika path pertama 0 ONT, otomatis coba Hioso → ZTE → HS-Airpo
- SysDescr generik (bukan merek) prioritas coba Hioso dulu

## [1.1.1] — 2026-09-08

### Fixed
- Mode Auto firmware: selalu coba V2 + V1 (GETBULK & GETNEXT)
- Jika boards filter menihilkan semua ONT, ulangi tanpa filter board

## [1.1.0] — 2026-09-08

### Fixed
- Deteksi firmware ZTE V1/V2 lebih robust (probe name/serial/status)
- Auto fallback: jika V1 kosong coba V2 (dan sebaliknya)
- Update dari GitHub + script jaga folder data

### Changed
- README dikurasi untuk end-user

## [1.0.0] — 2026-09-07

### Added
- Rilis pertama stabil
- Multi-OLT dashboard (ONT status, Rx/Tx, ODP, downtime)
- Vendor ZTE C320 (SNMP), Hioso (SNMP), HS-EPT1004 (CLI), Hioso HA7302 (CLI optical-ddm)
- Mapping ODP inline + CSV
- Lisensi Trial (1 OLT) / Full (HWID key); keygen admin terpisah
- Background refresh ONT 30 menit
- Auto ping 5 detik + grafik latency
- Health OLT (CPU, Memory, Uptime, Temperature via SNMP)

### Fixed (termasuk dalam baseline 1.0.0)
- Rx/Tx kembar antar PON pada HS-EPT (merge by MAC + section optical)
- Telnet tanpa `telnetlib` (Python 3.13+)
- Settings: field SNMP/CLI sesuai vendor
- Port CLI tidak fallback ke 161

---

## Unreleased

_Perubahan berikutnya akan dicatat di sini sebelum rilis._
