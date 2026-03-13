import os
import time
import threading
import requests
import telebot
from flask import Flask

# --- CONFIGURAÇÃO ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DEX_INTERVAL = 2 

# FILTROS RECALIBRADOS PARA PROMISSORES (BALEIAS EM FORMAÇÃO)
MIN_LIQUIDITY = 1200       # Baixado para pegar o início do pump
MIN_WHALE_BUYS = 3         # Começa a avisar com 3, mas sinaliza força se tiver +8
MIN_VOLUME_M5 = 1500       # Volume mínimo inicial

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

seen_tokens = set()
monitored_prices = {} 

def send(msg):
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Erro Telegram: {e}")

# --- RELATÓRIO DE PERFORMANCE (2H) ---
def performance_report():
    while True:
        time.sleep(7200)
        if not monitored_prices: continue
        report = "📊 *BALANÇO DE PERFORMANCE (2H)*\n\n"
        try:
            addrs = list(monitored_prices.keys())
            for i in range(0, len(addrs), 30):
                batch = ",".join(addrs[i:i+30])
                url = f"https://api.dexscreener.com/latest/dex/tokens/{batch}"
                r = requests.get(url, timeout=10)
                data = r.json()
                pairs = data.get("pairs", []) if data.get("pairs") else []
                
                current_prices = {p.get("baseToken", {}).get("address"): float(p.get("priceUsd", 0)) for p in pairs}

                for addr in addrs[i:i+30]:
                    info = monitored_prices[addr]
                    initial = info["price"]
                    current = current_prices.get(addr, 0)
                    if current > 0:
                        change = ((current - initial) / initial) * 100
                        emoji = "🚀" if change >= 0 else "🔻"
                        report += f"{emoji} *{info['symbol']}*: `{change:+.2f}%` (Entrada: {initial:.8f})\n"
            send(report)
        except Exception as e:
            print(f"Erro Report: {e}")

# --- SCANNER WHALE TRACKER ---
def scan():
    print("🐋 WHALE HUNTER V3 INICIADO...")
    send("🚀 *Bot Online:* Monitorando Baleias e Tokens Promissores na Solana!")
    
    while True:
        try:
            # Busca ampliada
            r = requests.get("https://api.dexscreener.com/latest/dex/search?q=solana", timeout=10)
            if r.status_code != 200: continue
            
            pairs = r.json().get("pairs", [])
            for pair in pairs:
                if pair.get("chainId") != "solana": continue
                
                addr = pair.get("baseToken", {}).get("address")
                symbol = pair.get("baseToken", {}).get("symbol", "???")
                
                if not addr or addr in seen_tokens: continue

                liq = pair.get("liquidity", {}).get("usd", 0)
                vol5m = pair.get("volume", {}).get("m5", 0)
                buys5m = pair.get("txns", {}).get("m5", {}).get("buys", 0)
                price_usd = pair.get("priceUsd")
                
                if not price_usd: continue
                price = float(price_usd)

                # FILTRO DE BALEIA/PROMISSOR
                if liq < MIN_LIQUIDITY or buys5m < MIN_WHALE_BUYS or vol5m < MIN_VOLUME_M5:
                    continue

                seen_tokens.add(addr)
                monitored_prices[addr] = {"symbol": symbol, "price": price}

                # Tags de Força
                whale_tag = "🐋 BALEIA DETECTADA" if buys5m >= 8 else "📈 ACUMULAÇÃO INICIAL"
                
                # Links de Ação Rápida
                gmgn_url = f"https://gmgn.ai/sol/token/{addr}"
                trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{addr}"

                msg = (
                    f"{whale_tag}\n"
                    f"💎 *Ativo:* ${symbol}\n\n"
                    f"📄 *CA:* `{addr}`\n\n"
                    f"💰 Preço: `${price:.10f}`\n"
                    f"💧 Liq: `${liq:,.0f}` | 📊 Vol 5m: `${vol5m:,.0f}`\n"
                    f"🔥 Compras: `{buys5m} trades (5m)`\n\n"
                    f"🔗 [ANALISAR NO GMGN]({gmgn_url})\n"
                    f"⚡ [COMPRAR NO TROJAN (RÁPIDO)]({trojan_url})"
                )
                send(msg)

        except Exception as e:
            print(f"Erro Scan: {e}")
        time.sleep(DEX_INTERVAL)

@app.route("/")
def health(): return "WHALE SNIPER ONLINE"

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
