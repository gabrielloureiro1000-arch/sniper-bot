import os
import time
import threading
import requests
import telebot
from flask import Flask

# --- CONFIGURAÇÃO ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DEX_INTERVAL = 2  # Scan ultra rápido (2 segundos)

# FILTROS REDUZIDOS PARA MAIOR FREQUÊNCIA DE SINAIS
MIN_LIQUIDITY = 500       # Aceita pools pequenas (lançamentos)
MIN_VOLUME_M5 = 500       # Qualquer volume inicial já dispara
MIN_BUYS_M5 = 3           # Apenas 3 compras em 5min já alertam

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

seen_tokens = set()
monitored_prices = {} 
alerts_count = 0

def send(msg):
    global alerts_count
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        alerts_count += 1
    except Exception as e:
        print(f"Erro Telegram: {e}")

# --- RELATÓRIO DE PERFORMANCE ---
def performance_report():
    while True:
        time.sleep(7200) # 2 Horas
        if not monitored_prices:
            continue
        report = "📊 *RELATÓRIO DE PERFORMANCE (2H)*\n\n"
        try:
            # Pega todos os endereços monitorados
            addrs = list(monitored_prices.keys())
            # Consulta em lotes de 30 para não travar a API
            for i in range(0, len(addrs), 30):
                batch = ",".join(addrs[i:i+30])
                url = f"https://api.dexscreener.com/latest/dex/tokens/{batch}"
                r = requests.get(url, timeout=10)
                pairs = r.json().get("pairs", [])
                
                # Preços atuais
                current_prices = {p.get("baseToken", {}).get("address"): float(p.get("priceUsd", 0)) for p in pairs}

                for addr in addrs[i:i+30]:
                    data = monitored_prices[addr]
                    initial_p = data["price"]
                    current_p = current_prices.get(addr, 0)

                    if current_p > 0:
                        change = ((current_p - initial_p) / initial_p) * 100
                        emoji = "🚀" if change >= 0 else "🔻"
                        report += f"{emoji} *{data['symbol']}*: `{change:+.2f}%` desde o alerta\n"
            
            send(report if len(report) > 40 else "📊 *Relatório:* Nenhum token com dados ativos no momento.")
        except Exception as e:
            print(f"Erro Relatório: {e}")

# --- SCANNER DE TOKENS RECENTES (MAIS SINAIS) ---
def scan():
    print("🔥 SCANNER DE LANÇAMENTOS INICIADO")
    while True:
        try:
            # MUDANÇA CRÍTICA: Usando o endpoint de tokens recentes em vez de busca
            # Isso garante que tokens novos apareçam no radar
            url = "https://api.dexscreener.com/token-profiles/latest/v1" 
            # Como a API acima é limitada, alternamos com a busca global de SOL filtrada por data
            r = requests.get("https://api.dexscreener.com/latest/dex/search?q=solana", timeout=10)
            
            if r.status_code != 200: 
                time.sleep(5)
                continue
            
            pairs = r.json().get("pairs", [])
            # Ordenar por criação (os mais novos primeiro)
            pairs = sorted(pairs, key=lambda x: x.get("pairCreatedAt", 0), reverse=True)

            for pair in pairs:
                # Filtrar apenas rede Solana
                if pair.get("chainId") != "solana": continue
                
                addr = pair.get("baseToken", {}).get("address")
                symbol = pair.get("baseToken", {}).get("symbol", "???")
                
                if not addr or addr in seen_tokens: continue

                liq = pair.get("liquidity", {}).get("usd", 0)
                vol5m = pair.get("volume", {}).get("m5", 0)
                buys5m = pair.get("txns", {}).get("m5", {}).get("buys", 0)
                price = float(pair.get("priceUsd", 0))

                # Filtros para não pegar lixo, mas ser agressivo
                if liq < MIN_LIQUIDITY: continue
                if buys5m < MIN_BUYS_M5: continue

                seen_tokens.add(addr)
                monitored_prices[addr] = {"symbol": symbol, "price": price}

                # Link de busca direta para evitar erro de rede
                gmgn_fix = f"https://gm
