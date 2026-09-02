import os
from threading import Thread
from flask import Flask
import telebot
from groq import Groq

# ====================== КЛЮЧИ ======================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не найден!")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY не найден!")

# ====================== ИНИЦИАЛИЗАЦИЯ ======================
client = Groq(api_key=GROQ_API_KEY)
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
        "Привет! Я твой ИИ-ассистент на базе Groq (Llama 3.3 70B).\n"
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
            user_chats[chat_id] = [
                {
                    "role": "system",
                    "content": "Ты вежливый, умный и полезный ассистент. Отвечай понятно, структурировано и по делу."
                }
            ]

        user_chats[chat_id].append({
            "role": "user",
            "content": message.text
        })

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=user_chats[chat_id],
            temperature=0.7,
            max_tokens=2048
        )

        answer = response.choices[0].message.content

        user_chats[chat_id].append({
            "role": "assistant",
            "content": answer
        })

        # Ограничиваем историю
        if len(user_chats[chat_id]) > 21:
            user_chats[chat_id] = user_chats[chat_id][:1] + user_chats[chat_id][-20:]

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                bot.send_message(chat_id, answer[i:i+4000])
        else:
            bot.reply_to(message, answer)

    except Exception as e:
        print(f"Ошибка Groq: {e}")
        bot.reply_to(message, f"Произошла ошибка:\n{e}")

# ====================== ЗАПУСК ======================
if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    print("Бот успешно запущен...")
    bot.polling(none_stop=True)
