import os
from threading import Thread
from flask import Flask
import telebot
from google import genai
from google.genai import types

# ====================== КЛЮЧИ ======================
TELEGRAM_TOKEN = "8975360035:AAFjoKwlEZH74H2EJTHAkIXTTMkXoBtm6es"
GEMINI_API_KEY = "AQ.Ab8RN6In2pgzUgwjVwDSqIhukD_nxha-boweIsivw0AnqsACaQ"   

# ====================== ИНИЦИАЛИЗАЦИЯ ======================
client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

user_chats = {}

# ====================== FLASK ======================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ====================== ОБРАБОТЧИКИ ======================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Привет! Я твой ИИ-ассистент на базе Gemini 3.8 Flash.\n"
        "Просто напиши мне любой вопрос.\n\n"
        "Команда /reset — сбросить историю диалога."
    )

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    chat_id = message.chat.id
    if chat_id in user_chats:
        del user_chats[chat_id]
    bot.reply_to(message, "История диалога успешно сброшена.")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'typing')

    try:
        if chat_id not in user_chats:
            user_chats[chat_id] = client.chats.create(
                model="gemini-3.8-flash",
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "Ты вежливый, умный и полезный ассистент. "
                        "Отвечай понятно, структурировано и по делу."
                    )
                )
            )

        chat = user_chats[chat_id]
        response = chat.send_message(message.text)
        answer = response.text

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                bot.send_message(chat_id, answer[i:i + 4000])
        else:
            bot.reply_to(message, answer)

    except Exception as e:
        print(f"Ошибка Gemini: {e}")
        bot.reply_to(message, f"Произошла ошибка:\n{e}")

# ====================== ЗАПУСК ======================
if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    print("Бот запущен...")
    bot.polling(none_stop=True)
