import os
import io
import json
import re
import uuid
import time
import logging
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from threading import Thread, RLock
from urllib.parse import urlparse

import pytz
import requests
import telebot
import yt_dlp
import docx
from bs4 import BeautifulSoup
from flask import Flask
from groq import Groq
from pypdf import PdfReader
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# ====================== ЛОГИ ======================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("bot")

# ====================== НАСТРОЙКИ ======================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
OWNER_ID = int(os.environ["OWNER_ID"]) if os.environ.get("OWNER_ID") else None
SELF_URL = os.environ.get("RENDER_EXTERNAL_URL")  # Render задаёт сам

if not TELEGRAM_TOKEN or not GROQ_API_KEY:
    raise ValueError("Нужны переменные окружения TELEGRAM_TOKEN и GROQ_API_KEY")

TZ = pytz.timezone("Etc/GMT-4")  # UTC+4 (в этой записи знак инвертирован - так и надо)
DEFAULT_CITY = "Саратов"
TEXT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "qwen/qwen3.6-27b"
WHISPER_MODEL = "whisper-large-v3-turbo"
STATE_FILE = "bot_state.json"
STATE_NAME = "bot_state.json"

client = Groq(api_key=GROQ_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=True)
scheduler = BackgroundScheduler(timezone=TZ)
lock = RLock()
histories = {}  # короткая память диалога, живёт до перезапуска; долгая память - facts в state

# ====================== СОСТОЯНИЕ ======================
# Render free стирает диск при каждом перезапуске, поэтому состояние дублируется
# в закреплённый файл в чате с ботом (внешняя база не нужна).
state = {
    "owner": OWNER_ID,
    "reminders": [],   # {id, text, kind: once|daily, at: iso, time: "HH:MM"}
    "tasks": [],       # {id, text, due: "YYYY-MM-DD"|None, done: bool}
    "facts": [],       # долгая память о Вове
    "brief": {"on": True, "time": "09:00"},
    "sync_msg": None,
}


def now():
    return datetime.now(TZ)


def parse_local(s):
    """'2026-10-23 18:30' (время Вовы, UTC+4) -> aware datetime."""
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return TZ.localize(datetime.strptime(s, fmt))
        except ValueError:
            pass
    raise ValueError(f"не понял дату '{s}', нужен формат ГГГГ-ММ-ДД ЧЧ:ММ")


def parse_clock(s):
    s = s.strip().lower()
    m = re.search(r"(\d{1,2})(?:[:.](\d{2}))?", s)
    if not m:
        raise ValueError(f"не понял время '{s}'")
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if ("вечера" in s or "pm" in s) and h < 12:
        h += 12
    if ("утра" in s or "am" in s) and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ValueError(f"некорректное время '{s}'")
    return h, mi


def save_local():
    with lock:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)


def sync_remote():
    """Кладёт файл состояния в чат, закрепляет, старый удаляет."""
    owner = state.get("owner")
    if not owner:
        return
    try:
        with lock:
            payload = json.dumps(state, ensure_ascii=False, indent=1).encode("utf-8")
            old = state.get("sync_msg")
        buf = io.BytesIO(payload)
        buf.name = STATE_NAME
        sent = bot.send_document(owner, buf, caption="Резервная копия памяти бота. Не удаляй и не откручивай.",
                                 disable_notification=True)
        bot.pin_chat_message(owner, sent.message_id, disable_notification=True)
        with lock:
            state["sync_msg"] = sent.message_id
        save_local()
        if old:
            try:
                bot.delete_message(owner, old)
            except Exception:
                pass
        logger.info("Состояние сохранено в чат")
    except Exception as e:
        logger.error(f"sync_remote: {e}")


def touch():
    """Сохранить локально сразу, в чат - через 20 секунд (чтобы не спамить)."""
    save_local()
    if state.get("owner"):
        scheduler.add_job(sync_remote, "date", run_date=now() + timedelta(seconds=20),
                          id="sync_state", replace_existing=True)


def load_state():
    loaded = None
    if OWNER_ID:
        try:
            pinned = bot.get_chat(OWNER_ID).pinned_message
            if pinned and pinned.document and pinned.document.file_name == STATE_NAME:
                fi = bot.get_file(pinned.document.file_id)
                loaded = json.loads(bot.download_file(fi.file_path).decode("utf-8"))
                logger.info("Состояние загружено из закреплённого файла")
        except Exception as e:
            logger.error(f"Не смог загрузить состояние из чата: {e}")
    if loaded is None and os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                loaded = json.load(f)
            logger.info("Состояние загружено с диска")
        except Exception as e:
            logger.error(f"Не смог загрузить локальное состояние: {e}")
    if loaded:
        state.update({k: v for k, v in loaded.items() if k in state})
    if OWNER_ID:
        state["owner"] = OWNER_ID


# ====================== РАСПИСАНИЕ ПАР ======================
# Из Project/учеба/расписание.md. Первая пара (около 8:20) и время "Соц коммуникации" неизвестны.
SCHEDULE = {
    0: [("10:00-11:35", "Социология молодежи", "лекция", "7 корп. 215"),
        ("12:05-13:40", "Социальное прогнозирование", "лекция", "7 корп. 207")],
    1: [("10:00-11:35", "Теория и практика соц. работы", "лекция", "7 корп. 304"),
        ("12:05-13:40", "Социология семьи", "лекция", "7 корп. 208"),
        ("время не знаю", "Социология коммуникации", "", "")],
    2: [("10:00-11:35", "Теории государства", "лекция", "7 корп. 201"),
        ("12:05-13:40", "Теории государства", "практика", "7 корп. 215")],
    3: [("12:05-13:40", "Социология лидерства", "практика", "7 корп. 215"),
        ("13:50-15:25", "Социология лидерства", "лекция", "7 корп. 201")],
    4: [("10:00-11:35", "Социальная антропология", "лекция", "7 корп. 207"),
        ("12:05-13:40", "Социальные технологии", "лекция", "7 корп. 207")],
    5: [("10:00-11:35", "Социология семьи", "практика", "7 корп. 201")],
    6: [],
}
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def lessons_text(day=None):
    d = day if day is not None else now().weekday()
    items = SCHEDULE.get(d, [])
    if not items:
        return f"{WEEKDAYS[d].capitalize()}: пар нет"
    lines = [f"{WEEKDAYS[d].capitalize()}:"]
    for t, name, kind, room in items:
        lines.append(f"{t} - {name}" + (f", {kind}" if kind else "") + (f", {room}" if room else ""))
    return "\n".join(lines)


# ====================== НАПОМИНАНИЯ ======================
def sorted_reminders():
    with lock:
        once = sorted([r for r in state["reminders"] if r["kind"] == "once"], key=lambda r: r["at"])
        daily = sorted([r for r in state["reminders"] if r["kind"] == "daily"], key=lambda r: r["time"])
    return once + daily


def fire_reminder(rid, late=False):
    with lock:
        rem = next((r for r in state["reminders"] if r["id"] == rid), None)
    if not rem:
        return
    text = f"⏰ Напоминание: {rem['text']}" + (" (пропущено, пока бот спал)" if late else "")
    try:
        bot.send_message(state["owner"], text)
    except Exception as e:
        logger.error(f"fire_reminder: {e}")
    if rem["kind"] == "once":
        with lock:
            state["reminders"] = [r for r in state["reminders"] if r["id"] != rid]
        touch()


def schedule_reminder(rem):
    job_id = f"rem_{rem['id']}"
    if rem["kind"] == "once":
        at = datetime.fromisoformat(rem["at"])
        if at <= now():
            scheduler.add_job(fire_reminder, "date", run_date=now() + timedelta(seconds=5),
                              args=[rem["id"], True], id=job_id, replace_existing=True)
        else:
            scheduler.add_job(fire_reminder, "date", run_date=at, args=[rem["id"]],
                              id=job_id, replace_existing=True)
    else:
        h, m = parse_clock(rem["time"])
        scheduler.add_job(fire_reminder, CronTrigger(hour=h, minute=m, timezone=TZ),
                          args=[rem["id"]], id=job_id, replace_existing=True)


def fmt_dt(iso):
    return datetime.fromisoformat(iso).astimezone(TZ).strftime("%d.%m %H:%M")


def set_reminder(amount, unit, reminder_text):
    amount = float(amount)
    unit = unit.lower()
    mult = 1 if unit.startswith("сек") else 3600 if unit.startswith("час") else 86400 if unit.startswith("д") else 60
    at = now() + timedelta(seconds=amount * mult)
    return add_once(at, reminder_text)


def set_reminder_at(datetime_local, reminder_text):
    at = parse_local(datetime_local)
    if at <= now():
        return "❌ Это время уже прошло. Уточни дату."
    return add_once(at, reminder_text)


def add_once(at, text):
    rem = {"id": uuid.uuid4().hex[:8], "text": text, "kind": "once", "at": at.isoformat()}
    with lock:
        state["reminders"].append(rem)
    schedule_reminder(rem)
    touch()
    return f"✅ Напомню {fmt_dt(rem['at'])} (UTC+4): {text}"


def set_daily_reminder(time_str, reminder_text):
    h, m = parse_clock(time_str)
    hhmm = f"{h:02d}:{m:02d}"
    with lock:
        if any(r["kind"] == "daily" and r["time"] == hhmm and r["text"] == reminder_text for r in state["reminders"]):
            return f"❌ Такое ежедневное напоминание на {hhmm} уже есть"
        rem = {"id": uuid.uuid4().hex[:8], "text": reminder_text, "kind": "daily", "time": hhmm}
        state["reminders"].append(rem)
    schedule_reminder(rem)
    touch()
    return f"✅ Каждый день в {hhmm} (UTC+4): {reminder_text}"


def list_reminders():
    items = sorted_reminders()
    if not items:
        return "📭 Напоминаний нет"
    lines = ["📋 Напоминания (время UTC+4):"]
    for i, r in enumerate(items, 1):
        when = fmt_dt(r["at"]) if r["kind"] == "once" else f"каждый день {r['time']}"
        lines.append(f"{i}. {when} - {r['text']}")
    lines.append("\nОтменить: /cancel 2, /cancel 1,3 или /cancel all")
    return "\n".join(lines)


def cancel_reminders(arg):
    """arg: 'all', номера '1,3' или кусок текста напоминания."""
    arg = str(arg).strip()
    items = sorted_reminders()
    if not items:
        return "📭 Отменять нечего - напоминаний нет"
    if arg.lower() in ("all", "все", "всё"):
        victims = items
    elif re.fullmatch(r"[\d\s,]+", arg):
        nums = [int(x) for x in re.findall(r"\d+", arg)]
        bad = [n for n in nums if not 1 <= n <= len(items)]
        if bad:
            return f"❌ Нет номера {', '.join(map(str, bad))}. Список: /reminders"
        victims = [items[n - 1] for n in nums]
    else:
        victims = [r for r in items if arg.lower() in r["text"].lower()]
        if not victims:
            return f"❌ Не нашёл напоминание по слову '{arg}'. Список: /reminders"
    ids = {r["id"] for r in victims}
    for rid in ids:
        try:
            scheduler.remove_job(f"rem_{rid}")
        except Exception:
            pass
    with lock:
        state["reminders"] = [r for r in state["reminders"] if r["id"] not in ids]
    touch()
    return "🗑 Отменил:\n" + "\n".join(f"- {r['text']}" for r in victims)


# ====================== ДЕЛА ======================
def open_tasks():
    with lock:
        t = [x for x in state["tasks"] if not x["done"]]
    return sorted(t, key=lambda x: (x["due"] is None, x["due"] or ""))


def add_task(task_text, due=None):
    due = (due or "").strip() or None
    if due:
        try:
            datetime.strptime(due, "%Y-%m-%d")
        except ValueError:
            return "❌ Срок нужен в формате ГГГГ-ММ-ДД"
    with lock:
        state["tasks"].append({"id": uuid.uuid4().hex[:8], "text": task_text, "due": due, "done": False})
    touch()
    return f"✅ Записал: {task_text}" + (f" (до {due})" if due else "")


def list_tasks():
    t = open_tasks()
    if not t:
        return "📭 Открытых дел нет"
    today = now().strftime("%Y-%m-%d")
    lines = ["📝 Дела:"]
    for i, x in enumerate(t, 1):
        mark = ""
        if x["due"]:
            mark = f" (до {x['due']}" + (", ПРОСРОЧЕНО)" if x["due"] < today else ")")
        lines.append(f"{i}. {x['text']}{mark}")
    lines.append("\nГотово: /done 2")
    return "\n".join(lines)


def complete_task(number):
    t = open_tasks()
    try:
        n = int(number)
        task = t[n - 1]
        assert n >= 1
    except Exception:
        return "❌ Нет такого номера. Список: /tasks"
    with lock:
        for x in state["tasks"]:
            if x["id"] == task["id"]:
                x["done"] = True
    touch()
    return f"✅ Готово: {task['text']}"


# ====================== ПАМЯТЬ О ВОВЕ ======================
def remember_fact(fact):
    with lock:
        if fact in state["facts"]:
            return "Это я уже помню"
        state["facts"].append(fact)
    touch()
    return f"🧠 Запомнил: {fact}"


def list_facts():
    with lock:
        f = list(state["facts"])
    if not f:
        return "🧠 Пока ничего не запомнил. Скажи: запомни, что ..."
    return "🧠 Что я помню:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(f, 1)) + "\n\nУдалить: /forget 2"


def forget_fact(number):
    try:
        n = int(number)
        assert n >= 1
        with lock:
            gone = state["facts"].pop(n - 1)
    except Exception:
        return "❌ Нет такого номера. Список: /facts"
    touch()
    return f"🗑 Забыл: {gone}"


# ====================== ВНЕШНИЕ ДАННЫЕ ======================
def get_weather(city=DEFAULT_CITY):
    try:
        r = requests.get(f"https://wttr.in/{city}?format=3&lang=ru", timeout=8)
        return r.text.strip() if r.status_code == 200 else "❌ Не удалось получить погоду"
    except Exception as e:
        return f"❌ Ошибка погоды: {e}"


def get_news():
    try:
        r = requests.get("https://news.google.com/rss?hl=ru&gl=RU&ceid=RU:ru", timeout=8)
        root = ET.fromstring(r.content)
        titles = [i.findtext("title") for i in root.iter("item")][:5]
        return "📰 Новости:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
    except Exception as e:
        return f"❌ Ошибка новостей: {e}"


def fmt_duration(sec):
    m, s = divmod(int(sec or 0), 60)
    h, m = divmod(m, 60)
    return f"{h}ч {m}м {s}с" if h else f"{m}м {s}с"


def get_video_info(url):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return "\n".join([f"🎬 {info.get('title', '?')}", f"👤 {info.get('uploader', '?')}",
                          f"⏱ {fmt_duration(info.get('duration'))}", f"👁 {info.get('view_count') or 0:,}"])
    except Exception as e:
        return f"❌ Ошибка видео: {e}"


def extract_article(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.find("h1") or soup.find("title")
        for s in soup(["script", "style"]):
            s.extract()
        text = "\n".join(l.strip() for l in soup.get_text().splitlines() if l.strip())
        return f"📄 {title.get_text().strip() if title else 'Без заголовка'}\n\n{text[:3500]}"
    except Exception as e:
        return f"❌ Ошибка статьи: {e}"


def process_link(url):
    host = urlparse(url).netloc.lower()
    if any(d in host for d in ("youtube.com", "youtu.be", "vimeo.com", "rutube.ru", "dzen.ru")):
        return "🎥 Видео:\n" + get_video_info(url)
    return "📰 Статья:\n" + extract_article(url)


# ====================== УТРЕННЯЯ СВОДКА ======================
def build_brief():
    n = now()
    today = n.strftime("%Y-%m-%d")
    parts = [f"☀️ Доброе утро, Вова! {n.strftime('%d.%m.%Y')}, {WEEKDAYS[n.weekday()]}", "", "🎓 " + lessons_text()]
    tasks = open_tasks()
    hot = [t for t in tasks if t["due"] and t["due"] <= today]
    if hot:
        parts += ["", "🔥 Горит:"] + [f"- {t['text']} (до {t['due']})" for t in hot]
    rest = len(tasks) - len(hot)
    if rest:
        parts.append(f"\nЕщё открытых дел: {rest} (/tasks)")
    daily = [r for r in sorted_reminders() if r["kind"] == "daily"]
    today_once = [r for r in sorted_reminders() if r["kind"] == "once" and r["at"][:10] == today]
    if daily or today_once:
        parts += ["", "⏰ Сегодня напомню:"]
        parts += [f"- {r['time']} {r['text']}" for r in daily]
        parts += [f"- {fmt_dt(r['at'])[6:]} {r['text']}" for r in today_once]
    parts += ["", "🌤 " + get_weather()]
    return "\n".join(parts)


def send_brief():
    if state.get("owner"):
        try:
            bot.send_message(state["owner"], build_brief())
        except Exception as e:
            logger.error(f"send_brief: {e}")


def schedule_brief():
    try:
        scheduler.remove_job("brief")
    except Exception:
        pass
    if state["brief"]["on"]:
        h, m = parse_clock(state["brief"]["time"])
        scheduler.add_job(send_brief, CronTrigger(hour=h, minute=m, timezone=TZ), id="brief")


# ====================== ИИ ======================
def fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": required or []}}}


S = {"type": "string"}
TOOLS = [
    fn("set_reminder", "Разовое напоминание через N секунд/минут/часов/дней",
       {"amount": {"type": "number"}, "unit": {"type": "string", "enum": ["секунды", "минуты", "часы", "дни"]},
        "reminder_text": S}, ["amount", "unit", "reminder_text"]),
    fn("set_reminder_at", "Разовое напоминание на конкретную дату и время по часам Вовы (UTC+4)",
       {"datetime_local": {"type": "string", "description": "ГГГГ-ММ-ДД ЧЧ:ММ"}, "reminder_text": S},
       ["datetime_local", "reminder_text"]),
    fn("set_daily_reminder", "Ежедневное напоминание в конкретное время",
       {"time": {"type": "string", "description": "ЧЧ:ММ, 24 часа"}, "reminder_text": S}, ["time", "reminder_text"]),
    fn("list_reminders", "Показать все напоминания с номерами"),
    fn("cancel_reminder", "Отменить напоминание: номера через запятую, слово из текста или 'all'",
       {"which": S}, ["which"]),
    fn("add_task", "Записать дело в ежедневник, опционально со сроком",
       {"task_text": S, "due": {"type": "string", "description": "ГГГГ-ММ-ДД или пусто"}}, ["task_text"]),
    fn("list_tasks", "Показать открытые дела"),
    fn("complete_task", "Отметить дело выполненным по номеру из списка", {"number": {"type": "integer"}}, ["number"]),
    fn("remember_fact", "Запомнить надолго важный факт о Вове, его планах, предпочтениях, проектах", {"fact": S}, ["fact"]),
    fn("forget_fact", "Забыть факт по номеру", {"number": {"type": "integer"}}, ["number"]),
    fn("get_schedule", "Расписание пар на день", {"day": {"type": "string", "description": "сегодня, завтра или день недели"}}),
    fn("get_weather", "Погода в городе", {"city": S}),
    fn("get_news", "Последние новости"),
    fn("process_link", "Прочитать статью или видео по ссылке", {"url": S}, ["url"]),
]


def schedule_tool(day=None):
    d = (day or "сегодня").lower()
    n = now().weekday()
    if d.startswith("завтра"):
        return lessons_text((n + 1) % 7)
    for i, w in enumerate(WEEKDAYS):
        if d.startswith(w[:4]):
            return lessons_text(i)
    return lessons_text(n)


def run_tool(name, a):
    try:
        if name == "set_reminder":
            return set_reminder(a["amount"], a["unit"], a["reminder_text"])
        if name == "set_reminder_at":
            return set_reminder_at(a["datetime_local"], a["reminder_text"])
        if name == "set_daily_reminder":
            return set_daily_reminder(a["time"], a["reminder_text"])
        if name == "list_reminders":
            return list_reminders()
        if name == "cancel_reminder":
            return cancel_reminders(a["which"])
        if name == "add_task":
            return add_task(a["task_text"], a.get("due"))
        if name == "list_tasks":
            return list_tasks()
        if name == "complete_task":
            return complete_task(a["number"])
        if name == "remember_fact":
            return remember_fact(a["fact"])
        if name == "forget_fact":
            return forget_fact(a["number"])
        if name == "get_schedule":
            return schedule_tool(a.get("day"))
        if name == "get_weather":
            return get_weather(a.get("city") or DEFAULT_CITY)
        if name == "get_news":
            return get_news()
        if name == "process_link":
            return process_link(a["url"])
        return f"Неизвестный инструмент {name}"
    except Exception as e:
        logger.error(f"tool {name}: {e}", exc_info=True)
        return f"❌ Ошибка: {e}"


BASE_PROMPT = """Ты Воскресенье - личный помощник Вовы в Telegram. Обращайся на "ты", взрослый партнёрский тон.
Про Вову: студент 4 курса, социология (СГУ). Подрабатывает редактором Telegram-канала про торты. Раньше делал VFX в Unreal Engine.
Через 2-3 месяца или после универа хочет найти работу. Планирует TikTok, Reels, YouTube. Часовой пояс UTC+4. Город по умолчанию - Саратов.

Подстраивай стиль под тему:
- Учёба: чётко и по делу, структура, сроки. Помогай разобрать задание, составить план ответа, конспект. Не выдумывай источники и цитаты.
- Посты для канала про торты: живой, аппетитный, тёплый тон, короткие абзацы, 2-3 варианта заголовка, мягкий призыв в конце. Только черновик - публикует Вова сам.
- Работа и карьера: конкретные шаги, резюме, письма, подготовка к собеседованиям.
- Видео: сценарий, план монтажа, субтитры, идеи для хуков.
- Бытовое и напоминалки: максимально коротко, одной-двумя строками.

Правила:
- Пиши простым языком, коротко, главное в первой строке. Без форматирования (звёздочки, решётки, обратные кавычки), только обычный текст и дефис.
- Напоминания, дела, расписание, погоду и память делай ТОЛЬКО через инструменты. Никогда не говори "поставил" или "записал", если инструмент не вызывался.
- Когда Вова просит отменить напоминание без уточнений - сначала вызови list_reminders и спроси, какое.
- Если в разговоре появился устойчивый факт о Вове (планы, предпочтения, проекты, дедлайны, люди), вызови remember_fact. Мелочи не запоминай. Пароли, коды и номера карт не запоминай никогда.
- Не знаешь - так и скажи. Не выдумывай числа, даты и имена.
- Время считай по часам Вовы (UTC+4), текущее время указано ниже."""


def system_prompt():
    n = now()
    with lock:
        facts = list(state["facts"])
    p = BASE_PROMPT + f"\n\nСейчас у Вовы: {n.strftime('%Y-%m-%d %H:%M')}, {WEEKDAYS[n.weekday()]}."
    if facts:
        p += "\n\nЧто ты помнишь о Вове:\n" + "\n".join(f"- {f}" for f in facts)
    return p


def clean(text):
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"[*`]", "", text)
    text = re.sub(r"(?m)^\s*#+\s*", "", text)
    return "\n".join(l.rstrip() for l in text.splitlines()).strip()


def llm(messages, tools=None, max_tokens=1500):
    kw = dict(model=TEXT_MODEL, messages=messages, temperature=0.6, max_tokens=max_tokens)
    if tools:
        kw.update(tools=tools, tool_choice="auto")
    return client.chat.completions.create(**kw).choices[0].message


def reply(chat_id, text, to=None):
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]
    for i, c in enumerate(chunks):
        if i == 0 and to is not None:
            bot.reply_to(to, c)
        else:
            bot.send_message(chat_id, c)


def process_ai(chat_id, user_text, to=None):
    try:
        hist = histories.setdefault(chat_id, [])
        hist.append({"role": "user", "content": user_text})
        msgs = [{"role": "system", "content": system_prompt()}] + hist[-20:]
        out = None
        for _ in range(5):  # цепочка вызовов инструментов
            m = llm(msgs, TOOLS)
            if not m.tool_calls:
                out = m.content
                break
            msgs.append({"role": "assistant", "content": m.content or "", "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in m.tool_calls]})
            for tc in m.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                logger.info(f"tool {tc.function.name} {args}")
                msgs.append({"role": "tool", "tool_call_id": tc.id, "name": tc.function.name,
                              "content": str(run_tool(tc.function.name, args))})
        out = clean(out) or "Не получилось сформулировать ответ, попробуй ещё раз."
        hist.append({"role": "assistant", "content": out})
        del hist[:-20]
        reply(chat_id, out, to)
    except Exception as e:
        logger.error(f"process_ai: {e}", exc_info=True)
        reply(chat_id, f"Ошибка: {str(e)[:150]}", to)


# ====================== ТЕЛЕГРАМ ======================
def allowed(message):
    """Бот личный: пускаем только владельца. Первый /start делает владельцем, если OWNER_ID не задан."""
    uid = message.chat.id
    if state.get("owner") is None:
        state["owner"] = uid
        touch()
    return uid == state["owner"]


def arg_of(message):
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


@bot.message_handler(commands=["start", "help"])
def cmd_start(m):
    if not allowed(m):
        return
    note = ""
    if not OWNER_ID:
        note = (f"\n\nВажно: добавь на Render переменную OWNER_ID = {m.chat.id}. "
                "Без неё после перезапуска я не смогу достать память из чата.")
    bot.reply_to(m, "Привет, Вова! Я Воскресенье.\n\n"
                    "Напоминания: /reminders, /cancel 2, /cancel all\n"
                    "Дела: /tasks, /done 2\n"
                    "Память: /facts, /forget 2, /remember текст\n"
                    "Сводка: /brief, /brieftime 9:00, /briefoff, /briefon\n"
                    "Пары: /today, /tomorrow\n"
                    "Сброс диалога: /reset\n\n"
                    "Остальное пиши как человеку: голосом, текстом, фото или файлом (PDF, DOCX, TXT)." + note)


@bot.message_handler(commands=["reminders"])
def cmd_reminders(m):
    if allowed(m):
        bot.reply_to(m, list_reminders())


@bot.message_handler(commands=["cancel"])
def cmd_cancel(m):
    if not allowed(m):
        return
    a = arg_of(m)
    if not a:
        bot.reply_to(m, list_reminders() if state["reminders"] else "📭 Отменять нечего")
        return
    bot.reply_to(m, cancel_reminders(a))


@bot.message_handler(commands=["tasks"])
def cmd_tasks(m):
    if allowed(m):
        bot.reply_to(m, list_tasks())


@bot.message_handler(commands=["done"])
def cmd_done(m):
    if allowed(m):
        bot.reply_to(m, complete_task(arg_of(m)))


@bot.message_handler(commands=["facts"])
def cmd_facts(m):
    if allowed(m):
        bot.reply_to(m, list_facts())


@bot.message_handler(commands=["forget"])
def cmd_forget(m):
    if allowed(m):
        bot.reply_to(m, forget_fact(arg_of(m)))


@bot.message_handler(commands=["remember"])
def cmd_remember(m):
    if allowed(m):
        a = arg_of(m)
        bot.reply_to(m, remember_fact(a) if a else "Напиши: /remember что запомнить")


@bot.message_handler(commands=["today"])
def cmd_today(m):
    if allowed(m):
        bot.reply_to(m, lessons_text())


@bot.message_handler(commands=["tomorrow"])
def cmd_tomorrow(m):
    if allowed(m):
        bot.reply_to(m, lessons_text((now().weekday() + 1) % 7))


@bot.message_handler(commands=["brief"])
def cmd_brief(m):
    if allowed(m):
        bot.reply_to(m, build_brief())


@bot.message_handler(commands=["brieftime"])
def cmd_brieftime(m):
    if not allowed(m):
        return
    try:
        h, mi = parse_clock(arg_of(m))
    except Exception:
        bot.reply_to(m, "Напиши так: /brieftime 9:00")
        return
    state["brief"].update(time=f"{h:02d}:{mi:02d}", on=True)
    schedule_brief()
    touch()
    bot.reply_to(m, f"✅ Сводка каждый день в {h:02d}:{mi:02d} (UTC+4)")


@bot.message_handler(commands=["briefoff", "briefon"])
def cmd_briefswitch(m):
    if not allowed(m):
        return
    state["brief"]["on"] = m.text.startswith("/briefon")
    schedule_brief()
    touch()
    bot.reply_to(m, "✅ Сводка включена" if state["brief"]["on"] else "✅ Сводка выключена")


@bot.message_handler(commands=["reset"])
def cmd_reset(m):
    if allowed(m):
        histories.pop(m.chat.id, None)
        bot.reply_to(m, "🔄 Диалог сброшен. Напоминания, дела и память о тебе целы.")


def transcribe(file_bytes):
    r = client.audio.transcriptions.create(file=("voice.ogg", file_bytes), model=WHISPER_MODEL,
                                           language="ru", response_format="text")
    return (r if isinstance(r, str) else getattr(r, "text", "")).strip()


@bot.message_handler(content_types=["voice", "audio"])
def on_voice(m):
    if not allowed(m):
        return
    bot.send_chat_action(m.chat.id, "typing")
    try:
        f = m.voice or m.audio
        data = bot.download_file(bot.get_file(f.file_id).file_path)
        text = transcribe(data)
        if not text:
            bot.reply_to(m, "❌ Не расслышал, повтори")
            return
        bot.reply_to(m, f"🎤 {text}")
        process_ai(m.chat.id, text)
    except Exception as e:
        logger.error(f"voice: {e}", exc_info=True)
        bot.reply_to(m, f"❌ Ошибка голосового: {str(e)[:150]}")


@bot.message_handler(content_types=["photo"])
def on_photo(m):
    if not allowed(m):
        return
    bot.send_chat_action(m.chat.id, "typing")
    try:
        import base64
        data = bot.download_file(bot.get_file(m.photo[-1].file_id).file_path)
        b64 = base64.b64encode(data).decode()
        caption = m.caption or "Опиши, что на фото"
        msgs = [{"role": "system", "content": system_prompt()}] + histories.get(m.chat.id, [])[-10:]
        msgs.append({"role": "user", "content": [
            {"type": "text", "text": caption},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]})
        out = clean(client.chat.completions.create(model=VISION_MODEL, messages=msgs, temperature=0.6,
                                                   max_tokens=1000).choices[0].message.content)
        out = out or "❌ Не удалось разобрать фото"
        h = histories.setdefault(m.chat.id, [])
        h += [{"role": "user", "content": f"[Фото] {caption}"}, {"role": "assistant", "content": out}]
        del h[:-20]
        reply(m.chat.id, out, m)
    except Exception as e:
        logger.error(f"photo: {e}", exc_info=True)
        bot.reply_to(m, f"❌ Ошибка фото: {str(e)[:150]}")


@bot.message_handler(content_types=["document"])
def on_document(m):
    if not allowed(m):
        return
    bot.send_chat_action(m.chat.id, "typing")
    try:
        name = (m.document.file_name or "").lower()
        data = bot.download_file(bot.get_file(m.document.file_id).file_path)
        text = ""
        if name.endswith(".pdf"):
            text = "\n".join(f"[Стр. {i + 1}] {p.extract_text() or ''}" for i, p in enumerate(PdfReader(io.BytesIO(data)).pages))
        elif name.endswith(".docx"):
            text = "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
        elif name.endswith(".txt"):
            text = data.decode("utf-8", errors="replace")
        else:
            bot.reply_to(m, "📄 Понимаю только PDF, DOCX, TXT")
            return
        if not text.strip():
            bot.reply_to(m, "❌ В файле нет текста (может, это скан)")
            return
        caption = m.caption or f"Проанализируй файл {m.document.file_name}"
        extra = "\n\n(файл длинный, прочитана только первая часть)" if len(text) > 12000 else ""
        process_ai(m.chat.id, f"{caption}\n\nСодержимое файла:\n{text[:12000]}{extra}", m)
    except Exception as e:
        logger.error(f"document: {e}", exc_info=True)
        bot.reply_to(m, f"❌ Ошибка файла: {str(e)[:150]}")


@bot.message_handler(content_types=["text"])
def on_text(m):
    if allowed(m):
        process_ai(m.chat.id, m.text, m)


# ====================== FLASK + ЗАПУСК ======================
app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!"


@app.route("/health")
def health():
    return {"status": "ok", "time": now().isoformat()}


def self_ping():
    # Render free усыпляет сервис через 15 минут без входящих запросов - будим сами себя
    if SELF_URL:
        try:
            requests.get(SELF_URL + "/health", timeout=10)
        except Exception:
            pass


def restore_jobs():
    for rem in list(state["reminders"]):
        try:
            schedule_reminder(rem)
        except Exception as e:
            logger.error(f"restore {rem}: {e}")
    schedule_brief()
    scheduler.add_job(self_ping, "interval", minutes=10, id="self_ping", replace_existing=True)


if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000))), daemon=True).start()
    scheduler.start()
    load_state()
    restore_jobs()
    try:
        bot.set_my_commands([
            telebot.types.BotCommand("reminders", "список напоминаний"),
            telebot.types.BotCommand("cancel", "отменить напоминание: /cancel 2 или all"),
            telebot.types.BotCommand("tasks", "открытые дела"),
            telebot.types.BotCommand("done", "дело сделано: /done 2"),
            telebot.types.BotCommand("brief", "сводка на сегодня"),
            telebot.types.BotCommand("today", "пары сегодня"),
            telebot.types.BotCommand("tomorrow", "пары завтра"),
            telebot.types.BotCommand("facts", "что я помню о тебе"),
            telebot.types.BotCommand("reset", "сбросить диалог"),
        ])
    except Exception as e:
        logger.error(f"set_my_commands: {e}")
    logger.info("🚀 Бот запущен")
    bot.infinite_polling(timeout=60, long_polling_timeout=60)

