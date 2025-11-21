#!/usr/bin/env python3
"""
worker_entrada.py

Orquestrador da ENTRADA do AUTOTRADER.

- MODO_DEMO = True  -> gera sinais internos, sem corretoras,
                      apenas para alimentar o painel ENTRADA.
- MODO_DEMO = False -> usa exchanges (KuCoin, Gate.io, OKX) +
                       calculadora + analise_sinal.

Saída: entrada.json no formato:
{
  "generated_at": "...",
  "swing": [...],
  "posicional": [...]
}
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List

from config import TZINFO, PRICE_DECIMALS, PCT_DECIMALS  # type: ignore
from exchanges import get_ohlcv  # camada A (usado só no modo real)
from calculadora import calcular_indicadores  # camada B
from analise_sinal import analisar_sinal  # camada C

# ============================
# CONFIGURAÇÃO GERAL
# ============================

# Liga/desliga modo DEMO (pode mudar para False no futuro)
MODO_DEMO = os.getenv("MODO_DEMO_ENTRADA", "true").lower() == "true"

# Universo fixo de moedas
COINS = sorted(
    [
        "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH", "BNB",
        "BTC", "DOGE", "DOT", "ETH", "FET", "FIL", "FLUX", "ICP", "INJ",
        "LDO", "LINK", "LTC", "NEAR", "OP", "PEPE", "POL", "RATS", "RENDER",
        "RUNE", "SEI", "SHIB", "SOL", "SUI", "TIA", "TNSR", "TON", "TRX",
        "UNI", "WIF", "XRP",
    ]
)

# Timeframes oficiais (para modo real)
TIMEFRAME_SWING = "4h"
TIMEFRAME_POSICIONAL = "1d"

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
# MODO DEMO – GERAÇÃO INTERNA
# ============================

def _gerar_sinais_demo_para_modo(modo: str) -> List[SinalEntrada]:
    """
    Gera sinais sintéticos (demo) para todas as moedas.

    - Valores diferentes por moeda.
    - Swing: ganhos menores (~3–6%), assert 68–80%.
    - Posicional: ganhos maiores (~8–12%), assert 72–84%.
    """
    resultados: List[SinalEntrada] = []
    ts = _now_brt()
    data_str = ts.strftime("%Y-%m-%d")
    hora_str = ts.strftime("%H:%M")

    for i, coin in enumerate(COINS):
        # Preço base varia por moeda e modo
        base_preco = 10.0 + (i * 7.5)
        if modo == "posicional":
            base_preco *= 1.1

        # Define direção LONG/SHORT alternando
        if (i % 2 == 0 and modo == "swing") or (i % 3 == 0 and modo == "posicional"):
            sinal = "LONG"
        else:
            sinal = "SHORT"

        # GANHO % varia por moeda e modo
        if modo == "swing":
            ganho_base = 3.0 + (i % 5) * 0.35  # ~3.0 a ~4.4
        else:
            ganho_base = 8.0 + (i % 6) * 0.5   # ~8.0 a ~10.5

        # ASSERT % varia por moeda
        if modo == "swing":
            assert_base = 68.0 + (i % 4) * 1.8  # ~68–73
        else:
            assert_base = 72.0 + (i % 4) * 2.0  # ~72–78

        preco = round(base_preco, PRICE_DECIMALS)

        if sinal == "LONG":
            alvo = preco * (1.0 + ganho_base / 100.0)
        else:
            alvo = preco * (1.0 - ganho_base / 100.0)

        ganho_pct = ganho_base
        assert_pct = max(65.0, min(88.0, assert_base))

        resultados.append(
            SinalEntrada(
                par=coin,
                sinal=sinal,
                preco=round(preco, PRICE_DECIMALS),
                alvo=round(alvo, PRICE_DECIMALS),
                ganho_pct=round(ganho_pct, PCT_DECIMALS),
                assert_pct=round(assert_pct, PCT_DECIMALS),
                data=data_str,
                hora=hora_str,
            )
        )

    resultados.sort(key=lambda s: s.par)
    _log(f"[DEMO] Gerados {len(resultados)} sinais para modo={modo}.")
    return resultados


def gerar_sinais_demo() -> Dict[str, object]:
    _log("[DEMO] Iniciando geração de sinais DEMO...")
    swing = _gerar_sinais_demo_para_modo("swing")
    posicional = _gerar_sinais_demo_para_modo("posicional")

    payload = {
        "generated_at": _now_brt().isoformat(),
        "swing": [asdict(s) for s in swing],
        "posicional": [asdict(s) for s in posicional],
    }

    _log(
        f"[DEMO] Sinais gerados: {len(payload['swing'])} swing, "
        f"{len(payload['posicional'])} posicional."
    )
    return payload


# ============================
# MODO REAL – USA CORRETORAS
# ============================

def _gerar_sinais_por_modo_real(
    modo: str,
    timeframe: str,
) -> List[SinalEntrada]:
    resultados: List[SinalEntrada] = []
    _log(f"[REAL] Iniciando geração de sinais ({modo}, tf={timeframe})...")

    for coin in COINS:
        df = get_ohlcv(coin, timeframe=timeframe, limit=200)
        if df is None:
            _log(f"[REAL] {coin} {modo}: sem dados de candles, pulando.")
            continue

        indicadores = calcular_indicadores(df)
        if indicadores is None:
            _log(f"[REAL] {coin} {modo}: sem indicadores, pulando.")
            continue

        sinal_info = analisar_sinal(coin, modo, indicadores)
        if sinal_info is None:
            # Filtrado pelos critérios (ganho >= 3%, assert >= 65%)
            continue

        preco = float(indicadores["preco"])
        alvo = float(sinal_info["alvo"])
        ganho_pct = float(sinal_info["ganho_pct"])
        assert_pct = float(sinal_info["assert_pct"])
        sinal = str(sinal_info["sinal"]).upper()

        ts = _now_brt()
        data_str = ts.strftime("%Y-%m-%d")
        hora_str = ts.strftime("%H:%M")

        resultados.append(
            SinalEntrada(
                par=coin,
                sinal=sinal,
                preco=round(preco, PRICE_DECIMALS),
                alvo=round(alvo, PRICE_DECIMALS),
                ganho_pct=round(ganho_pct, PCT_DECIMALS),
                assert_pct=round(assert_pct, PCT_DECIMALS),
                data=data_str,
                hora=hora_str,
            )
        )

    resultados.sort(key=lambda s: s.par)
    _log(f"[REAL] Finalizado modo={modo}: {len(resultados)} sinais aprovados.")
    return resultados


def gerar_sinais_real() -> Dict[str, object]:
    _log("[REAL] Iniciando geração de sinais para todas as moedas...")
    swing = _gerar_sinais_por_modo_real("swing", TIMEFRAME_SWING)
    posicional = _gerar_sinais_por_modo_real("posicional", TIMEFRAME_POSICIONAL)

    payload = {
        "generated_at": _now_brt().isoformat(),
        "swing": [asdict(s) for s in swing],
        "posicional": [asdict(s) for s in posicional],
    }

    _log(
        f"[REAL] Sinais gerados: {len(payload['swing'])} swing, "
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
    if MODO_DEMO:
        _log("Executando worker_entrada em MODO_DEMO=TRUE.")
        payload = gerar_sinais_demo()
    else:
        _log("Executando worker_entrada em modo REAL (corretoras).")
        payload = gerar_sinais_real()

    salvar_json(payload)
    _log("worker_entrada finalizado com sucesso.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("Encerrado pelo usuário (Ctrl+C).")
