## [1.10.1] — 2026-09-21

### Fixed
- Hioso: jumlah ONT kurang — seed dari **name ∪ serial ∪ status** (bukan hanya name OID)

## [1.10.0] — 2026-09-21

### Changed
- **Optimasi SNMP walk**
  - `snmp_parallel_walk`: beberapa tabel OID di-walk paralel
  - `snmp_probe_alive`: skip cepat jika OLT tidak merespon
  - GETBULK max-repetitions default 50
  - Hioso / C-Data / ZTE memakai parallel walk

## [1.9.9] — 2026-09-21

### Fixed
- App "bengong": Flask `threaded=True`, debug off
- Background refresh hanya OLT aktif + skip saat refresh UI
- Ping/health lebih ringan (health ~60s, skip saat SNMP walk)
- Cache ONT dilindungi lock

## [1.9.8] — 2026-09-21

### Fixed
- **Trial max 1 OLT** ditegakkan: dropdown/monitor/refresh hanya OLT dalam kuota (bukan semua di settings)

## [1.9.7] — 2026-09-21

### Changed
- Default community **Hioso**: read `SNMPREAD`, write `SNMPWRITE` (sesuai web GUI Hioso)

## [1.9.6] — 2026-09-21

### Fixed
- Import hilang setelah split parsers (`_snmp_number`, `snmp_getnext_walk`, `as_completed`, `STATUS_MAP`)

## [1.9.5] — 2026-09-21

### Changed
- Parser SNMP OID dipisah per vendor di folder `parsers/`:
  - `common.py` — engine SNMP, OnuInfo, convert power
  - `zte.py` — ZTE C320/C300
  - `hioso.py` — Hioso EPON/GPON
  - `cdata.py` — C-Data GPON/EPON
  - `vsol.py` / `bdcom.py` / `hsairpo.py`
  - `router.py` — dispatcher `fetch_all_onts`
- `snmp_zte.py` tetap ada sebagai compatibility shim

## [1.9.4] — 2026-09-21

### Added
- Support **C-Data GPON** SNMP (MIB 34592.1.5) — status, SN, desc, Rx/Tx, distance
- Vendor option **C-Data** di Settings + auto-detect dari sysDescr

## [1.9.3] — 2026-09-19

### Added
- Detail ONT: nama, status, Rx, **grafik Rx**, **10 log down terakhir**

### Fixed
- Modal detail kadang hanya alert `Detail: NA` (bootstrap belum siap)

## [1.9.1] — 2026-09-19

### Added
- **Export CSV** data ONT (mengikuti filter OLT/PON/ODP/cari)

## [1.9.0] — 2026-09-18

### Added
- **Login** (session): default `admin` / `admin`
- Logout di navbar
- Ganti password di Settings

## [1.8.0] — 2026-09-18

### Added
- Refresh **non-blocking** (background) + **progress bar**
- UI tetap bisa dipakai saat refresh berjalan

## [1.7.8] — 2026-09-18

### Fixed
- **Hioso Rx/Tx** tidak kebaca: parse power mendukung bytes/ASCII setelah decode SNMP

## [1.7.7] — 2026-09-18

### Added
- **Rx power terakhir sebelum down** — ditampilkan saat ONT offline (dari history)

## [1.7.6] — 2026-09-15

### Changed
- Clear cache hanya untuk **OLT yang sedang difilter**, bukan semua OLT

## [1.7.4] — 2026-09-15

### Fixed
- Nama ONT ZTE: pakai **description** jika name masih generik `ONU-x:y`

### Added
- Tombol **Clear cache** di dashboard

## [1.7.3] — 2026-09-15

### Fixed
- Nama ONT rusak setelah perubahan decode SNMP (kembali normal)
- Serial ZTE: parse konsisten (bytes + hex spasi) → `ZTEGxxxxxxxx` / setara
- Cache load: serial di-reparse

## [1.7.2] — 2026-09-15

### Fixed
- Serial ZTE: decode hex spasi (`52 54 45 47...`) jadi format `ZTEGxxxxxxxx`

## [1.7.0] — 2026-09-13

### Added
- Detail ONT (modal): lokasi, serial, Rx/Tx, ODP, downtime, dll.
- Tombol **Restart ONT** (SNMP SET best-effort / CLI Hioso & HS-Airpo)

## [1.6.4] — 2026-09-11 · **STABLE**

Rilis stabil. Tag: `v1.6.4`.

### Fixed
- Error dashboard: `_pon_sort_key` salah terdaftar sebagai route `/`
- Urutan grup PON numerik
- Uptime health (TimeTicks vs detik)
- Memory health fallback UCD-SNMP

## [1.6.3] — 2026-09-11

### Fixed
- Urutan grup PON numerik (`2/1`…`2/9`…`2/10`, bukan lexicographic)
- Uptime health: deteksi TimeTicks vs detik (HS-EPT dll)
- Memory: fallback UCD-SNMP MIB

# Changelog — OLT MONITOR

Format berdasarkan [Keep a Changelog](https://keepachangelog.com/).  
Versioning: **MAJOR** = fitur baru; **MINOR** = perbaikan bug / penyempurnaan; **PATCH** = perbaikan kecil.

---

## [1.5.9] — 2026-09-11

### Changed
- Tombol **Filter** dihapus — filter OLT/PON/ODP/tampilan **otomatis** saat diganti
- Kotak cari submit otomatis setelah berhenti mengetik (~0,45 dtk)

## [1.5.8] — 2026-09-10

### Removed
- Fitur **Waktu Host / NTP / Timezone** di Settings (di-rollback)

## [1.5.7] — 2026-09-10

### Added
- Settings: **Waktu Host** — atur timezone (WIB/WITA/WIT) + NTP server via `timedatectl`

## [1.5.6] — 2026-09-10

### Added
- **Update dari GitHub** di Settings: setelah `git pull` sukses, **auto-restart** app
  - prioritas: `systemctl restart olt-monitor`
  - fallback: re-spawn proses `python app.py`
- UI menunggu app hidup lagi lalu reload halaman

## [1.5.5] — 2026-09-10

### Fixed
- Inline edit ODP: endpoint `/api/odp` (sebelumnya hanya `/api/set-odp` → response HTML → error JSON)

### Added
- `install.sh`: opsi pasang **systemd** auto-start

## [1.5.4] — 2026-09-09

### Added
- Vendor **Auto**: setelah menemukan vendor yang cocok, otomatis **dikunci** di `olts.json` (refresh berikutnya langsung path itu, lebih cepat)

## [1.5.3] — 2026-09-09

### Added
- Dropdown list OLT: **merah + [RTO]** jika ping gagal, hijau jika UP

## [1.5.2] — 2026-09-09 · **STABLE**

Rilis stabil untuk produksi. Tag GitHub: `v1.5.2`.

### Fixed
- Hioso: lokasi disesuaikan **0-based** seperti web HA7304 (`0/2:1` bukan `1/2:1`)
- Status string Up/PwrDown dikenali
- Nama kosong tampil `NA` seperti NMS Hioso

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
