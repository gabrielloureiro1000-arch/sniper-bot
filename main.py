import os
import time
import threading
import requests
import telebot
from flask import Flask

# ─── CONFIG ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

MIN_SCORE     = 35        
MIN_LIQUIDITY = 1000      
DEX_INTERVAL  = 3         

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# Rastreamento: { endereço: {"symbol": str, "price_at_alert": float, "timestamp": float} }
monitored_tokens = {}
seen = set()
alerts = 0

def send(msg):
    global alerts
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        alerts += 1
    except Exception as e:
        print(f"Telegram Error: {e}")

# ─── MONITORAMENTO DE PERFORMANCE (2 EM 2 HORAS) ──────────────────────────
def report_performance():
    while True:
        time.sleep(7200) # 2 horas exatas
        if not monitored_tokens:
            continue
            
        report_msg = "📊 *RELATÓRIO DE PERFORMANCE (Últimas 2h)*\n\n"
        
        # Busca preços atuais no DexScreener
        addresses = ",".join(monitored_tokens.keys())
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{addresses}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json().get("pairs", [])
                
                # Mapear preços atuais por endereço
                current_prices = {p['baseToken']['address']: float(p['priceUsd']) for p in data if 'priceUsd' in p}
                
                for addr, info in list(monitored_tokens.items()):
                    if addr in current_prices:
                        p_initial = info["price_at_alert"]
                        p_current = current_prices[addr]
                        change = ((p_current - p_initial) / p_initial) * 100
                        
                        emoji = "🚀" if change > 0 else "🔻"
                        report_msg += f"{emoji} *{info['symbol']}*: `{change:+.2f}%` desde o sinal\n"
                    
                    # Remove tokens do monitoramento após 24h para não poluir
                    if time.time() - info["timestamp"] > 86400:
                        monitored_tokens.pop(addr)
                        
                send(report_msg)
        except Exception as e:
            print(f"Erro no relatório: {e}")

# ─── SCANNER PRINCIPAL ─────────────────────────────────────────────────────
def scan_dex():
    global seen
    print("Sniper Ativo - Links Corrigidos")
    
    while True:
        try:
            r = requests.get("https://api.dexscreener.com/latest/dex/search/?q=sol", timeout=5)
            if r.status_code != 200: continue

            pairs = r.json().get("pairs", [])
            for pair in pairs:
                token_addr = pair.get("baseToken", {}).get("address")
                symbol = pair.get("baseToken", {}).get("symbol", "???")
                liq = pair.get("liquidity", {}).get("usd", 0)
                price_usd = float(pair.get("priceUsd", 0)) if pair.get("priceUsd") else 0
                
                if not token_addr or token_addr in seen: continue
                if liq < MIN_LIQUIDITY: continue

                # Filtro de Momentum (M5)
                m5_buys = pair.get("txns", {}).get("m5", {}).get("buys", 0)
                if m5_buys > 12: # Só avisa se tiver volume real agora
                    seen.add(token_addr)
                    
                    # Salva para o relatório de 2h
                    monitored_tokens[token_addr] = {
                        "symbol": symbol,
                        "price_at_alert": price_usd,
                        "timestamp": time.time()
                    }
                    
                    # --- SOLUÇÃO PARA O LINK GMGN ---
                    # O formato abaixo força o carregamento da busca, evitando o erro de rede
                    gm_link = f"https://gmgn.ai/sol/token/{token_addr}"
                    # Link alternativo via Trojan Bot (Mais rápido para mobile)
                    tj_link = f"https://t.me/solana_trojan_bot?start=r-user_{token_addr}"

                    msg = (
                        f"🚀 *OPORTUNIDADE: ${symbol}*\n\n"
                        f"📄 *CONTRATO:* \n`{token_addr}`\n\n"
                        f"💰 Preço inicial: `${price_usd:.8f}`\n"
                        f"💧 Liquidez: `${liq:,.0f}`\n\n"
                        f"🔗 [ABRIR NO GMGN AGORA]({gm_link})\n\n"
                        f"⚡ [COMPRA DIRETA (Trojan Bot)]({tj_link})"
                    )
                    send(msg)

        except Exception as e:
            print(f"Erro: {e}")
        time.sleep(DEX_INTERVAL)

@app.route("/")
def health():
    return "Sniper Rodando"

if __name__ == "__main__":
    threading.Thread(target=scan_dex, daemon=True).start()
    threading.Thread(target=report_performance, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
