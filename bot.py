import os
from threading import Thread
from flask import Flask
import telebot
import google.generativeai as genai

# === 1. ВСТАВЬТЕ ВАШИ КЛЮЧИ ===
TELEGRAM_TOKEN = "ВАШ_ТОКЕН_ОТ_BOTFATHER"
GEMINI_API_KEY = "ВАШ_КЛЮЧ_ОТ_GOOGLE_AI_STUDIO"

# === 2. ИНИЦИАЛИЗАЦИЯ ИИ И БОТА ===
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction="Ты вежливый и умный ассистент. Отвечай понятно, структурировано и по делу."
)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_chats = {}

# === 3. МИНИ-СЕРВЕР ДЛЯ РЕНДЕРА (чтобы сервис не засыпал) ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_flask():
    # Render автоматически выделяет порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# === 4. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ ===
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
        bot.reply_to(message, response.text, parse_mode='Markdown')
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.reply_to(message, "Произошла ошибка при обработке запроса.")

# === 5. ЗАПУСК ===
if __name__ == '__main__':
    # Запускаем Flask в фоновом потоке
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
    
    print("Бот успешно запущен!")
    bot.polling(none_stop=True)
