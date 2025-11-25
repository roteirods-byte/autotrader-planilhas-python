#!/usr/bin/env python3
"""
worker_entrada.py

Gerador de sinais para o PAINEL ENTRADA (Swing 4H e Posicional 1D).

Modelo profissional baseado em boas práticas de trading quantitativo em cripto:

- Usa OHLCV REAL das corretoras via exchanges.get_ohlcv().
- Usa DAILY (1d) para medir variação de 24h de cada moeda.
- Usa EMAs (20/50) para identificar tendência (LONG / SHORT).
- Usa ATR(14) como medida de volatilidade para definir o alvo.
- Calcula assertividade por backtest simples:
  * Procura setups de tendência nos últimos candles.
  * Mede quantas vezes o preço andou >= MIN_GAIN_PCT na direção do setup.
- Aplica filtros:
  * ganho alvo >= MIN_GAIN_PCT (ex.: 3%).
  * assertividade >= MIN_ASSERT_PCT (ex.: 65%).

Saída: arquivo JSON `entrada.json` no formato esperado pelo painel:

{
  "generated_at": "...",
  "swing": [
    {
      "par": "BTC",
      "sinal": "LONG" | "SHORT" | "NAO ENTRAR",
      "preco": 88000.0,
      "alvo": 91000.0,
      "ganho_pct": 3.5,
      "assert_pct": 68.2,
      "data": "2025-11-24",
      "hora": "20:12"
    },
    ...
  ],
  "posicional": [ ... ]
}
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Literal, Optional

import pandas as pd

from config import PCT_DECIMALS, PRICE_DECIMALS, TZINFO
from exchanges import get_ohlcv

# ======================================================================
# CONFIGURAÇÕES GERAIS
# ======================================================================

Direction = Literal["LONG", "SHORT"]

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

# Caminho do JSON lido pelo painel
ENTRADA_JSON_PATH = os.getenv("ENTRADA_JSON_PATH", "entrada.json")

# Nº de candles usados em cada modo
CANDLES_SWING = 200        # 4h
CANDLES_POSICIONAL = 260   # 1d

# Parâmetros do modelo (podem ser ajustados depois)
MIN_GAIN_PCT = 3.0        # lucro mínimo desejado
MIN_ASSERT_PCT = 65.0     # assertividade mínima
ATR_MULT_SWING = 2.0      # alvo em múltiplos de ATR (swing)
ATR_MULT_POSIC = 2.5      # alvo em múltiplos de ATR (posicional)
CHANGE_24H_MIN_SWING = 1.0   # variação mínima 24h p/ considerar trade (swing)
CHANGE_24H_MIN_POSIC = 2.0   # variação mínima 24h p/ considerar trade (posicional)

# Janela para calcular assertividade (nº de candles à frente)
ASSERT_HORIZON_SWING = 6     # ~ 1 dia em 4h
ASSERT_HORIZON_POSIC = 4     # ~ 4 dias em 1d
ASSERT_MIN_SAMPLES = 8       # mínimo de amostras de setup p/ medir assertividade

# Cache para não buscar OHLCV diário duas vezes por moeda
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
    """
    Carrega OHLCV em DataFrame com colunas: open, high, low, close, volume.
    """
    df = get_ohlcv(coin, timeframe, limit=limit)
    if df is None or df.empty:
        raise RuntimeError(f"Sem OHLCV para {coin} timeframe={timeframe}")
    # Garante ordenação por data
    df = df.sort_index()
    return df


def _add_indicators(
    df: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 50,
    atr_period: int = 14,
) -> pd.DataFrame:
    """
    Adiciona EMAs e ATR ao DataFrame.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]

    df = df.copy()
    df["ema_fast"] = close.ewm(span=ema_fast, adjust=False).mean()
    df["ema_slow"] = close.ewm(span=ema_slow, adjust=False).mean()

    # ATR
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (prev_close - low).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=atr_period, min_periods=atr_period).mean()

    return df.dropna()


def _get_daily_change_24h(coin: str) -> float:
    """
    Variação % de 24h baseada em candles 1D da moeda.
    """
    if coin in _DAILY_CHANGE_CACHE:
        return _DAILY_CHANGE_CACHE[coin]

    df_d = _load_ohlcv_df(coin, "1d", limit=40)
    if len(df_d) < 2:
        _DAILY_CHANGE_CACHE[coin] = 0.0
        return 0.0

    last = df_d["close"].iloc[-1]
    prev = df_d["close"].iloc[-2]
    change_pct = (last / prev - 1.0) * 100.0
    _DAILY_CHANGE_CACHE[coin] = float(change_pct)
    return float(change_pct)


def _calc_assertividade(
    df: pd.DataFrame,
    direction: Direction,
    min_gain_pct: float,
    horizon_bars: int,
) -> float:
    """
    Mede probabilidade de o preço andar >= min_gain_pct na direção do setup,
    nos próximos `horizon_bars` candles, condicionado a:
      - tendência pelo cruzamento das EMAs (20/50).
    """
    closes = df["close"].values
    ema_fast = df["ema_fast"].values
    ema_slow = df["ema_slow"].values
    n = len(df)

    if n <= horizon_bars + 5:
        return 55.0  # fallback se histórico insuficiente

    successes = 0
    total = 0

    # Vamos usar todos os candles exceto os últimos `horizon_bars`
    for i in range(n - horizon_bars - 1):
        price_i = closes[i]

        # Condição de tendência no passado (setup semelhante ao atual)
        if direction == "LONG":
            if not (closes[i] > ema_fast[i] > ema_slow[i]):
                continue
        else:  # SHORT
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
        # Poucas amostras -> assertividade neutra
        return 60.0

    assert_pct = (successes / total) * 100.0
    return round(assert_pct, 2)


# ======================================================================
# GERAÇÃO DE SINAL POR MOEDA / MODO
# ======================================================================


def _gerar_sinal_para_moeda(
    coin: str,
    modo: str,
    change_24h_pct: float,
) -> SinalEntrada:
    """
    Gera o sinal para uma moeda em um modo específico ("swing" ou "posicional").
    Usa:
      - tendência por EMAs 20/50
      - variação 24h
      - ATR para alvo
      - backtest simples para assertividade
    """

    if modo == "swing":
        timeframe = "4h"
        limit = CANDLES_SWING
        ema_fast = 20
        ema_slow = 50
        atr_mult = ATR_MULT_SWING
        change_min = CHANGE_24H_MIN_SWING
        horizon = ASSERT_HORIZON_SWING
    elif modo == "posicional":
        timeframe = "1d"
        limit = CANDLES_POSICIONAL
        ema_fast = 20
        ema_slow = 50
        atr_mult = ATR_MULT_POSIC
        change_min = CHANGE_24H_MIN_POSIC
        horizon = ASSERT_HORIZON_POSIC
    else:
        raise ValueError(f"Modo inválido: {modo}")

    try:
        df_raw = _load_ohlcv_df(coin, timeframe, limit=limit)
        df = _add_indicators(df_raw, ema_fast=ema_fast, ema_slow=ema_slow, atr_period=14)
    except Exception as e:
        _log(f"ERRO ao carregar dados de {coin} modo={modo}: {e}")
        ts = _now_brt()
        return SinalEntrada(
            par=coin,
            sinal="NAO ENTRAR",
            preco=0.0,
            alvo=0.0,
            ganho_pct=0.0,
            assert_pct=0.0,
            data=ts.strftime("%Y-%m-%d"),
            hora=ts.strftime("%H:%M"),
        )

    if df.empty:
        ts = _now_brt()
        return SinalEntrada(
            par=coin,
            sinal="NAO ENTRAR",
            preco=0.0,
            alvo=0.0,
            ganho_pct=0.0,
            assert_pct=0.0,
            data=ts.strftime("%Y-%m-%d"),
            hora=ts.strftime("%H:%M"),
        )

    last = df.iloc[-1]
    price = float(last["close"])
    ema_f = float(last["ema_fast"])
    ema_s = float(last["ema_slow"])
    atr = float(last["atr"])

    ts_now = _now_brt()
    data_str = ts_now.strftime("%Y-%m-%d")
    hora_str = ts_now.strftime("%H:%M")

    # Se volatilidade ou preço inválidos -> sem sinal
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

    # Definição de direção pela tendência + força em 24h
    direction: Optional[Direction] = None

    if (
        change_24h_pct >= change_min
        and price > ema_f > ema_s
    ):
        direction = "LONG"
    elif (
        change_24h_pct <= -change_min
        and price < ema_f < ema_s
    ):
        direction = "SHORT"

    if direction is None:
        # Mercado sem tendência clara ou 24h fraco -> não operar
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

    # Calcula assertividade histórica do setup
    assert_pct = _calc_assertividade(
        df=df,
        direction=direction,
        min_gain_pct=MIN_GAIN_PCT,
        horizon_bars=horizon,
    )

    # Alvo baseado em múltiplos de ATR, respeitando ganho mínimo
    atr_pct = (atr / price) * 100.0
    alvo_pct = max(MIN_GAIN_PCT, atr_mult * atr_pct)
    ganho_pct = round(alvo_pct, PCT_DECIMALS)

    if direction == "LONG":
        alvo = price * (1.0 + alvo_pct / 100.0)
    else:
        alvo = price * (1.0 - alvo_pct / 100.0)

    alvo = round(alvo, PRICE_DECIMALS)
    preco_fmt = round(price, PRICE_DECIMALS)

    # Aplica filtro final pela assertividade
    if assert_pct >= MIN_ASSERT_PCT:
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
            change_24h = _get_daily_change_24h(coin)
            sinal = _gerar_sinal_para_moeda(coin, modo, change_24h_pct=change_24h)
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

        # pequena pausa para não sobrecarregar API
        time.sleep(0.2)

    sinais.sort(key=lambda s: s.par)
    _log(f"Sinais gerados para modo={modo}: {len(sinais)} moedas.")
    return sinais


# ======================================================================
# PIPELINE COMPLETO
# ======================================================================


def gerar_sinais() -> Dict[str, object]:
    _log("Iniciando geração de sinais (modelo tendência + 24h + ATR + assertividade)...")

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
    _log("Executando worker_entrada (AUTOMAÇÃO PROFISSIONAL)...")
    payload = gerar_sinais()
    salvar_json(payload)
    _log("worker_entrada finalizado com sucesso.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("Encerrado pelo usuário (Ctrl+C).")
