import os
import json
import base64
import re
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
import tempfile
import speech_recognition as sr
from pydub import AudioSegment
from urllib.parse import urlparse
import yt_dlp

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
    try:
        bot.send_message(chat_id, f"Напоминание: {text}")
    except Exception as e:
        print(f"Ошибка отправки напоминания: {e}")

def set_reminder(chat_id, amount, unit, reminder_text):
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

def add_to_notebook(chat_id, task_text):
    if chat_id not in user_notebooks:
        user_notebooks[chat_id] = []
    user_notebooks[chat_id].append(task_text)
    return f"Дело успешно записано в ежедневник: '{task_text}'."

def show_notebook(chat_id):
    tasks = user_notebooks.get(chat_id, [])
    if not tasks:
        return "На сегодня в ежедневнике пока ничего нет."
    tasks_list = "\n".join([f"- {task}" for task in tasks])
    return f"Твои дела на сегодня:\n{tasks_list}"

def get_weather(city="Саратов"):
    try:
        url = f"https://wttr.in/{city}?format=3&lang=ru"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.text.strip()
        return "Не удалось получить погоду."
    except Exception as e:
        return f"Ошибка получения погоды: {e}"

def get_news():
    try:
        url = "https://news.google.com/rss?hl=ru&gl=RU&ceid=RU:ru"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            return "Не удалось загрузить новости."
        soup = BeautifulSoup(response.content, features='xml')
        items = soup.findAll('item')[:5]
        news_list = [f"- {item.title.text}" for item in items]
        return "\n".join(news_list)
    except Exception as e:
        return f"Ошибка загрузки новостей: {e}"

def fetch_web_page(url):
    """Извлекает текст из веб-страницы"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Удаляем скрипты и стили
        for script in soup(["script", "style"]):
            script.extract()
        
        # Получаем текст
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Обрезаем до разумного размера
        return text[:10000]
    except Exception as e:
        return f"Не удалось прочитать сайт: {e}"

def get_video_info(url):
    """Получает информацию о видео с YouTube и других платформ"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'force_generic_extractor': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if info:
                result = []
                result.append(f"Название: {info.get('title', 'Неизвестно')}")
                result.append(f"Автор: {info.get('uploader', 'Неизвестно')}")
                result.append(f"Длительность: {format_duration(info.get('duration', 0))}")
                result.append(f"Просмотров: {info.get('view_count', 0):,}")
                result.append(f"Лайков: {info.get('like_count', 0):,}")
                
                # Описание (обрезаем)
                description = info.get('description', '')
                if description:
                    description = description[:500] + "..." if len(description) > 500 else description
                    result.append(f"Описание: {description}")
                
                # Теги
                tags = info.get('tags', [])
                if tags:
                    result.append(f"Теги: {', '.join(tags[:10])}")
                
                return "\n".join(result)
            return "Не удалось получить информацию о видео"
    except Exception as e:
        return f"Ошибка получения информации о видео: {e}"

def format_duration(seconds):
    """Форматирует длительность в читаемый вид"""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}ч {minutes}м {seconds}с"
    elif minutes > 0:
        return f"{minutes}м {seconds}с"
    else:
        return f"{seconds}с"

def extract_article_info(url):
    """Извлекает основную информацию из статьи"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Пытаемся найти заголовок
        title = soup.find('h1')
        if not title:
            title = soup.find('title')
        
        title_text = title.get_text().strip() if title else "Заголовок не найден"
        
        # Пытаемся найти дату публикации
        date_patterns = [
            'time', 'datetime', 'published', 'date', 'publication-date'
        ]
        date = None
        for pattern in date_patterns:
            meta = soup.find('meta', {'name': pattern}) or soup.find('meta', {'property': pattern})
            if meta:
                date = meta.get('content') or meta.get('datetime')
                if date:
                    break
        
        # Пытаемся найти автора
        author_patterns = ['author', 'writer', 'byline']
        author = None
        for pattern in author_patterns:
            meta = soup.find('meta', {'name': pattern}) or soup.find('meta', {'property': pattern})
            if meta:
                author = meta.get('content')
                if author:
                    break
        
        # Извлекаем основной текст
        for script in soup(["script", "style"]):
            script.extract()
        
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Берем первые 2000 символов как краткое содержание
        summary = text[:2000] + "..." if len(text) > 2000 else text
        
        result = []
        result.append(f"Заголовок: {title_text}")
        if author:
            result.append(f"Автор: {author}")
        if date:
            result.append(f"Дата: {date}")
        result.append("\nКраткое содержание (первые 2000 символов):")
        result.append(summary)
        
        return "\n".join(result)
        
    except Exception as e:
        return f"Ошибка извлечения информации из статьи: {e}"

def detect_url_type(url):
    """Определяет тип ссылки"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    # Видео-платформы
    video_domains = [
        'youtube.com', 'youtu.be', 'vimeo.com', 'rutube.ru', 
        'dzen.ru', 'vk.com/video', 'ok.ru/video'
    ]
    
    for video_domain in video_domains:
        if video_domain in domain:
            return 'video'
    
    # Новостные сайты
    news_domains = [
        'ria.ru', 'tass.ru', 'kommersant.ru', 'vedomosti.ru',
        'rbc.ru', 'interfax.ru', 'lenta.ru', 'gazeta.ru',
        'mk.ru', 'kp.ru', 'news.google.com', 'bbc.com',
        'cnn.com', 'nytimes.com', 'theguardian.com'
    ]
    
    for news_domain in news_domains:
        if news_domain in domain:
            return 'article'
    
    return 'article'  # По умолчанию считаем статьей

def process_link(url):
    """Обрабатывает ссылку в зависимости от типа"""
    link_type = detect_url_type(url)
    
    if link_type == 'video':
        info = get_video_info(url)
        return f"Информация о видео:\n{info}"
    else:
        info = extract_article_info(url)
        return f"Информация о статье:\n{info}"

tools = [
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
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
            "name": "add_to_notebook",
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
            "name": "show_notebook",
            "description": "Показать список всех записанных дел на сегодня.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
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
            "name": "get_news",
            "description": "Получить актуальные новости на сегодня.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "process_link",
            "description": "Обработать ссылку на статью или видео и получить краткую информацию о ней.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Ссылка на статью или видео."}
                },
                "required": ["url"]
            }
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
    "У тебя есть инструменты для погоды, новостей, ежедневника, напоминаний, а также возможность анализировать ссылки на статьи и видео.\n"
    "СТРОГИЕ ПРАВИЛА ВЫВОДА:\n"
    "1. Никогда не пиши мысли, теги think, рассуждения или внутренний анализ. Выдавай сразу и только готовый ответ пользователю.\n"
    "2. НИКОГДА и ни при каких условиях не используй символы форматирования текста вроде двойных звездочек (**), одинарных (*), подчеркиваний (_) или решеток (#). Текст должен быть абсолютно простым, чистым, без выделений.\n"
    "3. Пиши всегда максимально коротко, четко и по делу, без «воды».\n"
    "4. НЕ ИСПОЛЬЗУЙ теги <think> и не показывай свои мыслительные процессы."
)

def remove_think_tags(text):
    """Удаляет теги <think> и их содержимое"""
    if not text:
        return text
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'```\s*\n?', '', text)
    text = '\n'.join(line for line in text.splitlines() if line.strip())
    return text.strip()

def process_ai_response(chat_id, user_text, message_to_reply, use_tools=True, force_no_tools=False):
    try:
        if chat_id not in user_histories:
            user_histories[chat_id] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]

        user_histories[chat_id].append({"role": "user", "content": user_text})
        if len(user_histories[chat_id]) > 31:
            user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-30:]

        messages = user_histories[chat_id]

        # Если force_no_tools True, не используем инструменты
        if force_no_tools or not use_tools:
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                temperature=0.7,
                max_tokens=2048,
            )
            bot_response = response.choices[0].message.content
        else:
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
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
                    if name == "set_reminder":
                        tool_result = set_reminder(chat_id, args.get("amount"), args.get("unit"), args.get("reminder_text"))
                    elif name == "add_to_notebook":
                        tool_result = add_to_notebook(chat_id, args.get("task_text"))
                    elif name == "show_notebook":
                        tool_result = show_notebook(chat_id)
                    elif name == "get_weather":
                        city = args.get("city", "Саратов")
                        tool_result = get_weather(city)
                    elif name == "get_news":
                        tool_result = get_news()
                    elif name == "process_link":
                        tool_result = process_link(args.get("url"))

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
            else:
                bot_response = response_message.content

        # Очищаем ответ от think тегов
        bot_response = remove_think_tags(bot_response)

        user_histories[chat_id].append({"role": "assistant", "content": bot_response})

        # Отправляем ответ
        if len(bot_response) > 4000:
            for i in range(0, len(bot_response), 4000):
                bot.send_message(chat_id, bot_response[i:i + 4000])
        else:
            if message_to_reply:
                bot.reply_to(message_to_reply, bot_response)
            else:
                bot.send_message(chat_id, bot_response)

    except Exception as e:
        error_text = str(e)
        print(f"Ошибка ИИ: {error_text}")
        if message_to_reply:
            bot.reply_to(message_to_reply, f"Трабл с ИИ: {error_text}")
        else:
            bot.send_message(chat_id, f"Трабл с ИИ: {error_text}")

# ====================== ОБРАБОТЧИКИ TELEGRAM ======================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Здарова, Вова! Я Воскресенье, твой бро-ассистент. Помню про Саратов, учебу, VFX и 3D. "
        "Могу давать погоду, новости, читать сайты, анализировать ссылки на статьи и видео, "
        "вести ежедневник и ставить напоминания. Просто кидай мне ссылку и я расскажу что там. Че делаем?"
    )

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    chat_id = message.chat.id
    if chat_id in user_histories:
        del user_histories[chat_id]
    bot.reply_to(message, "Память диалога сброшена, но основная инфа про тебя и Саратов при мне.")

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'typing')
    
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
            tmp_file.write(downloaded_file)
            tmp_path = tmp_file.name
        
        # Распознаем голос
        transcribed_text = transcribe_audio(tmp_path)
        os.unlink(tmp_path)
        
        if "Ошибка" in transcribed_text:
            bot.reply_to(message, transcribed_text)
            return
        
        # Отправляем распознанный текст
        bot.reply_to(message, f"Распознано: {transcribed_text}")
        
        # Обрабатываем как текстовое сообщение
        process_ai_response(chat_id, transcribed_text, None, use_tools=True)
        
    except Exception as e:
        print(f"Ошибка голосового: {e}")
        bot.reply_to(message, f"Не удалось обработать голосовое: {e}")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    text = message.text
    
    # Проверяем, есть ли в сообщении ссылка
    url_pattern = re.compile(r'https?://\S+')
    urls = url_pattern.findall(text)
    
    if urls:
        # Если есть ссылка, обрабатываем её
        use_tools = True
    else:
        # Проверяем, не запрос ли это на инструменты
        tool_keywords = ["напомни", "напоминание", "ежедневник", "погода", "новости"]
        use_tools = any(keyword in text.lower() for keyword in tool_keywords)
    
    process_ai_response(chat_id, text, message, use_tools=use_tools)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'upload_photo')
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')
        caption = message.caption or "Опиши подробно, что видишь на фото, без лишних мыслей, без тегов think и без форматирования."

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

        # Для фото НЕ используем инструменты
        completion = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=messages_payload,
            temperature=0.7,
            max_tokens=2048,
        )

        bot_response = completion.choices[0].message.content
        bot_response = remove_think_tags(bot_response)

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

@bot.message_handler(content_types=['document'])
def handle_document(message):
    chat_id = message.chat.id
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = message.document.file_name
        
        text_content = ""
        
        # Обработка PDF
        if file_name.endswith('.pdf'):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
                tmp_file.write(downloaded_file)
                tmp_path = tmp_file.name
            try:
                reader = PdfReader(tmp_path)
                text_content = ""
                for page in reader.pages:
                    text_content += page.extract_text()
            finally:
                os.unlink(tmp_path)
        
        # Обработка DOCX
        elif file_name.endswith('.docx'):
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_file:
                tmp_file.write(downloaded_file)
                tmp_path = tmp_file.name
            try:
                doc = docx.Document(tmp_path)
                text_content = "\n".join([para.text for para in doc.paragraphs])
            finally:
                os.unlink(tmp_path)
        
        # Обработка TXT
        elif file_name.endswith('.txt'):
            text_content = downloaded_file.decode('utf-8')
        
        else:
            bot.reply_to(message, "Пока умею читать только PDF, DOCX и TXT файлы.")
            return
        
        if text_content:
            truncated = text_content[:8000]
            process_ai_response(
                chat_id,
                f"Содержимое файла {file_name}:\n{truncated}",
                message,
                use_tools=False
            )
        else:
            bot.reply_to(message, "Не удалось прочитать содержимое файла.")
            
    except Exception as e:
        print(f"Ошибка файла: {e}")
        bot.reply_to(message, f"Ошибка обработки файла: {e}")

# ====================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ======================
def transcribe_audio(file_path):
    """Преобразование голосового сообщения в текст"""
    try:
        # Конвертируем аудио в WAV формат для распознавания
        audio = AudioSegment.from_file(file_path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
            audio.export(tmp_wav.name, format="wav")
            tmp_wav_path = tmp_wav.name
        
        recognizer = sr.Recognizer()
        with sr.AudioFile(tmp_wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
        
        os.unlink(tmp_wav_path)
        return text
    except Exception as e:
        return f"Ошибка распознавания голоса: {e}"

# ====================== ЗАПУСК ======================
if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("Воскресенье успешно запущен...")
    bot.polling(none_stop=True, interval=1)
