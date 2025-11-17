# exchanges.py
from __future__ import annotations
import time
from typing import List, Tuple, Dict
import pandas as pd
import ccxt
from config import PRICE_DECIMALS, TZINFO

def _mk_binance():
    return ccxt.binance({
        "enableRateLimit": True,
        "timeout": 15000,
        "options": {"defaultType": "spot"},
    })

def _mk_bybit():
    return ccxt.bybit({
        "enableRateLimit": True,
        "timeout": 15000,
        "options": {"defaultType": "spot"},
    })

class Exchanges:
    """
    Duas corretoras (Binance + Bybit). Tenta a 1ª, faz fallback na 2ª.
    Pares normalizados como COIN/USDT (painéis sem 'USDT').
    """
    def __init__(self):
        self.clients = [ _mk_binance(), _mk_bybit() ]

    @staticmethod
    def coin_to_pair(coin: str) -> str:
        return f"{coin.upper()}/USDT"

    def _fetch_ticker_last(self, pair: str) -> Tuple[float, str]:
        err = None
        for ex in self.clients:
            try:
                t = ex.fetch_ticker(pair)
                last = t.get("last") or t.get("close")
                if last is not None:
                    return float(last), ex.id
            except Exception as e:
                err = e
                time.sleep(0.2)
        raise RuntimeError(f"Falha ao obter preço de {pair}: {err}")

    def get_price(self, coin: str) -> Tuple[float, str]:
        pair = self.coin_to_pair(coin)
        px, src = self._fetch_ticker_last(pair)
        return round(px, PRICE_DECIMALS), src

    def get_prices(self, coins: List[str]) -> Dict[str, Tuple[float, str]]:
        out = {}
        for c in coins:
            out[c] = self.get_price(c)
        return out

    def fetch_ohlcv(self, coin: str, timeframe: str = "4h", limit: int = 400) -> pd.DataFrame:
        """
        OHLCV com fallback; retorna DataFrame com índice datetime (TZ BRT).
        """
        pair = self.coin_to_pair(coin)
        last_err = None
        for ex in self.clients:
            try:
                data = ex.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
                df = pd.DataFrame(data, columns=["ts","open","high","low","close","volume"])
                df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(TZINFO)
                df = df.set_index("ts")
                return df
            except Exception as e:
                last_err = e
                time.sleep(0.2)
        raise RuntimeError(f"Falha ao obter OHLCV {pair} {timeframe}: {last_err}")
