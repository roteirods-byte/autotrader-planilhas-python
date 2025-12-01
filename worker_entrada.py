#!/usr/bin/env python3
# worker_entrada.py
#
# Gera o arquivo data/entrada.json para o painel de ENTRADA.
# - Usa preço ao vivo (ticker) para cada moeda.
# - Calcula ALVO a partir do histórico (Fibo + tendência).
# - Calcula GANHO % somente de (preço_ao_vivo x alvo).
# - Filtra sinais com GANHO % >= 3% e ASSERT % >= 65%.
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
    "LDO", "LINK", "LTC", "NEAR", "OP", "PEPE", "POL", "RATS",
    "RENDER", "RUNE", "SEI", "SHIB", "SOL", "SUI", "TIA", "TNSR",
    "TON", "TRX", "UNI", "WIF", "XRP",
]

TIMEFRAMES = {
    "SWING": "4h",
    "POSICIONAL": "1d",
}

MIN_GAIN_PCT = 3.0      # filtro mínimo de ganho
LOOKBACK_CANDLES = 120  # histórico para cálculo


# ==========================
# CONEXÃO COM CORRETORAS
# ==========================

def criar_exchanges():
    """
    Cria conexões públicas com 3 corretoras.
    (sem uso de chaves – apenas dados públicos)
    """
    print("[exchanges] Criando conexões com KuCoin, Gate.io e OKX...")
    exchanges = {
        "kucoin": ccxt.kucoin(),
        "gateio": ccxt.gateio(),
        "okx": ccxt.okx(),
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
    data = _fetch_first_ok(exchanges, "ohlcv", symbol, timeframe, limit=limit)
    return data


def get_price_live(exchanges, symbol):
    """
    Busca o preço AO VIVO (ticker.last).
    """
    print(f"[exchanges] Buscando preço ao vivo de {symbol}...")
    ticker = _fetch_first_ok(exchanges, "ticker", symbol)
    return float(ticker["last"])


# ==========================
# CÁLCULOS DE INDICADORES
# ==========================

def ema(series, period):
    """
    Calcula EMA simples em uma lista de valores.
    Retorna lista com mesmo tamanho da série.
    """
    if not series:
        return []

    k = 2 / (period + 1)
    ema_vals = [series[0]]
    for price in series[1:]:
        ema_vals.append(price * k + ema_vals[-1] * (1 - k))
    return ema_vals


def calc_atr(ohlcv, period=14):
    """
    Calcula ATR a partir de OHLCV.
    ohlcv: lista de [timestamp, open, high, low, close, volume]
    Retorna ATR atual (último valor).
    """
    if len(ohlcv) < period + 1:
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
    Calcula um alvo aproximado usando Fibo de extensão
    sobre o último movimento relevante (máx/min recente).
    """
    if len(ohlcv) < 10:
        return None

    highs = [c[2] for c in ohlcv[-60:]]  # janela recente
    lows = [c[3] for c in ohlcv[-60:]]

    swing_high = max(highs)
    swing_low = min(lows)
    amplitude = swing_high - swing_low
    if amplitude <= 0:
        return None

    fib_ext = 1.618  # extensão principal

    if side == "LONG":
        # alvo acima da máxima recente
        alvo = swing_high + amplitude * fib_ext
    else:
        # alvo abaixo da mínima recente
        alvo = swing_low - amplitude * fib_ext

    return float(alvo)


def calcular_assertividade(preco, alvo, atr):
    """
    Cria uma métrica de "assertividade" baseada em
    (distância até o alvo / ATR). Quanto maior a
    relação, maior a assertividade (até um teto).
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
# GERAÇÃO DOS SINAIS
# ==========================

def gerar_sinais_para_modo(exchanges, modo, timeframe):
    """
    Gera lista de sinais para um modo (SWING / POSICIONAL).

    Regras atuais (acordadas com o JORGE):
    - TODAS as moedas de COINS devem aparecer sempre no JSON.
    - O campo "sinal" pode ser: "LONG", "SHORT" ou "NÃO ENTRAR".
    - O limiar de 3% (MIN_GAIN_PCT) NÃO exclui a moeda:
      - ganho_pct >= MIN_GAIN_PCT e tendência válida -> sinal = LONG/SHORT
      - ganho_pct <  MIN_GAIN_PCT ou tendência neutra -> sinal = "NÃO ENTRAR"
    - A assertividade (assert_pct) nunca é filtro, apenas indicador visual no painel.
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
                limit=LOOKBACK_CANDLES,
            )
            closes = [c[4] for c in ohlcv]

            # 2) Tendência bruta (LONG / SHORT / NEUTRO)
            side_trend = detectar_tendencia(closes)

            # 3) Preço ao vivo
            preco_live = get_price_live(exchanges, symbol)

            # 4) ATR (volatilidade)
            atr = calc_atr(ohlcv)

            # Valores padrão (fallback) caso algo não possa ser calculado
            ganho_pct = 0.0
            assert_pct = 0.0
            alvo = preco_live

            # 5) Só tentamos calcular alvo/ganho/assert se houver tendência clara e ATR > 0
            if side_trend in ("LONG", "SHORT") and atr > 0:
                alvo_calc = calcular_alvo_fibo(ohlcv, side_trend)

                if alvo_calc is not None:
                    alvo = alvo_calc

                    # 6) GANHO % = diferença entre preço ao vivo e alvo
                    if side_trend == "LONG":
                        ganho_pct = (alvo / preco_live - 1.0) * 100.0
                    else:
                        ganho_pct = (preco_live / alvo - 1.0) * 100.0

                    ganho_pct = round(ganho_pct, 2)

                    # 7) ASSERT % = função da relação (distância / ATR)
                    assert_pct = calcular_assertividade(preco_live, alvo, atr)

            # 8) Decisão final do sinal usando o limiar de 3%
            if side_trend == "NEUTRO" or ganho_pct < MIN_GAIN_PCT:
                sinal_final = "NÃO ENTRAR"
            else:
                sinal_final = side_trend

            # 9) Data/Hora em BRT
            now = datetime.now(ZoneInfo("America/Sao_Paulo"))
            data_str = now.strftime("%Y-%m-%d")
            hora_str = now.strftime("%H:%M")

            # 10) Registro final
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
                f"[sinais] {modo} {coin}: {sinal_final} "
                f"preco={registro['preco']} alvo={registro['alvo']} "
                f"ganho={ganho_pct:.2f}% assert={assert_pct:.2f}% "
                f"(trend={side_trend})"
            )

        except Exception as e:
            # Em caso de erro, ainda assim registramos a moeda como "NÃO ENTRAR"
            print(f"[erro] Falha ao processar {coin} ({modo}): {e}")

            try:
                now = datetime.now(ZoneInfo("America/Sao_Paulo"))
                data_str = now.strftime("%Y-%m-%d")
                hora_str = now.strftime("%H:%M")

                registro = {
                    "par": coin,
                    "modo": modo,
                    "sinal": "NÃO ENTRAR",
                    "preco": 0.0,
                    "alvo": 0.0,
                    "ganho_pct": 0.0,
                    "assert_pct": 0.0,
                    "data": data_str,
                    "hora": hora_str,
                }
                resultados.append(registro)
            except Exception:
                # Não deve acontecer, mas não pode quebrar o loop.
                pass

        # 11) Pequena pausa para não sobrecarregar as APIs
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
