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


def _log(msg: str) -> None:
    """Log simples deste módulo."""
    print(f"[exchanges] {msg}", flush=True)


def _create_exchanges() -> Dict[str, ccxt.Exchange]:
    """
    Cria conexões com as 3 corretoras escolhidas:
    - KuCoin
    - Gate.io
    - OKX
    Modo anônimo (somente dados públicos).
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


# instancia compartilhada
_EXCHANGES: Dict[str, ccxt.Exchange] = _create_exchanges()


def _coin_to_symbol(coin: str) -> str:
    """
    Converte o ticker em symbol da corretora.

    - Se já vier "AAVE/USDT", devolve igual.
    - Se vier só "AAVE", monta "AAVE/USDT".
    """
    c = coin.strip().upper()

    # Já é par completo? Não mexe.
    if "/" in c:
        return c

    # Só ticker? Acrescenta /USDT
    return f"{c}/USDT"

def get_ohlcv(
    coin: str,
    timeframe: str,
    limit: int = 200,
    sleep_between: float = 0.3,
) -> Optional[pd.DataFrame]:
    """
    Busca candles OHLCV para uma moeda/timeframe usando
    KuCoin, Gate.io e OKX (nessa ordem).

    Retorna um DataFrame com:
        index: datetime (TZINFO)
        colunas: ["open", "high", "low", "close", "volume"]

    Se todas as corretoras falharem, retorna None.
    """
    symbol = _coin_to_symbol(coin)
    errors = []

    for name in ("kucoin", "gateio", "okx"):
        ex = _EXCHANGES.get(name)
        if ex is None:
            continue

        try:
            _log(f"Buscando OHLCV {symbol} {timeframe} em {name}...")
            ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

            if not ohlcv:
                errors.append(f"{name}: resposta vazia")
                continue

            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            df = df.tz_convert(TZINFO)

            _log(
                f"OK {coin} {timeframe} em {name}: {len(df)} candles "
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
