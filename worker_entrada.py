# ================================================================
#   WORKER DE ENTRADA PROFISSIONAL — AUTOTRADER
#
#   - Lê lista de moedas (fixa, 39 moedas)
#   - Para cada moeda, calcula sinais em dois modos:
#       * SWING  (4H)
#       * POSICIONAL (1D)
#   - Usa:
#       * Tendência (EMAs 20 e 50)
#       * ATR (14)
#       * Variação de preço (janela ~24h)
#       * Fibonacci simples para projetar 3 alvos (ALVO 1, 2, 3)
#   - Aplica o filtro oficial:
#       * GANHO % (ALVO 1) < 3%  => NAO ENTRAR
#   - Gera o arquivo entrada.json no formato:
#       {
#         "swing": [... 39 sinais ...],
#         "posicional": [... 39 sinais ...]
#       }
# ================================================================

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import exchanges  # usa o mesmo exchanges.py do projeto


# ------------------------------------------------
# Configuração básica
# ------------------------------------------------

ENTRADA_JSON_PATH = os.environ.get("ENTRADA_JSON_PATH", "entrada.json")

# Timeframes por modo
MODOS = {
    "SWING": {
        "timeframe": "4h",
        "janela_ohlcv": 120,   # candles para cálculo
        "janela_24h": 6,       # 6 x 4h = 24h
    },
    "POSICIONAL": {
        "timeframe": "1d",
        "janela_ohlcv": 120,
        "janela_24h": 2,       # 2 dias para medir variação
    },
}

# Lista oficial de moedas (sem USDT)
MOEDAS = [
    "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH",
    "BNB", "BTC", "DOGE", "DOT", "ETH", "FET", "FIL", "FLUX",
    "ICP", "INJ", "LDO", "LINK", "LTC", "NEAR", "OP", "PEPE",
    "POL", "RATS", "RENDER", "RUNE", "SEI", "SHIB", "SOL", "SUI",
    "TIA", "TNSR", "TON", "TRX", "UNI", "WIF", "XRP",
]


# ------------------------------------------------
# Funções auxiliares de tempo e JSON
# ------------------------------------------------

def agora_brt() -> Tuple[str, str]:
    """Retorna data e hora BRT (YYYY-MM-DD, HH:MM)."""
    agora_utc = datetime.utcnow()
    brt = agora_utc - timedelta(hours=3)
    return brt.strftime("%Y-%m-%d"), brt.strftime("%H:%M")


def salvar_json_entrada(dados: Dict[str, List[Dict[str, Any]]]) -> None:
    try:
        with open(ENTRADA_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        logging.info(
            f"[worker_entrada] Gravado {ENTRADA_JSON_PATH}: "
            f"{len(dados.get('swing', []))} sinais swing, "
            f"{len(dados.get('posicional', []))} sinais posicional."
        )
    except Exception as e:
        logging.error(f"[worker_entrada] Erro ao gravar {ENTRADA_JSON_PATH}: {e}")


# ------------------------------------------------
# Indicadores: EMA, ATR, variação, Fibonacci
# ------------------------------------------------

def ema(valores: List[float], periodo: int) -> float:
    if len(valores) < periodo:
        return valores[-1]
    k = 2 / (periodo + 1)
    ema_val = sum(valores[:periodo]) / periodo
    for v in valores[periodo:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def calcular_atr(ohlcv: List[List[float]], periodo: int = 14) -> float:
    if len(ohlcv) < periodo + 1:
        return 0.0

    trs: List[float] = []
    for i in range(1, len(ohlcv)):
        _, _, high, low, close_anterior, _ = ohlcv[i - 1]
        _, _, high_atual, low_atual, close_atual, _ = ohlcv[i]

        tr = max(
            high_atual - low_atual,
            abs(high_atual - close_anterior),
            abs(low_atual - close_anterior),
        )
        trs.append(tr)

    if len(trs) < periodo:
        return sum(trs) / max(len(trs), 1)

    ultimos = trs[-periodo:]
    return sum(ultimos) / periodo


def variacao_percentual_24h(closes: List[float], janela_24h: int) -> float:
    if len(closes) <= janela_24h:
        return 0.0
    atual = closes[-1]
    anterior = closes[-(janela_24h + 1)]
    if anterior == 0:
        return 0.0
    return (atual - anterior) / anterior * 100.0


def calcular_fibonacci_alvos(
    side: str,
    closes: List[float],
    highs: List[float],
    lows: List[float],
) -> Tuple[float, float, float]:
    """
    Calcula três alvos usando uma abordagem simples de Fibonacci.
    - Busca o último range (máx e mín) numa janela recente (por ex. últimos 40 candles).
    - Usa extensões em cima do preço atual (para LONG) ou abaixo (para SHORT).
    """
    if not closes or not highs or not lows:
        return 0.0, 0.0, 0.0

    janela = min(40, len(closes))
    recent_high = max(highs[-janela:])
    recent_low = min(lows[-janela:])
    preco_atual = closes[-1]

    amplitude = recent_high - recent_low
    if amplitude <= 0:
        amplitude = max(preco_atual * 0.02, 0.01)  # fallback simples

    side = (side or "").upper()

    if side == "LONG":
        alvo1 = preco_atual + 0.382 * amplitude
        alvo2 = preco_atual + 0.618 * amplitude
        alvo3 = preco_atual + 1.000 * amplitude
    elif side == "SHORT":
        alvo1 = preco_atual - 0.382 * amplitude
        alvo2 = preco_atual - 0.618 * amplitude
        alvo3 = preco_atual - 1.000 * amplitude
    else:
        # Se não tiver direção, projeta só um alvo pequeno para frente
        alvo1 = preco_atual * 1.03
        alvo2 = preco_atual * 1.06
        alvo3 = preco_atual * 1.10

    return round(alvo1, 3), round(alvo2, 3), round(alvo3, 3)


def calcular_ganho_percentual(side: str, preco: float, alvo: float) -> float:
    if not preco or not alvo:
        return 0.0
    side = (side or "").upper()
    if side == "LONG":
        ganho = (alvo - preco) / preco * 100.0
    elif side == "SHORT":
        ganho = (preco - alvo) / preco * 100.0
    else:
        ganho = 0.0
    return round(ganho, 2)


def calcular_assertividade_estimada(
    side: str,
    ema_curta: float,
    ema_longa: float,
    variacao_24h: float,
    atr_val: float,
    preco_atual: float,
) -> float:
    """
    Estimativa simples de assertividade (0–100%).
    Não é backtest real, mas dá uma noção de confiança.
    - Alinha tendência (EMAs) com variação de 24h.
    - Penaliza quando direção está “contra” a variação.
    """
    base = 60.0  # ponto de partida

    side = (side or "").upper()
    tendencia_alta = ema_curta > ema_longa
    tendencia_baixa = ema_curta < ema_longa

    if side == "LONG" and tendencia_alta:
        base += 10
    if side == "SHORT" and tendencia_baixa:
        base += 10

    if side == "LONG" and variacao_24h > 0:
        base += 10
    if side == "SHORT" and variacao_24h < 0:
        base += 10

    if (side == "LONG" and variacao_24h < 0) or (side == "SHORT" and variacao_24h > 0):
        base -= 10

    # Pequeno ajuste de volatilidade relativa
    if preco_atual > 0 and atr_val > 0:
        vol_pct = atr_val / preco_atual * 100.0
        if 2 <= vol_pct <= 10:
            base += 5
        elif vol_pct > 15:
            base -= 5

    # Limita entre 5% e 95%
    base = max(5.0, min(95.0, base))
    return round(base, 2)


# ------------------------------------------------
# Coleta de dados e geração de sinais
# ------------------------------------------------

def obter_ohlcv(par: str, timeframe: str, limit: int) -> List[List[float]]:
    """
    Recebe apenas o ticker (AAVE, ADA, BTC, etc.).
    O exchanges.py já acrescenta /USDT internamente.
    """
    try:
        if hasattr(exchanges, "get_ohlcv"):
            return exchanges.get_ohlcv(par, timeframe=timeframe, limit=limit)
        elif hasattr(exchanges, "get_ohlcv_binance"):
            return exchanges.get_ohlcv_binance(par, timeframe=timeframe, limit=limit)
        else:
            raise RuntimeError("Ajuste obter_ohlcv() para o seu exchanges.py")
    except Exception as e:
        logging.error(f"[worker_entrada] Erro ao obter OHLCV de {par}: {e}")
        return []


def gerar_sinal_para_par_modo(par: str, modo: str) -> Dict[str, Any]:
    cfg = MODOS[modo]
    timeframe = cfg["timeframe"]
    janela_ohlcv = cfg["janela_ohlcv"]
    janela_24h = cfg["janela_24h"]

    ohlcv = obter_ohlcv(par, timeframe, janela_ohlcv)
    if not ohlcv:
        return {}

    highs = [c[2] for c in ohlcv]
    lows = [c[3] for c in ohlcv]
    closes = [c[4] for c in ohlcv]

    preco_atual = closes[-1]
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    atr_val = calcular_atr(ohlcv, 14)
    var_24h = variacao_percentual_24h(closes, janela_24h)

    # Direção base
    if ema20 > ema50 and var_24h >= 0:
        side = "LONG"
    elif ema20 < ema50 and var_24h <= 0:
        side = "SHORT"
    else:
        side = "NAO ENTRAR"

    # Calcula alvos com Fibonacci
    alvo_1, alvo_2, alvo_3 = calcular_fibonacci_alvos(side, closes, highs, lows)

    # Ganho esperado no ALVO 1
    ganho_pct = calcular_ganho_percentual(side, preco_atual, alvo_1)

    # Aplica filtro oficial de 3%:
    # se ganho < 3%, o side vira NAO ENTRAR
    if ganho_pct < 3.0:
        side_filtrado = "NAO ENTRAR"
    else:
        side_filtrado = side

    # Assertividade estimada (informativa)
    assert_pct = calcular_assertividade_estimada(
        side_filtrado, ema20, ema50, var_24h, atr_val, preco_atual
    )

    data_str, hora_str = agora_brt()

    sinal = {
        "par": par,
        "modo": modo,  # SWING ou POSICIONAL
        "sinal": side_filtrado,  # LONG / SHORT / NAO ENTRAR
        "preco": round(preco_atual, 3),
        "alvo_1": alvo_1,
        "alvo_2": alvo_2,
        "alvo_3": alvo_3,
        "ganho_pct": ganho_pct if side_filtrado != "NAO ENTRAR" else 0.0,
        "assert_pct": assert_pct,
        "data": data_str,
        "hora": hora_str,
    }

    return sinal


def gerar_todos_sinais() -> Dict[str, List[Dict[str, Any]]]:
    logging.info("[worker_entrada] Iniciando geração de sinais.")
    resultado = {"swing": [], "posicional": []}

    for par in MOEDAS:
        # Modo SWING
        sinal_swing = gerar_sinal_para_par_modo(par, "SWING")
        if sinal_swing:
            resultado["swing"].append(sinal_swing)

        # Modo POSICIONAL
        sinal_pos = gerar_sinal_para_par_modo(par, "POSICIONAL")
        if sinal_pos:
            resultado["posicional"].append(sinal_pos)

    logging.info(
        f"[worker_entrada] Gerados {len(resultado['swing'])} sinais swing e "
        f"{len(resultado['posicional'])} sinais posicional."
    )
    return resultado


# ------------------------------------------------
# main()
# ------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    dados = gerar_todos_sinais()
    salvar_json_entrada(dados)


if __name__ == "__main__":
    main()
