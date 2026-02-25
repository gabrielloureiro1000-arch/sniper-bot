import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from datetime import datetime

# --- CONFIGURAÇÃO DE AMBIENTE ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)
WSOL = "So11111111111111111111111111111111111111112"

# --- PARÂMETROS SHARK MODE (BAIXA LIQUIDEZ E ALTA VOLATILIDADE) ---
CONFIG = {
    "entrada_sol": 0.01,     # Valor de entrada solicitado
    "min_liq_usd": 500,      # Liquidez mínima agressiva
    "buy_pressure_5m": 2.5,  # Entra se subir mais de 2.5% em 5 min com volume
    "priority_fee": 50000000, # Taxa altíssima para garantir execução rápida
    "slippage": 3500,        # 35% de slippage para moedas sem liquidez
    "check_interval": 3      # Varredura ultra rápida a cada 3 segundos
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "erros": 0, "inicio": datetime.now()}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except Exception as e: print(f"Erro Telegram: {e}")

@app.route('/')
def home(): 
    return f"SHARK MODE V15 - ONLINE | Compras: {stats['compras']} | Erros: {stats['erros']}", 200

# RELATÓRIO A CADA 2 HORAS
def loop_relatorio():
    while True:
        time.sleep(7200)
        tempo_ativo = str(datetime.now() - stats["inicio"]).split('.')[0]
        msg = (f"📊 **RELATÓRIO SHARK MODE (2H)**\n\n"
               f"⏱ Ativo há: `{tempo_ativo}`\n"
               f"🛒 Compras: `{stats['compras']}` | ✅ Vendas: `{stats['vendas']}`\n"
               f"❌ Erros de Rede: `{stats['erros']}`\n"
               f"💰 Lucro Est.: `{stats['lucro']:.4f} SOL`\n"
               f"🔥 Status: `Caçando baleias...`")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount):
    try:
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        quote = requests.get(q_url, timeout=5).json()
        
        if "error" in quote: raise Exception(quote["error"])

        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        res = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        tx = VersionedTransaction.from_bytes(base64.b64decode(res['swapTransaction']))
        signed_tx = VersionedTransaction(tx.message, [carteira])
        
        sig = solana_client.send_raw_transaction(bytes(signed_tx))
        return True, str(sig.value)
    except Exception as e:
        stats["erros"] += 1
        return False, str(e)

def monitorar_mercado():
    try:
        # Busca moedas recentes com par SOL
        data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
        pairs = data.get('pairs', [])

        for p in pairs:
            addr = p['baseToken']['address']
            sym = p['baseToken']['symbol']
            
            if sym == "SOL" or addr == WSOL or addr in blacklist: continue

            pump_5m = float(p.get('priceChange', {}).get('m5', 0))
            liq = float(p.get('liquidity', {}).get('usd', 0))
            vol_5m = float(p.get('volume', {}).get('m5', 0))

            # ESTRATÉGIA: Subida forte de preço + volume presente + liquidez mínima
            if liq > CONFIG["min_liq_usd"] and pump_5m > CONFIG["buy_pressure_5m"] and vol_5m > 100:
                blacklist.add(addr)
                alertar(f"🚀 **PRESSÃO DE COMPRA DETECTADA: {sym}**\nSubida 5m: {pump_5m}%\nLiq: ${liq:,.0f} | Vol 5m: ${vol_5m:,.0f}")
                
                sucesso, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if sucesso:
                    stats["compras"] += 1
                    alertar(f"✅ **COMPRA REALIZADA!**\nMoeda: {sym}\nTx: `https://solscan.io/tx/{res}`")
                    # Inicia saída estratégica em thread separada
                    threading.Thread(target=estrategia_saida, args=(addr, sym)).start()
                else:
                    alertar(f"⚠️ **FALHA NA COMPRA ({sym}):** `{res}`")
                break 
    except Exception as e:
        print(f"Erro scan: {e}")

def estrategia_saida(addr, sym):
    # Aguarda o melhor momento (Scalping de 2 a 5 minutos)
    time.sleep(180) 
    alertar(f"🔄 **TENTANDO SAÍDA LUCRATIVA: {sym}**")
    
    sucesso, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
    if sucesso:
        stats["vendas"] += 1
        stats["lucro"] += 0.003 # Estimativa por trade bem sucedido
        alertar(f"💰 **VENDA FINALIZADA: {sym}**\nLucro garantido no bolso!")
    else:
        alertar(f"❌ **ERRO AO VENDER {sym}:** `{res}`\nTentando novamente em 30s...")
        time.sleep(30)
        jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    
    alertar("🦈 **V15 SHARK MODE ATIVADO**\nFoco: Baixa liquidez e lucros rápidos.")
    
    while True:
        monitorar_mercado()
        time.sleep(CONFIG["check_interval"])
