#!/usr/bin/env python3
"""
worker_entrada.py  (MODO REAL)

- Usa dados REAIS das corretoras (Binance + Bybit).
- NÃO usa versão demo.
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
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Tuple

import ccxt  # type: ignore

from config import TZINFO, PRICE_DECIMALS, PCT_DECIMALS  # type: ignore

# ======================================================================
# CONFIGURAÇÕES GERAIS
# ======================================================================

# Universo fixo de moedas (sem USDT)
COINS = sorted(
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

# Caminho do JSON usado pelo backend (mesmo do server.js)
ENTRADA_JSON_PATH = os.getenv("ENTRADA_JSON_PATH", "entrada.json")

# Quantidade de candles para cálculo de ATR e assertividade
CANDLES_SWING = 120   # 4h
CANDLES_POSICIONAL = 200  # 1d

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
    print(f"[{ts}] [worker_entrada_real] {msg}", flush=True)


def _create_exchanges() -> Dict[str, ccxt.Exchange]:
    """
    Cria instâncias das corretoras principais.

    Estratégia:
    - Usamos Binance como principal.
    - Usamos Bybit como backup.
    """
    binance = ccxt.binance(
        {
            "enableRateLimit": True,
            "options": {"adjustForTimeDifference": True},
        }
    )
    bybit = ccxt.bybit(
        {
            "enableRateLimit": True,
            "options": {"adjustForTimeDifference": True},
        }
    )

    # Faz um ping rápido para sincronizar tempo (não é obrigatório, mas ajuda)
    try:
        binance.load_markets()
        _log("Mercados carregados (Binance).")
    except Exception as e:  # noqa: BLE001
        _log(f"ATENÇÃO: erro ao carregar mercados Binance: {e}")

    try:
        bybit.load_markets()
        _log("Mercados carregados (Bybit).")
    except Exception as e:  # noqa: BLE001
        _log(f"ATENÇÃO: erro ao carregar mercados Bybit: {e}")

    return {"binance": binance, "bybit": bybit}


def _build_symbol(coin: str) -> str:
    """
    Constrói o símbolo padrão da moeda.

    Ex: "BTC" -> "BTC/USDT"
    """
    return f"{coin}/USDT"


def _fetch_ohlcv_with_fallback(
    exchanges: Dict[str, ccxt.Exchange],
    symbol: str,
    timeframe: str,
    limit: int,
) -> List[List[float]]:
    """
    Busca OHLCV usando:
    1) Binance como principal
    2) Bybit como backup

    Sempre retorna uma lista de candles ou lança exceção.
    """
    err_msgs = []

    for name in ("binance", "bybit"):
        ex = exchanges.get(name)
        if ex is None:
            continue
        try:
            _log(f"Buscando OHLCV em {name} para {symbol} tf={timeframe}, limit={limit}...")
            ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not ohlcv:
                raise RuntimeError("lista vazia")
            _log(f"OK {name}: recebidos {len(ohlcv)} candles para {symbol} ({timeframe}).")
            return ohlcv
        except Exception as e:  # noqa: BLE001
            msg = f"{name}: erro ao buscar OHLCV para {symbol} ({timeframe}): {e}"
            _log(msg)
            err_msgs.append(msg)
            # pequena pausa antes de tentar próxima corretora
            time.sleep(0.5)

    raise RuntimeError("Falha ao buscar OHLCV em todas as corretoras: " + " | ".join(err_msgs))


def _calc_atr(ohlcv: List[List[float]], period: int = 14) -> float:
    """
    Calcula ATR (Average True Range) simples com base em candles OHLCV.

    Cada candle: [timestamp, open, high, low, close, volume]
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

    # Média simples dos últimos "period" TRs
    last_trs = trs[-period:]
    atr = sum(last_trs) / float(len(last_trs))
    return atr


def _calc_assertividade(ohlcv: List[List[float]], step: int = 5, max_barras: int = 60) -> float:
    """
    Mede uma "assertividade" simples baseada na direção dos fechamentos.

    Lógica:
    - Compara fechamento atual com fechamento de 'step' barras atrás.
    - Conta quantas vezes houve "acerto" no sentido da tendência.
    - Converte para um percentual entre ~60% e ~85% (ajustado).
    """
    closes = [float(c[4]) for c in ohlcv]
    n = len(closes)

    if n <= step:
        return 70.0  # fallback razoável

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

    base = wins / total  # 0..1
    # Normaliza em torno de 0.7 com amplitude controlada
    pct = 60.0 + (base - 0.5) * 50.0  # de ~35 a ~85
    pct = max(50.0, min(85.0, pct))
    return pct


def _gerar_sinal_para_moeda(
    exchanges: Dict[str, ccxt.Exchange],
    coin: str,
    modo: str,
) -> SinalEntrada:
    """
    Gera o sinal REAL para uma única moeda e um único modo.

    modo:
    - "swing"      -> timeframe 4h, ATR menor
    - "posicional" -> timeframe 1d, ATR maior
    """
    symbol = _build_symbol(coin)

    if modo == "swing":
        timeframe = "4h"
        limit = CANDLES_SWING
        atr_mult = 1.3
    elif modo == "posicional":
        timeframe = "1d"
        limit = CANDLES_POSICIONAL
        atr_mult = 2.0
    else:
        raise ValueError(f"Modo desconhecido: {modo}")

    ohlcv = _fetch_ohlcv_with_fallback(exchanges, symbol, timeframe, limit)
    if not ohlcv:
        raise RuntimeError(f"Nenhum OHLCV retornado para {symbol} ({timeframe}).")

    # Preço atual = fechamento do último candle
    ultimo = ohlcv[-1]
    preco_atual = float(ultimo[4])

    # Tendência simples: compara com fechamento 5 candles atrás
    ref_index = max(0, len(ohlcv) - 6)
    preco_ref = float(ohlcv[ref_index][4])

    if preco_atual >= preco_ref:
        sinal = "LONG"
    else:
        sinal = "SHORT"

    # Calcula ATR
    atr = _calc_atr(ohlcv, period=14)

    # Calcula preço ALVO com base em ATR
    if sinal == "LONG":
        alvo = preco_atual + atr * atr_mult
        ganho_pct = (alvo / preco_atual - 1.0) * 100.0
    elif sinal == "SHORT":
        alvo = max(0.0, preco_atual - atr * atr_mult)
        ganho_pct = (preco_atual / alvo - 1.0) * 100.0 if alvo > 0 else 0.0
    else:
        # fallback (não deve cair aqui)
        alvo = preco_atual
        ganho_pct = 0.0

    # Calcula assertividade
    assert_pct = _calc_assertividade(ohlcv)

    # Aplica filtros: se não atender critérios, vira "NAO ENTRAR"
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


def _gerar_sinais_por_modo(exchanges: Dict[str, ccxt.Exchange], modo: str) -> List[SinalEntrada]:
    resultados: List[SinalEntrada] = []
    for coin in COINS:
        try:
            sinal = _gerar_sinal_para_moeda(exchanges, coin, modo)
            resultados.append(sinal)
        except Exception as e:  # noqa: BLE001
            _log(f"ERRO ao gerar sinal para {coin} (modo={modo}): {e}")
            # Em caso de erro, registramos um "NAO ENTRAR" para não ficar vazio
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

    resultados.sort(key=lambda s: s.par)
    _log(f"Sinais gerados para modo={modo}: {len(resultados)} moedas.")
    return resultados


def gerar_sinais_reais() -> Dict[str, object]:
    _log("Iniciando geração de sinais REAIS (Binance + Bybit)...")
    exchanges = _create_exchanges()

    swing = _gerar_sinais_por_modo(exchanges, "swing")
    posicional = _gerar_sinais_por_modo(exchanges, "posicional")

    payload = {
        "generated_at": _now_brt().isoformat(),
        "swing": [asdict(s) for s in swing],
        "posicional": [asdict(s) for s in posicional],
    }

    _log(
        f"Sinais REAIS gerados: {len(payload['swing'])} swing, "
        f"{len(payload['posicional'])} posicional."
    )
    return payload


def salvar_json(payload: Dict[str, object]) -> None:
    """
    Salva JSON em caminho temporário e depois faz replace atômico.
    """
    tmp_path = ENTRADA_JSON_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, ENTRADA_JSON_PATH)
    _log(f"Arquivo salvo em: {ENTRADA_JSON_PATH}")


def main() -> None:
    _log("Executando worker_entrada REAL (Binance + Bybit)...")
    payload = gerar_sinais_reais()
    salvar_json(payload)
    _log("worker_entrada REAL finalizado com sucesso.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("Encerrado pelo usuário (Ctrl+C).")
