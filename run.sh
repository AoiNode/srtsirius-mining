#!/usr/bin/env bash
# Jalankan bot terus-menerus. Kalau python keluar/crash, langsung nyala lagi.
# Pakai:  ./run.sh
# Termux: termux-wake-lock  dulu, biar HP nggak tidur.

cd "$(dirname "$0")" || exit 1
PYTHON="${PYTHON:-python3}"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] bot nyala"
  "$PYTHON" -u bot.py
  code=$?
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] bot keluar (code $code) — restart dalam 10 detik"
  sleep 10
done
