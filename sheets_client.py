from datetime import datetime

# Lista oficial de 39 moedas do projeto (ordem alfabética)
MOEDAS = [
    "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "AXS", "BCH", "BNB",
    "BTC", "DOGE", "DOT", "ETH", "FET", "FIL", "FLUX", "ICP", "INJ",
    "LDO", "LINK", "LTC", "NEAR", "OP", "PEPE", "POL", "RATS", "RENDER",
    "RUNE", "SEI", "SHIB", "SOL", "SUI", "TIA", "TNSR", "TON", "TRX",
    "UNI", "WIF", "XRP",
]


def get_moedas():
    """Devolve a lista fixa de moedas."""
    return MOEDAS


def append_log(msg: str):
    """Só imprime o log no terminal, sem usar Google Sheets."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{agora}] {msg}")
