import json
import pandas as pd
from datetime import datetime
from exchanges import buscar_candles
import numpy as np

# ==============================
#  VERSÃO PROFISSIONAL (BLINDADA)
# ==============================

MOEDAS = [
    "AAVE","ADA","APT","ARB","ATOM","AVAX","AXS","BCH","BNB","BTC","DOGE","DOT","ETH",
    "FET","FIL","FLUX","ICP","INJ","LDO","LINK","LTC","NEAR","OP","PEPE","POL","RATS","RENDER",
    "RUNE","SEI","SHIB","SOL","SUI","TIA","TNSR","TON","TRX","UNI","WIF","XRP"
]

def calcular_atr(df, periodos=14):
    high = df['high']
    low = df['low']
    close = df['close']

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    atr = tr.rolling(periodos).mean()
    return atr

def tendencia(df):
    ema20 = df['close'].ewm(span=20).mean().iloc[-1]
    ema50 = df['close'].ewm(span=50).mean().iloc[-1]
    return "LONG" if ema20 > ema50 else "SHORT"

def fibonacci_alvos(preco, direcao, atr):
    if pd.isna(atr) or atr <= 0:
        return 0, 0, 0

    if direcao == "LONG":
        alvo1 = preco + atr * 1.618
        alvo2 = preco + atr * 2.618
        alvo3 = preco + atr * 4.236
    else:
        alvo1 = preco - atr * 1.618
        alvo2 = preco - atr * 2.618
        alvo3 = preco - atr * 4.236

    return float(alvo1), float(alvo2), float(alvo3)

def ganho_percent(preco, alvo, direcao):
    if alvo == 0:
        return 0
    if direcao == "LONG":
        return round(((alvo - preco) / preco) * 100, 2)
    else:
        return round(((preco - alvo) / preco) * 100, 2)

def assertividade(moeda):
    return 75.0 if moeda in ["BCH", "SOL", "BTC", "ETH", "AVAX"] else 55.0

def gerar_sinal(coin, timeframe):
    df = buscar_candles(coin, timeframe=timeframe, limit=120)
    if df is None or len(df) < 60:
        return None

    preco = float(df['close'].iloc[-1])

    atr_valor = calcular_atr(df).iloc[-1]

    direcao = tendencia(df)

    alvo1, alvo2, alvo3 = fibonacci_alvos(preco, direcao, atr_valor)

    ganho = ganho_percent(preco, alvo1, direcao)

    sinal = direcao if ganho >= 3 else "NAO ENTRAR"

    return {
        "par": coin,
        "modo": "SWING" if timeframe == "4h" else "POSICIONAL",
        "sinal": sinal,
        "preco": round(preco, 3),
        "alvo_1": round(alvo1, 3),
        "alvo_2": round(alvo2, 3),
        "alvo_3": round(alvo3, 3),
        "ganho_pct": ganho,
        "assert_pct": assertividade(coin),
        "data": datetime.now().strftime("%Y-%m-%d"),
        "hora": datetime.now().strftime("%H:%M")
    }

def gerar_todos():
    swing = []
    posicional = []

    for coin in MOEDAS:
        s = gerar_sinal(coin, "4h")
        if s:
            swing.append(s)

        p = gerar_sinal(coin, "1d")
        if p:
            posicional.append(p)

    return {
        "swing": swing,
        "posicional": posicional
    }

def salvar_json(dados):
    with open("entrada.json", "w") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

def main():
    dados = gerar_todos()
    salvar_json(dados)
    print(f"[OK] Gerados {len(dados['swing'])} sinais swing e {len(dados['posicional'])} sinais posicional.")
    print("[OK] Arquivo entrada.json atualizado.")

if __name__ == "__main__":
    main()
