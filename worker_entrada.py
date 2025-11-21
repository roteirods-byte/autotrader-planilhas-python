#!/usr/bin/env python3
"""
worker_entrada.py

Orquestrador da ENTRADA do AUTOTRADER.

Fluxo:
- Para cada moeda do universo oficial:
    * Busca candles pela camada de CONEXÃO (exchanges.get_ohlcv)
    * Calcula indicadores (calculadora.calcular_indicadores)
    * Analisa o sinal (analise_sinal.analisar_sinal)
- Monta as listas de:
    * swing  (timeframe 4h)
    * posicional (timeframe 1d)
- Salva tudo em entrada.json para o PAINEL ENTRADA.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List

from config import TZINFO, PRICE_DECIMALS, PCT_DECIMALS  # type: ignore
from exchanges import get_ohlcv  # camada A
from calculadora import calcular_indicadores  # camada B
from analise_sinal import analisar_sinal  # camada C


# ============================
# CONFIGURAÇÃO GERAL
# ============================

# Universo fixo de moedas (sem "USDT", ordem alfabética)
COINS = sorted(
    [
        "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH", "BNB",
        "BTC", "DOGE", "DOT", "ETH", "FET", "FIL", "FLUX", "ICP", "INJ",
        "LDO", "LINK", "LTC", "NEAR", "OP", "PEPE", "POL", "RATS", "RENDER",
        "RUNE", "SEI", "SHIB", "SOL", "SUI", "TIA", "TNSR", "TON", "TRX",
        "UNI", "WIF", "XRP",
    ]
)

# Timeframes oficiais
TIMEFRAME_SWING = "4h"   # Swing  (painel: ENTRADA 4H – SWING)
TIMEFRAME_POSICIONAL = "1d"  # Posicional (painel: ENTRADA 1D – POSICIONAL)

# Caminho padrão do JSON de saída
ENTRADA_JSON_PATH = os.getenv("ENTRADA_JSON_PATH", "entrada.json")


# ============================
# MODELOS E HELPERS
# ============================

@dataclass
class SinalEntrada:
    par: str
    sinal: str
    preco: float
    alvo: float
    ganho_pct: float
    assert_pct: float
    data: str
    hora: str


def _now_brt() -> datetime:
    return datetime.now(TZINFO)


def _log(msg: str) -> None:
    ts = _now_brt().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [worker_entrada] {msg}", flush=True)


# ============================
# GERAÇÃO DE SINAIS
# ============================

def _gerar_sinais_por_modo(
    modo: str,
    timeframe: str,
) -> List[SinalEntrada]:
    """
    Gera lista de sinais para um modo específico:
    - modo: "swing" ou "posicional"
    - timeframe: "4h" ou "1d"
    """
    resultados: List[SinalEntrada] = []
    _log(f"Iniciando geração de sinais ({modo}, tf={timeframe})...")

    for coin in COINS:
        # 1) Coleta de candles (camada A)
        df = get_ohlcv(coin, timeframe=timeframe, limit=200)
        if df is None:
            _log(f"{coin} {modo}: sem dados de candles, pulando.")
            continue

        # 2) Cálculos (camada B)
        indicadores = calcular_indicadores(df)
        if indicadores is None:
            _log(f"{coin} {modo}: não foi possível calcular indicadores, pulando.")
            continue

        # 3) Análise de sinal (camada C)
        sinal_info = analisar_sinal(coin, modo, indicadores)
        if sinal_info is None:
            # Filtrado pelos critérios (ganho >= 3%, assert >= 65%)
            continue

        preco = float(indicadores["preco"])
        alvo = float(sinal_info["alvo"])
        ganho_pct = float(sinal_info["ganho_pct"])
        assert_pct = float(sinal_info["assert_pct"])
        sinal = str(sinal_info["sinal"]).upper()

        # Arredondamentos finais conforme projeto
        preco_r = round(preco, PRICE_DECIMALS)
        alvo_r = round(alvo, PRICE_DECIMALS)
        ganho_r = round(ganho_pct, PCT_DECIMALS)
        assert_r = round(assert_pct, PCT_DECIMALS)

        ts = _now_brt()
        data_str = ts.strftime("%Y-%m-%d")
        hora_str = ts.strftime("%H:%M")

        resultados.append(
            SinalEntrada(
                par=coin,
                sinal=sinal,
                preco=preco_r,
                alvo=alvo_r,
                ganho_pct=ganho_r,
                assert_pct=assert_r,
                data=data_str,
                hora=hora_str,
            )
        )

    # Ordena alfabeticamente por par
    resultados.sort(key=lambda s: s.par)
    _log(f"Finalizado modo={modo}: {len(resultados)} sinais aprovados.")
    return resultados


def gerar_sinais() -> Dict[str, object]:
    """
    Gera o payload completo de entrada:
    {
      "generated_at": "...",
      "swing": [...],
      "posicional": [...]
    }
    """
    _log(f"Iniciando geração de sinais para {len(COINS)} moedas...")

    swing = _gerar_sinais_por_modo("swing", TIMEFRAME_SWING)
    posicional = _gerar_sinais_por_modo("posicional", TIMEFRAME_POSICIONAL)

    payload = {
        "generated_at": _now_brt().isoformat(),
        "swing": [asdict(s) for s in swing],
        "posicional": [asdict(s) for s in posicional],
    }

    _log(
        "Sinais gerados (resumo): "
        f"{len(payload['swing'])} swing, "
        f"{len(payload['posicional'])} posicional."
    )

    return payload


# ============================
# PERSISTÊNCIA
# ============================

def salvar_json(payload: Dict[str, object]) -> None:
    """Salva o payload em ENTRADA_JSON_PATH de forma atômica."""
    tmp_path = ENTRADA_JSON_PATH + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    os.replace(tmp_path, ENTRADA_JSON_PATH)
    _log(f"Arquivo salvo em: {ENTRADA_JSON_PATH}")


# ============================
# MAIN
# ============================

def main() -> None:
    _log("Iniciando worker_entrada...")
    payload = gerar_sinais()
    salvar_json(payload)
    _log("worker_entrada finalizado com sucesso.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("Encerrado pelo usuário (Ctrl+C).")
