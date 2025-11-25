#!/usr/bin/env python3
"""
worker_entrada.py

Gerador de sinais para o PAINEL ENTRADA (Swing 4H e Posicional 1D).

Modelo:

- Usa OHLCV real via exchanges.get_ohlcv().
- Calcula EMAs (20/50) para tendência.
- Calcula ATR(14) para volatilidade.
- Usa variação de 24h (1d) como reforço de direção.
- Calcula alvo em múltiplos de ATR.
- Calcula assertividade simples via backtest:
  * quantas vezes o preço andou >= MIN_GAIN_PCT na direção do setup,
    dentro de um horizonte de candles.
- Sempre preenche PREÇO, ALVO, GANHO%, ASSERT% para todas as moedas
  que tiverem dados.
- SINAL é LONG/SHORT somente quando:
    ganho_pct >= MIN_GAIN_PCT e assert_pct >= MIN_ASSERT_PCT.
  Caso contrário, SINAL = "NAO ENTRAR".

Saída: entrada.json no formato esperado pelo painel.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Literal

import pandas as pd

from config import PCT_DECIMALS, PRICE_DECIMALS, TZINFO
from exchanges import get_ohlcv

Direction = Literal["LONG", "SHORT"]

# ======================================================================
# CONFIGURAÇÕES DO PROJETO
# ======================================================================

COINS: List[str] = sorted(
    [
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
)

ENTRADA_JSON_PATH = os.getenv("ENTRADA_JSON_PATH", "entrada.json")

# Nº de candles usados em cada modo
CANDLES_SWING = 200        # timeframe 4h
CANDLES_POSICIONAL = 260   # timeframe 1d

# Parâmetros do setup
MIN_GAIN_PCT = 3.0       # lucro mínimo desejado
MIN_ASSERT_PCT = 65.0    # assertividade mínima
ATR_MULT_SWING = 2.0     # multiplicador de ATR para alvo swing
ATR_MULT_POSIC = 2.5     # multiplicador de ATR para alvo posicional

# Janela para assertividade
ASSERT_HORIZON_SWING = 6     # ~ 1 dia em 4h
ASSERT_HORIZON_POSIC = 4     # ~ 4 dias em 1d
ASSERT_MIN_SAMPLES = 8       # mínimo de setups históricos para medir assert

# Cache de variação diária
_DAILY_CHANGE_CACHE: Dict[str, float] = {}


@dataclass
class SinalEntrada:
    par: str
    sinal: str  # "LONG", "SHORT" ou "NAO ENTRAR"
    preco: float
    alvo: float
    ganho_pct: float
    assert_pct: float
    data: str
    hora: str


# ======================================================================
# FUNÇÕES AUXILIARES
# ======================================================================


def _now_brt() -> datetime:
    return datetime.now(TZINFO)


def _log(msg: str) -> None:
    ts = _now_brt().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [worker_entrada] {msg}", flush=True)


def _load_ohlcv_df(coin: str, timeframe: str, limit: int) -> pd.DataFrame:
    df = get_ohlcv(coin, timeframe, limit=limit)
    if df is None or df.empty:
        raise RuntimeError(f"Sem OHLCV para {coin} timeframe={timeframe}")
    df = df.sort_index()
    return df


def _add_indicators(
    df: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 50,
    atr_period: int = 14,
) -> pd.DataFrame:
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]

    df["ema_fast"] = close.ewm(span=ema_fast, adjust=False).mean()
    df["ema_slow"] = close.ewm(span=ema_slow, adjust=False).mean()

    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (prev_close - low).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=atr_period, min_periods=atr_period).mean()

    return df.dropna()


def _get_daily_change_24h(coin: str) -> float:
    """
    Variação % de 24h com base em candles 1d (close contra close anterior).
    """
    if coin in _DAILY_CHANGE_CACHE:
        return _DAILY_CHANGE_CACHE[coin]

    df = get_ohlcv(coin, "1d", limit=40)
    if df is None or df.empty or len(df) < 2:
        _DAILY_CHANGE_CACHE[coin] = 0.0
        return 0.0

    df = df.sort_index()
    last = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])
    change_pct = (last / prev - 1.0) * 100.0
    _DAILY_CHANGE_CACHE[coin] = change_pct
    return change_pct


def _calc_assertividade(
    df: pd.DataFrame,
    direction: Direction,
    min_gain_pct: float,
    horizon_bars: int,
) -> float:
    """
    Probabilidade histórica do preço andar >= min_gain_pct na direção do setup
    nos próximos `horizon_bars` candles, condicionado à tendência por EMAs.
    """
    closes = df["close"].values
    ema_fast = df["ema_fast"].values
    ema_slow = df["ema_slow"].values
    n = len(df)

    if n <= horizon_bars + 5:
        return 60.0  # neutro quando histórico é curto

    successes = 0
    total = 0

    for i in range(n - horizon_bars - 1):
        price_i = float(closes[i])

        # filtro de tendência semelhante ao estado atual
        if direction == "LONG":
            if not (closes[i] > ema_fast[i] > ema_slow[i]):
                continue
        else:
            if not (closes[i] < ema_fast[i] < ema_slow[i]):
                continue

        future_window = closes[i + 1 : i + 1 + horizon_bars]
        if future_window.size == 0:
            continue

        if direction == "LONG":
            fut_max = float(future_window.max())
            ret_pct = (fut_max / price_i - 1.0) * 100.0
        else:
            fut_min = float(future_window.min())
            ret_pct = (price_i / fut_min - 1.0) * 100.0

        total += 1
        if ret_pct >= min_gain_pct:
            successes += 1

    if total < ASSERT_MIN_SAMPLES:
        return 60.0

    assert_pct = (successes / total) * 100.0
    return round(assert_pct, 2)


# ======================================================================
# GERAÇÃO DE SINAL POR MOEDA / MODO
# ======================================================================


def _gerar_sinal_para_moeda(coin: str, modo: str) -> SinalEntrada:
    """
    Gera o sinal para uma moeda e um modo ("swing" 4h ou "posicional" 1d).
    Sempre retorna PREÇO, ALVO, GANHO%, ASSERT% quando houver dados.
    SINAL só é LONG/SHORT quando passar nos filtros.
    """

    if modo == "swing":
        timeframe = "4h"
        limit = CANDLES_SWING
        atr_mult = ATR_MULT_SWING
        horizon = ASSERT_HORIZON_SWING
    elif modo == "posicional":
        timeframe = "1d"
        limit = CANDLES_POSICIONAL
        atr_mult = ATR_MULT_POSIC
        horizon = ASSERT_HORIZON_POSIC
    else:
        raise ValueError(f"Modo inválido: {modo}")

    ts_now = _now_brt()
    data_str = ts_now.strftime("%Y-%m-%d")
    hora_str = ts_now.strftime("%H:%M")

    try:
        df_raw = _load_ohlcv_df(coin, timeframe, limit=limit)
        df = _add_indicators(df_raw, ema_fast=20, ema_slow=50, atr_period=14)
    except Exception as e:
        _log(f"ERRO ao carregar dados de {coin} ({timeframe}): {e}")
        return SinalEntrada(
            par=coin,
            sinal="NAO ENTRAR",
            preco=0.0,
            alvo=0.0,
            ganho_pct=0.0,
            assert_pct=0.0,
            data=data_str,
            hora=hora_str,
        )

    if df.empty:
        return SinalEntrada(
            par=coin,
            sinal="NAO ENTRAR",
            preco=0.0,
            alvo=0.0,
            ganho_pct=0.0,
            assert_pct=0.0,
            data=data_str,
            hora=hora_str,
        )

    last = df.iloc[-1]
    price = float(last["close"])
    ema_f = float(last["ema_fast"])
    ema_s = float(last["ema_slow"])
    atr = float(last["atr"])

    if price <= 0 or atr <= 0:
        return SinalEntrada(
            par=coin,
            sinal="NAO ENTRAR",
            preco=0.0,
            alvo=0.0,
            ganho_pct=0.0,
            assert_pct=0.0,
            data=data_str,
            hora=hora_str,
        )

    # variação 24h (reforço de direção)
    change_24h = _get_daily_change_24h(coin)

    # Direção principal pelos EMAs; se neutro, usa sinal da variação 24h
    if price > ema_f > ema_s:
        direction: Direction = "LONG"
    elif price < ema_f < ema_s:
        direction = "SHORT"
    else:
        direction = "LONG" if change_24h >= 0 else "SHORT"

    # Assertividade histórica do setup
    assert_pct = _calc_assertividade(
        df=df,
        direction=direction,
        min_gain_pct=MIN_GAIN_PCT,
        horizon_bars=horizon,
    )

    # Ganho alvo em %: múltiplo de ATR, mas nunca abaixo do mínimo
    atr_pct = (atr / price) * 100.0
    alvo_pct = max(MIN_GAIN_PCT, atr_mult * atr_pct)
    ganho_pct = round(alvo_pct, PCT_DECIMALS)

    if direction == "LONG":
        alvo = price * (1.0 + alvo_pct / 100.0)
    else:
        alvo = price * (1.0 - alvo_pct / 100.0)

    alvo = round(alvo, PRICE_DECIMALS)
    preco_fmt = round(price, PRICE_DECIMALS)

    # Regra FINAL de operação:
    # se (ganho >= 3% e assert >= 65%) -> sinal LONG/SHORT
    # caso contrário -> NAO ENTRAR, mas mantendo os cálculos
    if ganho_pct >= MIN_GAIN_PCT and assert_pct >= MIN_ASSERT_PCT:
        sinal_final = direction
    else:
        sinal_final = "NAO ENTRAR"

    return SinalEntrada(
        par=coin,
        sinal=sinal_final,
        preco=preco_fmt,
        alvo=alvo,
        ganho_pct=ganho_pct,
        assert_pct=round(assert_pct, PCT_DECIMALS),
        data=data_str,
        hora=hora_str,
    )


def _gerar_sinais_por_modo(modo: str) -> List[SinalEntrada]:
    sinais: List[SinalEntrada] = []

    for coin in COINS:
        try:
            sinal = _gerar_sinal_para_moeda(coin, modo)
            sinais.append(sinal)
        except Exception as e:
            _log(f"ERRO geral na moeda {coin} modo={modo}: {e}")
            ts = _now_brt()
            sinais.append(
                SinalEntrada(
                    par=coin,
                    sinal="NAO ENTRAR",
                    preco=0.0,
                    alvo=0.0,
                    ganho_pct=0.0,
                    assert_pct=0.0,
                    data=ts.strftime("%Y-%m-%d"),
                    hora=ts.strftime("%H:%M"),
                )
            )

        time.sleep(0.2)

    sinais.sort(key=lambda s: s.par)
    _log(f"Sinais gerados para modo={modo}: {len(sinais)} moedas.")
    return sinais


# ======================================================================
# PIPELINE COMPLETO
# ======================================================================


def gerar_sinais() -> Dict[str, object]:
    _log("Iniciando geração de sinais (tendência + ATR + variação 24h + assertividade)...")

    swing = _gerar_sinais_por_modo("swing")
    posicional = _gerar_sinais_por_modo("posicional")

    payload = {
        "generated_at": _now_brt().isoformat(),
        "swing": [asdict(s) for s in swing],
        "posicional": [asdict(s) for s in posicional],
    }

    _log(
        f"Sinais gerados: {len(payload['swing'])} swing, "
        f"{len(payload['posicional'])} posicional."
    )
    return payload


def salvar_json(payload: Dict[str, object]) -> None:
    tmp_path = f"{ENTRADA_JSON_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, ENTRADA_JSON_PATH)
    _log(f"Arquivo atualizado: {ENTRADA_JSON_PATH}")


def main() -> None:
    _log("Executando worker_entrada (modelo profissional de entrada)...")
    payload = gerar_sinais()
    salvar_json(payload)
    _log("worker_entrada finalizado com sucesso.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("Encerrado pelo usuário (Ctrl+C).")
