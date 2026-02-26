import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from datetime import datetime

# --- CONFIGURAÇÃO ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)
WSOL = "So11111111111111111111111111111111111111112"

# --- PARÂMETROS EXTREME DEGEN (MÁXIMO LUCRO) ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_liq_usd": 300,       # Entra em moedas ultra-novas
    "trigger_pump": 0.5,      # Qualquer sinal de subida, ele compra
    "take_profit": 1.15,      # Vende com 15% de lucro
    "stop_loss": 0.92,        # Vende se cair 8%
    "priority_fee": 60000000, # Taxa agressiva para não ficar travado
    "slippage": 4000          # 40% de slippage (Essencial para baixa liquidez)
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "erros": 0, "inicio": datetime.now()}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

@app.route('/')
def home(): return f"EXTREME DEGEN V16 - ATIVO | Compras: {stats['compras']}", 200

def loop_relatorio():
    while True:
        time.sleep(7200)
        msg = (f"🏴‍☠️ **RELATÓRIO DE GUERRA (2H)**\n\n"
               f"🛒 Compras: `{stats['compras']}` | ✅ Vendas: `{stats['vendas']}`\n"
               f"💰 Lucro Total: `{stats['lucro']:.4f} SOL`\n"
               f"❌ Falhas: `{stats['erros']}`\n"
               f"🚀 Status: `Sniper pronto para o abate`")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount, is_sell=False):
    try:
        slippage = CONFIG["slippage"] if not is_sell else 5000 # 50% na venda p/ garantir
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slippage}"
        quote = requests.get(q_url, timeout=5).json()
        
        if "error" in quote: return False, quote["error"]

        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        res = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        tx = VersionedTransaction.from_bytes(base64.b64decode(res['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(sig.value)
    except Exception as e:
        return False, str(e)

def caçar_moedas():
    try:
        # Busca moedas com volume recente na Solana
        data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
        for p in data.get('pairs', []):
            addr = p['baseToken']['address']
            sym = p['baseToken']['symbol']
            
            if addr in blacklist or sym == "SOL": continue

            liq = float(p.get('liquidity', {}).get('usd', 0))
            pump = float(p.get('priceChange', {}).get('m5', 0))

            if liq > CONFIG["min_liq_usd"] and pump > CONFIG["trigger_pump"]:
                blacklist.add(addr)
                alertar(f"🎯 **ALVO DETECTADO: {sym}**\nLiq: ${liq:,.0f} | Pump: {pump}%\n*Enviando 0.01 SOL...*")
                
                ok, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if ok:
                    stats["compras"] += 1
                    alertar(f"✅ **COMPRA OK!**\nTx: `https://solscan.io/tx/{res}`")
                    threading.Thread(target=gestao_venda, args=(addr, sym)).start()
                else:
                    stats["erros"] += 1
                    alertar(f"⚠️ **FALHA COMPRA:** `{res[:50]}`")
                break
    except: pass

def gestao_venda(addr, sym):
    # Monitoramento de saída (Máximo 10 minutos de trade)
    start_trade = time.time()
    while time.time() - start_trade < 600:
        try:
            # Verifica preço atual via Jupiter para precisão
            q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={addr}&outputMint={WSOL}&amount={int(CONFIG['entrada_sol']*1e9)}&slippageBps=50"
            quote = requests.get(q_url, timeout=5).json()
            
            if "outAmount" in quote:
                valor_atual = int(quote["outAmount"]) / 1e9
                ratio = valor_atual / CONFIG["entrada_sol"]

                # Take Profit ou Stop Loss
                if ratio >= CONFIG["take_profit"] or ratio <= CONFIG["stop_loss"]:
                    motivo = "LUCRO" if ratio >= 1 else "STOP"
                    alertar(f"⚡ **SAÍDA ESTRATÉGICA ({motivo}): {sym}**\nRatio: {ratio:.2f}x")
                    ok, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)
                    if ok:
                        stats["vendas"] += 1
                        stats["lucro"] += (valor_atual - CONFIG["entrada_sol"])
                        alertar(f"💰 **VENDA CONCLUÍDA!**")
                        return
            time.sleep(2) # Checa preço a cada 2s
        except: time.sleep(5)
    
    # Venda forçada após 10 min se não bateu alvo
    jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    alertar("💀 **V16 EXTREME DEGEN ATIVADO**\nModo de alto risco e alta frequência.")
    while True:
        caçar_moedas()
        time.sleep(2)
