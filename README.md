# srtsirius-mining

Bot auto-mining untuk aplikasi **Sirius**. Taruh key di satu file, jalan terus — semua akun diurus sendiri-sendiri.

Bisa ratusan akun, satu proses.

## Isinya

- **Login** pakai key, token di-refresh otomatis
- **Pasang kode invite** kalau akunnya belum punya
- **Nyalain mining** kalau mati — termasuk pas reset 24 jam
- **Kerjain task** yang belum dikerjakan
- **Cek saldo** tiap cycle

Semua akun punya jam mining sendiri-sendiri (dihitung dari waktu akun itu mulai), jadi nggak perlu disinkronkan.

## Cara pasang

Butuh Python 3.8+ sama internet. Nggak ada browser, nggak ada Playwright — ringan.

### Di HP (Termux)

1. Install **Termux** (dari F-Droid, ambil yang paling baru).

2. Buka Termux, jalanin ini satu-satu:

```bash
pkg update && pkg upgrade
pkg install python git python-cryptography
python -m pip install requests
```

Catatan: `cryptography` memang harus lewat `pkg` (bukan `pip`) — di Termux pip nggak bisa nge-build itu.

3. Ambil botnya:

```bash
git clone https://github.com/AoiNode/srtsirius-mining.git
cd srtsirius-mining
```

4. Siapkan dua file. Ini aja yang nggak ikut ke GitHub (biar rahasia):

```bash
cp accounts.example.txt accounts.txt
cp invite.example.txt invite.txt
nano accounts.txt     # tempel key, satu baris satu akun. Selesai: Ctrl+X lalu Y
nano invite.txt       # isi kode invite kamu, satu baris
```

5. Nyalain:

```bash
termux-wake-lock
./run.sh
```

`run.sh` ngecek dependensi dulu — kalau `requests`/`cryptography` belum ada, dia pasang sendiri. Jadi `ModuleNotFoundError: No module named 'cryptography'` nggak bakal kejadian lagi. Abis itu jalan terus: kalau python-nya ke-close, nyala lagi 10 detik kemudian.

6. Mau lihat lagi jalan apa nggak:

```bash
tail -f log.txt
```

Matiin: `Ctrl+C`.

### Di server / VPS

```bash
git clone https://github.com/AoiNode/srtsirius-mining.git
cd srtsirius-mining
python3 -m venv .venv
.venv/bin/pip install requests cryptography
./run.sh
```

### Kalau error

| Error | Solusinya |
|---|---|
| `ModuleNotFoundError: No module named 'cryptography'` | di Termux: `pkg install python-cryptography` lalu `python -m pip install requests` |
| `Target triple not supported by rustup` / gagal build `cryptography` | pip memang nggak bisa build itu di Termux — pakai `pkg install python-cryptography` |
| `Permission denied` | `chmod +x run.sh` |
| `pkg: command not found` | kamu belum di Termux / Termux belum keinstall |
| bot langsung ke-close | cek `log.txt`, kemungkinan kena rate limit — tunggu sebentar lalu `./run.sh` lagi |

## Pakai

**1. Buat file key**

```bash
cp accounts.example.txt accounts.txt
```

Isi `accounts.txt` — satu key per baris:

```
1f0a7c3e9b2d4856a7c9e01b3d5f7a9c2e4b6d8f0a1c3e5b7d9f1a3c5e7b9d1f
2a1b8d4f6c0e3759b2d4f6a8c0e2b4d6f8a0c2e4b6d8f0a2c4e6b8d0f2a4c6e8
```

Mau nambah akun tinggal tambah baris — bot baca ulang tiap cycle, nggak perlu restart.

**2. Kode invite**

```bash
cp invite.example.txt invite.txt
```

Isi `invite.txt` dengan kode invite kamu (satu baris). Dipakai buat semua akun yang belum punya inviter. Kalau cuma mau beda buat 1 akun, tulis di `accounts.txt`:

```
<key> <kode_invite>
```

**3. Jalanin**

```bash
./run.sh                # jalan terus + auto-restart
./run.sh --once         # sekali jalan, lalu keluar
python3 bot.py          # jalan tanpa pelindung (sekali error ya berhenti)
```

## Contoh log

```
Bot starting... 2 akun  (2026-10-03 15:12 UTC)
Account 1/2  Ab12Cd  ...........  Mining success   saldo 25.8332   task 5/5   reward 0.8332
Account 2/2  Xy34Zz  ...........  Mining success   saldo 25.4166   task 5/5   reward 0.4166
Done — 2 success, 0 failed — total 51.2498 SST (11s)
```

Tiap baris keluar **begitu akunnya selesai** — bukan nunggu semua akun beres. Jadi keliatan langsung jalan atau nggak.

Yang ada di belakang cuma kalau ada yang berubah:

```
Account 1/2  Ab12Cd  ..........  Mining success   saldo 50.0000   task 5/5   [mining dimulai]
Account 2/2  Xy34Zz  ..........  Mining success   saldo 50.0000   task 5/5   [task 5 (+25.0000)]
Account 3/3  deadbeef ........  Failed — login 401 AUTH_INVALID_CREDENTIAL (gagal 3x, dilewati dulu)
```

Isinya juga ditulis ke `log.txt`. **Log dibersihkan tiap cycle baru** — jadi file itu cuma nyimpen 1 cycle terakhir, nggak pernah numpuk walau jalan berbulan-bulan.

## Supaya nggak ketahuan bot

Pola kerjanya sengaja dibikin nggak kaku:

- jeda antar request **acak** 0,7–2,4 detik
- sesekali jeda panjang 4–13 detik (kayak orang baca layar)
- urutan akun **diacak** tiap cycle
- jeda antar akun 2–6 detik
- delay 3–15 detik sebelum nyalain mining
- cycle **8,5–13 menit** (bukan pas 10 menit)
- **01:00–06:00 WIB** pelanin ke 25–40 menit sekali
- token di-refresh, bukan login ulang terus (login itu event paling mencurigakan)
- kena rate limit → diam sesuai `retryAfter`

## Opsi environment

| Variabel | Default | Fungsi |
|---|---|---|
| `SIRIUS_POLL` | `600` | jeda dasar antar cycle (detik) |
| `SIRIUS_ACCOUNTS` | `./accounts.txt` | lokasi file key |
| `SIRIUS_INVITE` | `./invite.txt` | lokasi file kode invite |
| `SIRIUS_RETRY` | `3` | berapa kali akun yang gagal dicoba ulang |

## Gagal? Nggak mati

Kalau satu akun error (jaringan putus, token nolak, server lagi aneh):

1. dicoba ulang sampai **3 kali** (dengan jeda mundur),
2. masih gagal → **dilewati cycle ini**,
3. cycle berikutnya akun itu **dicoba lagi sendiri** — nggak pernah dibuang.

Akun lain tetap jalan — satu akun rusak nggak pernah menghentikan yang lain.

Botnya sendiri juga dirancang nggak gampang mati:

- loop utama nggak pernah keluar sendiri, error cycle ditahan + backoff
- nulis log yang gagal (disk penuh) nggak bikin crash
- crash total pun tetap dicatat ke `log.txt`
- dijalankan lewat `./run.sh` → kalau python keluar, langsung nyala lagi 10 detik kemudian

## Biar nggak mati pas VPS reboot

Pakai systemd:

```bash
sudo cp srtsirius-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now srtsirius-bot
```

`Restart=always` → otomatis nyala lagi walau crash atau server reboot.
Log: `journalctl -u srtsirius-bot -f`

## Struktur file

```
bot.py                  bot utama (multi-akun)
api.py                  client API + envelope JWE
run.sh                  pelindung: restart terus kalau python keluar
srtsirius-bot.service   unit systemd buat VPS
accounts.txt            key milikmu          (tidak ikut ke git)
invite.txt              kode invite          (tidak ikut ke git)
accounts/*.json         token tiap akun      (tidak ikut ke git)
log.txt                 log                  (tidak ikut ke git)
```

## Catatan penting

- **Bot ini tidak bisa daftar akun.** Registrasi butuh verifikasi Turnstile yang cuma lolos dari aplikasinya. Daftar manual dulu di app, key-nya masukin ke `accounts.txt`.
- Key = `identityId` 64 karakter hex dari akunmu.
- `accounts.txt`, `invite.txt`, `accounts/` dan `log.txt` masuk `.gitignore` — datanya nggak akan pernah ke-commit.

## Lisensi

MIT
