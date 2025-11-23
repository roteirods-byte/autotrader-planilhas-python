#!/bin/bash
cd /home/roteiro_ds/autotrader-planilhas-python
source venv/bin/activate

while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rodando worker_entrada.py REAL..."
  python worker_entrada.py
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Aguardando 5 minutos..."
  sleep 300
done
