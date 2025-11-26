# ================================================================
#   WORKER DE SAÍDA — AUTOTRADER
#   Lê saida_manual.json, busca preço atual nas corretoras,
#   calcula PNL% e situação (ABERTA / ALVO 1 / ALVO 2 / ALVO 3)
#   e grava o resultado em saida_monitoramento.json.
#
#   Ajuste os caminhos dos arquivos ou use variáveis de ambiente:
#   SAIDA_MANUAL_JSON_PATH e SAIDA_MONITORAMENTO_JSON_PATH
# ================================================================

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import exchanges  # usa o mesmo arquivo exchanges.py do worker_entrada


# ------------------------------------------------
# Configuração básica
# ------------------------------------------------

SAIDA_MANUAL_JSON_PATH = os.environ.get(
    "SAIDA_MANUAL_JSON_PATH",
    "saida_manual.json",
)

SAIDA_MONITORAMENTO_JSON_PATH = os.environ.get(
    "SAIDA_MONITORAMENTO_JSON_PATH",
    "saida_monitoramento.json",
)

# Caso você queira forçar uma corretora principal para os preços:
EXCHANGE_PREFERENCIAL = os.environ.get("SAIDA_EXCHANGE", "binance")


# ------------------------------------------------
# Funções auxiliares
# ------------------------------------------------

def agora_brt():
    """Retorna data e hora no fuso de Brasília (sem horário de verão)."""
    agora_utc = datetime.utcnow()
    brt = agora_utc - timedelta(hours=3)
    return brt


def carregar_json(caminho: str) -> List[Dict[str, Any]]:
    """Carrega um arquivo JSON de lista. Se não existir, retorna lista vazia."""
    if not os.path.exists(caminho):
        logging.warning(f"[worker_saida] Arquivo não encontrado: {caminho}")
        return []

    try:
        with open(caminho, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logging.warning(f"[worker_saida] Formato inesperado em {caminho}, esperado lista.")
            return []
        return data
    except Exception as e:
        logging.error(f"[worker_saida] Erro ao ler {caminho}: {e}")
        return []


def salvar_json(caminho: str, dados: List[Dict[str, Any]]) -> None:
    """Salva a lista em JSON com identação."""
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        logging.info(f"[worker_saida] Gravado arquivo: {caminho} ({len(dados)} linhas)")
    except Exception as e:
        logging.error(f"[worker_saida] Erro ao gravar {caminho}: {e}")


def buscar_preco_atual(par: str) -> Optional[float]:
    """
    Busca o preço atual da moeda na corretora.

    IMPORTANTE: ajuste esta função de acordo com o que já existe
    no seu arquivo exchanges.py.

    Abaixo está uma tentativa genérica usando um par 'TICKER/USDT'.
    Se o seu exchanges.py tiver outro nome de função, adapte aqui.
    """
    simbolo = f"{par}/USDT"

    try:
        # Tenta algumas assinaturas comuns.
        if hasattr(exchanges, "get_price"):
            preco = exchanges.get_price(simbolo, exchange_name=EXCHANGE_PREFERENCIAL)
        elif hasattr(exchanges, "get_last_price"):
            preco = exchanges.get_last_price(simbolo, exchange_name=EXCHANGE_PREFERENCIAL)
        else:
            raise RuntimeError(
                "Ajuste buscar_preco_atual() para usar a função correta de exchanges.py"
            )

        return float(preco)
    except Exception as e:
        logging.error(f"[worker_saida] Erro ao obter preço de {simbolo}: {e}")
        return None


def calcular_pnl_pct(side: str, preco_entrada: float, preco_atual: float) -> float:
    """Calcula PNL% da operação com base na direção (LONG ou SHORT)."""
    if preco_entrada is None or preco_entrada == 0 or preco_atual is None:
        return 0.0

    side = (side or "").upper()
    if side == "LONG":
        pnl = (preco_atual - preco_entrada) / preco_entrada * 100.0
    elif side == "SHORT":
        pnl = (preco_entrada - preco_atual) / preco_entrada * 100.0
    else:
        pnl = 0.0

    return round(pnl, 2)


def calcular_ganho_pct(side: str, preco_entrada: float, alvo: Optional[float]) -> float:
    """Calcula o ganho esperado (%) entre a entrada e um alvo."""
    if alvo is None or preco_entrada is None or preco_entrada == 0:
        return 0.0

    side = (side or "").upper()
    if side == "LONG":
        ganho = (alvo - preco_entrada) / preco_entrada * 100.0
    elif side == "SHORT":
        ganho = (preco_entrada - alvo) / preco_entrada * 100.0
    else:
        ganho = 0.0

    return round(ganho, 2)


def classificar_situacao(
    side: str,
    preco_atual: Optional[float],
    alvo_1: Optional[float],
    alvo_2: Optional[float],
    alvo_3: Optional[float],
) -> str:
    """
    Define a SITUAÇÃO da operação com base no preço atual e nos alvos.

    Regras simples:
      - se não há alvo → "ABERTA"
      - LONG:
          preço >= alvo_3 → "ALVO 3"
          senão preço >= alvo_2 → "ALVO 2"
          senão preço >= alvo_1 → "ALVO 1"
          senão → "ABERTA"
      - SHORT (inverte as desigualdades)
    """
    if preco_atual is None or alvo_1 is None:
        return "ABERTA"

    side = (side or "").upper()

    if side == "LONG":
        if alvo_3 is not None and preco_atual >= alvo_3:
            return "ALVO 3"
        if alvo_2 is not None and preco_atual >= alvo_2:
            return "ALVO 2"
        if preco_atual >= alvo_1:
            return "ALVO 1"
        return "ABERTA"

    if side == "SHORT":
        if alvo_3 is not None and preco_atual <= alvo_3:
            return "ALVO 3"
        if alvo_2 is not None and preco_atual <= alvo_2:
            return "ALVO 2"
        if preco_atual <= alvo_1:
            return "ALVO 1"
        return "ABERTA"

    return "ABERTA"


# ------------------------------------------------
# Worker principal
# ------------------------------------------------

def processar_operacoes():
    """Lê saida_manual.json, calcula preços/PNL e grava saida_monitoramento.json."""
    logging.info("[worker_saida] Iniciando processamento.")

    operacoes = carregar_json(SAIDA_MANUAL_JSON_PATH)
    if not operacoes:
        logging.info("[worker_saida] Nenhuma operação encontrada em saida_manual.json.")
        salvar_json(SAIDA_MONITORAMENTO_JSON_PATH, [])
        return

    agora = agora_brt()
    data_str = agora.strftime("%Y-%m-%d")
    hora_str = agora.strftime("%H:%M")

    saida_monitoramento: List[Dict[str, Any]] = []

    for op in operacoes:
        try:
            par = (op.get("par") or op.get("PAR") or "").upper()
            if not par:
                continue

            # Aceita tanto "side" quanto "sinal" como nome de campo
            side = (op.get("side") or op.get("sinal") or op.get("SINAL") or "").upper()
            modo = (op.get("modo") or op.get("MODO") or "SWING").upper()

            preco_entrada = op.get("entrada") or op.get("preco_entrada") or op.get("ENTRADA")
            if preco_entrada is None:
                continue
            preco_entrada = float(preco_entrada)

            # Alvos (podem não existir ainda; tudo opcional)
            alvo_1 = op.get("alvo_1") or op.get("ALVO_1")
            alvo_2 = op.get("alvo_2") or op.get("ALVO_2")
            alvo_3 = op.get("alvo_3") or op.get("ALVO_3")

            alvo_1 = float(alvo_1) if alvo_1 is not None else None
            alvo_2 = float(alvo_2) if alvo_2 is not None else None
            alvo_3 = float(alvo_3) if alvo_3 is not None else None

            alav = op.get("alav") or op.get("ALAV") or 1
            alav = int(alav)

            # Busca preço atual
            preco_atual = buscar_preco_atual(par)
            if preco_atual is None:
                continue

            # Calcula PNL% da operação
            pnl_pct = calcular_pnl_pct(side, preco_entrada, preco_atual)

            # Calcula ganhos potenciais para cada alvo (se existirem)
            ganho_1_pct = calcular_ganho_pct(side, preco_entrada, alvo_1)
            ganho_2_pct = calcular_ganho_pct(side, preco_entrada, alvo_2)
            ganho_3_pct = calcular_ganho_pct(side, preco_entrada, alvo_3)

            # Situação atual (ABERTA / ALVO 1 / ALVO 2 / ALVO 3)
            situacao = classificar_situacao(side, preco_atual, alvo_1, alvo_2, alvo_3)

            linha = {
                "par": par,
                "side": side,
                "modo": modo,
                "entrada": round(preco_entrada, 3),
                "preco": round(preco_atual, 3),
                "pnl_pct": pnl_pct,
                "alvo_1": round(alvo_1, 3) if alvo_1 is not None else None,
                "ganho_1_pct": ganho_1_pct if alvo_1 is not None else None,
                "alvo_2": round(alvo_2, 3) if alvo_2 is not None else None,
                "ganho_2_pct": ganho_2_pct if alvo_2 is not None else None,
                "alvo_3": round(alvo_3, 3) if alvo_3 is not None else None,
                "ganho_3_pct": ganho_3_pct if alvo_3 is not None else None,
                "situacao": situacao,
                "alav": alav,
                "data": data_str,
                "hora": hora_str,
            }

            saida_monitoramento.append(linha)

        except Exception as e:
            logging.error(f"[worker_saida] Erro ao processar operação {op}: {e}")

    salvar_json(SAIDA_MONITORAMENTO_JSON_PATH, saida_monitoramento)
    logging.info(
        f"[worker_saida] Processamento concluído. {len(saida_monitoramento)} operações atualizadas."
    )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    processar_operacoes()


if __name__ == "__main__":
    main()
