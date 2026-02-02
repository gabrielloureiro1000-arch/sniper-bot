import os
import time
import threading
import requests
import telebot
import base58
from flask import Flask
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# === CONFIGURAÇÕES ===
TOKEN_TELEGRAM = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"
RPC_URL = "https://api.mainnet-beta.solana.com"

# Puxa a chave privada que você salvou no Koyeb
PRIVATE_KEY_B58 = os.environ.get("SOLANA_PRIVATE_KEY")

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
solana_client = Client(RPC_URL)

tokens_processados = set()

@app.route('/')
def health(): return "AUTO_TRADER_ACTIVE", 200

def executar_compra_jupiter(mint_address, amount_sol=0.1):
    """Executa a compra real via API da Jupiter v6"""
    try:
        if not PRIVATE_KEY_B58:
            print("❌ Erro: Variável SOLANA_PRIVATE_KEY não encontrada no Koyeb.")
            return None

        payer = Keypair.from_base58_string(PRIVATE_KEY_B58)
        lamports = int(amount_sol * 1_000_000_000)

        # 1. Pegar a cotação (Quote)
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint=So11111111111111111111111111111111111111112&outputMint={mint_address}&amount={lamports}&slippageBps=1000"
        quote = requests.get(quote_url).json()

        # 2. Gerar a transação de Swap
        swap_data = {
            "quoteResponse": quote,
            "userPublicKey": str(payer.pubkey()),
            "wrapAndUnwrapSol": True
        }
        tx_res = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_data).json()
        
        # 3. Assinar e Enviar
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(tx_res['swapTransaction']))
        signature = payer.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        
        result = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(result.value)
    except Exception as e:
        print(f"Erro no Swap Jupiter: {e}")
        return None

def scanner_loop():
    print("🚀 Auto-Trader iniciado: Escaneando e Comprando...")
    while True:
        try:
            # Scanner de novos tokens via DexScreener
            url = "https://api.dexscreener.com/token-profiles/latest/v1"
            data = requests.get(url, timeout=10).json()
            
            for item in data:
                addr = item.get('tokenAddress')
                if item.get('chainId') == 'solana' and addr not in tokens_processados:
                    
                    # TENTA COMPRAR AUTOMATICAMENTE
                    tx_sig = executar_compra_jupiter(addr)
                    
                    if tx_sig:
                        msg = (
                            f"✅ **COMPRA EXECUTADA AUTOMATICAMENTE**\n\n"
                            f"🪙 **Token:** `{addr}`\n"
                            f"💰 **Valor:** 0.1 SOL\n"
                            f"🔗 **TX:** [Solscan](https://solscan.io/tx/{tx_sig})\n"
                            f"📊 **Monitorar:** [GMGN](https://gmgn.ai/sol/token/{addr})"
                        )
                        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                    
                    tokens_processados.add(addr)
            
            time.sleep(20)
        except Exception as e:
            time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
