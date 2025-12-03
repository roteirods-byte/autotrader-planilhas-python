import json
import time
import ccxt
from datetime import datetime, timezone, timedelta

# =============================
# CONFIG
# =============================
PATH_MANUAL = "data/saida_manual.json"
PATH_OUT = "data/saida_monitoramento.json"

binance = ccxt.binance()
bybit = ccxt.bybit()

# =============================
# HORA BRASIL
# =============================
def agora_brt():
    return datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=-3))
    )

# =============================
# PREÇO AO VIVO
# =============================
def get_price(par):
    symbol = f"{par}/USDT"
    try:
        p1 = binance.fetch_ticker(symbol)["last"]
    except:
        p1 = None
    try:
        p2 = bybit.fetch_ticker(symbol)["last"]
    except:
        p2 = None

    valores = [v for v in [p1, p2] if v is not None]
    if not valores:
        return 0

    return sum(valores) / len(valores)

# =============================
# ALVOS (FIBO SIMPLES)
# =============================
def gerar_alvos(preco, side):
    alvo1 = preco * (1.01 if side == "LONG" else 0.99)
    alvo2 = preco * (1.02 if side == "LONG" else 0.98)
    alvo3 = preco * (1.03 if side == "LONG" else 0.97)
    return alvo1, alvo2, alvo3

# =============================
# SITUAÇÃO
# =============================
def situacao(preco, a1, a2, a3, side):
    if side == "LONG":
        if preco >= a3: return "ALVO 3"
        if preco >= a2: return "ALVO 2"
        if preco >= a1: return "ALVO 1"
        return "ABERTA"
    else:
        if preco <= a3: return "ALVO 3"
        if preco <= a2: return "ALVO 2"
        if preco <= a1: return "ALVO 1"
        return "ABERTA"

# =============================
# LOOP PRINCIPAL
# =============================
def loop_saida():
    while True:
        try:
            with open(PATH_MANUAL, "r") as f:
                ops = json.load(f)
        except:
            ops = []

        resultado = []
        agora = agora_brt()
        data = agora.strftime("%Y-%m-%d")
        hora = agora.strftime("%H:%M")

        for op in ops:
            preco_atual = get_price(op["par"])
            a1, a2, a3 = gerar_alvos(op["entrada"], op["side"])
            sit = situacao(preco_atual, a1, a2, a3, op["side"])

            resultado.append({
                "par": op["par"],
                "side": op["side"],
                "modo": op["modo"],
                "entrada": op["entrada"],
                "preco": round(preco_atual, 3),
                "alvo_1": round(a1, 3),
                "ganho_1_pct": 0.00,
                "alvo_2": round(a2, 3),
                "ganho_2_pct": 0.00,
                "alvo_3": round(a3, 3),
                "ganho_3_pct": 0.00,
                "situacao": sit,
                "alav": op["alav"],
                "data": data,
                "hora": hora
            })

        with open(PATH_OUT, "w") as f:
            json.dump(resultado, f, indent=2)

        time.sleep(300)  # 5 minutos


if __name__ == "__main__":
    loop_saida()
