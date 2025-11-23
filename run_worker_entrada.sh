#!/bin/bash
# Script para rodar o worker de ENTRADA a cada execução

cd /home/roteiro_ds/autotrader-planilhas-python
source venv/bin/activate
python worker_entrada.py >> worker_entrada_cron.log 2>&1
