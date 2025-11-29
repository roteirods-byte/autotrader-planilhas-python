#!/usr/bin/env bash
set -euo pipefail

# Diretório do projeto na VM
PROJECT_DIR="/home/roteiro_ds/autotrader-planilhas-python"
VENV_DIR="$PROJECT_DIR/venv"
LOG_FILE="$PROJECT_DIR/worker_entrada_cron.log"

cd "$PROJECT_DIR"

# Ativa o ambiente virtual, se existir
if [ -d "$VENV_DIR" ]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando loop contínuo do worker_entrada (intervalo ~5 minutos)..." >> "$LOG_FILE"

while true; do
  TS="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[$TS] Executando worker_entrada..." >> "$LOG_FILE"

  # Executa o worker e registra saída no log
  python worker_entrada.py >> "$LOG_FILE" 2>&1 || echo "[$TS] ERRO na execução do worker_entrada.py" >> "$LOG_FILE"

  # Intervalo entre execuções (segundos)
  # Recomendado para swing/posicional:
  # - começar com 300s (5 min)
  # - se tudo estiver leve, pode reduzir para 180s (3 min)
  sleep 300
done
