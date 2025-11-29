import json
from datetime import datetime, timedelta

import pandas as pd
import exchanges

from config_autotrader import (
    MOEDAS_OFICIAIS,
    ENTRADA_JSON_PATH,
    garantir_pastas,
    agora_data_hora_br,
    SINAL_CONFIG,
    ATR_PERIODO,
)

# ===========================================
#    WORKER DE ENTRADA PROFISSIONAL (REV 2025-11)
#
#  - Histórico multi-timeframe (4h / 1d) para contexto
#  - Preço AO VIVO (ticker) para coluna PREÇO e ganho%
#  - Tendência (EMA20 x EMA50)
#  - ATR + ATR%
#  - FIBONACCI com ATR
#  - Assertividade PROFISSIONAL (score contínuo)
#
#  OBS:
#   - 3% de ganho e 65% de assertividade são filtros aplicados
#     APENAS na hora de exibir/publicar (painel/saída),
#     não aqui no cálculo bruto.
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

        # Se já veio como DataFrame
        if isinstance(dados, pd.DataFrame):
            return dados if not dados.empty else None

        # Caso venha como lista de candles
        if len(dados) == 0:
            return None

        df = pd.DataFrame(
            dados,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        return df

    except Exception as e:  # noqa: BLE001
        print(f"[ERRO buscar_candles] {coin}: {e}")
        return None


# =====================================================
# BUSCA PREÇO AO VIVO (TICKER)
# =====================================================
def buscar_preco_ao_vivo(coin: str) -> float:
    """
    Tenta buscar o preço AO VIVO via exchanges.get_price(coin).
    Se não existir ou falhar, retorna 0.0.
    """
    try:
        if hasattr(exchanges, "get_price"):
            preco = exchanges.get_price(coin)
            if preco is not None and preco > 0:
                return float(preco)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN buscar_preco_ao_vivo] {coin}: {e}")

    return 0.0


# =====================================================
# ATR
# =====================================================
def calcular_atr(df: pd.DataFrame, periodos: int | None = None) -> pd.Series:
    if periodos is None:
        periodos = ATR_PERIODO

    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(periodos).mean()
    return atr


# =====================================================
# Tendência
# =====================================================
def tendencia(df: pd.DataFrame) -> str:
    ema20 = df["close"].ewm(span=20).mean().iloc[-1]
    ema50 = df["close"].ewm(span=50).mean().iloc[-1]
    return "LONG" if ema20 > ema50 else "SHORT"


# =====================================================
# FIBO com ATR
# =====================================================
def fibonacci_alvos(preco: float, direcao: str, atr: float) -> tuple[float, float, float]:
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
def ganho_percent(preco: float, alvo: float, direcao: str) -> float:
    if preco <= 0 or alvo == 0:
        return 0.0

    if direcao == "LONG":
        return round(((alvo - preco) / preco) * 100.0, 2)
    else:
        return round(((preco - alvo) / preco) * 100.0, 2)


# =====================================================
# ASSERTIVIDADE PROFISSIONAL
# =====================================================

ALTA_CONFIANCA = {
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "AVAX",
    "LINK",
    "ATOM",
}

MEDIA_CONFIANCA = {
    "ADA",
    "NEAR",
    "OP",
    "INJ",
    "AAVE",
    "LTC",
    "XRP",
    "BCH",
    "DOT",
    "TIA",
    "ARB",
}


def assertividade(moeda: str, modo: str, ganho_pct: float, atr_pct: float) -> float:
    """
    Score contínuo = Base + Pontos do ganho + Pontos do ATR
    Faixa final: 40% a 95%
    """

    moeda = moeda.upper()
    modo = modo.upper()

    # 1) Base por grupo
    if moeda in ALTA_CONFIANCA:
        base = 62.0
    elif moeda in MEDIA_CONFIANCA:
        base = 58.0
    else:
        base = 54.0

    # 2) Ganho (máx 20%)
    g = max(0.0, min(ganho_pct, 20.0))
    ganho_score = (g / 20.0) * 18.0  # até +18

    # 3) ATR % (faixas ideais)
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

    # 4) Limites
    score = max(40.0, min(score, 95.0))

    return round(score, 2)


# =====================================================
# GERADOR DE SINAL (usa HISTÓRICO + PREÇO AO VIVO)
# =====================================================
def gerar_sinal(coin: str, timeframe: str) -> dict | None:
    """
    - Usa candles 4h/1d para contexto (tendência, ATR, Fibo).
    - Usa preço AO VIVO (ticker) para PREÇO e ganho %.
    """

    modo = "SWING" if timeframe == "4h" else "POSICIONAL"

    df = buscar_candles(coin, timeframe=timeframe, limit=120)
    if df is None or len(df) < 60:
        return None

    # Preço de referência do candle (fallback)
    preco_candle = float(df["close"].iloc[-1])

    # Tenta buscar preço ao vivo
    preco_live = buscar_preco_ao_vivo(coin)
    preco = preco_live if preco_live > 0 else preco_candle

    atr_serie = calcular_atr(df, periodos=ATR_PERIODO)
    atr_valor = atr_serie.iloc[-1]

    if pd.isna(atr_valor) or atr_valor <= 0:
        return None

    atr_pct = abs(atr_valor / preco) * 100.0

    # ATR% (faixas amplas) definem se é "NAO ENTRAR"
    sinal = None
    if timeframe == "4h":
        # SWING
        if not (0.3 <= atr_pct <= 12.0):
            sinal = "NAO ENTRAR"
    else:
        # POSICIONAL
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

    # Data/hora BRT via config_autotrader
    data_str, hora_str = agora_data_hora_br()

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
        "data": data_str,
        "hora": hora_str,
    }


# =====================================================
# GERAR TODOS
# =====================================================
def gerar_todos() -> dict:
    swing: list[dict] = []
    posicional: list[dict] = []

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


# =====================================================
# SALVAR JSON (FORMATO SIMPLIFICADO PARA O PAINEL)
# =====================================================
def _simplificar_lista(lista: list[dict]) -> list[dict]:
    simples: list[dict] = []

    for s in lista or []:
        try:
            par = s.get("par")
            sinal = s.get("sinal")
            preco = float(s.get("preco", 0.0))

            # usa "alvo" se existir; senão cai para "alvo_1"
            alvo_base = s.get("alvo", s.get("alvo_1", 0.0))
            alvo = float(alvo_base or 0.0)

            ganho = float(s.get("ganho_pct", 0.0))
            assert_pct = float(s.get("assert_pct", 0.0))

            data_str = s.get("data", "")
            hora_str = s.get("hora", "")

            simples.append(
                {
                    "par": par,
                    "sinal": str(sinal) if sinal is not None else "",
                    "preco": round(preco, 3),
                    "alvo": round(alvo, 3),
                    "ganho_pct": round(ganho, 2),
                    "assert_pct": round(assert_pct, 2),
                    "data": data_str,
                    "hora": hora_str,
                }
            )
        except Exception as e:  # noqa: BLE001
            print(f"[WARN salvar_json] Erro ao simplificar sinal {s}: {e}")
            continue

    return simples


def salvar_json(dados: dict) -> None:
    """
    Converte o resultado completo de gerar_todos()
    em um formato SIMPLIFICADO, exatamente igual
    ao que o painel de ENTRADA espera.

    Formato final:

    {
      "swing": [ { ...campos... }, ... ],
      "posicional": [ { ...campos... }, ... ]
    }
    """
    swing_raw = dados.get("swing", [])
    pos_raw = dados.get("posicional", [])

    saida = {
        "swing": _simplificar_lista(swing_raw),
        "posicional": _simplificar_lista(pos_raw),
    }

    garantir_pastas()
    caminho = ENTRADA_JSON_PATH

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, indent=4, ensure_ascii=False)


# =====================================================
# MAIN
# =====================================================
def main() -> None:
    dados = gerar_todos()
    salvar_json(dados)
    print("[OK] entrada.json gerado com sucesso.")
    print(f"Swing: {len(dados['swing'])}  |  Posicional: {len(dados['posicional'])}")


if __name__ == "__main__":
    main()
