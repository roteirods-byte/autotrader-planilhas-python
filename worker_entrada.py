#!/usr/bin/env python3
"""
worker_entrada.py  (MODO DEMO REALISTA USANDO exchanges.get_ohlcv)

- Usa dados REAIS das corretoras que já funcionam no projeto (KuCoin, Gate.io, OKX),
  através da função get_ohlcv() do módulo exchanges.py.
- NÃO usa Binance / Bybit diretamente.
- NÃO usa ccxt.
- NÃO gera valores iguais para todas as moedas.
- Calcula ATR 4H (Swing) e ATR 1D (Posicional).
- Calcula PREÇO ALVO primeiro e depois GANHO %.
- Aplica filtros para gerar sinal "NAO ENTRAR" quando:
  - ganho_pct < 3.0, ou
  - assert_pct < 65.0

Saída: arquivo JSON (entrada.json) no formato esperado pelo painel ENTRADA.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List

from config import PCT_DECIMALS, PRICE_DECIMALS, TZINFO
from exchanges import get_ohlcv

# ======================================================================
# CONFIGURAÇÕES GERAIS
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

# Caminho do JSON usado pelo backend (server.js usa o mesmo padrão)
ENTRADA_JSON_PATH = os.getenv("ENTRADA_JSON_PATH", "entrada.json")

# Quantidade de candles para cálculo
CANDLES_SWING = 120      # 4h
CANDLES_POSICIONAL = 200 # 1d

# Critérios mínimos para publicar sinal
MIN_GAIN_PCT = 3.0
MIN_ASSERT_PCT = 65.0


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
# FUNÇÕES DE APOIO
# ======================================================================


def _now_brt() -> datetime:
    return datetime.now(TZINFO)


def _log(msg: str) -> None:
    ts = _now_brt().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [worker_entrada] {msg}", flush=True)


def _ohlcv_from_df(coin: str, timeframe: str, limit: int) -> List[List[float]]:
    """
    Usa exchanges.get_ohlcv() para obter um DataFrame e converte para
    lista de candles [ts, open, high, low, close, volume] compatível
    com as funções de ATR / assertividade.
    """
    df = get_ohlcv(coin, timeframe, limit=limit)
    if df is None or df.empty:
        raise RuntimeError(f"Sem OHLCV para {coin} {timeframe}")

    df2 = df.tail(limit)
    ohlcv: List[List[float]] = []
    for ts, row in df2.iterrows():
        ms = int(ts.timestamp() * 1000.0)
        ohlcv.append(
            [
                ms,
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            ]
        )
    return ohlcv


def _calc_atr(ohlcv: List[List[float]], period: int = 14) -> float:
    """
    Calcula ATR (Average True Range) simples com base em candles OHLCV.
    """
    if len(ohlcv) < period + 1:
        raise ValueError(f"Poucos candles para ATR: {len(ohlcv)} < {period + 1}")

    trs: List[float] = []
    prev_close = float(ohlcv[0][4])

    for c in ohlcv[1:]:
        high = float(c[2])
        low = float(c[3])
        close = float(c[4])

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(prev_close - low),
        )
        trs.append(tr)
        prev_close = close

    if not trs:
        raise ValueError("Lista de TR vazia ao calcular ATR.")

    last_trs = trs[-period:]
    atr = sum(last_trs) / float(len(last_trs))
    return atr


def _calc_assertividade(
    ohlcv: List[List[float]],
    step: int = 5,
    max_barras: int = 60,
) -> float:
    """
    Mede uma "assertividade" simples baseada na direção dos fechamentos.
    """
    closes = [float(c[4]) for c in ohlcv]
    n = len(closes)

    if n <= step:
        return 70.0  # fallback

    wins = 0
    total = 0

    start = max(0, n - max_barras)
    for i in range(start + step, n):
        prev = closes[i - step]
        cur = closes[i]
        if cur > prev:
            wins += 1
        total += 1

    if total == 0:
        return 70.0

    base = wins / total
    pct = 60.0 + (base - 0.5) * 50.0
    pct = max(50.0, min(85.0, pct))
    return pct


# ======================================================================
# GERAÇÃO DE SINAL POR MOEDA
# ======================================================================


def _gerar_sinal_para_moeda(coin: str, modo: str) -> SinalEntrada:
    """
    Gera o sinal para uma única moeda e um único modo (swing/posicional).
    """
    if modo == "swing":
        timeframe = "4h"
        limit = CANDLES_SWING
        atr_mult = 1.3
    elif modo == "posicional":
        timeframe = "1d"
        limit = CANDLES_POSICIONAL
        atr_mult = 1.5
    else:
        raise ValueError(f"Modo inválido: {modo}")

    ohlcv = _ohlcv_from_df(coin, timeframe, limit)

    if not ohlcv:
        raise RuntimeError(f"Nenhum candle para {coin} ({timeframe})")

    preco_atual = float(ohlcv[-1][4])
    ref_index = max(0, len(ohlcv) - 6)
    preco_ref = float(ohlcv[ref_index][4])

    if preco_atual >= preco_ref:
        sinal = "LONG"
    else:
        sinal = "SHORT"

    atr = _calc_atr(ohlcv, period=14)

    if sinal == "LONG":
        alvo = preco_atual + atr * atr_mult
        ganho_pct = (alvo / preco_atual - 1.0) * 100.0
    else:  # SHORT
        alvo = max(0.0, preco_atual - atr * atr_mult)
        ganho_pct = (preco_atual / alvo - 1.0) * 100.0 if alvo > 0 else 0.0

    assert_pct = _calc_assertividade(ohlcv)

    if ganho_pct < MIN_GAIN_PCT or assert_pct < MIN_ASSERT_PCT:
        sinal_final = "NAO ENTRAR"
        alvo_final = preco_atual
        ganho_final = 0.0
    else:
        sinal_final = sinal
        alvo_final = alvo
        ganho_final = ganho_pct

    ts = _now_brt()
    data_str = ts.strftime("%Y-%m-%d")
    hora_str = ts.strftime("%H:%M")

    return SinalEntrada(
        par=coin,
        sinal=sinal_final,
        preco=round(preco_atual, PRICE_DECIMALS),
        alvo=round(alvo_final, PRICE_DECIMALS),
        ganho_pct=round(ganho_final, PCT_DECIMALS),
        assert_pct=round(assert_pct, PCT_DECIMALS),
        data=data_str,
        hora=hora_str,
    )


def _gerar_sinais_por_modo(modo: str) -> List[SinalEntrada]:
    resultados: List[SinalEntrada] = []

    for coin in COINS:
        try:
            sinal = _gerar_sinal_para_moeda(coin, modo)
            resultados.append(sinal)
        except Exception as e:
            _log(f"ERRO ao gerar sinal para {coin} (modo={modo}): {e}")
            ts = _now_brt()
            data_str = ts.strftime("%Y-%m-%d")
            hora_str = ts.strftime("%H:%M")
            resultados.append(
                SinalEntrada(
                    par=coin,
                    sinal="NAO ENTRAR",
                    preco=0.0,
                    alvo=0.0,
                    ganho_pct=0.0,
                    assert_pct=0.0,
                    data=data_str,
                    hora=hora_str,
                )
            )

        time.sleep(0.2)

    resultados.sort(key=lambda s: s.par)
    _log(f"Sinais gerados para modo={modo}: {len(resultados)} moedas.")
    return resultados


def gerar_sinais() -> Dict[str, object]:
    _log("Iniciando geração de sinais (KuCoin/Gate/OKX via exchanges.get_ohlcv)...")

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
    _log("Executando worker_entrada (modo DEMO REALISTA)...")
    payload = gerar_sinais()
    salvar_json(payload)
    _log("worker_entrada finalizado com sucesso.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("Encerrado pelo usuário (Ctrl+C).")
