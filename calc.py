# calc.py
from __future__ import annotations
import numpy as np
import pandas as pd
import ta  # usamos a biblioteca "ta" para indicadores
from typing import Literal, Dict, Any

Mode = Literal["SWING", "POSICIONAL"]

# ====== PARÂMETROS INICIAIS ======
ADX_LEN = 14
EMA_FAST = 9
EMA_SLOW = 21
ATR_LEN = 14
ATR_MULT_STOP = 1.5
ADX_MIN = 20.0
MIN_EXPECTED_PROFIT_PCT = 3.0   # filtro 3%
MIN_ASSERTIVIDADE = 65.0        # filtro 65%
# =================================

def _ensure(df: pd.DataFrame):
    req = {"open","high","low","close","volume"}
    if not req.issubset(df.columns):
        raise ValueError("Dados OHLCV inválidos.")

def indicadores(df: pd.DataFrame) -> pd.DataFrame:
    _ensure(df)
    out = df.copy()

    # EMAs
    ema_f = ta.trend.EMAIndicator(close=out["close"], window=EMA_FAST).ema_indicator()
    ema_s = ta.trend.EMAIndicator(close=out["close"], window=EMA_SLOW).ema_indicator()
    out["ema_fast"] = ema_f
    out["ema_slow"] = ema_s

    # ADX e +DI / -DI
    adx_ind = ta.trend.ADXIndicator(
        high=out["high"], low=out["low"], close=out["close"], window=ADX_LEN
    )
    out["adx"] = adx_ind.adx()
    out["+di"] = adx_ind.adx_pos()
    out["-di"] = adx_ind.adx_neg()

    # ATR
    atr_ind = ta.volatility.AverageTrueRange(
        high=out["high"], low=out["low"], close=out["close"], window=ATR_LEN
    )
    out["atr"] = atr_ind.average_true_range()

    return out.dropna()

def filtros_direcao(row) -> Literal["LONG","SHORT","NAO_ENTRAR"]:
    if row["adx"] < ADX_MIN:
        return "NAO_ENTRAR"
    if row["ema_fast"] > row["ema_slow"] and row["+di"] > row["-di"]:
        return "LONG"
    if row["ema_fast"] < row["ema_slow"] and row["+di"] < row["-di"]:
        return "SHORT"
    return "NAO_ENTRAR"

def calculo_stop(entry: float, side: str, atr: float) -> float:
    if side == "LONG":
        return max(0.0, entry - ATR_MULT_STOP * atr)
    if side == "SHORT":
        return entry + ATR_MULT_STOP * atr
    return entry

def alvo_basico(entry: float, side: str) -> float:
    # Placeholder: 3% mínimo (vamos trocar depois pelo alvo GBM/ETS)
    if side == "LONG":
        return entry * (1.0 + MIN_EXPECTED_PROFIT_PCT/100.0)
    if side == "SHORT":
        return entry * (1.0 - MIN_EXPECTED_PROFIT_PCT/100.0)
    return entry

def assertividade_placeholder() -> float:
    # Placeholder: será trocado pelo blend teórico-empírico
    return 70.0

def decidir_sinal(df_ind: pd.DataFrame) -> Dict[str, Any]:
    last = df_ind.iloc[-1]
    side = filtros_direcao(last)
    entry = float(last["close"])
    atr   = float(last["atr"])

    if side == "NAO_ENTRAR":
        return {
            "SIDE": "NÃO ENTRAR",
            "ENTRADA": round(entry, 3),
            "ALVO": round(entry, 3),
            "PNL_PCT": 0.0,
            "ASSERTIVIDADE_PCT": 0.0,
            "SITUACAO": "Fora dos filtros",
        }

    alvo = float(alvo_basico(entry, side))
    pnl_pct = (alvo/entry - 1.0) * 100.0 if side == "LONG" else (1.0 - alvo/entry) * 100.0
    assertiv = assertividade_placeholder()

    if pnl_pct < MIN_EXPECTED_PROFIT_PCT or assertiv < MIN_ASSERTIVIDADE:
        return {
            "SIDE": "NÃO ENTRAR",
            "ENTRADA": round(entry, 3),
            "ALVO": round(alvo, 3),
            "PNL_PCT": round(pnl_pct, 2),
            "ASSERTIVIDADE_PCT": round(assertiv, 2),
            "SITUACAO": "Reprovado por filtros",
        }

    return {
        "SIDE": side,
        "ENTRADA": round(entry, 3),
        "ALVO": round(alvo, 3),
        "PNL_PCT": round(pnl_pct, 2),
        "ASSERTIVIDADE_PCT": round(assertiv, 2),
        "SITUACAO": "Apto",
    }

def pipeline_sinal(df_ohlcv: pd.DataFrame, modo: Mode = "SWING") -> Dict[str, Any]:
    df_ind = indicadores(df_ohlcv)
    return decidir_sinal(df_ind)
