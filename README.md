# autotrader-planilhas-python

Worker em Python que gera o arquivo `entrada.json` usado pelo painel `autotrader-painel`.

- Universo fixo de 39 moedas (sem "USDT" no ticker)
- Corretoras: Binance e Bybit (via ccxt)
- Modos: Swing (4H) e Posicional (1D)
- Saída: `entrada.json` com campos:
  - `par`, `sinal`, `preco`, `alvo`, `ganho_pct`, `assert_pct`, `data`, `hora`

## Como rodar local

```bash
pip install -r requirements.txt
python worker_entrada.py
