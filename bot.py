import os
from threading import Thread
from flask import Flask
import telebot
from groq import Groq

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_histories = {}

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я твой ИИ-ассистент на базе Groq (Llama 3).\nЗадай мне вопрос!")

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    chat_id = message.chat.id
    if chat_id in user_histories:
        del user_histories[chat_id]
    bot.reply_to(message, "История сброшена!")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'typing')
    
    if chat_id not in user_histories:
        user_histories[chat_id] = [{"role": "system", "content": "Ты умный и полезный ассистент."}]
    
    user_histories[chat_id].append({"role": "user", "content": message.text})
    
    if len(user_histories[chat_id]) > 11:
        user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-10:]

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=user_histories[chat_id],
            temperature=0.7,
            max_tokens=2048,
        )
        
        bot_response = completion.choices[0].message.content
        user_histories[chat_id].append({"role": "assistant", "content": bot_response})
        
        if len(bot_response) > 4000:
            for i in range(0, len(bot_response), 4000):
                bot.send_message(chat_id, bot_response[i:i+4000])
        else:
            bot.reply_to(message, bot_response, parse_mode='Markdown')
            
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка: {e}")

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    bot.polling(none_stop=True, interval=1)
