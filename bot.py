import os
import json
import base64
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
import telebot
from groq import Groq
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
import docx

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
user_notebooks = {} 

# ====================== FLASK (ДЛЯ RENDER) ======================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ====================== ИНСТРУМЕНТЫ (TOOLS) ======================

def trigger_reminder(chat_id, text):
    """Срабатывание таймера напоминания"""
    try:
        bot.send_message(chat_id, f"Напоминание: {text}")
    except Exception as e:
        print(f"Ошибка отправки напоминания: {e}")

def set_reminder_function(chat_id, amount, unit, reminder_text):
    """Установка напоминания (секунды, минуты, часы)"""
    try:
        amount = float(amount)
        if unit in ["секунда", "секунды", "секунд", "sec", "seconds"]:
            delta_seconds = amount
        elif unit in ["час", "часа", "часов", "hour", "hours"]:
            delta_seconds = amount * 3600
        else: 
            delta_seconds = amount * 60

        run_time = datetime.now() + timedelta(seconds=delta_seconds)
        scheduler.add_job(trigger_reminder, 'date', run_date=run_time, args=[chat_id, reminder_text])
        return f"Успешно напомню через {amount} {unit}: '{reminder_text}'."
    except Exception as e:
        return f"Не получилось поставить напоминание: {e}"

def add_to_notebook_function(chat_id, task_text):
    """Добавление дела в ежедневник"""
    if chat_id not in user_notebooks:
        user_notebooks[chat_id] = []
    
    user_notebooks[chat_id].append(task_text)
    return f"Дело успешно записано в ежедневник: '{task_text}'."

def show_notebook_function(chat_id):
    """Показать список дел на сегодня"""
    tasks = user_notebooks.get(chat_id, [])
    if not tasks:
        return "На сегодня в ежедневнике пока ничего нет."
    
    tasks_list = "\n".join([f"- {task}" for task in tasks])
    return f"Твои дела на сегодня:\n{tasks_list}"

def get_weather_function(city="Саратов"):
    """Получить погоду"""
    try:
        url = f"https://wttr.in/{city}?format=3&lang=ru"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.text.strip()
        return "Не удалось получить погоду."
    except Exception as e:
        return f"Ошибка получения погоды: {e}"

def get_news_function():
    """Получить свежие новости"""
    try:
        url = "https://news.google.com/rss?hl=ru&gl=RU&ceid=RU:ru"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            return "Не удалось загрузить новости."
        
        soup = BeautifulSoup(response.content, features='xml')
        items = soup.findAll('item')[:5]
        news_list = []
        for item in items:
            news_list.append(f"- {item.title.text}")
        return "\n".join(news_list)
    except Exception as e:
        return f"Ошибка загрузки новостей: {e}"

def fetch_web_page(url):
    """Чтение текста с веб-сайта по ссылке"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for script in soup(["script", "style"]):
            script.extract()
            
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text[:10000] # Ограничение для контекста
    except Exception as e:
        return f"Не удалось прочитать сайт: {e}"

# Описание инструментов для Groq API
tools = [
    {
        "type": "function",
        "function": {
            "name": "set_reminder_function",
            "description": "Установить напоминание через определенное время (секунды, минуты или часы).",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Числовое значение времени."},
                    "unit": {"type": "string", "description": "Единица измерения времени.", "enum": ["секунды", "минуты", "часы"]},
                    "reminder_text": {"type": "string", "description": "Суть напоминания."}
                },
                "required": ["amount", "unit", "reminder_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_notebook_function",
            "description": "Записать важное дело или задачу в ежедневник.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_text": {"type": "string", "description": "Краткая суть дела или задачи."}
                },
                "required": ["task_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "show_notebook_function",
            "description": "Показать список всех записанных дел на сегодня.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_function",
            "description": "Узнать актуальную погоду в Саратове или другом городе.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Название города, по умолчанию Саратов."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_news_function",
            "description": "Получить актуальные новости на сегодня.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

scheduler = BackgroundScheduler()
scheduler.start()

# ====================== ЛОГИКА ИИ ======================
SYSTEM_PROMPT = (
    "Твое имя — Воскресенье. Ты общаешься с пользователем как друг-тинейджер: на «ты», просто, легко, "
    "без токсичного сленга и без лишней официальщины.\n"
    "Информация о пользователе: его зовут Вова, ему 21 год, он студент университета, живет в Саратове, Саратовской области. "
    "У него есть опыт работы с VFX на Unreal Engine 5, он изучает Houdini, планирует развиваться в 3D и геймдеве.\n"
    "У тебя есть инструменты для погоды, новостей, ежедневника и напоминаний, а также возможность читать сайты по ссылкам.\n"
    "Самое главное правило: НИКОГДА и ни при каких условиях не используй символы форматирования текста "
    "вроде двойных звездочек (**), одинарных (*), подчеркиваний (_) или решеток (#). Текст должен быть абсолютно простым, "
    "чистым, без выделений.\n"
    "Пиши всегда максимально коротко, четко и по делу, без «воды»."
)

def process_ai_response(chat_id, user_text, message_to_reply):
    try:
        if chat_id not in user_histories:
            user_histories[chat_id] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]

        user_histories[chat_id].append({"role": "user", "content": user_text})

        if len(user_histories[chat_id]) > 31:
            user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-30:]

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
                args = json.loads(tool_call.function.arguments or "{}")
                name = tool_call.function.name
                
                tool_result = ""
                if name == "set_reminder_function":
                    tool_result = set_reminder_function(chat_id, args.get("amount"), args.get("unit"), args.get("reminder_text"))
                elif name == "add_to_notebook_function":
                    tool_result = add_to_notebook_function(chat_id, args.get("task_text"))
                elif name == "show_notebook_function":
                    tool_result = show_notebook_function(chat_id)
                elif name == "get_weather_function":
                    city = args.get("city", "Саратов")
                    tool_result = get_weather_function(city)
                elif name == "get_news_function":
                    tool_result = get_news_function()
                
                user_histories[chat_id].append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": name,
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
            bot.reply_to(message_to_reply, bot_response)

        else:
            bot_response = response_message.content
            user_histories[chat_id].append({"role": "assistant", "content": bot_response})

            if len(bot_response) > 4000:
                for i in range(0, len(bot_response), 4000):
                    bot.send_message(chat_id, bot_response[i:i + 4000])
            else:
                bot.reply_to(message_to_reply, bot_response)

    except Exception as e:
        error_text = str(e)
        print(f"Ошибка ИИ: {error_text}")
        bot.reply_to(message_to_reply, f"Трабл с ИИ: {error_text}")

# ====================== ОБРАБОТЧИКИ TELEGRAM ======================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Здарова, Вова! Я Воскресенье, твой бро-ассистент. Помню, что ты из Саратова, студент, шаришь за VFX в UE5, копаешь Гудини и метишь в 3D. "
        "Могу давать погоду, новости, читать сайты, файлы и видео по ссылкам, вести ежедневник и ставить напоминания. Че делаем?"
    )

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    chat_id = message.chat.id
    if chat_id in user_histories:
        del user_histories[chat_id]
    bot.reply_to(message, "Память диалога сброшена, но основная инфа про тебя и Саратов при мне.")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    text = message.text
    
    # Проверка на наличие ссылки в тексте для парсинга сайта
    if "http://" in text or "https://" in text:
        words = text.split()
        url = next((w for w in words if w.startswith("http://") or w.startswith("https://")), None)
        if url:
            bot.send_chat_action(chat_id, 'typing')
            page_content = fetch_web_page(url)
            prompt_with_page = f"Пользователь скинул ссылку {url} с текстом: '{text}'. Вот содержимое страницы:\n{page_content}\nВыдели самую суть простым текстом без форматирования."
            process_ai_response(chat_id, prompt_with_page, message)
            return

    bot.send_chat_action(chat_id, 'typing')
    process_ai_response(chat_id, text, message)

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
            bot.reply_to(message, "Не вышло разобрать голосовуху.")
            return

        process_ai_response(chat_id, user_text, message)

    except Exception as e:
        print(f"Ошибка голосового: {e}")
        bot.reply_to(message, f"Ошибка с голосом: {e}")

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
            bot.reply_to(message, "Не вышло разобрать кружочек.")
            return

        process_ai_response(chat_id, user_text, message)

    except Exception as e:
        print(f"Ошибка кружочка: {e}")
        bot.reply_to(message, f"Ошибка с кружочком: {e}")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'typing')

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = message.document.file_name.lower()

        extracted_text = ""
        temp_path = f"temp_{message.document.file_name}"
        with open(temp_path, 'wb') as f:
            f.write(downloaded_file)

        if file_name.endswith('.pdf'):
            reader = PdfReader(temp_path)
            for page in reader.pages:
                extracted_text += page.extract_text() or ""
        elif file_name.endswith('.docx'):
            doc = docx.Document(temp_path)
            for para in doc.paragraphs:
                extracted_text += para.text + "\n"

        if os.path.exists(temp_path):
            os.remove(temp_path)

        if not extracted_text.strip():
            bot.reply_to(message, "Не удалось прочитать текст из файла.")
            return

        prompt_text = f"Пользователь прикрепил документ {message.document.file_name}. Вот его текст:\n{extracted_text[:10000]}\nВыдай самую суть простым текстом без форматирования."
        process_ai_response(chat_id, prompt_text, message)

    except Exception as e:
        print(f"Ошибка файла: {e}")
        bot.reply_to(message, f"Не удалось обработать файл: {e}")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'upload_photo')

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')

        caption = message.caption or "Опиши подробно, что видишь на фото."

        if chat_id not in user_histories:
            user_histories[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

        messages_payload = user_histories[chat_id].copy()
        messages_payload.append({
            "role": "user",
            "content": [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        })

        completion = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=messages_payload,
            temperature=0.7,
            max_tokens=2048,
        )

        bot_response = completion.choices[0].message.content
        user_histories[chat_id].append({"role": "user", "content": f"[Фото: {caption}]"})
        user_histories[chat_id].append({"role": "assistant", "content": bot_response})

        if len(user_histories[chat_id]) > 31:
            user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-30:]

        if len(bot_response) > 4000:
            for i in range(0, len(bot_response), 4000):
                bot.send_message(chat_id, bot_response[i:i + 4000])
        else:
            bot.reply_to(message, bot_response)

    except Exception as e:
        print(f"Ошибка картинки: {e}")
        bot.reply_to(message, f"Не удалось обработать изображение: {e}")

# ====================== ЗАПУСК ======================
if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    print("Воскресенье успешно запущен...")
    bot.polling(none_stop=True, interval=1)
