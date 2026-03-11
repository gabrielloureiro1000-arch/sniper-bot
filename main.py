def scan_dex():
    global seen
    while True:
        try:
            # Busca tokens recentes na Solana
            url = "https://api.dexscreener.com/latest/dex/search/?q=sol"
            r = requests.get(url, timeout=10)

            if r.status_code == 429:
                print("⚠️ Rate limit atingido! Aguardando 60s...")
                time.sleep(60)
                continue
            
            if r.status_code != 200:
                time.sleep(DEX_INTERVAL)
                continue

            data = r.json()
            pairs = data.get("pairs", [])

            for pair in pairs:
                token = pair.get("baseToken", {}).get("address")
                liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
                
                # Filtros mais rigorosos
                if not token or token in seen or liquidity < 500:
                    continue

                seen.add(token)
                
                # Limita o tamanho do set para não estourar a RAM
                if len(seen) > 5000:
                    seen.pop() 

                # Lógica de envio da mensagem...
                send_alert(pair)

        except Exception as e:
            print(f"❌ Erro no Dex: {e}")
        
        time.sleep(DEX_INTERVAL)
