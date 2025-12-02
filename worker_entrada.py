#!/usr/bin/env python3
# worker_entrada.py
#
# Gera o arquivo data/entrada.json para o painel de ENTRADA.
# - Usa preço ao vivo (ticker) para cada moeda.
# - Calcula ALVO a partir do histórico (Fibo + tendência).
# - Calcula GANHO % somente de (preço_ao_vivo x alvo).
# - Usa filtro de 3% APENAS para classificar o sinal: LONG/SHORT/NAO_ENTRAR.
# - Assertividade NÃO é mais filtro (apenas cor no painel).
# - Usa timeframe 4h para SWING e 1d para POSICIONAL.

import json
import math
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import ccxt  # biblioteca de corretoras


# ==========================
# CONFIGURAÇÕES BÁSICAS
# ==========================

COINS = [
    "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH", "BNB",
    "BTC", "DOGE", "DOT", "ETH", "FET", "FIL", "FLUX", "ICP", "INJ",
    "LDO", "LINK", "LTC", "NEAR", "OP", "PEPE", "POL", "RATS", "RENDER",
    "RUNE", "SEI", "SHIB", "SOL", "SUI", "TIA", "TNSR", "TON", "TRX",
    "UNI", "WIF", "XRP",
]

TIMEFRAMES = {
    "SWING": "4h",
    "POSICIONAL": "1d",
}

MIN_GAIN_PCT = 3.0      # filtro mínimo de ganho para classificar LONG/SHORT
MIN_ASSERT_PCT = 65.0   # NÃO usado como filtro (apenas referência visual)
LOOKBACK_CANDLES = 120  # histórico para cálculo


# ==========================
# FUNÇÕES DE EXCHANGES
# ==========================

def criar_exchanges():
    """
    Cria instâncias das corretoras.
    """
    print("[exchanges] Criando conexões com KuCoin, Gate.io e OKX...")

    kucoin = ccxt.kucoin({
        "enableRateLimit": True,
    })
    gate = ccxt.gateio({
        "enableRateLimit": True,
    })
    okx = ccxt.okx({
        "enableRateLimit": True,
    })

    exchanges = {
        "kucoin": kucoin,
        "gate": gate,
        "okx": okx,
    }
    return exchanges


def _fetch_first_ok(exchanges, func_name, *args, **kwargs):
    """
    Tenta a mesma chamada em todas as corretoras até funcionar.
    """
    last_error = None
    for name, ex in exchanges.items():
        try:
            if func_name == "ohlcv":
                data = ex.fetch_ohlcv(*args, **kwargs)
            elif func_name == "ticker":
                data = ex.fetch_ticker(*args, **kwargs)
            else:
                raise ValueError(f"função desconhecida: {func_name}")
            print(f"[exchanges] OK {func_name} em {name} para {args[0]}")
            return data
        except Exception as e:
            print(f"[exchanges] Erro em {name} para {func_name} {args[0]}: {e}")
            last_error = e
            continue
    raise last_error if last_error else RuntimeError("Nenhuma exchange disponível")


def get_ohlcv_multi(exchanges, symbol, timeframe, limit):
    """
    Busca OHLCV em alguma corretora disponível.
    """
    print(f"[exchanges] Buscando OHLCV {symbol} {timeframe}...")
    return _fetch_first_ok(exchanges, "ohlcv", symbol, timeframe, limit=limit)


def get_price_live(exchanges, symbol):
    """
    Busca preço ao vivo em alguma corretora disponível.
    """
    print(f"[exchanges] Buscando preço ao vivo de {symbol}...")
    ticker = _fetch_first_ok(exchanges, "ticker", symbol)
    return float(ticker["last"])


# ==========================
# FUNÇÕES DE CÁLCULO
# ==========================

def ema(values, period):
    """
    Calcula EMA simples.
    """
    if not values or period <= 0 or len(values) < period:
        return []

    k = 2 / (period + 1)
    ema_values = []
    ema_prev = sum(values[:period]) / period
    ema_values.append(ema_prev)

    for price in values[period:]:
        ema_prev = (price - ema_prev) * k + ema_prev
        ema_values.append(ema_prev)

    return ema_values


def calc_atr(ohlcv, period=14):
    """
    Calcula ATR a partir do histórico de candles.
    """
    if not ohlcv or len(ohlcv) < period + 1:
        return 0.0

    trs = []
    for i in range(1, len(ohlcv)):
        high = ohlcv[i][2]
        low = ohlcv[i][3]
        prev_close = ohlcv[i-1][4]
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        trs.append(tr)

    atr_series = ema(trs, period)
    return float(atr_series[-1]) if atr_series else 0.0


def detectar_tendencia(closes):
    """
    Define LONG/SHORT com base em EMA20 x EMA50.
    """
    if len(closes) < 50:
        return "NEUTRO"

    ema20 = ema(closes, 20)[-1]
    ema50 = ema(closes, 50)[-1]

    if ema20 > ema50 * 1.002:   # pequena folga
        return "LONG"
    elif ema20 < ema50 * 0.998:
        return "SHORT"
    else:
        return "NEUTRO"


def calcular_alvo_fibo(ohlcv, side):
    """
    Calcula um alvo Fibo simples com base no último movimento.
    """
    if not ohlcv or len(ohlcv) < 2:
        return None

    closes = [c[4] for c in ohlcv]
    last_close = closes[-1]
    prev_close = closes[-2]

    move = last_close - prev_close
    if side == "LONG":
        alvo = last_close + move * 1.618
    elif side == "SHORT":
        alvo = last_close - move * 1.618
    else:
        return None

    return float(alvo)


def calcular_assertividade(preco, alvo, atr):
    """
    Calcula uma assertividade aproximada com base em (distância até o alvo / ATR).
    Quanto maior a relação, maior a assertividade (até um teto).
    """
    if atr <= 0:
        return 60.0

    dist = abs(alvo - preco)
    rr = dist / atr  # "reward / ATR"

    # mapeia rr em 60%..90%
    base = 60.0
    extra = min(rr, 3.0) * 10.0  # até +30
    assert_pct = base + extra
    if assert_pct > 90.0:
        assert_pct = 90.0

    return round(assert_pct, 2)


# ==========================
# GERAÇÃO DE SINAIS
# ==========================

def gerar_sinais_para_modo(exchanges, modo, timeframe):
    """
    Gera lista de sinais para um modo (SWING / POSICIONAL).
    """
    resultados = []

    for coin in COINS:
        symbol = f"{coin}/USDT"

        try:
            # 1) Histórico para cálculo (Fibo, ATR, tendência)
            ohlcv = get_ohlcv_multi(
                exchanges,
                symbol,
                timeframe,
                limit=LOOKBACK_CANDLES
            )
            closes = [c[4] for c in ohlcv]

            # 2) Tendência -> LONG / SHORT
            side = detectar_tendencia(closes)
            # Se não houver tendência clara, vamos marcar como NAO_ENTRAR,
            # mas ainda assim registrar a moeda no painel.

            # 3) Preço ao vivo
            preco_live = get_price_live(exchanges, symbol)

            # 4) ATR (volatilidade)
            atr = calc_atr(ohlcv)

            # 5) Alvo (modelo Fibo + histórico)
            alvo = calcular_alvo_fibo(ohlcv, side)
            if alvo is None:
                print(f"[sinais] {coin} sem alvo calculado, usando alvo = preço atual e ganho 0%.")
                alvo = preco_live

            # 6) GANHO % = resultado do modelo no momento,
            #    usando apenas preço ao vivo x alvo.
            if side == "LONG":
                ganho_pct = (alvo / preco_live - 1.0) * 100.0
            elif side == "SHORT":
                ganho_pct = (preco_live / alvo - 1.0) * 100.0
            else:
                # Sem tendência clara: não faz sentido projetar alvo direcional.
                # Consideramos ganho 0 e alvo = preço atual.
                ganho_pct = 0.0
                alvo = preco_live

            ganho_pct = round(ganho_pct, 2)

            # 7) ASSERT % = função da relação (distância / ATR)
            assert_pct = calcular_assertividade(preco_live, alvo, atr)

            # 8) Classificação do sinal (sem filtrar moedas)
            # Regra oficial:
            # - Se há tendência (LONG/SHORT) E ganho_pct >= MIN_GAIN_PCT → sinal = LONG/SHORT
            # - Caso contrário → sinal = NAO_ENTRAR
            if side in ("LONG", "SHORT") and ganho_pct >= MIN_GAIN_PCT:
                sinal_final = side
            else:
                sinal_final = "NAO_ENTRAR"

            # 9) Data/Hora em BRT
            now = datetime.now(ZoneInfo("America/Sao_Paulo"))
            data_str = now.strftime("%Y-%m-%d")
            hora_str = now.strftime("%H:%M")

            registro = {
                "par": coin,
                "modo": modo,
                "sinal": sinal_final,
                "preco": round(preco_live, 3),
                "alvo": round(alvo, 3),
                "ganho_pct": ganho_pct,
                "assert_pct": assert_pct,
                "data": data_str,
                "hora": hora_str,
            }

            resultados.append(registro)
            print(
                f"[sinais] {modo} {coin}: {side} "
                f"preco={registro['preco']} alvo={registro['alvo']} "
                f"ganho={ganho_pct:.2f}% assert={assert_pct:.2f}%"
            )

        except Exception as e:
            print(f"[erro] Falha ao processar {coin} ({modo}): {e}")
            continue

        # pequena pausa para não sobrecarregar as APIs
        time.sleep(0.3)

    return resultados


# ==========================
# ROTINA PRINCIPAL
# ==========================

def main():
    base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data"
    data_dir.mkdir(exist_ok=True)
    saida_arquivo = data_dir / "entrada.json"

    exchanges = criar_exchanges()

    swing_sinais = gerar_sinais_para_modo(
        exchanges,
        modo="SWING",
        timeframe=TIMEFRAMES["SWING"],
    )

    pos_sinais = gerar_sinais_para_modo(
        exchanges,
        modo="POSICIONAL",
        timeframe=TIMEFRAMES["POSICIONAL"],
    )

    dados = {
        "swing": swing_sinais,
        "posicional": pos_sinais,
    }

    with saida_arquivo.open("w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=4)

    print(f"[OK] entrada.json gerado em {saida_arquivo}")
    print(f"Swing: {len(swing_sinais)} | Posicional: {len(pos_sinais)}")


if __name__ == "__main__":
    main()
