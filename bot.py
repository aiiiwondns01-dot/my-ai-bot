import os
from threading import Thread
from flask import Flask
import telebot
import google.generativeai as genai

# === КЛЮЧИ ===
TELEGRAM_TOKEN = "8975360035:AAFjoKwlEZH74H2EJTHAkIXTTMkXoBtm6es"
GEMINI_API_KEY = "AQ.Ab8RN6LTaeguTtaj4F-ZmF57LX2oXXckGdat90nsp4KmQUeJ0Q"

# Инициализация API
genai.configure(api_key=GEMINI_API_KEY)

# Передаем api_key прямо при создании модели для надежности
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction="Ты вежливый и умный ассистент. Отвечай понятно, структурировано и по делу."
)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_chats = {}

# Веб-сервер Flask для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Обработчики Telegram
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
            user_chats[chat_id] = model.start_chat(history=[])
        
        chat_session = user_chats[chat_id]
        response = chat_session.send_message(message.text)
        
        # Разбиваем ответ, если он слишком длинный для Telegram
        if len(response.text) > 4000:
            for i in range(0, len(response.text), 4000):
                bot.send_message(chat_id, response.text[i:i+4000])
        else:
            bot.reply_to(message, response.text, parse_mode='Markdown')
            
    except Exception as e:
        print(f"Ошибка Gemini API: {e}")
        # Если разметка Markdown ломается, отправляем чистым текстом
        try:
            bot.reply_to(message, response.text)
        except Exception:
            bot.reply_to(message, f"Ошибка при запросе к ИИ: {e}")

if __name__ == '__main__':
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
    
    bot.polling(none_stop=True)
