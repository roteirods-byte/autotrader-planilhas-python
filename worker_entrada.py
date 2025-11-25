# ================================================================
#   WORKER DE ENTRADA PROFISSIONAL — VERSÃO FINAL
#   FIBO + TENDÊNCIA + ATR + SWINGS
#   3 ALVOS PROFISSIONAIS
#   Filtragem somenta por ganho >= 3%
#   ASSERTIVIDADE NÃO FILTRA — só indicador
# ================================================================

import ccxt
import pandas as pd
import numpy as np
import json
import time
from datetime import datetime, timezone, timedelta

# ================================================================
# AJUSTES GERAIS
# ================================================================
MOEDAS = [
    "AAVE","ADA","APT","ARB","ATOM","AVAX","AXS","BCH","BNB","BTC","DOGE","DOT","ETH",
    "FET","FIL","FLUX","ICP","INJ","LDO","LINK","LTC","NEAR","OP","PEPE","POL","RATS",
    "RENDER","RUNE","SEI","SHIB","SOL","SUI","TIA","TNSR","TON","TRX","UNI","WIF","XRP"
]

INTERVALOS = {
    "SWING": "4h",
    "POSICIONAL": "1d"
}

BRT = timezone(timedelta(hours=-3))

MIN_GAIN = 3.0           # filtro de entrada
FIB_EXT_1 = 1.0
FIB_EXT_2 = 1.272
FIB_EXT_3 = 1.618
ATR_PERIOD = 14
WINDOW_SWING = 30         # barras usadas para detectar swings

# ================================================================
# FUNÇÕES PROFISSIONAIS
# ================================================================

def calcular_atr(df):
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(ATR_PERIOD).mean()
    return atr.iloc[-1]

def detectar_tendencia(df):
    """
    Tendência real:
    - LONG: fechamento atual mais próximo do topo do range
    - SHORT: fechamento atual mais próximo do fundo do range
    """
    close = df["close"].iloc[-1]
    max_h = df["high"].max()
    min_l = df["low"].min()

    faixa = max_h - min_l
    if faixa == 0:
        return "NAO ENTRAR"

    pos = (close - min_l) / faixa

    if pos > 0.55:
        return "LONG"
    elif pos < 0.45:
        return "SHORT"
    else:
        return "NAO ENTRAR"

def calcular_fibo_alvos(preco_atual, tendencia, high, low):
    if tendencia == "LONG":
        movimento = high - low
        alvo1 = preco_atual + movimento * FIB_EXT_1
        alvo2 = preco_atual + movimento * FIB_EXT_2
        alvo3 = preco_atual + movimento * FIB_EXT_3
    else:  # SHORT
        movimento = high - low
        alvo1 = preco_atual - movimento * FIB_EXT_1
        alvo2 = preco_atual - movimento * FIB_EXT_2
        alvo3 = preco_atual - movimento * FIB_EXT_3

    return alvo1, alvo2, alvo3

def calcular_ganho(preco, alvo, tendencia):
    if tendencia == "LONG":
        return (alvo - preco) / preco * 100
    else:
        return (preco - alvo) / preco * 100

def gerar_assertividade(tendencia, gain_pct):
    """
    Assertividade simples, independente, NÃO filtra entrada.
    """
    base = 40
    tendencia_bonus = 10 if tendencia != "NAO ENTRAR" else -5
    volatilidade = min(max(gain_pct, 0), 10)  # limita
    return base + tendencia_bonus + volatilidade

# ================================================================
# EXCHANGE CCXT
# ================================================================
exchange = ccxt.bybit({
    "enableRateLimit": True
})

# ================================================================
# LOOP PRINCIPAL
# ================================================================
def gerar_sinais():
    resultados = {"SWING": [], "POSICIONAL": []}

    for modo, timeframe in INTERVALOS.items():
        print(f"[worker entrada] Calculando para modo {modo}...")

        for mo in MOEDAS:
            par = f"{mo}/USDT"

            try:
                ohlcv = exchange.fetch_ohlcv(par, timeframe, limit=WINDOW_SWING)
                df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])

                preco = df["close"].iloc[-1]
                high = df["high"].max()
                low = df["low"].min()

                tendencia = detectar_tendencia(df)
                if tendencia == "NAO ENTRAR":
                    alvo1 = preco
                    ganho1 = 0
                else:
                    alvo1, alvo2, alvo3 = calcular_fibo_alvos(preco, tendencia, high, low)

                    ganho1 = calcular_ganho(preco, alvo1, tendencia)
                    ganho2 = calcular_ganho(preco, alvo2, tendencia)
                    ganho3 = calcular_ganho(preco, alvo3, tendencia)

                # Filtro: apenas ganho_1
                sinal = tendencia
                if ganho1 < MIN_GAIN:
                    sinal = "NAO ENTRAR"

                assert_pct = gerar_assertividade(tendencia, ganho1)

                data_brt = datetime.now(BRT).strftime("%Y-%m-%d")
                hora_brt = datetime.now(BRT).strftime("%H:%M")

                resultados[modo].append({
                    "par": mo,
                    "sinal": sinal,
                    "preco": round(preco, 6),
                    "alvo_1": round(alvo1, 6),
                    "ganho_1_pct": round(ganho1, 2),
                    "alvo_2": round(alvo2, 6) if tendencia != "NAO ENTRAR" else 0,
                    "ganho_2_pct": round(ganho2, 2) if tendencia != "NAO ENTRAR" else 0,
                    "alvo_3": round(alvo3, 6) if tendencia != "NAO ENTRAR" else 0,
                    "ganho_3_pct": round(ganho3, 2) if tendencia != "NAO ENTRAR" else 0,
                    "assert_pct": round(assert_pct, 2),
                    "data": data_brt,
                    "hora": hora_brt
                })

            except Exception as e:
                print(f"Erro em {par}: {e}")

    # salva
    with open("entrada.json", "w") as f:
        json.dump(resultados, f, indent=4)

    print("[worker entrada] Finalizado com sucesso.")

# executa
if __name__ == "__main__":
    gerar_sinais()
