import os, time, threading, requests, telebot, base58
from flask import Flask
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# === CONFIGURAÇÕES ===
TOKEN_TELEGRAM = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"
RPC_URL = "https://api.mainnet-beta.solana.com"
PRIVATE_KEY_B58 = os.environ.get("SOLANA_PRIVATE_KEY")

# Estratégia
VALOR_COMPRA_SOL = 0.1
TAKE_PROFIT = 1.5  # 50% de lucro
STOP_LOSS = 0.8    # 20% de queda

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
solana_client = Client(RPC_URL)

# Banco de dados em memória
posicoes = {}
tokens_processados = set()
lucro_total_hora = 0.0
compras_total_hora = 0

@app.route('/')
def health(): return "SNIPER_SILENCIOSO_ONLINE", 200

def fazer_swap(input_mint, output_mint, amount):
    try:
        payer = Keypair.from_base58_string(PRIVATE_KEY_B58)
        quote = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount)}&slippageBps=1500", timeout=10).json()
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote, "userPublicKey": str(payer.pubkey()), "wrapAndUnwrapSol": True
        }, timeout=10).json()
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(swap_res['swapTransaction']))
        signature = payer.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        tx_id = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(tx_id.value), quote.get('outAmount')
    except: return None, None

def relatorio_financeiro():
    global lucro_total_hora, compras_total_hora
    while True:
        time.sleep(3600) # 1 hora
        msg = (
            f"📊 **RELATÓRIO DE LUCROS (ÚLTIMA HORA)**\n\n"
            f"🛒 Compras Realizadas: {compras_total_hora}\n"
            f"💰 Resultado Líquido: `{lucro_total_hora:.4f} SOL`"
        )
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        # Reset para a próxima hora
        lucro_total_hora = 0.0
        compras_total_hora = 0

def monitor_vendas():
    global lucro_total_hora
    while True:
        for mint in list(posicoes.keys()):
            pos = posicoes[mint]
            try:
                res = requests.get(f"https://api.jup.ag/price/v2?ids={mint}").json()
                preco_atual = float(res['data'][mint]['price'])
                rendimento = preco_atual / pos['entry_price']
                
                if rendimento >= TAKE_PROFIT or rendimento <= STOP_LOSS:
                    tx, _ = fazer_swap(mint, "So11111111111111111111111111111111111111112", pos['amount_tokens'])
                    if tx:
                        lucro = (VALOR_COMPRA_SOL * rendimento) - VALOR_COMPRA_SOL
                        lucro_total_hora += lucro
                        emoji = "✅" if lucro > 0 else "🛑"
                        bot.send_message(CHAT_ID, f"{emoji} **VENDA EXECUTADA**\n\nToken: `{mint}`\nLucro: {rendimento:.2f}x\nTX: [Solscan](https://solscan.io/tx/{tx})")
                        del posicoes[mint]
            except: continue
        time.sleep(20)

def sniper_scanner():
    global compras_total_hora
    while True:
        try:
            # Puxa tokens novos
            data = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for item in data:
                addr = item.get('tokenAddress')
                
                # FILTRO SOCIAL (Qualidade)
                tem_social = any(l.get('type') in ['website', 'twitter'] for l in item.get('links', []))
                
                if item.get('chainId') == 'solana' and addr not in tokens_processados and tem_social:
                    tokens_processados.add(addr)
                    
                    # COMPRA EM SILÊNCIO (Não avisa nada aqui)
                    lamports = int(VALOR_COMPRA_SOL * 1_000_000_000)
                    tx, out_amount = fazer_swap("So11111111111111111111111111111111111111112", addr, lamports)
                    
                    if tx:
                        # APENAS SE A COMPRA DER CERTO, ELE AVISA
                        time.sleep(2)
                        res_p = requests.get(f"https://api.jup.ag/price/v2?ids={addr}").json()
                        preco_e = float(res_p['data'][addr]['price'])
                        posicoes[addr] = {'entry_price': preco_e, 'amount_tokens': out_amount}
                        compras_total_hora += 1
                        bot.send_message(CHAT_ID, f"🛒 **NOVA COMPRA**\n\nToken: `{addr}`\nTX: [Solscan](https://solscan.io/tx/{tx})")
            
            time.sleep(40) # Delay maior para evitar spam
        except: time.sleep(20)

if __name__ == "__main__":
    threading.Thread(target=sniper_scanner, daemon=True).start()
    threading.Thread(target=monitor_vendas, daemon=True).start()
    threading.Thread(target=relatorio_financeiro, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
