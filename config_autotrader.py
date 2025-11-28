from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytz

# ====== MOEDAS OFICIAIS DO PROJETO (sempre em ordem alfabética) ======
MOEDAS_OFICIAIS = [
    "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS",
    "BCH", "BNB", "BTC",
    "DOGE", "DOT",
    "ETH",
    "FET", "FIL", "FLUX",
    "ICP", "INJ",
    "LDO", "LINK", "LTC",
    "NEAR",
    "OP",
    "PEPE", "POL",
    "RATS", "RENDER", "RUNE",
    "SEI", "SHIB", "SOL", "SUI",
    "TIA", "TNSR", "TON", "TRX",
    "UNI",
    "WIF",
    "XRP",
]

# ====== PASTAS E ARQUIVOS PADRÃO (JSON) ======
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

ENTRADA_JSON_PATH = DATA_DIR / "entrada.json"
SAIDA_MANUAL_JSON_PATH = DATA_DIR / "saida_manual.json"
SAIDA_MONITORAMENTO_JSON_PATH = DATA_DIR / "saida_monitoramento.json"

# ====== TIMEZONE E FORMATAÇÃO ======
TZ = pytz.timezone("America/Sao_Paulo")

PRECO_CASAS_DECIMAIS = 3
PCT_CASAS_DECIMAIS = 2

# ====== PARÂMETROS DE CÁLCULO ======
ATR_PERIODO = 14

TIMEFRAME_SWING = "4h"
TIMEFRAME_POSICIONAL = "1d"


@dataclass(frozen=True)
class SinalConfig:
    """Configuração padrão para geração de sinais."""

    ganho_minimo_pct: float = 3.0
    assertividade_minima_pct: float = 65.0


SINAL_CONFIG = SinalConfig()


def agora_data_hora_br():
    """
    Retorna (data_str, hora_str) já no fuso horário de São Paulo.
    Formatos:
      data -> 'YYYY-MM-DD'
      hora -> 'HH:MM'
    """
    now = datetime.now(TZ)
    data_str = now.strftime("%Y-%m-%d")
    hora_str = now.strftime("%H:%M")
    return data_str, hora_str


def garantir_pastas():
    """Garante que a pasta 'data/' exista antes de salvar os JSONs."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
