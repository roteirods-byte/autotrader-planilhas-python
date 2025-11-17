# ARQUIVO: exchange.py

import ccxt
import os

# A corretora (exchange) é definida na variável de ambiente EXCHANGE no Render
EXCHANGE_ID = os.environ.get("EXCHANGE", "binance") 

def get_current_price(symbol_pair: str) -> float | None:
    """
    Busca o preço atual de uma moeda (par) na corretora configurada.
    
    Exemplo: symbol_pair = 'BTC/USDT'
    """
    try:
        # 1. Tenta carregar a corretora (ex: Binance)
        exchange_class = getattr(ccxt, EXCHANGE_ID)
        
        # 2. Cria uma instância da corretora (sem chaves secretas para apenas ler o preço)
        exchange = exchange_class()
        
        # 3. Busca o preço atual (ticker)
        ticker = exchange.fetch_ticker(symbol_pair)
        
        # O preço de 'ask' (venda) é geralmente o mais seguro para monitoramento
        price = ticker.get('ask') 
        
        if price is None:
            print(f"Alerta: Preço de 'ask' não disponível para {symbol_pair}")
            price = ticker.get('last') # Usa o último preço como alternativa
        
        print(f"Preço de {symbol_pair} na {EXCHANGE_ID}: {price}")
        return float(price)
        
    except ccxt.BaseError as e:
        # Registra erros de conexão ou de par de moedas
        print(f"ERRO CCXT ao buscar preço de {symbol_pair}: {e}")
        return None
    except Exception as e:
        print(f"ERRO geral em exchange.py: {e}")
        return None

# Nota: Para operações reais de compra/venda, usaremos as chaves API.
# Este é um módulo simples de busca de preço.
