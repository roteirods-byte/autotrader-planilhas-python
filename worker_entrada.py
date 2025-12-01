#!/usr/bin/env python3
# worker_entrada.py (versão alinhada com o painel EntryPanel)
#
# Gera o arquivo data/entrada.json no formato:
# {
#   "swing": [ { par, sinal, preco, alvo, ganho_pct, assert_pct, data, hora }, ... ],
#   "posicional": [ ... ]
# }
#
# - Usa exchanges.gerar_sinal(moeda, timeframe)
#   que deve devolver um dicionário com campos:
#   par, sinal, preco, alvo, ganho, assertividade, data, hora.
# - Aqui apenas adaptamos os nomes dos campos e separamos
#   em listas "swing" (4h) e "posicional" (1d).
# - TODAS as 39 moedas são sempre incluídas (sem filtro).
#
# IMPORTANTE (regras atuais do JORGE):
# - O limite de 3% de ganho NÃO exclui a moeda, só muda o "sinal"
#   para "NÃO ENTRAR" (isso deve estar dentro de exchanges.gerar_sinal).
# - A assertividade NÃO é filtro, apenas muda a cor no painel.

import os
import json
from datetime import datetime
from typing import Dict, Any, List

import exchanges


# Lista fixa das 39 moedas (ordem alfabética, sem USDT)
MOEDAS = [
    "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH", "BNB", "BTC",
    "DOGE", "DOT", "ETH", "FET", "FIL", "FLUX", "ICP", "INJ", "LDO", "LINK",
    "LTC", "NEAR", "OP", "PEPE", "POL", "RATS", "RENDER", "RUNE", "SEI", "SHIB",
    "SOL", "SUI", "TIA", "TNSR", "TON", "TRX", "UNI", "WIF", "XRP",
]


def gera_data_hora_br() -> (str, str):
    agora = datetime.now()
    data = agora.strftime("%d/%m/%Y")
    hora = agora.strftime("%H:%M:%S")
    return data, hora


def salvar_json_entrada(dados: Dict[str, Any]) -> bool:
    try:
        os.makedirs("data", exist_ok=True)
        caminho = os.path.join("data", "entrada.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)
        print(f"[OK] entrada.json salvo em {caminho}")
        print(
            f"Swing: {len(dados.get('swing', []))} | "
            f"Posicional: {len(dados.get('posicional', []))}"
        )
        return True
    except Exception as e:
        print(f"[ERRO] ao salvar JSON de entrada: {e}")
        return False


def adaptar_sinal(bruto: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converte o dicionário vindo de exchanges.gerar_sinal
    para o formato esperado pelo painel de entrada.
    Campos esperados no bruto:
      - par, sinal, preco, alvo, ganho, assertividade, data, hora
    """
    data_br, hora_br = gera_data_hora_br()

    return {
        "par": bruto.get("par") or bruto.get("moeda") or "",
        "sinal": bruto.get("sinal", "NÃO ENTRAR"),
        "preco": bruto.get("preco", 0),
        "alvo": bruto.get("alvo", 0),
        "ganho_pct": bruto.get("ganho", 0),
        "assert_pct": bruto.get("assertividade", 0),
        "data": bruto.get("data", data_br),
        "hora": bruto.get("hora", hora_br),
    }


def gerar_lista_para_modo(
    modo: str, timeframe: str, moedas: List[str]
) -> List[Dict[str, Any]]:
    """
    Gera a lista de sinais para um modo (swing ou posicional)
    chamando exchanges.gerar_sinal para cada moeda.
    """
    print(f"→ Gerando sinais para modo {modo.upper()} ({timeframe}), {len(moedas)} moedas...")
    sinais: List[Dict[str, Any]] = []

    for moeda in moedas:
        try:
            bruto = exchanges.gerar_sinal(moeda, timeframe)
            adaptado = adaptar_sinal(bruto)
            sinais.append(adaptado)
            print(f"  ✓ {moeda} - {adaptado['sinal']}")
        except Exception as e:
            print(f"  ✗ {moeda} - ERRO: {e}")
            data_br, hora_br = gera_data_hora_br()
            sinais.append(
                {
                    "par": moeda,
                    "sinal": "NÃO ENTRAR",
                    "preco": 0,
                    "alvo": 0,
                    "ganho_pct": 0,
                    "assert_pct": 0,
                    "data": data_br,
                    "hora": hora_br,
                }
            )

    return sinais


def main() -> None:
    print("\n" + "=" * 70)
    print("AUTOTRADER - GERANDO SINAIS DE ENTRADA")
    print("=" * 70)

    # SWING (4h)
    swing_sinais = gerar_lista_para_modo("swing", "4h", MOEDAS)

    # POSICIONAL (1d)
    pos_sinais = gerar_lista_para_modo("posicional", "1d", MOEDAS)

    data_br, hora_br = gera_data_hora_br()
    dados = {
        "swing": swing_sinais,
        "posicional": pos_sinais,
        "ultima_atualizacao": f"{data_br} às {hora_br}",
    }

    salvar_json_entrada(dados)
    print(f"\nCONCLUÍDO às {hora_br} - Sinais prontos para o painel!\n")


if __name__ == "__main__":
    main()
