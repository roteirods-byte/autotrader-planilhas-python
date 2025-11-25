#!/usr/bin/env python3
"""
worker_entrada.py  (MODO REAL, FIBO PROFISSIONAL)

- Usa dados REAIS das corretoras (Binance + Bybit) via ccxt.
- Calcula sinais para:
    * SWING  (4H)
    * POSICIONAL (1D)
- Para cada moeda e modo:
    * Calcula ATR, EMAs, ADX, swing high/low recentes.
    * Calcula 3 ALVOS (Fibonacci + ATR):
        - ALVO_1, ALVO_2, ALVO_3
        - GANHO_1_PCT, GANHO_2_PCT, GANHO_3_PCT.
    * Define a direção base:
        - LONG  (tendência de alta)
        - SHORT (tendência de baixa)
    * Define o sinal final:
        - se GANHO_1_PCT < 3.0 → "NAO ENTRAR"
        - se GANHO_1_PCT >= 3.0 → LONG ou SHORT

Saída: arquivo JSON entrada.json com campos:
- par, sinal, preco, alvo, ganho_pct, assert_pct, data, hora
- campos extras para o painel de SAÍDA:
  alvo_1, ganho_1_pct, alvo_2, ganho_2_pct, alvo_3, ganho_3_pct, sinal_base
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import ccxt  # type: ignore
import numpy as np
import pandas as pd
import ta  # type: ignore

from config import TZINFO, PRICE_DECIMALS, PCT_DECIMALS

# ====== CONSTANTES DO PROJETO ======

# Universo fixo de 39 moedas (sem "USDT")
COINS: List[str] = [
    "AAVE",
    "ADA",
    "APT",
    "ARB",
    "ATOM",
    "AVAX",
    "AXS",
    "BCH",
    "BNB",
    "BTC",
    "DOGE",
    "DOT",
    "ETH",
    "FET",
    "FIL",
    "FLUX",
    "ICP",
    "INJ",
    "LDO",
    "LINK",
    "LTC",
    "NEAR",
    "OP",
    "PEPE",
    "POL",
    "RATS",
    "RENDER",
    "RUNE",
    "SEI",
    "SHIB",
    "SOL",
    "SUI",
    "TIA",
    "TNSR",
    "TON",
    "TRX",
    "UNI",
    "WIF",
    "XRP",
]

BASE = "USDT"

# Timeframes por modo
SWING_TIMEFRAME = "4h"
POSICIONAL_TIMEFRAME = "1d"
CANDLE_LIMIT = 200  # candles por modo/moeda

# Parâmetros técnicos
ATR_LEN = 14
EMA_FAST = 9
EMA_SLOW = 21
ADX_LEN = 14
FIB_LOOKBACK = 55  # candles para swing high/low
MIN_GAIN_PCT = 3.0  # filtro de NAO ENTRAR baseado em GANHO_1

# Peso da assertividade (tudo 0–1, depois convertemos para %)
ADX_MIN = 15.0
ADX_MAX = 40.0
EMA_DIFF_MAX = 3.0  # % de distância entre EMAs onde saturamos a força

# ====== ESTRUTURAS ======


@dataclass
class IndicatorContext:
    price: float
    atr: float
    ema_fast: float
    ema_slow: float
    adx: float
    swing_high: float
    swing_low: float


@dataclass
class Targets:
    alvo_1: float
    alvo_2: float
    alvo_3: float
    ganho_1_pct: float
    ganho_2_pct: float
    ganho_3_pct: float


# ====== LOG SIMPLES ======


def _log(msg: str) -> None:
    now = datetime.now(TZINFO).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


# ====== EXCHANGES (BINANCE + BYBIT) ======


def create_exchanges() -> Dict[str, ccxt.Exchange]:
    """
    Cria instâncias de Binance e Bybit com rate limit habilitado.
    """
    _log("Inicializando conexões com Binance e Bybit...")
    binance = ccxt.binance({"enableRateLimit": True})
    bybit = ccxt.bybit({"enableRateLimit": True})
    return {"binance": binance, "bybit": bybit}


def fetch_ohlcv_with_backup(
    exchanges: Dict[str, ccxt.Exchange],
    symbol: str,
    timeframe: str,
    limit: int,
    sleep_between: float = 0.2,
) -> Optional[List[List[float]]]:
    """
    Tenta buscar OHLCV primeiro na Binance e depois na Bybit.
    Retorna a lista de candles ou None em caso de falha.
    """
    errors: List[str] = []
    for name in ("binance", "bybit"):
        ex = exchanges.get(name)
        if ex is None:
            continue
        try:
            _log(f"Buscando OHLCV {symbol} {timeframe} em {name}...")
            data = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            time.sleep(sleep_between)
            return data
        except Exception as e:  # noqa: BLE001
            msg = f"{name}: {e!r}"
            errors.append(msg)
            _log(f"Erro em {name} para {symbol} {timeframe}: {e!r}")
            continue

    _log(f"FALHA ao buscar OHLCV para {symbol} {timeframe} ({'; '.join(errors)})")
    return None


# ====== CÁLCULO DE INDICADORES ======


def build_indicator_context(ohlcv: List[List[float]]) -> Optional[IndicatorContext]:
    """
    Converte OHLCV em DataFrame e calcula ATR, EMAs, ADX, swing high/low.
    """
    if not ohlcv or len(ohlcv) < ATR_LEN + 5:
        return None

    df = pd.DataFrame(
        ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"], unit="ms")
        .dt.tz_localize("UTC")
        .dt.tz_convert(TZINFO)
    )

    high = df["high"]
    low = df["low"]
    close = df["close"]

    # ATR
    atr_ind = ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=ATR_LEN
    )
    df["atr"] = atr_ind.average_true_range()

    # EMAs
    ema_fast_ind = ta.trend.EMAIndicator(close=close, window=EMA_FAST)
    ema_slow_ind = ta.trend.EMAIndicator(close=close, window=EMA_SLOW)
    df["ema_fast"] = ema_fast_ind.ema_indicator()
    df["ema_slow"] = ema_slow_ind.ema_indicator()

    # ADX
    adx_ind = ta.trend.ADXIndicator(
        high=high, low=low, close=close, window=ADX_LEN
    )
    df["adx"] = adx_ind.adx()

    ctx_row = df.iloc[-1]
    price = float(ctx_row["close"])
    atr = float(ctx_row["atr"])
    ema_fast = float(ctx_row["ema_fast"])
    ema_slow = float(ctx_row["ema_slow"])
    adx = float(ctx_row["adx"])

    # swing high/low dos últimos FIB_LOOKBACK candles
    window = df.tail(FIB_LOOKBACK)
    swing_high = float(window["high"].max())
    swing_low = float(window["low"].min())

    if price <= 0 or np.isnan(price):
        return None

    # Sanitiza ATR e swing range
    if atr <= 0 or np.isnan(atr):
        atr = abs(swing_high - swing_low) / 20.0 if swing_high > swing_low else price * 0.01

    return IndicatorContext(
        price=price,
        atr=atr,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        adx=adx,
        swing_high=swing_high,
        swing_low=swing_low,
    )


# ====== DIREÇÃO (LONG / SHORT) ======


def infer_direction(ctx: IndicatorContext) -> str:
    """
    Direção baseada na relação EMA rápida vs EMA lenta.
    """
    if ctx.ema_fast > ctx.ema_slow * 1.001:
        return "LONG"
    if ctx.ema_fast < ctx.ema_slow * 0.999:
        return "SHORT"
    return "NAO ENTRAR"


# ====== FIBONACCI + ATR: CÁLCULO DOS ALVOS ======


def compute_fibo_targets(direction: str, ctx: IndicatorContext) -> Targets:
    """
    Alvos usando extensão de Fibonacci sobre o range swing_high/low
    combinada com ATR para evitar alvos irreais.

    - Para LONG: preço + delta_x
    - Para SHORT: preço - delta_x
    """
    price = ctx.price
    swing_range = max(ctx.swing_high - ctx.swing_low, 0.0000001)
    atr = max(ctx.atr, price * 0.005)  # pelo menos 0.5% do preço

    # Razões de Fibonacci "clássicas" (23.6 / 38.2 / 61.8),
    # usadas como múltiplos do swing_range. Sempre garantindo >= 1 ATR.
    fib_ratios = [0.236, 0.382, 0.618]
    deltas: List[float] = []

    for r in fib_ratios:
        base_delta = swing_range * r
        delta = max(base_delta, atr)
        deltas.append(delta)

    targets: List[float] = []
    gains_pct: List[float] = []

    for delta in deltas:
        if direction == "LONG":
            t = price + delta
            g = (t - price) / price * 100.0
        elif direction == "SHORT":
            t = max(price - delta, 0.0000001)
            g = (price - t) / price * 100.0
        else:
            # direção neutra: devolve o próprio preço e ganho 0
            t = price
            g = 0.0

        targets.append(t)
        gains_pct.append(g)

    return Targets(
        alvo_1=targets[0],
        alvo_2=targets[1],
        alvo_3=targets[2],
        ganho_1_pct=gains_pct[0],
        ganho_2_pct=gains_pct[1],
        ganho_3_pct=gains_pct[2],
    )


# ====== ASSERTIVIDADE (0–100%) ======


def compute_assertiveness(direction: str, ctx: IndicatorContext) -> float:
    """
    Score empírico 0–100 com base em:
    - ADX (força da tendência)
    - distância entre EMAs
    - direção definida (LONG/SHORT vs neutro)
    """
    if direction == "NAO ENTRAR":
        return 0.0

    # Força ADX normalizada
    adx = max(ctx.adx, 0.0)
    adx_norm = (adx - ADX_MIN) / (ADX_MAX - ADX_MIN)
    adx_norm = float(np.clip(adx_norm, 0.0, 1.0))

    # Distância relativa entre EMAs
    ema_diff_pct = abs(ctx.ema_fast - ctx.ema_slow) / ctx.price * 100.0
    ema_norm = ema_diff_pct / EMA_DIFF_MAX
    ema_norm = float(np.clip(ema_norm, 0.0, 1.0))

    # Combinação ponderada
    score_0_1 = 0.6 * adx_norm + 0.4 * ema_norm

    # Mapeia para uma faixa 40–95%
    assert_pct = 40.0 + score_0_1 * 55.0
    return float(np.clip(assert_pct, 0.0, 100.0))


# ====== SINAL POR MOEDA/MODO ======


def build_signal_for_coin(
    coin: str,
    mode: str,
    exchanges: Dict[str, ccxt.Exchange],
) -> Dict[str, object]:
    """
    Calcula o sinal completo para uma moeda em um modo (SWING ou POSICIONAL).
    """
    symbol = f"{coin}/{BASE}"
    timeframe = SWING_TIMEFRAME if mode == "SWING" else POSICIONAL_TIMEFRAME

    now = datetime.now(TZINFO)
    data_str = now.strftime("%Y-%m-%d")
    hora_str = now.strftime("%H:%M")

    ohlcv = fetch_ohlcv_with_backup(exchanges, symbol, timeframe, CANDLE_LIMIT)
    if ohlcv is None:
        # Falha → devolve linha neutra
        return {
            "par": coin,
            "sinal": "NAO ENTRAR",
            "preco": 0.0,
            "alvo": 0.0,
            "ganho_pct": 0.0,
            "assert_pct": 0.0,
            "data": data_str,
            "hora": hora_str,
            "alvo_1": 0.0,
            "ganho_1_pct": 0.0,
            "alvo_2": 0.0,
            "ganho_2_pct": 0.0,
            "alvo_3": 0.0,
            "ganho_3_pct": 0.0,
            "sinal_base": "NAO ENTRAR",
        }

    ctx = build_indicator_context(ohlcv)
    if ctx is None:
        return {
            "par": coin,
            "sinal": "NAO ENTRAR",
            "preco": 0.0,
            "alvo": 0.0,
            "ganho_pct": 0.0,
            "assert_pct": 0.0,
            "data": data_str,
            "hora": hora_str,
            "alvo_1": 0.0,
            "ganho_1_pct": 0.0,
            "alvo_2": 0.0,
            "ganho_2_pct": 0.0,
            "alvo_3": 0.0,
            "ganho_3_pct": 0.0,
            "sinal_base": "NAO ENTRAR",
        }

    direction = infer_direction(ctx)
    targets = compute_fibo_targets(direction, ctx)
    assert_pct = compute_assertiveness(direction, ctx)

    # Aplica filtro: se GANHO_1 < 3%, sinal vira NAO ENTRAR,
    # mas mantemos todos os cálculos na linha.
    sinal_final = direction
    if targets.ganho_1_pct < MIN_GAIN_PCT:
        sinal_final = "NAO ENTRAR"

    preco_fmt = round(ctx.price, PRICE_DECIMALS)
    alvo1_fmt = round(targets.alvo_1, PRICE_DECIMALS)
    alvo2_fmt = round(targets.alvo_2, PRICE_DECIMALS)
    alvo3_fmt = round(targets.alvo_3, PRICE_DECIMALS)

    ganho1_fmt = round(targets.ganho_1_pct, PCT_DECIMALS)
    ganho2_fmt = round(targets.ganho_2_pct, PCT_DECIMALS)
    ganho3_fmt = round(targets.ganho_3_pct, PCT_DECIMALS)

    assert_fmt = round(assert_pct, PCT_DECIMALS)

    # IMPORTANTE:
    # - campo "alvo" e "ganho_pct" continuam sendo o ALVO 1 (para o painel ENTRADA)
    # - campos extras serão usados depois no PAINEL SAÍDA.
    return {
        "par": coin,
        "sinal": sinal_final,
        "preco": preco_fmt,
        "alvo": alvo1_fmt,
        "ganho_pct": ganho1_fmt,
        "assert_pct": assert_fmt,
        "data": data_str,
        "hora": hora_str,
        "alvo_1": alvo1_fmt,
        "ganho_1_pct": ganho1_fmt,
        "alvo_2": alvo2_fmt,
        "ganho_2_pct": ganho2_fmt,
        "alvo_3": alvo3_fmt,
        "ganho_3_pct": ganho3_fmt,
        "sinal_base": direction,
    }


# ====== LOOP PRINCIPAL (TODAS AS MOEDAS) ======


def gerar_sinais_reais() -> Dict[str, object]:
    exchanges = create_exchanges()

    swing_rows: List[Dict[str, object]] = []
    pos_rows: List[Dict[str, object]] = []

    # Mantém a ordem alfabética fixa
    for coin in COINS:
        _log(f"Gerando sinais para {coin} – SWING...")
        swing_rows.append(build_signal_for_coin(coin, "SWING", exchanges))

    for coin in COINS:
        _log(f"Gerando sinais para {coin} – POSICIONAL...")
        pos_rows.append(build_signal_for_coin(coin, "POSICIONAL", exchanges))

    generated_at = datetime.now(TZINFO).isoformat()

    return {
        "generated_at": generated_at,
        "swing": swing_rows,
        "posicional": pos_rows,
    }


def salvar_json(payload: Dict[str, object], path: str = "entrada.json") -> None:
    _log(f"Salvando arquivo JSON em {path}...")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    _log("Executando worker_entrada REAL (FIBO + TENDÊNCIA + ATR)...")
    payload = gerar_sinais_reais()
    salvar_json(payload)
    _log("worker_entrada REAL finalizado com sucesso.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("Encerrado pelo usuário (Ctrl+C).")
