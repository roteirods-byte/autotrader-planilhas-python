#!/usr/bin/env python3
"""
worker_entrada.py

Gera o arquivo entrada.json usado pelo painel ENTRADA.

- Universo fixo de 39 moedas (sem USDT no ticker).
- Busca dados de preço/candles nas corretoras via ccxt (Binance e Bybit).
- Calcula sinais Swing (4H) e Posicional (1D) moeda por moeda.
- Para cada moeda/mode:
    * Decide LONG ou SHORT a partir da tendência (EMAs).
    * Calcula alvo em função da volatilidade (ATR) e converte em GANHO %.
    * Calcula uma ASSERT % individual por moeda com base em ADX / tendência.
- Aplica filtros mínimos ANTES de publicar o sinal:
    * ganho_pct >= 3.0
    * assert_pct >= 65.0

O resultado é salvo em entrada.json com o formato:

{
  "generated_at": "2025-11-21T12:10:00-03:00",
  "swing": [
    {
      "par": "AAVE",
      "sinal": "LONG",
      "preco": 155.38,
      "alvo": 161.92,
      "ganho_pct": 4.21,
      "assert_pct": 71.35,
      "data": "2025-11-21",
      "hora": "12:10"
    },
    ...
  ],
  "posicional": [
    ...
  ]
}
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional

import ccxt  # type: ignore
import numpy as np  # type: ignore
import pandas as pd  # type: ignore
from ta.trend import EMAIndicator, ADXIndicator  # type: ignore
from ta.volatility import AverageTrueRange  # type: ignore

try:
    # Config oficial do projeto (se existir)
    from config import TZINFO, PRICE_DECIMALS, PCT_DECIMALS  # type: ignore
except Exception:  # fallback seguro para testes
    from zoneinfo import ZoneInfo

    TZINFO = ZoneInfo("America/Sao_Paulo")
    PRICE_DECIMALS = int(os.getenv("PRICE_DECIMALS", "3"))
    PCT_DECIMALS = int(os.getenv("PCT_DECIMALS", "2"))


# ============================
# PARÂMETROS GERAIS
# ============================

# Universo fixo de moedas (sem "USDT")
COINS = [
    "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH", "BNB",
    "BTC", "DOGE", "DOT", "ETH", "FET", "FIL", "FLUX", "ICP", "INJ",
    "LDO", "LINK", "LTC", "NEAR", "OP", "PEPE", "POL", "RATS", "RENDER",
    "RUNE", "SEI", "SHIB", "SOL", "SUI", "TIA", "TNSR", "TON", "TRX",
    "UNI", "WIF", "XRP",
]
COINS = sorted(COINS)

# Timeframes
TF_SWING = "4h"   # Swing
TF_POS = "1d"     # Posicional

# Multiplicadores de ATR por modo
ATR_MULT_SWING = 1.0
ATR_MULT_POS = 1.5

# Limites de filtros
MIN_GANHO = 3.0     # mínimo 3%
MIN_ASSERT = 65.0   # mínimo 65%

# Limites de assertividade (para não ficar absurdo)
MIN_ASSERT_CLAMP = 50.0
MAX_ASSERT_CLAMP = 90.0

# Caminho padrão de saída
ENTRADA_JSON_PATH = os.getenv("ENTRADA_JSON_PATH", "entrada.json")


# ============================
# HELPERS DE TEMPO / LOG
# ============================


def now_brt() -> datetime:
    """Agora em timezone BRT."""
    return datetime.now(TZINFO)


def log(msg: str) -> None:
    ts = now_brt().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [worker_entrada] {msg}", flush=True)


# ============================
# MODELOS
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


# ============================
# EXCHANGES (ccxt)
# ============================


def criar_exchanges() -> Dict[str, ccxt.Exchange]:
    """
    Cria conexões de exchange via ccxt.
    Usa modo anônimo (só leitura de dados públicos).
    """
    binance = ccxt.binance({"enableRateLimit": True})
    bybit = ccxt.bybit({"enableRateLimit": True})
    return {"binance": binance, "bybit": bybit}


def coin_to_pair(coin: str) -> str:
    """Converte 'BTC' -> 'BTC/USDT'."""
    return f"{coin}/USDT"


def fetch_ohlcv_any(
    exs: Dict[str, ccxt.Exchange],
    symbol: str,
    timeframe: str,
    limit: int = 200,
) -> Optional[pd.DataFrame]:
    """
    Busca OHLCV em qualquer exchange disponível (Binance ou Bybit).
    Tenta Binance primeiro; se falhar, tenta Bybit.
    Retorna DataFrame com colunas: [open, high, low, close, volume]
    e índice datetime em TZINFO.
    """
    errors: List[str] = []

    for name in ("binance", "bybit"):
        ex = exs.get(name)
        if ex is None:
            continue

        try:
            ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not ohlcv:
                errors.append(f"{name}: resposta vazia")
                continue

            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            # converte timestamp para datetime
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            df = df.tz_convert(TZINFO)

            return df
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e!r}")
            continue

    log(f"Falha ao buscar OHLCV para {symbol} {timeframe}: {' | '.join(errors)}")
    return None


# ============================
# CÁLCULOS DOS SINAIS
# ============================

def calcular_sinal_para_df(
    coin: str,
    df: pd.DataFrame,
    modo: str,
) -> Optional[SinalEntrada]:
    """
    Calcula o sinal (LONG/SHORT), alvo, ganho % e assert % para uma moeda.
    `modo` = "swing" ou "posicional".
    """
    if df.shape[0] < 60:
        log(f"{coin} modo={modo}: poucos candles ({df.shape[0]}), pulando.")
        return None

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    ema_fast = EMAIndicator(close=close, window=9).ema_indicator()
    ema_slow = EMAIndicator(close=close, window=21).ema_indicator()
    atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
    adx = ADXIndicator(high=high, low=low, close=close, window=14).adx()

    last_close = float(close.iloc[-1])
    last_ema_fast = float(ema_fast.iloc[-1])
    last_ema_slow = float(ema_slow.iloc[-1])
    last_atr = float(atr.iloc[-1])
    last_adx = float(adx.iloc[-1])

    if not all(math.isfinite(x) for x in [last_close, last_ema_fast, last_ema_slow, last_atr, last_adx]):
        log(f"{coin} modo={modo}: valores não finitos, pulando.")
        return None

    # Direção principal: LONG se EMA rápida acima da lenta, senão SHORT
    if last_ema_fast > last_ema_slow:
        sinal = "LONG"
    else:
        sinal = "SHORT"

    # ATR em % do preço (volatilidade relativa), com limites
    atr_pct = (last_atr / last_close) * 100.0
    atr_pct = max(0.5, min(atr_pct, 15.0))

    # Multiplicadores diferentes para Swing x Posicional
    if modo == "swing":
        mult = 1.2   # alvo menor, prazos curtos
    else:
        mult = 2.0   # alvo maior, prazo longo

    ganho_pct_raw = atr_pct * mult
    ganho_pct_raw = max(MIN_GANHO, min(ganho_pct_raw, 30.0))

    # Alvo conforme direção
    if sinal == "LONG":
        alvo = last_close * (1.0 + ganho_pct_raw / 100.0)
    else:
        alvo = last_close * (1.0 - ganho_pct_raw / 100.0)

    # Ganho real em %
    if sinal == "LONG":
        ganho_pct_real = ((alvo - last_close) / last_close) * 100.0
    else:
        ganho_pct_real = ((last_close - alvo) / last_close) * 100.0

    # ASSERT %:
    #  - parte do ADX (força da tendência)
    #  - parte do alinhamento entre sinal e EMAs
    adx_norm = max(0.0, min(1.0, (last_adx - 10.0) / 40.0))  # ADX ~10-50
    alinhado = (
        (sinal == "LONG" and last_ema_fast > last_ema_slow) or
        (sinal == "SHORT" and last_ema_fast < last_ema_slow)
    )
    align_score = 1.0 if alinhado else 0.0

    # Base 55%, + até 20% do ADX, +10% se alinhado
    assert_pct = 55.0 + 20.0 * adx_norm + 10.0 * align_score

    # Limites finais
    assert_pct = max(60.0, min(90.0, assert_pct))

    # Filtro mínimo antes de publicar
    if ganho_pct_real < MIN_GANHO or assert_pct < MIN_ASSERT:
        log(
            f"{coin} modo={modo}: filtrado (ganho={ganho_pct_real:.2f}%, "
            f"assert={assert_pct:.2f}%)."
        )
        return None

    # Arredondamentos
    preco_r = round(last_close, PRICE_DECIMALS)
    alvo_r = round(alvo, PRICE_DECIMALS)
    ganho_r = round(ganho_pct_real, PCT_DECIMALS)
    assert_r = round(assert_pct, PCT_DECIMALS)

    ts = now_brt()
    data_str = ts.strftime("%Y-%m-%d")
    hora_str = ts.strftime("%H:%M")

    return SinalEntrada(
        par=coin,
        sinal=sinal,
        preco=preco_r,
        alvo=alvo_r,
        ganho_pct=ganho_r,
        assert_pct=assert_r,
        data=data_str,
        hora=hora_str,
    )

 
    # EMAs para direção de tendência
    ema_fast = EMAIndicator(close=close, window=9).ema_indicator()
    ema_slow = EMAIndicator(close=close, window=21).ema_indicator()

    # ATR para volatilidade
    atr = AverageTrueRange(
        high=high,
        low=low,
        close=close,
        window=14,
    ).average_true_range()

    # ADX para medir força da tendência
    adx = ADXIndicator(
        high=high,
        low=low,
        close=close,
        window=14,
    ).adx()

    last_close = float(close.iloc[-1])
    last_ema_fast = float(ema_fast.iloc[-1])
    last_ema_slow = float(ema_slow.iloc[-1])
    last_atr = float(atr.iloc[-1])
    last_adx = float(adx.iloc[-1])

    if not all(math.isfinite(x) for x in [last_close, last_ema_fast, last_ema_slow, last_atr, last_adx]):
        log(f"{coin} modo={modo}: valores não finitos, pulando.")
        return None

    # Direção: LONG se EMA rápida acima da lenta; caso contrário, SHORT.
    if last_ema_fast > last_ema_slow:
        sinal = "LONG"
    else:
        sinal = "SHORT"

    # ATR em % do preço (volatilidade relativa)
    atr_pct = (last_atr / last_close) * 100.0

    # Regras diferentes para Swing vs Posicional
    if modo == "swing":
        atr_mult = ATR_MULT_SWING
        base_assert = 68.0  # base aproximada para swing
    else:
        atr_mult = ATR_MULT_POS
        base_assert = 72.0  # base aproximada para posicional

    # Ganho bruto em % a partir da volatilidade
    ganho_pct_raw = atr_pct * atr_mult

    # Pelo menos 3% de alvo
    ganho_pct_raw = max(ganho_pct_raw, MIN_GANHO)

    # Cap superior de alvo (para evitar números absurdos)
    ganho_pct_raw = min(ganho_pct_raw, 25.0)

    # Preço alvo
    if sinal == "LONG":
        alvo = last_close * (1.0 + ganho_pct_raw / 100.0)
    else:  # SHORT
        alvo = last_close * (1.0 - ganho_pct_raw / 100.0)

    # Recalcula ganho real a partir do alvo (só por segurança)
    if sinal == "LONG":
        ganho_pct_real = ((alvo - last_close) / last_close) * 100.0
    else:
        ganho_pct_real = ((last_close - alvo) / last_close) * 100.0

    # ASSERT % individual:
    # - parte da ADX (força de tendência)
    # - parte da "alinhamento" entre sinal e EMAs
    tendencia_score = 0.0
    if sinal == "LONG" and last_ema_fast > last_ema_slow:
        tendencia_score += 3.0
    elif sinal == "SHORT" and last_ema_fast < last_ema_slow:
        tendencia_score += 3.0
    else:
        tendencia_score -= 3.0

    # ADX > 25 indica tendência mais forte.
    adx_bonus = max(0.0, (last_adx - 25.0) / 5.0)
    assert_pct = base_assert + tendencia_score + adx_bonus

    # Clamp final da assertividade
    assert_pct = max(MIN_ASSERT_CLAMP, min(MAX_ASSERT_CLAMP, assert_pct))

    # Aplica filtros mínimos
    if ganho_pct_real < MIN_GANHO or assert_pct < MIN_ASSERT:
        # Sinal não aprovado; não publica.
        log(
            f"{coin} modo={modo}: filtrado (ganho={ganho_pct_real:.2f}%, "
            f"assert={assert_pct:.2f}%)."
        )
        return None

    # Arredondamentos finais
    preco_r = round(last_close, PRICE_DECIMALS)
    alvo_r = round(alvo, PRICE_DECIMALS)
    ganho_r = round(ganho_pct_real, PCT_DECIMALS)
    assert_r = round(assert_pct, PCT_DECIMALS)

    ts = now_brt()
    data_str = ts.strftime("%Y-%m-%d")
    hora_str = ts.strftime("%H:%M")

    return SinalEntrada(
        par=coin,
        sinal=sinal,
        preco=preco_r,
        alvo=alvo_r,
        ganho_pct=ganho_r,
        assert_pct=assert_r,
        data=data_str,
        hora=hora_str,
    )


def gerar_sinais() -> Dict[str, object]:
    """
    Gera todos os sinais Swing e Posicional para o universo de moedas.
    Retorna um dicionário pronto para ser salvo em JSON.
    """
    exs = criar_exchanges()
    swing: List[SinalEntrada] = []
    posicional: List[SinalEntrada] = []

    log(f"Gerando sinais para {len(COINS)} moedas...")

    for coin in COINS:
        symbol = coin_to_pair(coin)

        # -------- Swing (4H)
        df4 = fetch_ohlcv_any(exs, symbol, TF_SWING, limit=200)
        if df4 is not None:
            sinal_swing = calcular_sinal_para_df(coin, df4, modo="swing")
            if sinal_swing is not None:
                swing.append(sinal_swing)

        # -------- Posicional (1D)
        df1d = fetch_ohlcv_any(exs, symbol, TF_POS, limit=200)
        if df1d is not None:
            sinal_pos = calcular_sinal_para_df(coin, df1d, modo="posicional")
            if sinal_pos is not None:
                posicional.append(sinal_pos)

    # Ordena alfabeticamente por par
    swing_sorted = sorted(swing, key=lambda s: s.par)
    pos_sorted = sorted(posicional, key=lambda s: s.par)

    payload = {
        "generated_at": now_brt().isoformat(),
        "swing": [asdict(s) for s in swing_sorted],
        "posicional": [asdict(s) for s in pos_sorted],
    }

    log(
        "Sinais gerados: "
        f"{len(swing_sorted)} swing, {len(pos_sorted)} posicional."
    )
    return payload


def salvar_json(payload: Dict[str, object]) -> None:
    """Salva o payload no arquivo ENTRADA_JSON_PATH."""
    tmp_path = ENTRADA_JSON_PATH + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    os.replace(tmp_path, ENTRADA_JSON_PATH)
    log(f"Arquivo salvo em: {ENTRADA_JSON_PATH}")


def main() -> None:
    log("Iniciando worker_entrada.py...")
    payload = gerar_sinais()
    salvar_json(payload)
    log("worker_entrada.py finalizado com sucesso.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Encerrado pelo usuário (Ctrl+C).")
