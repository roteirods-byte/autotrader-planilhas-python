#!/usr/bin/env python3
"""
worker_entrada.py  (MODO DEMO PURO)

NÃO USA NENHUMA CORRETORA.
NÃO IMPORTA ccxt.
NÃO CHAMA exchanges/calculadora/analise_sinal.

Apenas gera dados sintéticos para alimentar o PAINEL ENTRADA,
com valores diferentes por moeda, para Swing (4h) e Posicional (1d).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List

from config import TZINFO, PRICE_DECIMALS, PCT_DECIMALS  # type: ignore


# Universo fixo de moedas (sem USDT)
COINS = sorted(
    [
        "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH", "BNB",
        "BTC", "DOGE", "DOT", "ETH", "FET", "FIL", "FLUX", "ICP", "INJ",
        "LDO", "LINK", "LTC", "NEAR", "OP", "PEPE", "POL", "RATS", "RENDER",
        "RUNE", "SEI", "SHIB", "SOL", "SUI", "TIA", "TNSR", "TON", "TRX",
        "UNI", "WIF", "XRP",
    ]
)

ENTRADA_JSON_PATH = os.getenv("ENTRADA_JSON_PATH", "entrada.json")


@dataclass
class SinalEntrada:
    par: str
    sinal: str
    preco: float
    alvo: float
    ganho_pct: float
    assert_pct: float
    data: str
    hora: str


def _now_brt() -> datetime:
    return datetime.now(TZINFO)


def _log(msg: str) -> None:
    ts = _now_brt().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [worker_entrada_demo] {msg}", flush=True)


def _gerar_sinais_demo_para_modo(modo: str) -> List[SinalEntrada]:
    """
    Gera sinais sintéticos para todas as moedas.

    - Swing: ganho ~3–5%, assert ~68–78%.
    - Posicional: ganho ~6–12%, assert ~70–84%.
    - Valores variam por moeda para ficar “com cara de real”.
    """
    resultados: List[SinalEntrada] = []
    ts = _now_brt()
    data_str = ts.strftime("%Y-%m-%d")
    hora_str = ts.strftime("%H:%M")

    for i, coin in enumerate(COINS):
        # Preço base aumenta por moeda
        preco_base = 5.0 + i * 7.3
        if modo == "posicional":
            preco_base *= 1.15

        # Direção alternada (só para visual)
        if (modo == "swing" and i % 2 == 0) or (modo == "posicional" and i % 3 == 0):
            sinal = "LONG"
        else:
            sinal = "SHORT"

        # GANHO %
        if modo == "swing":
            ganho = 3.0 + (i % 6) * 0.35      # ~3,00 a ~4,75
        else:
            ganho = 6.0 + (i % 8) * 0.65      # ~6,00 a ~10,55

        # ASSERT %
        if modo == "swing":
            assertiva = 68.0 + (i % 5) * 1.9  # ~68 a ~75,6
        else:
            assertiva = 70.0 + (i % 5) * 2.4  # ~70 a ~79,6

        preco = round(preco_base, PRICE_DECIMALS)

        if sinal == "LONG":
            alvo = preco * (1.0 + ganho / 100.0)
        else:
            alvo = preco * (1.0 - ganho / 100.0)

        resultados.append(
            SinalEntrada(
                par=coin,
                sinal=sinal,
                preco=round(preco, PRICE_DECIMALS),
                alvo=round(alvo, PRICE_DECIMALS),
                ganho_pct=round(ganho, PCT_DECIMALS),
                assert_pct=round(assertiva, PCT_DECIMALS),
                data=data_str,
                hora=hora_str,
            )
        )

    resultados.sort(key=lambda s: s.par)
    _log(f"[DEMO PURO] Gerados {len(resultados)} sinais para modo={modo}.")
    return resultados


def gerar_sinais_demo_puro() -> Dict[str, object]:
    _log("[DEMO PURO] Iniciando geração de sinais DEMO...")
    swing = _gerar_sinais_demo_para_modo("swing")
    posicional = _gerar_sinais_demo_para_modo("posicional")

    payload = {
        "generated_at": _now_brt().isoformat(),
        "swing": [asdict(s) for s in swing],
        "posicional": [asdict(s) for s in posicional],
    }

    _log(
        f"[DEMO PURO] Sinais gerados: {len(payload['swing'])} swing, "
        f"{len(payload['posicional'])} posicional."
    )
    return payload


def salvar_json(payload: Dict[str, object]) -> None:
    tmp_path = ENTRADA_JSON_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, ENTRADA_JSON_PATH)
    _log(f"Arquivo salvo em: {ENTRADA_JSON_PATH}")


def main() -> None:
    _log("Executando worker_entrada DEMO PURO (sem corretoras)...")
    payload = gerar_sinais_demo_puro()
    salvar_json(payload)
    _log("worker_entrada DEMO finalizado com sucesso.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("Encerrado pelo usuário (Ctrl+C).")
