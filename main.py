def iniciar_bot():
    print("🔄 Limpando sessões anteriores...")
    # Força o Telegram a invalidar qualquer polling ativo
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(5) # Pausa dramática para o Telegram respirar
    
    while True:
        try:
            print("🤖 Sniper conectado e aguardando comandos...")
            bot.polling(none_stop=True, interval=2, timeout=20)
        except Exception as e:
            print(f"❌ Erro: {e}")
            time.sleep(10)
