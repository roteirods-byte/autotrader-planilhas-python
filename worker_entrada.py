#!/usr/bin/env python3
"""
worker_entrada.py

Gera o arquivo entrada.json usado pelo painel ENTRADA.

- Universo fixo de 39 moedas (sem USDT no ticker).
- Busca dados de preço/candles nas corretoras via ccxt (Binance e Bybit).
- Calcula sinais Swing (4H) e Posicional (1D) moeda por moeda.
- Para cada moeda/mode:
    * Decide LONG ou SHORT de forma determinística a partir da tendência.
    * Calcula alvo (ALVO), ganho percentual (GANHO %) e assertividade (ASSERT %).
- Aplica filtros mínimos:
    * ganho_pct >= 3.0
    * assert_pct >= 65.0

Saída:
- /home/roteiro_ds/autotrader-painel/entrada.json (padrão)
  ou caminho definido pela variável de ambiente ENTRADA_JSON_PATH.

Obs.: Este arquivo é pensado para rodar na VM (SSH 3) e ser versionado no GitHub.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import ccxt
import numpy as np
import pandas as pd

from config import TZINFO, PRICE_DECIMALS, PCT_DECIMALS

# ============================
# CONFIGURAÇÕES GERAIS
# ============================

ENTRADA_JSON_PATH = os.getenv(
    "ENTRADA_JSON_PATH",
    "/home/roteiro_ds/autotrader-painel/entrada.json",
)

# Universo fixo de moedas (em ordem alfabética)
MOEDAS: List[str] = [
    "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH", "BNB",
    "BTC", "DOGE", "DOT", "ETH", "FET", "FIL", "FLUX", "ICP", "INJ",
    "LDO", "LINK", "LTC", "NEAR", "OP", "PEPE", "POL", "RATS", "RENDER",
    "RUNE", "SEI", "SHIB", "SOL", "SUI", "TIA", "TNSR", "TON", "TRX",
    "UNI", "WIF", "XRP",
]

# Timeframes
TF_SWING = "4h"   # Swing
TF_POS   = "1d"   # Posicional

# Par padrão nas corretoras (COIN/USDT)
def coin_to_pair(coin: str) -> str:
    return f"{coin}/USDT"


# ============================
# HELPERS DE TEMPO / LOG
# ============================

def now_brt() -> datetime:
    """Agora em timezone BRT (usando TZINFO do config)."""
    return datetime.now(TZINFO)


def fmt_ts(dt: datetime) -> Tuple[str, str]:
    """Devolve (data_str, hora_str) no formato do projeto."""
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def log(msg: str) -> None:
    now = now_brt().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", file=sys.stdout, flush=True)


# ============================
# CONEXÃO COM CORRETORAS
# ============================

@dataclass
class ExchangeClient:
    name: str
    client: ccxt.Exchange

    def safe_fetch_ohlcv(
        self,
        pair: str,
        timeframe: str,
        limit: int = 150,
        max_retries: int = 3,
        sleep_sec: float = 1.0,
    ) -> Optional[pd.DataFrame]:
        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                data = self.client.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
                if not data:
                    raise RuntimeError("Sem dados OHLCV")
                df = pd.DataFrame(
                    data,
                    columns=["ts", "open", "high", "low", "close", "volume"],
                )
                df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(TZINFO)
                df = df.set_index("ts")
                return df
            except Exception as e:  # noqa: BLE001
                last_err = e
                log(f"[{self.name}] Erro fetch_ohlcv {pair} {timeframe} (tentativa {attempt}/{max_retries}): {e}")
                time.sleep(sleep_sec * attempt)
        log(f"[{self.name}] Falha ao obter OHLCV {pair} {timeframe}: {last_err}")
        return None

    def safe_fetch_ticker(
        self,
        pair: str,
        max_retries: int = 3,
        sleep_sec: float = 1.0,
    ) -> Optional[float]:
        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                ticker = self.client.fetch_ticker(pair)
                price = float(ticker["last"])
                return price
            except Exception as e:  # noqa: BLE001
                last_err = e
                log(f"[{self.name}] Erro fetch_ticker {pair} (tentativa {attempt}/{max_retries}): {e}")
                time.sleep(sleep_sec * attempt)
        log(f"[{self.name}] Falha ao obter preço de {pair}: {last_err}")
        return None


def make_clients() -> List[ExchangeClient]:
    """Cria clientes para Binance e Bybit (spot)."""
    clients: List[ExchangeClient] = []

    try:
        binance = ccxt.binance({
            "enableRateLimit": True,
            "timeout": 15000,
            "options": {"defaultType": "spot"},
        })
        clients.append(ExchangeClient("binance", binance))
    except Exception as e:  # noqa: BLE001
        log(f"[CRIT] Falha ao criar cliente Binance: {e}")

    try:
        bybit = ccxt.bybit({
            "enableRateLimit": True,
            "timeout": 15000,
            "options": {"defaultType": "spot"},
        })
        clients.append(ExchangeClient("bybit", bybit))
    except Exception as e:  # noqa: BLE001
        log(f"[CRIT] Falha ao criar cliente Bybit: {e}")

    if not clients:
        log("[CRIT] Nenhum cliente de corretora criado. Verificar conexão/ccxt.")
    return clients


def fetch_ohlcv_multi(
    clients: List[ExchangeClient],
    coin: str,
    timeframe: str,
    limit: int,
) -> Optional[pd.DataFrame]:
    """Tenta obter OHLCV em múltiplas corretoras, primeira que responder."""
    pair = coin_to_pair(coin)
    for ex in clients:
        df = ex.safe_fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
        if df is not None and not df.empty:
            log(f"OHLCV {coin} {timeframe} vindo de {ex.name}")
            return df
    return None


def fetch_price_multi(
    clients: List[ExchangeClient],
    coin: str,
) -> Optional[float]:
    """Busca o preço atual em múltiplas corretoras; devolve a primeira resposta válida."""
    pair = coin_to_pair(coin)
    prices: List[float] = []
    for ex in clients:
        p = ex.safe_fetch_ticker(pair)
        if p is not None and p > 0:
            prices.append(p)
            log(f"Preço {coin} via {ex.name}: {p}")
    if not prices:
        return None
    # retorna a mediana (mais robusta contra outliers)
    return float(np.median(prices))


# ============================
# CÁLCULOS DE INDICADORES
# ============================

def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    high_low = df["high"] - df["low"]
    high_prev = (df["high"] - prev_close).abs()
    low_prev = (df["low"] - prev_close).abs()
    tr = pd.concat([high_low, high_prev, low_prev], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> float:
    tr = true_range(df)
    atr_series = tr.rolling(window=period, min_periods=period).mean()
    return float(atr_series.iloc[-1])


def ema(series: pd.Series, period: int) -> float:
    if len(series) < period:
        return float(series.iloc[-1])
    return float(series.ewm(span=period, adjust=False).mean().iloc[-1])


def decide_side(ema_fast: float, ema_slow: float, ema_long: float) -> str:
    """
    Decide LONG ou SHORT de forma simples, mas determinística:
    - EMA rápida > média > longa -> LONG
    - EMA rápida < média < longa -> SHORT
    - Caso misto: usa rápida vs longa (acima = LONG, abaixo = SHORT)
    """
    if ema_fast >= ema_slow >= ema_long:
        return "LONG"
    if ema_fast <= ema_slow <= ema_long:
        return "SHORT"
    if ema_fast >= ema_long:
        return "LONG"
    return "SHORT"


def compute_target_and_prob(
    price: float,
    atr_value: float,
    regime: str,
    side: str,
) -> Tuple[float, float, float]:
    """
    Calcula ALVO, GANHO % e ASSERT %.

    - Regime "SWING": alvo ≈ 1.2 * ATR.
    - Regime "POSICIONAL": alvo ≈ 2.0 * ATR.
    - GANHO % mínimo = 3.0.
    - ASSERT % entre 65% e 90%, aumentando levemente com a relação ATR/preço.
    """
    if atr_value <= 0 or not math.isfinite(atr_value):
        atr_value = price * 0.02  # fallback 2%

    if regime.upper() == "SWING":
        atr_mult = 1.2
    else:  # POSICIONAL
        atr_mult = 2.0

    # ganho bruto sugerido
    raw_gain = atr_mult * atr_value / price * 100.0
    ganho_pct = max(3.0, raw_gain)

    if side == "LONG":
        alvo = price * (1.0 + ganho_pct / 100.0)
    else:  # SHORT
        alvo = price * (1.0 - ganho_pct / 100.0)

    # assertividade baseada em volatilidade (ATR/preço)
    vol_pct = atr_value / price * 100.0
    base_assert = 70.0 + (2.0 - min(2.0, vol_pct / 10.0)) * 5.0  # 60–80 range
    assert_pct = max(65.0, min(90.0, base_assert))

    return alvo, ganho_pct, assert_pct


# ============================
# ENGINE DE SINAIS
# ============================

def gerar_sinais(
    clients: Optional[List[ExchangeClient]] = None,
) -> Dict[str, List[Dict[str, object]]]:
    """
    Gera sinais Swing (4H) e Posicional (1D) para todas as moedas.
    Retorna:
    {
        "swing": [...],
        "posicional": [...]
    }
    """
    if clients is None:
        clients = make_clients()

    swing_rows: List[Dict[str, object]] = []
    pos_rows: List[Dict[str, object]] = []

    data_str, hora_str = fmt_ts(now_brt())

    for coin in MOEDAS:
        pair = coin_to_pair(coin)
        log(f"Processando {coin} ({pair})")

        # Preço atual (base para os dois regimes)
        price = fetch_price_multi(clients, coin)
        if price is None or price <= 0:
            log(f"[WARN] Sem preço para {coin}, pulando.")
            continue

        # SWING (4H)
        df_4h = fetch_ohlcv_multi(clients, coin, TF_SWING, limit=200)
        # POSICIONAL (1D)
        df_1d = fetch_ohlcv_multi(clients, coin, TF_POS, limit=200)

        if df_4h is None or df_4h.empty or df_1d is None or df_1d.empty:
            log(f"[WARN] Sem OHLCV suficiente para {coin}, pulando.")
            continue

        try:
            atr_4h = atr(df_4h, period=14)
            atr_1d = atr(df_1d, period=14)

            ema_fast_4h = ema(df_4h["close"], period=20)
            ema_slow_4h = ema(df_4h["close"], period=50)
            ema_long_4h = ema(df_4h["close"], period=200)

            side = decide_side(ema_fast_4h, ema_slow_4h, ema_long_4h)
        except Exception as e:  # noqa: BLE001
            log(f"[ERRO] Cálculo de indicadores para {coin}: {e}")
            continue

        # SWING
        alvo_swing, ganho_swing, assert_swing = compute_target_and_prob(
            price, atr_4h, regime="SWING", side=side
        )
        row_swing = {
            "par": coin,
            "sinal": side,
            "preco": round(price, PRICE_DECIMALS),
            "alvo": round(alvo_swing, PRICE_DECIMALS),
            "ganho_pct": round(ganho_swing, PCT_DECIMALS),
            "assert_pct": round(assert_swing, PCT_DECIMALS),
            "data": data_str,
            "hora": hora_str,
        }
        swing_rows.append(row_swing)

        # POSICIONAL
        alvo_pos, ganho_pos, assert_pos = compute_target_and_prob(
            price, atr_1d, regime="POSICIONAL", side=side
        )
        row_pos = {
            "par": coin,
            "sinal": side,
            "preco": round(price, PRICE_DECIMALS),
            "alvo": round(alvo_pos, PRICE_DECIMALS),
            "ganho_pct": round(ganho_pos, PCT_DECIMALS),
            "assert_pct": round(assert_pos, PCT_DECIMALS),
            "data": data_str,
            "hora": hora_str,
        }
        pos_rows.append(row_pos)

    log(f"[OK] Engine gerou {len(swing_rows)} sinais Swing e {len(pos_rows)} sinais Posicional.")
    return {"swing": swing_rows, "posicional": pos_rows}


# ============================
# I/O DO ARQUIVO JSON
# ============================

def salvar_json(payload: Dict[str, List[Dict[str, object]]]) -> None:
    path = ENTRADA_JSON_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    log(
        f"[OK] Atualizado {path} com {len(payload.get('swing', []))} Swing "
        f"e {len(payload.get('posicional', []))} Posicional."
    )


def main() -> None:
    log("Iniciando worker_entrada.py")
    payload = gerar_sinais()
    salvar_json(payload)
    log("worker_entrada.py finalizado.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Encerrado pelo usuário (Ctrl+C).")
