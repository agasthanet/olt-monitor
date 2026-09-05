# OLT MONITOR

Web dashboard sederhana untuk memantau sinyal ONT dari OLT ZTE C320 via SNMP.

## Fitur

- Dual firmware support (V1 base 1012 & V2 base 1082) + auto detect
- Monitor semua ONT di slot 1 & 2
- Tampilan **per PON** dan **per ODP**
- Mapping ODP eksternal (CSV / JSON) — tidak tergantung data di OLT
- Filter, search, warna status & kekuatan sinyal
- Mode demo (tanpa OLT) untuk uji coba UI

## Instalasi

```bash
cd zte_c320_monitor
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Konfigurasi

```bash
cp .env.example .env
# edit .env — isi IP OLT, community, dll.
```

Untuk test UI tanpa OLT, set `DEMO_MODE=true`.

## Jalankan

```bash
python app.py
```

Buka browser: http://127.0.0.1:5000

## Mapping ODP

1. Menu **Mapping ODP**
2. Upload file CSV dengan kolom `serial,odp`  
   atau JSON: `{"ZTEGXXXXXXXX": "ODP-NAMA", ...}`
3. Atau tambah manual satu per satu

Contoh CSV:

```csv
serial,odp
ZTEG12345678,ODP-BLOKA-01
ZTEG87654321,ODP-BLOKB-02
```

## Catatan

- SNMP harus bisa diakses dari mesin yang menjalankan app (UDP 161).
- Index ifIndex ZTE cukup kompleks; app mencoba walk + parse otomatis.
- Jika data tidak muncul, coba ganti `FIRMWARE_MODE` ke `v1` atau `v2` di Settings / `.env`.
- Untuk production, sebaiknya jalankan di belakang reverse proxy dan batasi akses.

## Struktur

```
zte_c320_monitor/
├── app.py              # Flask main
├── config.py           # Konfigurasi
├── snmp_zte.py         # SNMP logic
├── odp_mapping.py      # Mapping ODP
├── requirements.txt
├── .env.example
├── data/
│   └── odp_mapping.csv
└── templates/
    ├── base.html
    ├── index.html
    ├── odp.html
    └── settings.html
```
