# Changelog — OLT MONITOR

Format berdasarkan [Keep a Changelog](https://keepachangelog.com/).  
Versioning: **MAJOR** = fitur baru; **MINOR** = perbaikan bug; **PATCH** = perbaikan sangat kecil.

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
