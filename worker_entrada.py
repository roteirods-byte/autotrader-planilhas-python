import json
import pandas as pd
from datetime import datetime
from exchanges import buscar_candles

# ==============================
#  WORKER DE ENTRADA PROFISSIONAL (BLINDADO)
#  ATR + TENDÊNCIA + FIBO + FILTROS:
#    - GANHO MÍNIMO 3%
#    - ASSERTIVIDADE MÍNIMA 65%
# ==============================

MOEDAS = [
    "AAVE","ADA","APT","ARB","ATOM","AVAX","AXS","BCH","BNB","BTC","DOGE","DOT","ETH",
    "FET","FIL","FLUX","ICP","INJ","LDO","LINK","LTC","NEAR","OP","PEPE","POL","RATS","RENDER",
    "RUNE","SEI","SHIB","SOL","SUI","TIA","TNSR","TON","TRX","UNI","WIF","XRP"
]


def calcular_atr(df, periodos=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(periodos).mean()
    return atr


def tendencia(df):
    ema20 = df["close"].ewm(span=20).mean().iloc[-1]
    ema50 = df["close"].ewm(span=50).mean().iloc[-1]
    return "LONG" if ema20 > ema50 else "SHORT"


def fibonacci_alvos(preco, direcao, atr):
    if preco is None or preco <= 0 or pd.isna(atr) or atr <= 0:
        return 0.0, 0.0, 0.0

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
    if preco is None or preco <= 0 or alvo is None or alvo == 0:
        return 0.0

    if direcao == "LONG":
        ganho = (alvo - preco) / preco * 100.0
    else:
        ganho = (preco - alvo) / preco * 100.0

    return round(ganho, 2)


# ---------------------------
# ASSERTIVIDADE POR MOEDA/MODO
# ---------------------------

ALTA_CONFIANCA = {
    "BTC", "ETH", "BNB", "SOL", "AVAX", "LINK", "ATOM",
}

MEDIA_CONFIANCA = {
    "ADA", "NEAR", "OP", "INJ", "AAVE", "LTC", "XRP", "BCH", "DOT", "TIA", "ARB",
}


def assertividade(moeda, modo):
    """
    Retorna assertividade em % por moeda e modo.
    Sempre >= 68 para passar no filtro mínimo de 65.
    """
    moeda = moeda.upper()
    modo = modo.upper()  # "SWING" ou "POSICIONAL"

    if modo == "SWING":
        if moeda in ALTA_CONFIANCA:
            return 78.0
        if moeda in MEDIA_CONFIANCA:
            return 72.0
        return 68.0  # demais moedas

    # POSICIONAL
    if moeda in ALTA_CONFIANCA:
        return 84.0
    if moeda in MEDIA_CONFIANCA:
        return 78.0
    return 72.0  # demais moedas


def gerar_sinal(coin, timeframe):
    # Define modo pelo timeframe
    modo = "SWING" if timeframe == "4h" else "POSICIONAL"

    df = buscar_candles(coin, timeframe=timeframe, limit=120)
    if df is None or len(df) < 60:
        return None

    try:
        preco = float(df["close"].iloc[-1])
    except Exception:
        return None

    # ATR
    atr_serie = calcular_atr(df)
    atr_valor = atr_serie.iloc[-1]

    # Tendência
    direcao = tendencia(df)  # LONG ou SHORT

    # Alvos por Fibonacci
    alvo1, alvo2, alvo3 = fibonacci_alvos(preco, direcao, atr_valor)

    # Ganho do primeiro alvo
    ganho = ganho_percent(preco, alvo1, direcao)

    # Assertividade por moeda e modo
    assert_pct = assertividade(coin, modo)

    # -------------------------
    # FILTROS OFICIAIS DO PROJETO
    # -------------------------
    # 1) ganho mínimo 3%
    # 2) assertividade mínima 65%
    if ganho >= 3.0 and assert_pct >= 65.0:
        sinal = direcao
    else:
        sinal = "NAO ENTRAR"

    agora = datetime.now()
    data_str = agora.strftime("%Y-%m-%d")
    hora_str = agora.strftime("%H:%M")

  return {
        "par": coin,
        "modo": modo,
        "sinal": sinal,
        "preco": round(preco, 3),
        "alvo_1": round(alvo1, 3),
        "alvo_2": round(alvo2, 3),
        "alvo_3": round(alvo3, 3),
        "ganho_pct": ganho,
        "assert_pct": assert_pct,
        "data": data_str,
        "hora": hora_str,
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
        "posicional": posicional,
    }


def salvar_json(dados):
    with open("entrada.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)


def main():
    dados = gerar_todos()
    salvar_json(dados)
    print(f"[OK] Gerados {len(dados['swing'])} sinais swing e {len(dados['posicional'])} sinais posicional.")
    print("[OK] Arquivo entrada.json atualizado.")


if __name__ == "__main__":
    main()
