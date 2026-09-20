import os
import json
import base64
import re
import logging
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
import telebot
from groq import Groq
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
import docx
import tempfile
import speech_recognition as sr
from pydub import AudioSegment
from urllib.parse import urlparse
import yt_dlp
import pickle
import hashlib

# ====================== ЛОГИРОВАНИЕ ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ====================== КЛЮЧИ ======================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

logger.info(f"TELEGRAM_TOKEN найден: {bool(TELEGRAM_TOKEN)}")
logger.info(f"GROQ_API_KEY найден: {bool(GROQ_API_KEY)}")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не найден в переменных окружения!")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY не найден в переменных окружения!")

# ====================== ИНИЦИАЛИЗАЦИЯ ======================
try:
    client = Groq(api_key=GROQ_API_KEY)
    # Тестовый запрос к API
    test_response = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[{"role": "user", "content": "test"}],
        max_tokens=10
    )
    logger.info("✅ Groq API работает!")
except Exception as e:
    logger.error(f"❌ Ошибка подключения к Groq API: {e}")
    raise

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_histories = {}
user_notebooks = {}
user_reminders = {}

# ====================== СОХРАНЕНИЕ ДАННЫХ ======================
DATA_FILE = "bot_data.pkl"

def save_data():
    try:
        data = {
            'notebooks': user_notebooks,
            'reminders': user_reminders
        }
        with open(DATA_FILE, 'wb') as f:
            pickle.dump(data, f)
        logger.info("💾 Данные сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения данных: {e}")

def load_data():
    global user_notebooks, user_reminders
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'rb') as f:
                data = pickle.load(f)
                user_notebooks = data.get('notebooks', {})
                user_reminders = data.get('reminders', {})
            logger.info("📂 Данные загружены")
    except Exception as e:
        logger.error(f"Ошибка загрузки данных: {e}")

# ====================== FLASK ======================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive! "

@app.route('/health')
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ====================== ИНСТРУМЕНТЫ ======================
def trigger_reminder(chat_id, text, reminder_id=None):
    try:
        bot.send_message(chat_id, f"⏰ Напоминание: {text}")
        logger.info(f" Напоминание отправлено пользователю {chat_id}")
        if reminder_id:
            save_data()
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания: {e}")

def normalize_unit(unit):
    unit = unit.lower().strip()
    if unit in ["секунда", "секунды", "секунд", "sec", "seconds", "сек"]:
        return "секунды"
    elif unit in ["минута", "минуты", "минут", "min", "minutes", "мин"]:
        return "минуты"
    elif unit in ["час", "часа", "часов", "hour", "hours", "ч"]:
        return "часы"
    return "минуты"

def set_reminder(chat_id, amount, unit, reminder_text):
    try:
        amount = float(amount)
        unit = normalize_unit(unit)
        
        if unit == "секунды":
            delta_seconds = amount
        elif unit == "часы":
            delta_seconds = amount * 3600
        else:
            delta_seconds = amount * 60
        
        run_time = datetime.now() + timedelta(seconds=delta_seconds)
        reminder_id = hashlib.md5(f"{chat_id}_{datetime.now()}".encode()).hexdigest()[:8]
        
        scheduler.add_job(
            trigger_reminder, 
            'date', 
            run_date=run_time, 
            args=[chat_id, reminder_text, reminder_id],
            id=f"reminder_{reminder_id}"
        )
        
        logger.info(f" Разовое напоминание установлено: {amount} {unit}")
        return f"✅ Напомню через {amount} {unit}: '{reminder_text}'"
    except Exception as e:
        logger.error(f"Ошибка установки напоминания: {e}")
        return f"❌ Не получилось поставить напоминание: {e}"

def set_daily_reminder(chat_id, time_str, reminder_text):
    try:
        time_str = time_str.strip().lower()
        
        if "вечера" in time_str or "pm" in time_str:
            hour = int(re.search(r'\d+', time_str).group())
            if hour < 12:
                hour += 12
            minute = 0
        elif "утра" in time_str or "am" in time_str:
            hour = int(re.search(r'\d+', time_str).group())
            if hour == 12:
                hour = 0
            minute = 0
        elif ":" in time_str:
            parts = time_str.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        elif "." in time_str:
            parts = time_str.split(".")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        else:
            hour = int(time_str)
            minute = 0
        
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return "❌ Некорректное время. Используй формат: 23:00 или '11 вечера'"
        
        reminder_id = hashlib.md5(f"{chat_id}_{hour}_{minute}_{reminder_text}".encode()).hexdigest()[:8]
        
        if chat_id not in user_reminders:
            user_reminders[chat_id] = []
        
        for rem in user_reminders[chat_id]:
            if rem.get('id') == reminder_id:
                return f"❌ Такое напоминание уже есть на {hour:02d}:{minute:02d}"
        
        user_reminders[chat_id].append({
            'id': reminder_id,
            'hour': hour,
            'minute': minute,
            'text': reminder_text,
            'active': True
        })
        
        job_id = f"daily_{chat_id}_{reminder_id}"
        scheduler.add_job(
            trigger_reminder,
            CronTrigger(hour=hour, minute=minute),
            args=[chat_id, reminder_text, reminder_id],
            id=job_id,
            replace_existing=True
        )
        
        save_data()
        logger.info(f" Ежедневное напоминание: {hour:02d}:{minute:02d}")
        return f"✅ Ежедневное напоминание на {hour:02d}:{minute:02d}: '{reminder_text}'"
    
    except Exception as e:
        logger.error(f"Ошибка установки ежедневного напоминания: {e}")
        return f" Ошибка: {e}"

def list_daily_reminders(chat_id):
    reminders = user_reminders.get(chat_id, [])
    if not reminders:
        return "📭 Нет ежедневных напоминаний"
    
    result = "📋 Твои напоминания:\n\n"
    for i, rem in enumerate(reminders, 1):
        status = "🟢" if rem.get('active', True) else ""
        result += f"{i}. {status} {rem['hour']:02d}:{rem['minute']:02d} - {rem['text']}\n"
    
    return result

def add_to_notebook(chat_id, task_text):
    if chat_id not in user_notebooks:
        user_notebooks[chat_id] = []
    user_notebooks[chat_id].append(task_text)
    save_data()
    return f"✅ Записал: '{task_text}'"

def show_notebook(chat_id):
    tasks = user_notebooks.get(chat_id, [])
    if not tasks:
        return "📭 В ежедневнике пусто"
    tasks_list = "\n".join([f"{i+1}. {task}" for i, task in enumerate(tasks)])
    return f" Дела:\n\n{tasks_list}"

def get_weather(city="Саратов"):
    try:
        url = f"https://wttr.in/{city}?format=3&lang=ru"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.text.strip()
        return "❌ Не удалось получить погоду"
    except Exception as e:
        logger.error(f"Ошибка погоды: {e}")
        return f"❌ Ошибка: {e}"

def get_news():
    try:
        url = "https://news.google.com/rss?hl=ru&gl=RU&ceid=RU:ru"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            return "❌ Не удалось загрузить новости"
        soup = BeautifulSoup(response.content, features='xml')
        items = soup.findAll('item')[:5]
        news_list = [f"{i+1}. {item.title.text}" for i, item in enumerate(items)]
        return "📰 Новости:\n\n" + "\n".join(news_list)
    except Exception as e:
        logger.error(f"Ошибка новостей: {e}")
        return f"❌ Ошибка: {e}"

def format_duration(seconds):
    if not seconds:
        return "0с"
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}ч {minutes}м {seconds}с"
    elif minutes > 0:
        return f"{minutes}м {seconds}с"
    return f"{seconds}с"

def get_video_info(url):
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                result = [
                    f"🎬 {info.get('title', 'Неизвестно')}",
                    f"👤 {info.get('uploader', 'Неизвестно')}",
                    f" {format_duration(info.get('duration', 0))}",
                    f"👁 {info.get('view_count', 0):,} просмотров"
                ]
                if info.get('like_count'):
                    result.append(f"👍 {info.get('like_count', 0):,}")
                return "\n".join(result)
            return "❌ Не удалось получить инфо"
    except Exception as e:
        logger.error(f"Ошибка видео: {e}")
        return f"❌ Ошибка: {e}"

def extract_article_info(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = soup.find('h1') or soup.find('title')
        title_text = title.get_text().strip() if title else "Заголовок не найден"
        
        for script in soup(["script", "style"]):
            script.extract()
        
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        text = '\n'.join(chunk for chunk in lines if chunk)
        
        summary = text[:2000] + "..." if len(text) > 2000 else text
        return f" {title_text}\n\n📝 Содержание:\n{summary}"
    except Exception as e:
        logger.error(f"Ошибка статьи: {e}")
        return f"❌ Ошибка: {e}"

def detect_url_type(url):
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    video_domains = ['youtube.com', 'youtu.be', 'vimeo.com', 'rutube.ru']
    for vd in video_domains:
        if vd in domain:
            return 'video'
    return 'article'

def process_link(url):
    if detect_url_type(url) == 'video':
        return f"🎥 Видео:\n{get_video_info(url)}"
    return f" Статья:\n{extract_article_info(url)}"

# ====================== TOOLS ======================
tools = [
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Разовое напоминание через время",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "unit": {"type": "string", "enum": ["секунды", "минуты", "часы"]},
                    "reminder_text": {"type": "string"}
                },
                "required": ["amount", "unit", "reminder_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_daily_reminder",
            "description": "Ежедневное напоминание на время",
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "reminder_text": {"type": "string"}
                },
                "required": ["time", "reminder_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_daily_reminders",
            "description": "Показать напоминания"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_notebook",
            "description": "Записать дело",
            "parameters": {
                "type": "object",
                "properties": {"task_text": {"type": "string"}},
                "required": ["task_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "show_notebook",
            "description": "Показать дела"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Погода",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "Новости"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "process_link",
            "description": "Обработать ссылку",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"]
            }
        }
    }
]

scheduler = BackgroundScheduler()
scheduler.start()
load_data()

# ====================== AI ======================
SYSTEM_PROMPT = (
    "Ты Воскресенье, друг-помощник. Общайся на 'ты', просто и кратко. "
    "Пользователь: Вова, 21 год, студент из Саратова. Интересы: VFX, Unreal Engine 5, Houdini, 3D, геймдев. "
    "Правила: без форматирования (**, *, #), без тегов think, коротко и по делу."
)

def remove_think_tags(text):
    if not text:
        return ""
    text = re.sub(r'[\*_#`]', '', text)
    return '\n'.join(line for line in text.splitlines() if line.strip()).strip()

def process_ai_response(chat_id, user_text, message_to_reply):
    try:
        logger.info(f"📨 Сообщение от {chat_id}: {user_text[:50]}...")
        
        if chat_id not in user_histories:
            user_histories[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        user_histories[chat_id].append({"role": "user", "content": user_text})
        
        if len(user_histories[chat_id]) > 21:
            user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-20:]
        
        logger.info("🔄 Отправка запроса к Groq API...")
        
        # Используем стабильную модель
        response = client.chat.completions.create(
            model="llama3-8b-8192",  # Стабильная бесплатная модель
            messages=user_histories[chat_id],
            tools=tools,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=1000,
        )
        
        logger.info("✅ Ответ от API получен")
        
        response_message = response.choices[0].message
        
        if hasattr(response_message, 'tool_calls') and response_message.tool_calls:
            logger.info(f"🔧 Вызов инструментов: {len(response_message.tool_calls)}")
            user_histories[chat_id].append(response_message)
            
            for tool_call in response_message.tool_calls:
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                
                name = tool_call.function.name
                logger.info(f" Инструмент: {name}")
                
                if name == "set_reminder":
                    tool_result = set_reminder(chat_id, args.get("amount", 0), args.get("unit", "минуты"), args.get("reminder_text", ""))
                elif name == "set_daily_reminder":
                    tool_result = set_daily_reminder(chat_id, args.get("time", ""), args.get("reminder_text", ""))
                elif name == "list_daily_reminders":
                    tool_result = list_daily_reminders(chat_id)
                elif name == "add_to_notebook":
                    tool_result = add_to_notebook(chat_id, args.get("task_text", ""))
                elif name == "show_notebook":
                    tool_result = show_notebook(chat_id)
                elif name == "get_weather":
                    tool_result = get_weather(args.get("city", "Саратов"))
                elif name == "get_news":
                    tool_result = get_news()
                elif name == "process_link":
                    tool_result = process_link(args.get("url", ""))
                else:
                    tool_result = f"Неизвестный инструмент: {name}"
                
                user_histories[chat_id].append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": name,
                    "content": tool_result
                })
            
            second_response = client.chat.completions.create(
                model="llama3-8b-8192",
                messages=user_histories[chat_id],
                temperature=0.7,
                max_tokens=1000,
            )
            bot_response = second_response.choices[0].message.content
        else:
            bot_response = response_message.content
        
        bot_response = remove_think_tags(bot_response)
        
        if not bot_response:
            bot_response = "Хм, что-то пошло не так. Попробуй еще раз!"
        
        user_histories[chat_id].append({"role": "assistant", "content": bot_response})
        
        logger.info(f"💬 Ответ: {bot_response[:50]}...")
        
        if len(bot_response) > 4000:
            for i in range(0, len(bot_response), 4000):
                bot.send_message(chat_id, bot_response[i:i + 4000])
        else:
            if message_to_reply:
                bot.reply_to(message_to_reply, bot_response)
            else:
                bot.send_message(chat_id, bot_response)
                
    except Exception as e:
        logger.error(f"❌ Ошибка ИИ: {e}", exc_info=True)
        error_msg = f"Извини, произошла ошибка: {str(e)[:100]}"
        if message_to_reply:
            bot.reply_to(message_to_reply, error_msg)
        else:
            bot.send_message(chat_id, error_msg)

# ====================== HANDLERS ======================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, " Привет, Вова! Я Воскресенье. Чем помочь?")

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    chat_id = message.chat.id
    if chat_id in user_histories:
        del user_histories[chat_id]
    if chat_id in user_notebooks:
        del user_notebooks[chat_id]
    if chat_id in user_reminders:
        for rem in user_reminders[chat_id]:
            try:
                scheduler.remove_job(f"daily_{chat_id}_{rem['id']}")
            except:
                pass
        del user_reminders[chat_id]
    save_data()
    bot.reply_to(message, "🔄 Память, ежедневник и напоминания сброшены")
    logger.info(f"🔄 Сброшены данные для {chat_id}")

@bot.message_handler(commands=['reminders'])
def show_reminders_command(message):
    result = list_daily_reminders(message.chat.id)
    bot.reply_to(message, result)

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    chat_id = message.chat.id
    logger.info(f"🎤 Голосовое от {chat_id}")
    bot.send_chat_action(chat_id, 'typing')
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
            tmp_file.write(downloaded_file)
            tmp_path = tmp_file.name
        
        transcribed_text = transcribe_audio(tmp_path)
        os.unlink(tmp_path)
        
        if "Ошибка" in transcribed_text:
            bot.reply_to(message, transcribed_text)
            return
        
        bot.reply_to(message, f"🎤 Распознано: {transcribed_text}")
        process_ai_response(chat_id, transcribed_text, None)
    except Exception as e:
        logger.error(f"Ошибка голосового: {e}")
        bot.reply_to(message, f" Ошибка обработки голосового: {e}")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    process_ai_response(message.chat.id, message.text, message)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    logger.info(f"🖼 Фото от {chat_id}")
    bot.send_chat_action(chat_id, 'upload_photo')
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')
        caption = message.caption or "Опиши фото"
        
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
        
        # Используем vision модель
        completion = client.chat.completions.create(
            model="llama-3.2-90b-vision-preview",
            messages=messages_payload,
            temperature=0.7,
            max_tokens=800,
        )
        
        bot_response = remove_think_tags(completion.choices[0].message.content)
        
        if not bot_response:
            bot_response = " Не удалось распознать"
        
        user_histories[chat_id].append({"role": "user", "content": f"[Фото]"})
        user_histories[chat_id].append({"role": "assistant", "content": bot_response})
        
        bot.reply_to(message, bot_response)
            
    except Exception as e:
        logger.error(f"Ошибка фото: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    chat_id = message.chat.id
    logger.info(f"📄 Файл от {chat_id}")
    bot.send_chat_action(chat_id, 'upload_document')
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = message.document.file_name
        text_content = ""
        
        if file_name.endswith('.pdf'):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
                tmp_file.write(downloaded_file)
                tmp_path = tmp_file.name
            try:
                reader = PdfReader(tmp_path)
                for i, page in enumerate(reader.pages):
                    text_content += f"\n[Стр. {i+1}] {page.extract_text()}"
            finally:
                os.unlink(tmp_path)
        elif file_name.endswith('.docx'):
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_file:
                tmp_file.write(downloaded_file)
                tmp_path = tmp_file.name
            try:
                doc = docx.Document(tmp_path)
                text_content = "\n".join([para.text for para in doc.paragraphs])
            finally:
                os.unlink(tmp_path)
        elif file_name.endswith('.txt'):
            text_content = downloaded_file.decode('utf-8')
        else:
            bot.reply_to(message, "📄 Поддерживаю: PDF, DOCX, TXT")
            return
        
        if text_content:
            truncated = text_content[:8000]
            caption = message.caption or f"Проанализируй {file_name}"
            process_ai_response(chat_id, f"{caption}\n\n{truncated}", message)
        else:
            bot.reply_to(message, "❌ Файл пустой")
            
    except Exception as e:
        logger.error(f"Ошибка файла: {e}", exc_info=True)
        bot.reply_to(message, f" Ошибка: {e}")

def transcribe_audio(file_path):
    try:
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
    except sr.UnknownValueError:
        return "❌ Не удалось распознать речь"
    except Exception as e:
        return f"❌ Ошибка: {e}"

if __name__ == '__main__':
    logger.info("🚀 Запуск бота...")
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("✅ Flask запущен")
    logger.info("📋 Команды: /reminders, /reset")
    bot.polling(non_stop=True, interval=1, timeout=60)
