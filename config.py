# config.py
import os
from zoneinfo import ZoneInfo

# Fuso horário padrão do projeto (Brasil / São Paulo)
TZINFO = ZoneInfo("America/Sao_Paulo")

# Casas decimais padrão usadas no worker_entrada
PRICE_DECIMALS = int(os.getenv("PRICE_DECIMALS", 3))
PCT_DECIMALS = int(os.getenv("PCT_DECIMALS", 2))
