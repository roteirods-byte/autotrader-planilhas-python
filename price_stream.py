#!/usr/bin/env python3
"""
price_stream.py

Atualiza PREÇO e GANHO% do entrada.json em alta frequência,
usando preço atual da corretora (Bybit) via ccxt.

- O worker_entrada.py continua responsável por:
  * ATR, ASSERT%, direção (sinal base), ALVO.
- Este script:
  * lê o entrada.json
  * busca o preço atual de cada moeda
  * recalcula PREÇO e GANHO% (para LONG/SHORT)
  * atualiza o campo generated_at
  * grava de volta no mesmo arquivo

Rodar em loop contínuo (depois vamos colocar em systemd).
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List

import ccxt  # já está no requirements.txt

from config import PCT_DECIMALS, PRICE_DECIMALS, TZINFO

ENTRADA_JSON_PATH = os.getenv("ENTRADA_JSON_PATH", "entrada.json")
SYMBOL_SUFFIX = "USDT"  # AAVEUSDT, BTCUSDT, etc.


def now_brt() -> datetime:
    return datetime.now(TZINFO)


def log(msg: str) -> None:
    ts = now_brt().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [price_stream] {msg}", flush=True)


def build_exchange() -> ccxt.bybit:
    """
    Cria cliente da Bybit com rate limit ligado.
    Se quiser trocar para Binance no futuro, é só ajustar aqui.
    """
    exchange = ccxt.bybit(
        {
            "enableRateLimit": True,
        }
    )
    return exchange


def fetch_prices(exchange: ccxt.Exchange, coins: List[str]) -> Dict[str, float]:
    """
    Busca o preço atual (last) de cada moeda na lista.
    Usa símbolo COIN/USDT (ex: BTC/USDT, ETH/USDT).
    """
    prices: Dict[str, float] = {}

    for coin in coins:
        symbol = f"{coin}/{SYMBOL_SUFFIX}"
        try:
            ticker = exchange.fetch_ticker(symbol)
            last = float(ticker["last"])
            prices[coin] = last
        except Exception as e:
            log(f"Erro ao buscar preço de {symbol}: {e}")
        # pequena pausa para respeitar rate limit
        time.sleep(0.2)

    return prices


def recalc_gain_for_signal(
    preco_atual: float,
    alvo: float,
    sinal: str,
    ganho_original: float,
) -> float:
    """
    Recalcula o GANHO% com base no preço atual e no alvo, só para LONG/SHORT.
    Para NAO ENTRAR, mantém o ganho original (para não inventar direção).
    """
    if alvo <= 0 or preco_atual <= 0:
        return ganho_original

    if sinal == "LONG":
        retorno = (alvo / preco_atual - 1.0) * 100.0
        return retorno
    elif sinal == "SHORT":
        retorno = (preco_atual / alvo - 1.0) * 100.0
        return retorno
    else:
        # NAO ENTRAR: mantém o valor que veio do worker
        return ganho_original


def update_payload_with_prices(payload: dict, prices: Dict[str, float]) -> dict:
    """
    Atualiza PREÇO e GANHO% nas listas swing e posicional.
    Também atualiza o campo generated_at para a hora atual.
    """
    for lista_nome in ("swing", "posicional"):
        lista = payload.get(lista_nome) or []
        for s in lista:
            coin = s.get("par")
            if not coin:
                continue

            preco_atual = prices.get(coin)
            if not preco_atual:
                continue

            preco_atual = float(preco_atual)
            s["preco"] = round(preco_atual, PRICE_DECIMALS)

            alvo = float(s.get("alvo") or 0.0)
            sinal = s.get("sinal", "NAO ENTRAR")
            ganho_original = float(s.get("ganho_pct") or 0.0)

            ganho_novo = recalc_gain_for_signal(
                preco_atual=preco_atual,
                alvo=alvo,
                sinal=sinal,
                ganho_original=ganho_original,
            )
            s["ganho_pct"] = round(ganho_novo, PCT_DECIMALS)

    # carimbo de "Dados atualizados às" para o painel
    payload["generated_at"] = now_brt().isoformat()
    return payload


def main_loop() -> None:
    log("Iniciando price_stream (atualização rápida de PREÇO e GANHO%)...")
    exchange = build_exchange()

    while True:
        try:
            with open(ENTRADA_JSON_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            log(f"Erro ao ler {ENTRADA_JSON_PATH}: {e}")
            time.sleep(5)
            continue

        # descobre todas as moedas presentes no JSON
        coins: List[str] = sorted(
            {
                s.get("par")
                for lista_nome in ("swing", "posicional")
                for s in (payload.get(lista_nome) or [])
                if s.get("par")
            }
        )

        if not coins:
            log("Nenhuma moeda encontrada no JSON; aguardando...")
            time.sleep(5)
            continue

        prices = fetch_prices(exchange, coins)
        if not prices:
            log("Nenhum preço obtido; aguardando...")
            time.sleep(5)
            continue

        payload = update_payload_with_prices(payload, prices)

        # grava de volta no mesmo arquivo, com escrita atômica
        tmp_path = f"{ENTRADA_JSON_PATH}.price.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, ENTRADA_JSON_PATH)
            log(f"Atualizado {ENTRADA_JSON_PATH} com preços em tempo quase real.")
        except Exception as e:
            log(f"Erro ao gravar {ENTRADA_JSON_PATH}: {e}")

        # intervalo entre atualizações (segundos)
        time.sleep(5)


if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        log("Encerrado pelo usuário (Ctrl+C).")
