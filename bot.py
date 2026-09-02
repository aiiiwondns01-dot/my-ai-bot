import os
import base64
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
active_chat_ids = set()

# ====================== FLASK ======================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ====================== ПЛАНИРОВЩИК НАПОМИНАНИЙ ======================
def send_scheduled_reminders():
    """Фоновая рассылка напоминаний"""
    for chat_id in active_chat_ids:
        try:
            bot.send_message(
                chat_id, 
                "⏰ **Автоматическое напоминание:**\n"
                "Не забудьте сделать перерыв, размяться и выпить воды!"
            )
        except Exception as e:
            print(f"Не удалось отправить напоминание чату {chat_id}: {e}")

scheduler = BackgroundScheduler()
# Напоминание каждый день в 10:00 утра
scheduler.add_job(send_scheduled_reminders, 'cron', hour=10, minute=0)
scheduler.start()

# ====================== ОБЩАЯ ЛОГИКА ТЕКСТОВОГО ОТВЕТА ИИ ======================
def process_ai_response(chat_id, user_text, message_to_reply):
    try:
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

        user_histories[chat_id].append({"role": "user", "content": user_text})

        if len(user_histories[chat_id]) > 31:
            user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-30:]

        completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=user_histories[chat_id],
            temperature=0.7,
            max_tokens=2048,
        )

        bot_response = completion.choices[0].message.content
        user_histories[chat_id].append({"role": "assistant", "content": bot_response})

        if len(bot_response) > 4000:
            for i in range(0, len(bot_response), 4000):
                bot.send_message(chat_id, bot_response[i:i + 4000])
        else:
            bot.reply_to(message_to_reply, bot_response, parse_mode='Markdown')

    except Exception as e:
        error_text = str(e)
        print(f"Ошибка Groq: {error_text}")
        bot.reply_to(message_to_reply, f"Произошла ошибка при обращении к ИИ:\n\n{error_text}")

# ====================== ОБРАБОТЧИКИ TELEGRAM ======================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    active_chat_ids.add(message.chat.id)
    bot.reply_to(
        message,
        "Привет! Я твой продвинутый ИИ-ассистент.\n"
        "• Понимаю текст, голосовые и **кружочки** (видеосообщения).\n"
        "• Анализирую **изображения** (фото с подписями).\n"
        "• Запоминаю до 30 сообщений контекста.\n"
        "• Умею присылать фоновые напоминания.\n\n"
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
    active_chat_ids.add(chat_id)
    bot.send_chat_action(chat_id, 'typing')
    process_ai_response(chat_id, message.text, message)

# Обработка голосовых сообщений и аудио
@bot.message_handler(content_types=['voice', 'audio'])
def handle_voice(message):
    chat_id = message.chat.id
    active_chat_ids.add(chat_id)
    bot.send_chat_action(chat_id, 'typing')

    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        transcription = client.audio.transcriptions.create(
            file=("voice.ogg", downloaded_file),
            model="whisper-large-v3",
            prompt="Распознай русскую речь",
            response_format="text"
        )

        user_text = transcription.strip() if isinstance(transcription, str) else transcription.text

        if not user_text:
            bot.reply_to(message, "Не удалось разобрать голосовое сообщение.")
            return

        bot.send_message(chat_id, f"🎙️ *Распознано:* {user_text}", parse_mode='Markdown')
        process_ai_response(chat_id, user_text, message)

    except Exception as e:
        print(f"Ошибка обработки голоса: {e}")
        bot.reply_to(message, f"Не удалось обработать голосовое сообщение:\n{e}")

# Обработка кружочков (видеосообщений)
@bot.message_handler(content_types=['video_note'])
def handle_video_note(message):
    chat_id = message.chat.id
    active_chat_ids.add(chat_id)
    bot.send_chat_action(chat_id, 'typing')

    try:
        file_info = bot.get_file(message.video_note.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Whisper отлично принимает mp4 файлы видеосообщений для извлечения аудио
        transcription = client.audio.transcriptions.create(
            file=("videonote.mp4", downloaded_file),
            model="whisper-large-v3",
            prompt="Распознай русскую речь",
            response_format="text"
        )

        user_text = transcription.strip() if isinstance(transcription, str) else transcription.text

        if not user_text:
            bot.reply_to(message, "Не удалось разобрать видеосообщение.")
            return

        bot.send_message(chat_id, f"🎥 *Распознано из кружочка:* {user_text}", parse_mode='Markdown')
        process_ai_response(chat_id, user_text, message)

    except Exception as e:
        print(f"Ошибка видеосообщения: {e}")
        bot.reply_to(message, f"Не удалось обработать видеосообщение:\n{e}")

# Обработка изображений (фото) через мультимодальную модель
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    active_chat_ids.add(chat_id)
    bot.send_chat_action(chat_id, 'upload_photo')

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')

        caption = message.caption or "Опиши эту картинку и ответь на вопросы, если они есть."

        if chat_id not in user_histories:
            user_histories[chat_id] = [
                {"role": "system", "content": "Ты вежливый, умный и полезный ассистент."}
            ]

        # Формируем запрос для мультимодальной модели
        messages_payload = user_histories[chat_id].copy()
        messages_payload.append({
            "role": "user",
            "content": [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        })

        completion = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=messages_payload,
            temperature=0.7,
            max_tokens=2048,
        )

        bot_response = completion.choices[0].message.content

        # Сохраняем текстовое описание взаимодействия в общую историю чата
        user_histories[chat_id].append({"role": "user", "content": f"[Отправлено изображение с подписью: {caption}]"})
        user_histories[chat_id].append({"role": "assistant", "content": bot_response})

        if len(user_histories[chat_id]) > 31:
            user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-30:]

        if len(bot_response) > 4000:
            for i in range(0, len(bot_response), 4000):
                bot.send_message(chat_id, bot_response[i:i + 4000])
        else:
            bot.reply_to(message, bot_response, parse_mode='Markdown')

    except Exception as e:
        print(f"Ошибка обработки изображения: {e}")
        bot.reply_to(message, f"Не удалось обработать изображение:\n{e}")

# ====================== ЗАПУСК ======================
if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    print("Бот успешно запущен...")
    bot.polling(none_stop=True, interval=1)
