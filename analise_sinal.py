"""
analise_sinal.py

Módulo de ANÁLISE DE SINAL do AUTOTRADER.

Aqui decidimos:
- LONG ou SHORT
- alvo (preço objetivo)
- ganho em %
- assertividade em %

Entrada:
    coin: str            -> "BTC", "ETH", etc.
    modo: str            -> "swing" ou "posicional"
    indicadores: dict    -> resultado de calculadora.calcular_indicadores()

Saída:
    dict com:
        {
          "sinal": "LONG" | "SHORT",
          "alvo": float,
          "ganho_pct": float,
          "assert_pct": float
        }
    ou None se o sinal não passar nos filtros mínimos.
"""

from __future__ import annotations

from typing import Dict, Optional

from config import PRICE_DECIMALS, PCT_DECIMALS  # type: ignore


# Filtros oficiais do projeto
MIN_GANHO = 3.0    # mínimo 3%
MIN_ASSERT = 65.0  # mínimo 65%

# Limites de segurança
MAX_GANHO = 30.0   # não deixar alvo absurdo
MIN_ASSERT_CLAMP = 60.0
MAX_ASSERT_CLAMP = 90.0


def _log(msg: str) -> None:
    print(f"[analise_sinal] {msg}", flush=True)


def analisar_sinal(
    coin: str,
    modo: str,
    indicadores: Dict[str, float],
) -> Optional[Dict[str, float]]:
    """
    Decide o sinal para uma moeda/mode a partir dos indicadores.

    - `modo` = "swing" ou "posicional"
    - `indicadores` precisa ter:
        preco, ema_fast, ema_slow, atr, adx
    """
    preco = float(indicadores["preco"])
    ema_fast = float(indicadores["ema_fast"])
    ema_slow = float(indicadores["ema_slow"])
    atr = float(indicadores["atr"])
    adx = float(indicadores["adx"])

    # Direção: LONG se EMA rápida acima da lenta, senão SHORT
    if ema_fast > ema_slow:
        sinal = "LONG"
    else:
        sinal = "SHORT"

    # ATR em % do preço (volatilidade relativa), com limites
    atr_pct = (atr / preco) * 100.0 if preco > 0 else 0.0
    atr_pct = max(0.5, min(atr_pct, 15.0))

    # Multiplicadores diferentes para Swing x Posicional
    if modo.lower() == "swing":
        mult = 1.2   # alvo menor, mais rápido
        base_assert = 68.0
    else:  # "posicional"
        mult = 2.0   # alvo maior, mais longo
        base_assert = 72.0

    ganho_pct_raw = atr_pct * mult
    ganho_pct_raw = max(MIN_GANHO, min(ganho_pct_raw, MAX_GANHO))

    # Alvo conforme direção
    if sinal == "LONG":
        alvo = preco * (1.0 + ganho_pct_raw / 100.0)
    else:  # SHORT
        alvo = preco * (1.0 - ganho_pct_raw / 100.0)

    # Ganho real em % (pela diferença entre preço atual e alvo)
    if sinal == "LONG":
        ganho_pct_real = ((alvo - preco) / preco) * 100.0
    else:
        ganho_pct_real = ((preco - alvo) / preco) * 100.0

    # ASSERT % baseada em:
    # - força da tendência (ADX)
    # - alinhamento entre sinal e EMAs
    adx_norm = max(0.0, min(1.0, (adx - 10.0) / 40.0))  # ADX ~10-50
    alinhado = (
        (sinal == "LONG" and ema_fast > ema_slow)
        or (sinal == "SHORT" and ema_fast < ema_slow)
    )
    align_score = 1.0 if alinhado else 0.0

    # Base + componente do ADX + bônus se alinhado
    assert_pct = base_assert + 20.0 * adx_norm + 10.0 * align_score

    # Limites finais
    assert_pct = max(MIN_ASSERT_CLAMP, min(MAX_ASSERT_CLAMP, assert_pct))

    # Filtro mínimo antes de publicar
    if ganho_pct_real < MIN_GANHO or assert_pct < MIN_ASSERT:
        _log(
            f"{coin} modo={modo}: filtrado (ganho={ganho_pct_real:.2f}%, "
            f"assert={assert_pct:.2f}%)."
        )
        return None

    # Arredondamentos oficiais do projeto
    alvo_r = round(alvo, PRICE_DECIMALS)
    ganho_r = round(ganho_pct_real, PCT_DECIMALS)
    assert_r = round(assert_pct, PCT_DECIMALS)

    return {
        "sinal": sinal,
        "alvo": alvo_r,
        "ganho_pct": ganho_r,
        "assert_pct": assert_r,
    }
