import os
from threading import Thread
from flask import Flask
import telebot
from groq import Groq
from apscheduler.schedulers.background import BackgroundScheduler

# ====================== КЛЮЧИ ======================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не найден в переменных окружения!")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY не найден в переменных окружения!")

# ====================== ИНИЦИАЛИЗАЦИЯ ======================
client = Groq(api_key=GROQ_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

user_histories = {}

# ====================== FLASK ======================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ====================== ПЛАНИРОВЩИК НАПОМИНАНИЙ ======================
def send_daily_reminder():
    """Функция фоновых напоминаний (например, утренняя рассылка)"""
    # Здесь можно прописать логику отправки напоминаний конкретным пользователям,
    # если сохранить их chat_id в базу данных или список.
    print("Фоновая задача: проверка плановых напоминаний выполнена.")

scheduler = BackgroundScheduler()
# Пример: запускать задачу каждый день в 9:00 утра
scheduler.add_job(send_daily_reminder, 'cron', hour=9, minute=0)
scheduler.start()

# ====================== ОБРАБОТЧИКИ TELEGRAM ======================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Привет! Я твой продвинутый ИИ-ассистент на базе Groq.\n"
        "• Я запоминаю до 30 последних сообщений контекста.\n"
        "• Умею обрабатывать текст и структурировать ответы.\n\n"
        "Команда /reset — сбросить историю диалога."
    )

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    chat_id = message.chat.id
    if chat_id in user_histories:
        del user_histories[chat_id]
    bot.reply_to(message, "История диалога успешно сброшена.")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'typing')

    try:
        # Инициализация истории для нового чата
        if chat_id not in user_histories:
            user_histories[chat_id] = [
                {
                    "role": "system",
                    "content": (
                        "Ты вежливый, умный и полезный ассистент. "
                        "Отвечай понятно, структурировано и по делу. "
                        "Если нужно — используй списки и выделения."
                    )
                }
            ]

        user_histories[chat_id].append({"role": "user", "content": message.text})

        # Удерживаем контекст в пределах 30 сообщений (31 элемент с системным промптом)
        if len(user_histories[chat_id]) > 31:
            user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-30:]

        # Запрос к Groq API
        completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=user_histories[chat_id],
            temperature=0.7,
            max_tokens=2048,
        )

        bot_response = completion.choices[0].message.content
        user_histories[chat_id].append({"role": "assistant", "content": bot_response})

        # Защита от лимитов длины сообщений Telegram (4000 символов)
        if len(bot_response) > 4000:
            for i in range(0, len(bot_response), 4000):
                bot.send_message(chat_id, bot_response[i:i + 4000])
        else:
            bot.reply_to(message, bot_response, parse_mode='Markdown')

    except Exception as e:
        error_text = str(e)
        print(f"Ошибка Groq: {error_text}")
        bot.reply_to(message, f"Произошла ошибка при обращении к ИИ:\n\n{error_text}")

@bot.message_handler(content_types=['voice', 'audio'])
def handle_voice(message):
    bot.reply_to(message, "Я получил голосовое сообщение, но пока работаю только с текстовыми запросами! 🎙️✍️")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    bot.reply_to(message, "Я вижу картинку, но моя текстовая модель пока не умеет их анализировать. Напишите текстом! 🖼️")

# ====================== ЗАПУСК ======================
if __name__ == '__main__':
    # Запуск Flask-сервера в отдельном потоке для Render
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    print("Бот успешно запущен...")
    bot.polling(none_stop=True, interval=1)
