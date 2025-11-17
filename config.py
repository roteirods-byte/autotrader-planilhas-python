# config.py
import os
from zoneinfo import ZoneInfo

SHEETS_SPREADSHEET_ID = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
TZINFO = ZoneInfo("America/Sao_Paulo")

RANGE_LOG     = ["LOG!A:C"]
RANGE_MOEDAS  = ["MOEDAS!A2:A", "MOEDAS!A:A", "MOEDA!A2:A", "Moedas!A2:A", "Moeda!A2:A"]
RANGE_SAIDA2  = ["SAÍDA 2!A:K", "SAIDA 2!A:K"]
RANGE_ENTRADA = ["ENTRADA!A:I"]
RANGE_EMAIL   = ["EMAIL!A:D"]

PRICE_DECIMALS = 3
PCT_DECIMALS   = 2
