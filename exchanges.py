"""
exchanges.py

Módulo de CONEXÃO com corretoras para o AUTOTRADER.

- Usa 3 corretoras: KuCoin, Gate.io e OKX.
- Função principal: get_ohlcv(coin, timeframe, limit=200)
    * coin: "BTC", "ETH", etc. (SEM "USDT")
    * timeframe: "4h", "1d", etc.
    * Retorna DataFrame com colunas:
        ["open", "high", "low", "close", "volume"]
      com índice datetime no fuso horário do projeto (TZINFO).
- Se uma corretora falhar, tenta as outras.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

import ccxt  # type: ignore
import pandas as pd  # type: ignore

try:
    from config import TZINFO  # type: ignore
except Exception:  # fallback para testes
    from zoneinfo import ZoneInfo

    TZINFO = ZoneInfo("America/Sao_Paulo")


# ======================================================================
# FUNÇÃO DE LOG SIMPLES
# ======================================================================


def _log(msg: str) -> None:
    """Log simples deste módulo."""
    print(f"[exchanges] {msg}", flush=True)


# ======================================================================
# CRIAÇÃO DAS CONEXÕES COM AS CORRETORAS
# ======================================================================


def _create_exchanges() -> Dict[str, ccxt.Exchange]:
    """
    Cria conexões com as 3 corretoras escolhidas:
    - KuCoin
    - Gate.io
    - OKX

    Todas em modo anônimo (somente dados públicos).
    """
    _log("Criando conexões com KuCoin, Gate.io e OKX...")

    kucoin = ccxt.kucoin({"enableRateLimit": True})
    gateio = ccxt.gateio({"enableRateLimit": True})
    okx = ccxt.okx({"enableRateLimit": True})

    return {
        "kucoin": kucoin,
        "gateio": gateio,
        "okx": okx,
    }


# ======================================================================
# CONVERSÃO SIMPLES DE TICKER -> SYMBOL COM USDT
# ======================================================================


def _coin_to_symbol(coin: str) -> str:
    """
    Converte 'BTC' -> 'BTC/USDT', etc.

    Garante que:
    - se já vier 'BTC/USDT', usa direto;
    - se vier 'BTCUSDT', vira 'BTC/USDT';
    - tudo em maiúsculas.
    """
    c = coin.upper().strip()

    # Já está no formato correto
    if "/" in c:
        return c

    # Formato BTCUSDT -> BTC/USDT
    if c.endswith("USDT") and len(c) > 4:
        base = c[:-4]
        return f"{base}/USDT"

    # Formato BTC -> BTC/USDT
    return f"{c}/USDT"


# ======================================================================
# OBTENÇÃO DE OHLCV (HISTÓRICO) PARA OS CÁLCULOS
# ======================================================================


def get_ohlcv(
    coin: str,
    timeframe: str,
    limit: int = 200,
    sleep_between: float = 0.8,
) -> Optional[pd.DataFrame]:
    """
    Busca candles OHLCV em uma das corretoras disponíveis.

    - coin: ticker SEM 'USDT' (ex.: 'BTC', 'ETH').
    - timeframe: '4h', '1d', etc.
    - limit: quantidade de candles.

    Estratégia:
    1) Tenta KuCoin.
    2) Se falhar, tenta Gate.io.
    3) Se falhar, tenta OKX.
    4) Se todas falharem, retorna None.
    """
    exchanges = _create_exchanges()
    symbol = _coin_to_symbol(coin)

    order = [
        ("kucoin", exchanges.get("kucoin")),
        ("gateio", exchanges.get("gateio")),
        ("okx", exchanges.get("okx")),
    ]

    errors = []

    for name, ex in order:
        if ex is None:
            continue

        try:
            _log(f"Buscando OHLCV {symbol} {timeframe} em {name}...")
            ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

            if not ohlcv:
                raise ValueError("Lista OHLCV vazia")

            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = (
                pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                .dt.tz_convert(TZINFO)
            )
            df.set_index("timestamp", inplace=True)

            _log(
                f"OK {symbol} em {name}: {len(df)} candles "
                f"({df.index[0]} -> {df.index[-1]})"
            )

            # pequena pausa para respeitar rate limit
            time.sleep(sleep_between)
            return df

        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e!r}")
            _log(f"Erro em {name} para {symbol} {timeframe}: {e!r}")
            continue

    _log(
        f"FALHA ao buscar OHLCV para {coin} {timeframe} "
        f"({'; '.join(errors)})"
    )
    return None


# ======================================================================
# PREÇO AO VIVO (TICKER)
# ======================================================================


def get_price(coin: str) -> float:
    """
    Retorna o último preço negociado ('last') para `coin` usando as
    corretoras disponíveis.

    - coin: ticker SEM "USDT" (ex.: "BTC", "ETH").
    - Tenta KuCoin, depois Gate.io, depois OKX.
    - Em caso de falha geral, retorna 0.0.
    """
    exchanges = _create_exchanges()
    symbol = _coin_to_symbol(coin)

    order = [
        ("kucoin", exchanges.get("kucoin")),
        ("gateio", exchanges.get("gateio")),
        ("okx", exchanges.get("okx")),
    ]

    for name, ex in order:
        if ex is None:
            continue
        try:
            _log(f"Buscando preço ao vivo de {symbol} em {name}...")
            ticker = ex.fetch_ticker(symbol)
            price = float(ticker.get("last") or ticker.get("close") or 0.0)
            if price <= 0:
                raise ValueError(f"Preço inválido retornado por {name}: {price}")
            _log(f"Preço ao vivo de {symbol} em {name}: {price}")
            return price
        except Exception as e:  # noqa: BLE001
            _log(f"Falha ao buscar preço ao vivo de {symbol} em {name}: {e!r}")
            continue

    _log(f"[WARN get_price] Não foi possível obter preço ao vivo para {symbol}")
    return 0.0
