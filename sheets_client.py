import os
from datetime import datetime
from zoneinfo import ZoneInfo
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import config

# JSON na mesma pasta
JSON_PATH = os.path.join(os.path.dirname(__file__), "chave-automacao.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _service():
    creds = Credentials.from_service_account_file(JSON_PATH, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)

def _agora():
    return datetime.now(ZoneInfo("America/Sao_Paulo"))

def _primeiro_range_valido(ranges):
    svc = _service()
    for rg in ranges:
        try:
            resp = svc.spreadsheets().values().get(
                spreadsheetId=config.SHEETS_SPREADSHEET_ID,
                range=rg
            ).execute()
            vals = resp.get("values", [])
            if vals:
                return rg, vals
        except Exception:
            continue
    return None, []

def get_moedas():
    _, rows = _primeiro_range_valido(config.RANGE_MOEDAS)
    out = []
    for r in rows:
        if not r:
            continue
        t = str(r[0]).strip().upper()
        if t:
            out.append(t)
    return out

def append_log(texto):
    dt = _agora()
    linha = [[dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"), texto]]
    _service().spreadsheets().values().append(
        spreadsheetId=config.SHEETS_SPREADSHEET_ID,
        range=config.RANGE_LOG[0],  # LOG!A:C
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": linha}
    ).execute()
