# config.py
import os
from zoneinfo import ZoneInfo

# Fuso horário oficial do projeto (Brasil/São Paulo)
TZINFO = ZoneInfo("America/Sao_Paulo")

# Casas decimais usadas no worker_entrada
PRICE_DECIMALS = int(os.getenv("PRICE_DECIMALS", "3"))
PCT_DECIMALS = int(os.getenv("PCT_DECIMALS", "2"))
