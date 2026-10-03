#!/usr/bin/env bash
# Jalankan bot terus-menerus. Kalau python keluar/crash, langsung nyala lagi.
#
#   ./run.sh            jalan terus
#   ./run.sh --once     sekali jalan, lalu keluar
#
# Termux: jalankan  termux-wake-lock  dulu, biar HP nggak tidur.

cd "$(dirname "$0")" || exit 1
PYTHON="${PYTHON:-python3}"
have() { "$PYTHON" -c "import $1" 2>/dev/null; }

# --- 1. dependensi (sekali di awal, bukan tiap restart) ---
if ! have requests || ! have cryptography; then
  echo "[$(date '+%H:%M:%S')] dependensi belum ada — pasang dulu"

  if [ -d /data/data/com.termux ]; then
    # Termux: cryptography butuh Rust buat dibuild dari pip, jadi pip pasti gagal.
    # Pakai package resmi Termux yang udah jadi binary.
    echo "  -> Termux: pakai package resmi (bukan pip)"
    pkg install -y python-cryptography >/dev/null 2>&1
    have cryptography || "$PYTHON" -m pip install --quiet cryptography
    have requests || "$PYTHON" -m pip install --quiet requests
  else
    "$PYTHON" -m pip install --quiet requests cryptography
  fi
fi

if ! have requests || ! have cryptography; then
  echo ""
  echo "Belum lengkap. Jalankan ini lalu ./run.sh lagi:"
  if [ -d /data/data/com.termux ]; then
    echo "    pkg install python-cryptography"
    echo "    python -m pip install requests"
  else
    echo "    $PYTHON -m pip install requests cryptography"
    echo "atau pakai venv:"
    echo "    $PYTHON -m venv .venv && .venv/bin/pip install requests cryptography"
    echo "    PYTHON=.venv/bin/python ./run.sh"
  fi
  exit 1
fi

# --- 2. loop utama: bot keluar apa pun alasnya, nyala lagi ---
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] bot nyala"
  "$PYTHON" -u bot.py "$@"
  code=$?
  [ "$code" -eq 0 ] && [ -n "$1" ] && exit 0      # --once: selesai, jangan diulang
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] bot keluar (code $code) — restart dalam 10 detik"
  sleep 10
done
