import os
from threading import Thread
from flask import Flask
import telebot
from google import genai
from google.genai import types

# === КЛЮЧИ (лучше через переменные окружения на Render) ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") or "8975360035:AAFjoKwlEZH74H2EJTHAkIXTTMkXoBtm6es"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or "AQ.Ab8RN6LTaeguTtaj4F-ZmF57LX2oXXckGdat90nsp4KmQUeJ0Q"

# Новый клиент
client = genai.Client(api_key=GEMINI_API_KEY)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_chats = {}

# Flask для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я твой личный ИИ-ассистент.\nЗадай мне любой вопрос!")

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    chat_id = message.chat.id
    if chat_id in user_chats:
        del user_chats[chat_id]
    bot.reply_to(message, "История сообщений сброшена!")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'typing')

    try:
        if chat_id not in user_chats:
            # Создаём чат с системной инструкцией
            user_chats[chat_id] = client.chats.create(
                model="gemini-2.5-flash",   # или gemini-2.0-flash / gemini-3.5-flash
                config=types.GenerateContentConfig(
                    system_instruction="Ты вежливый и умный ассистент. Отвечай понятно, структурировано и по делу."
                )
            )

        chat = user_chats[chat_id]
        response = chat.send_message(message.text)

        text = response.text

        # Разбиваем длинный ответ
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                bot.send_message(chat_id, text[i:i+4000])
        else:
            try:
                bot.reply_to(message, text, parse_mode='Markdown')
            except Exception:
                bot.reply_to(message, text)

    except Exception as e:
        print(f"Ошибка Gemini API: {e}")
        bot.reply_to(message, f"Ошибка при запросе к ИИ: {e}")

if __name__ == '__main__':
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
    
    bot.polling(none_stop=True)
