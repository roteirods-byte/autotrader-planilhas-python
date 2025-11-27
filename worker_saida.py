# ================================================================
#   WORKER DE SAÍDA — AUTOTRADER (VERSÃO PROFISSIONAL, INDEPENDENTE)
#
#   - Lê saida_manual.json  (operações digitadas)
#   - Busca OHLCV 4h nas corretoras (via exchanges.py)
#   - Calcula ATR 14 períodos
#   - Calcula alvos profissionais com FIBO + ATR:
#       LONG : alvo1 = entrada + 0.618*ATR
#              alvo2 = entrada + 1.000*ATR
#              alvo3 = entrada + 1.618*ATR
#       SHORT: simétrico para baixo
#   - Calcula ganho_1/2/3_pct, pnl_pct e situação (ABERTA / ALVO 1/2/3)
#   - Grava saida_monitoramento.json
#
#   Caminhos podem ser definidos por variáveis de ambiente:
#       SAIDA_MANUAL_JSON_PATH
#       SAIDA_MONITORAMENTO_JSON_PATH
# ================================================================

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

import exchanges  # mesmo exchanges.py do worker_entrada


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


# ------------------------------------------------
# Funções auxiliares
# ------------------------------------------------

def agora_brt() -> datetime:
    """Retorna data/hora no fuso de Brasília (UTC-3)."""
    return datetime.utcnow() - timedelta(hours=3)


def carregar_json(caminho: str) -> List[Dict[str, Any]]:
    """Carrega lista JSON; se não existir ou erro, retorna lista vazia."""
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
    """Salva lista em JSON com indentação."""
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        logging.info(f"[worker_saida] Gravado arquivo: {caminho} ({len(dados)} linhas)")
    except Exception as e:
        logging.error(f"[worker_saida] Erro ao gravar {caminho}: {e}")


def obter_ohlcv_4h(base: str, limit: int = 200) -> Optional[pd.DataFrame]:
    """
    Puxa OHLCV 4h da coin `base` usando exchanges.py.
    Retorna DataFrame com colunas ['open','high','low','close'].
    """
    timeframe = "4h"

    try:
        if hasattr(exchanges, "get_ohlcv"):
            dados = exchanges.get_ohlcv(base, timeframe=timeframe, limit=limit)
        elif hasattr(exchanges, "get_ohlcv_binance"):
            dados = exchanges.get_ohlcv_binance(base, timeframe=timeframe, limit=limit)
        else:
            raise RuntimeError(
                "Ajuste obter_ohlcv_4h() para usar a função correta de exchanges.py"
            )

        if dados is None:
            logging.error(f"[worker_saida] Nenhum dado OHLCV retornado para {base}")
            return None

        if isinstance(dados, pd.DataFrame):
            if dados.empty:
                logging.error(f"[worker_saida] DataFrame OHLCV vazio para {base}")
                return None
            return dados

        # Se vier lista de candles, converte para DataFrame
        if not isinstance(dados, list) or len(dados) == 0:
            logging.error(f"[worker_saida] Lista OHLCV vazia para {base}")
            return None

        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(dados, columns=cols[: len(dados[0])])
        return df

    except Exception as e:
        logging.error(f"[worker_saida] Erro ao obter OHLCV de {base}: {e}")
        return None


def calcular_atr(df: pd.DataFrame, periodos: int = 14) -> Optional[float]:
    """Calcula ATR simples a partir de DataFrame OHLCV."""
    try:
        if not {"high", "low", "close"}.issubset(df.columns):
            return None

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=periodos).mean().iloc[-1]

        if pd.isna(atr):
            return None
        return float(atr)
    except Exception as e:
        logging.error(f"[worker_saida] Erro ao calcular ATR: {e}")
        return None


def calcular_alvos_profissionais(
    side: str,
    preco_entrada: float,
    atr: Optional[float],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Calcula ALVO 1, 2 e 3 usando ATR + Fibo.

    - Se ATR não disponível: retorna (None, None, None).
    - LONG :
        alvo1 = entrada + 0.618 * ATR
        alvo2 = entrada + 1.000 * ATR
        alvo3 = entrada + 1.618 * ATR
    - SHORT:
        alvo1 = entrada - 0.618 * ATR
        alvo2 = entrada - 1.000 * ATR
        alvo3 = entrada - 1.618 * ATR
    """
    if atr is None or preco_entrada <= 0:
        return None, None, None

    side = (side or "").upper()
    atr = float(atr)

    if side == "LONG":
        a1 = preco_entrada + 0.618 * atr
        a2 = preco_entrada + 1.000 * atr
        a3 = preco_entrada + 1.618 * atr
    elif side == "SHORT":
        a1 = preco_entrada - 0.618 * atr
        a2 = preco_entrada - 1.000 * atr
        a3 = preco_entrada - 1.618 * atr
    else:
        return None, None, None

    return a1, a2, a3


def calcular_pnl_pct(side: str, preco_entrada: float, preco_atual: float) -> float:
    """PNL% da operação com base na direção (LONG/SHORT)."""
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
    """Ganho esperado (%) entre entrada e alvo."""
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
    """Define SITUAÇÃO com base no preço atual e nos alvos."""
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

def processar_operacoes() -> None:
    """
    Lê saida_manual.json, calcula alvos profissionais, PNL e situação,
    e grava saida_monitoramento.json.
    """
    logging.info("[worker_saida] Iniciando processamento.")

    operacoes = carregar_json(SAIDA_MANUAL_JSON_PATH)
    if not operacoes:
        logging.info("[worker_saida] Nenhuma operação em saida_manual.json.")
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

            base = par.split("/")[0].strip().upper()

            side = (op.get("side") or op.get("sinal") or op.get("SINAL") or "").upper()
            modo = (op.get("modo") or op.get("MODO") or "SWING").upper()

            preco_entrada = op.get("entrada") or op.get("preco_entrada") or op.get("ENTRADA")
            if preco_entrada is None:
                continue
            preco_entrada = float(preco_entrada)

            alav = op.get("alav") or op.get("ALAV") or 1
            alav = int(alav)

            # OHLCV 4h → ATR + preço atual (último close)
            df = obter_ohlcv_4h(base, limit=200)
            if df is None or df.empty:
                logging.error(f"[worker_saida] Sem OHLCV para {base}, pulando operação.")
                continue

            preco_atual = float(df["close"].iloc[-1])

            atr = calcular_atr(df, periodos=14)
            alvo_1, alvo_2, alvo_3 = calcular_alvos_profissionais(side, preco_entrada, atr)

            # PNL atual e ganhos para cada alvo
            pnl_pct = calcular_pnl_pct(side, preco_entrada, preco_atual)
            ganho_1_pct = calcular_ganho_pct(side, preco_entrada, alvo_1)
            ganho_2_pct = calcular_ganho_pct(side, preco_entrada, alvo_2)
            ganho_3_pct = calcular_ganho_pct(side, preco_entrada, alvo_3)

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
