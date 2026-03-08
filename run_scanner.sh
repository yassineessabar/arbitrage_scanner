#!/bin/bash
# run_scanner.sh — Keeps the scanner running in a loop, auto-restarts on crash.
cd "$(dirname "$0")"

echo "Starting arbitrage scanner (auto-restart on crash)..."

while true; do
    echo "[$(date)] Scanner starting..."
    ./venv/bin/python main.py
    EXIT_CODE=$?
    echo "[$(date)] Scanner exited with code $EXIT_CODE. Restarting in 3s..."
    sleep 3
done
