#!/usr/bin/env bash
# Jalankan bot terus-menerus. Kalau python keluar/crash, langsung nyala lagi.
#
#   ./run.sh            jalan terus
#   ./run.sh --once     sekali jalan, lalu keluar
#
# Termux: jalankan  termux-wake-lock  dulu, biar HP nggak tidur.

cd "$(dirname "$0")" || exit 1
PYTHON="${PYTHON:-python3}"

# --- 1. pastikan dependensi ada (sekali di awal, bukan tiap restart) ---
if ! "$PYTHON" -c "import requests, cryptography" 2>/dev/null; then
  echo "[$(date '+%H:%M:%S')] dependensi belum ada — pasang dulu ya"
  if "$PYTHON" -m pip install --quiet requests cryptography; then
    echo "[$(date '+%H:%M:%S')] requests + cryptography siap"
  else
    echo ""
    echo "Gagal pasang otomatis. Coba jalankan ini lalu jalankan ./run.sh lagi:"
    echo "    $PYTHON -m pip install requests cryptography"
    echo ""
    echo "Kalau tetap gagal, pakai venv:"
    echo "    $PYTHON -m venv .venv && .venv/bin/pip install requests cryptography"
    echo "    PYTHON=.venv/bin/python ./run.sh"
    exit 1
  fi
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
