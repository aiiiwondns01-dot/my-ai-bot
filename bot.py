import os
import json
import base64
from datetime import datetime, timedelta
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

# ====================== FLASK (ДЛЯ RENDER) ======================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ====================== СИСТЕМА НАПОМИНАНИЙ ======================
def trigger_reminder(chat_id, text):
    """Функция срабатывания напоминания по таймеру"""
    try:
        bot.send_message(
            chat_id, 
            f"⏰ **Напоминание:**\n{text}", 
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"Не удалось отправить напоминание чату {chat_id}: {e}")

def set_reminder_function(chat_id, minutes, reminder_text):
    """Инструмент, который вызывает нейросеть при запросе напоминания"""
    try:
        run_time = datetime.now() + timedelta(minutes=int(minutes))
        scheduler.add_job(trigger_reminder, 'date', run_date=run_time, args=[chat_id, reminder_text])
        return f"Успешно установлено напоминание через {minutes} мин. Текст: '{reminder_text}'."
    except Exception as e:
        return f"Ошибка при установке напоминания: {e}"

# Описание функций (Tools) для Groq API
tools = [
    {
        "type": "function",
        "function": {
            "name": "set_reminder_function",
            "description": "Установить напоминание для пользователя через определенное количество минут.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {
                        "type": "integer",
                        "description": "Через сколько минут нужно напомнить (например, 10, 30, 60)."
                    },
                    "reminder_text": {
                        "type": "string",
                        "description": "Текст или суть напоминания."
                    }
                },
                "required": ["minutes", "reminder_text"]
            }
        }
    }
]

scheduler = BackgroundScheduler()
scheduler.start()

# ====================== ЛОГИКА ОБРАБОТКИ ИИ С TOOLS ======================
def process_ai_response(chat_id, user_text, message_to_reply):
    try:
        active_chat_ids.add(chat_id)
        
        if chat_id not in user_histories:
            user_histories[chat_id] = [
                {
                    "role": "system",
                    "content": (
                        "Ты вежливый, умный и полезный ассистент. "
                        "Если пользователь просит о чем-то напомнить, обязательно используй функцию set_reminder_function."
                    )
                }
            ]

        user_histories[chat_id].append({"role": "user", "content": user_text})

        if len(user_histories[chat_id]) > 31:
            user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-30:]

        # Основная текстовая модель с поддержкой инструментов
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=user_histories[chat_id],
            tools=tools,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=2048,
        )

        response_message = response.choices[0].message

        if response_message.tool_calls:
            user_histories[chat_id].append(response_message)
            
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "set_reminder_function":
                    args = json.loads(tool_call.function.arguments)
                    mins = args.get("minutes")
                    text = args.get("reminder_text")
                    
                    tool_result = set_reminder_function(chat_id, mins, text)
                    
                    user_histories[chat_id].append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": "set_reminder_function",
                        "content": tool_result
                    })

            second_response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=user_histories[chat_id],
                temperature=0.7,
                max_tokens=2048,
            )
            bot_response = second_response.choices[0].message.content
            user_histories[chat_id].append({"role": "assistant", "content": bot_response})
            bot.reply_to(message_to_reply, bot_response, parse_mode='Markdown')

        else:
            bot_response = response_message.content
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
        "• Понимаю текст, голосовые и **кружочки**.\n"
        "• Анализирую **изображения**.\n"
        "• Умею ставить напоминания через голосовые или текст (просто скажи: *«напомни через 10 минут...»*).\n\n"
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
    process_ai_response(chat_id, message.text, message)

@bot.message_handler(content_types=['voice', 'audio'])
def handle_voice(message):
    chat_id = message.chat.id
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
        print(f"Ошибка голоса: {e}")
        bot.reply_to(message, f"Не удалось обработать голосовое:\n{e}")

@bot.message_handler(content_types=['video_note'])
def handle_video_note(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'typing')

    try:
        file_info = bot.get_file(message.video_note.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        transcription = client.audio.transcriptions.create(
            file=("videonote.mp4", downloaded_file),
            model="whisper-large-v3",
            prompt="Распознай русскую речь",
            response_format="text"
        )

        user_text = transcription.strip() if isinstance(transcription, str) else transcription.text
        if not user_text:
            bot.reply_to(message, "Не удалось разобрать кружочек.")
            return

        bot.send_message(chat_id, f"🎥 *Распознано из кружочка:* {user_text}", parse_mode='Markdown')
        process_ai_response(chat_id, user_text, message)

    except Exception as e:
        print(f"Ошибка кружочка: {e}")
        bot.reply_to(message, f"Не удалось обработать видеосообщение:\n{e}")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'upload_photo')

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')

        caption = message.caption or "Опиши эту картинку."

        if chat_id not in user_histories:
            user_histories[chat_id] = [{"role": "system", "content": "Ты полезный ассистент."}]

        messages_payload = user_histories[chat_id].copy()
        messages_payload.append({
            "role": "user",
            "content": [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        })

        # Мультимодальная модель для работы с изображениями
        completion = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=messages_payload,
            temperature=0.7,
            max_tokens=2048,
        )

        bot_response = completion.choices[0].message.content
        user_histories[chat_id].append({"role": "user", "content": f"[Фото с подписью: {caption}]"})
        user_histories[chat_id].append({"role": "assistant", "content": bot_response})

        if len(user_histories[chat_id]) > 31:
            user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-30:]

        if len(bot_response) > 4000:
            for i in range(0, len(bot_response), 4000):
                bot.send_message(chat_id, bot_response[i:i + 4000])
        else:
            bot.reply_to(message, bot_response, parse_mode='Markdown')

    except Exception as e:
        print(f"Ошибка изображения: {e}")
        bot.reply_to(message, f"Не удалось обработать изображение:\n{e}")

# ====================== ЗАПУСК ======================
if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    print("Бот успешно запущен...")
    bot.polling(none_stop=True, interval=1)
