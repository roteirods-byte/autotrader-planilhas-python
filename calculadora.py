"""
calculadora.py

Módulo de CÁLCULOS do AUTOTRADER.

Responsável apenas por calcular indicadores técnicos
a partir de um DataFrame de candles OHLCV.

- Entrada: DataFrame com colunas ["open", "high", "low", "close", "volume"]
  e índice datetime.
- Saída: dicionário com os últimos valores de:
    * preco
    * ema_fast
    * ema_slow
    * atr
    * adx
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np  # type: ignore
import pandas as pd  # type: ignore
from ta.trend import EMAIndicator, ADXIndicator  # type: ignore
from ta.volatility import AverageTrueRange  # type: ignore


def _log(msg: str) -> None:
    print(f"[calculadora] {msg}", flush=True)


def calcular_indicadores(
    df: pd.DataFrame,
    janela_ema_rapida: int = 9,
    janela_ema_lenta: int = 21,
    janela_atr: int = 14,
    janela_adx: int = 14,
) -> Optional[Dict[str, float]]:
    """
    Calcula EMAs, ATR e ADX para o DataFrame informado.

    Retorna um dicionário com os últimos valores ou None se não for possível.
    """
    if df.shape[0] < max(janela_ema_lenta, janela_atr, janela_adx) + 5:
        _log(f"Poucos candles ({df.shape[0]}), não é possível calcular.")
        return None

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    ema_fast = EMAIndicator(close=close, window=janela_ema_rapida).ema_indicator()
    ema_slow = EMAIndicator(close=close, window=janela_ema_lenta).ema_indicator()
    atr = AverageTrueRange(
        high=high,
        low=low,
        close=close,
        window=janela_atr,
    ).average_true_range()
    adx = ADXIndicator(
        high=high,
        low=low,
        close=close,
        window=janela_adx,
    ).adx()

    preco = float(close.iloc[-1])
    ema_f = float(ema_fast.iloc[-1])
    ema_s = float(ema_slow.iloc[-1])
    atr_v = float(atr.iloc[-1])
    adx_v = float(adx.iloc[-1])

    valores = [preco, ema_f, ema_s, atr_v, adx_v]
    if not np.isfinite(valores).all():
        _log("Encontrados valores não finitos nos indicadores, abortando.")
        return None

    return {
        "preco": preco,
        "ema_fast": ema_f,
        "ema_slow": ema_s,
        "atr": atr_v,
        "adx": adx_v,
    }
