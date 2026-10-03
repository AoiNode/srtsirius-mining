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

## Pasang

Butuh Python 3.8+.

```bash
git clone https://github.com/AoiNode/srtsirius-mining.git
cd srtsirius-mining
pip install requests cryptography
```

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
python3 bot.py          # jalan terus
python3 bot.py --once   # sekali jalan, lalu keluar
```

## Contoh log

```
14:03 UTC — 2 akun
  Ab12Cd    jalan   saldo   25.0000  reward    0.0000  task 5/5
  Xy34Zz    jalan   saldo   25.0000  reward    0.0000  task 5/5
  total 50.0000 SST
```

Yang muncul di belakang cuma kalau ada perubahan:

```
  Xy34Zz    jalan   saldo   50.0000  reward 0.4166  task 5/5   [mining dimulai]
  Ab12Cd    jalan   saldo   50.0000  reward 0.4166  task 5/5   [task 5 (+25.0000)]
  deadbeef  GAGAL  login 401 AUTH_INVALID_CREDENTIAL
```

Log juga disimpan ke `log.txt` (tiap baris ada tanggal).

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

## Jalan di HP (Termux)

```bash
pkg install python
pip install requests cryptography
termux-wake-lock
python3 bot.py
```

Butuh internet doang — nggak ada Playwright, nggak ada browser.

## Struktur file

```
bot.py                  bot utama (multi-akun)
api.py                  client API + envelope JWE
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
