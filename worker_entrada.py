import pandas as pd
import exchanges
import json
from datetime import datetime, timedelta
from config_autotrader import MOEDAS_OFICIAIS, ENTRADA_JSON_PATH, garantir_pastas

# ===========================================
#    WORKER DE ENTRADA PROFISSIONAL
#
#  - Tendência (EMA20 x EMA50)
#  - ATR + ATR%
#  - FIBONACCI com ATR
#  - Assertividade PROFISSIONAL (score contínuo)
#  - Faixas de ATR% amplas (Swing e Posicional)
#
#  OBS IMPORTANTES:
#   - 3% de ganho e 65% de assertividade NÃO são filtros.
#     Servem APENAS para cor no painel.
# ===========================================

MOEDAS = MOEDAS_OFICIAIS

# =====================================================
# BUSCA OHLCV
# =====================================================
def buscar_candles(coin: str, timeframe: str = "4h", limit: int = 120):
    base = coin.split("/")[0].strip().upper()

    try:
        if hasattr(exchanges, "get_ohlcv"):
            dados = exchanges.get_ohlcv(base, timeframe=timeframe, limit=limit)
        elif hasattr(exchanges, "get_ohlcv_binance"):
            dados = exchanges.get_ohlcv_binance(base, timeframe=timeframe, limit=limit)
        else:
            raise RuntimeError("Ajuste buscar_candles() para exchanges.py")

        if dados is None:
            return None

        # Caso venha como DataFrame
        if isinstance(dados, pd.DataFrame):
            return dados if not dados.empty else None

        # Caso venha como lista de candles
        if len(dados) == 0:
            return None

        df = pd.DataFrame(
            dados,
            columns=["timestamp","open","high","low","close","volume"]
        )
        return df

    except Exception as e:
        print(f"[ERRO buscar_candles] {coin}: {e}")
        return None


# =====================================================
# ATR
# =====================================================
def calcular_atr(df, periodos=14):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(periodos).mean()
    return atr


# =====================================================
# Tendência
# =====================================================
def tendencia(df):
    ema20 = df["close"].ewm(span=20).mean().iloc[-1]
    ema50 = df["close"].ewm(span=50).mean().iloc[-1]
    return "LONG" if ema20 > ema50 else "SHORT"


# =====================================================
# FIBO com ATR
# =====================================================
def fibonacci_alvos(preco, direcao, atr):
    if preco <= 0 or atr <= 0 or pd.isna(atr):
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


# =====================================================
# Ganho %
# =====================================================
def ganho_percent(preco, alvo, direcao):
    if preco <= 0 or alvo == 0:
        return 0.0

    if direcao == "LONG":
        return round(((alvo - preco) / preco) * 100.0, 2)
    else:
        return round(((preco - alvo) / preco) * 100.0, 2)


# =====================================================
# ASSERTIVIDADE PROFISSIONAL (SCORE CONTÍNUO)
# =====================================================

ALTA_CONFIANCA = {
    "BTC", "ETH", "BNB", "SOL", "AVAX", "LINK", "ATOM"
}

MEDIA_CONFIANCA = {
    "ADA","NEAR","OP","INJ","AAVE","LTC","XRP","BCH","DOT","TIA","ARB"
}


def assertividade(moeda, modo, ganho_pct, atr_pct):
    """
    Score contínuo = Base + Pontos do ganho + Pontos do ATR
    Faixa final: 40% a 95%
    """

    moeda = moeda.upper()
    modo = modo.upper()

    # -------------------------
    # 1) Base por grupo
    # -------------------------
    if moeda in ALTA_CONFIANCA:
        base = 62.0
    elif moeda in MEDIA_CONFIANCA:
        base = 58.0
    else:
        base = 54.0

    # -------------------------
    # 2) Ganho (máx 20%)
    # -------------------------
    g = max(0.0, min(ganho_pct, 20.0))
    ganho_score = (g / 20.0) * 18.0   # até +18

    # -------------------------
    # 3) ATR % (faixas ideais)
    # -------------------------
    if modo == "SWING":
        if 2.0 <= atr_pct <= 8.0:
            atr_score = 12.0
        elif 0.3 <= atr_pct <= 12.0:
            atr_score = 6.0
        else:
            atr_score = -8.0
    else:  # POSICIONAL
        if 3.0 <= atr_pct <= 20.0:
            atr_score = 12.0
        elif 1.0 <= atr_pct <= 30.0:
            atr_score = 6.0
        else:
            atr_score = -8.0

    score = base + ganho_score + atr_score

    # -------------------------
    # 4) Limites
    # -------------------------
    score = max(40.0, min(score, 95.0))

    return round(score, 2)


# =====================================================
# GERADOR DE SINAL
# =====================================================
def gerar_sinal(coin, timeframe):

    modo = "SWING" if timeframe == "4h" else "POSICIONAL"

    df = buscar_candles(coin, timeframe=timeframe, limit=120)
    if df is None or len(df) < 60:
        return None

    preco = float(df["close"].iloc[-1])

    atr_serie = calcular_atr(df)
    atr_valor = atr_serie.iloc[-1]

    if pd.isna(atr_valor) or atr_valor <= 0:
        return None

    atr_pct = abs(atr_valor / preco) * 100.0

    # ATR% (faixas amplas)
    sinal = None
    if timeframe == "4h":
        if not (0.3 <= atr_pct <= 12.0):
            sinal = "NAO ENTRAR"
    else:
        if not (1.0 <= atr_pct <= 30.0):
            sinal = "NAO ENTRAR"

    direcao = tendencia(df)

    alvo1, alvo2, alvo3 = fibonacci_alvos(preco, direcao, atr_valor)

    ganho = ganho_percent(preco, alvo1, direcao)

    # ASSERT CONTÍNUA
    assert_pct = assertividade(coin, modo, ganho, atr_pct)

    # Se ATR% ok → segue tendência
    if sinal is None:
        sinal = direcao

    # Horário BRT
    agora_utc = datetime.utcnow()
    agora_brt = agora_utc - timedelta(hours=3)

    return {
        "par": coin,
        "modo": modo,
        "sinal": sinal,
        "preco": round(preco, 3),
        "alvo": round(alvo1, 3),
        "alvo_1": round(alvo1, 3),
        "alvo_2": round(alvo2, 3),
        "alvo_3": round(alvo3, 3),
        "ganho_pct": ganho,
        "assert_pct": assert_pct,
        "data": agora_brt.strftime("%Y-%m-%d"),
        "hora": agora_brt.strftime("%H:%M"),
    }


# =====================================================
# GERAR TODOS
# =====================================================
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

    return {"swing": swing, "posicional": posicional}


# =====================================================
# SALVAR JSON
# =====================================================
def salvar_json(dados):
    # garante que a pasta data/ existe
    garantir_pastas()
    caminho = ENTRADA_JSON_PATH

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

# =====================================================
# MAIN
# =====================================================
def main():
    dados = gerar_todos()
    salvar_json(dados)
    print("[OK] entrada.json gerado com sucesso.")
    print(f"Swing: {len(dados['swing'])}  |  Posicional: {len(dados['posicional'])}")


if __name__ == "__main__":
    main()
