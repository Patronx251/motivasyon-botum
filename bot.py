import os
import sys
import logging
import httpx
from dotenv import load_dotenv
import asyncio
import random
from datetime import time, timedelta
import pytz
import shlex
import re
import json
import time as time_module

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode, ChatType
from telegram.error import TelegramError

# Kendi veritabanı modülümüzü import ediyoruz
import database as db

# --- Yapılandırma ve Kurulum ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=dotenv_path)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
VENICE_API_KEY = os.getenv("VENICE_API_KEY")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
LOG_FILE = os.path.join(BASE_DIR, "bot.log")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# --- YARDIMCI FONKSİYONLAR ---
def imzali(metin: str) -> str:
    return f"{metin}\n\n🤖 MOTİVASYON JARVIS | Kurucu: ✘🔍🌟🌈 Şef: Uğur"

def escape_markdown_v2(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# --- API FONKSİYONLARI ---
async def get_ai_response(prompt_messages: list, model: str = "venice-gpt-4") -> str:
    if not VENICE_API_KEY:
        return "API anahtarım eksik."
    headers = {"Authorization": f"Bearer {VENICE_API_KEY}"}
    payload = {
        "model": model,
        "messages": prompt_messages,
        "censorship": "none"
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post("https://api.venice.ai/v1/chat/completions", headers=headers, json=payload, timeout=90)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except httpx.ReadTimeout:
        logger.error("AI API hatası: İstek zaman aşımına uğradı.")
        return "Yapay zeka servisi biraz yavaş kaldı."
    except Exception as e:
        logger.error(f"AI API hatası: {e}")
        return "Yapay zeka servisimde bir sorun var."

async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        return "Hava durumu servisi için API anahtarım ayarlanmamış."
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=tr"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            if r.status_code == 200:
                d = r.json()
                city_name = escape_markdown_v2(d['name'])
                temp = escape_markdown_v2(str(d['main']['temp']))
                feels_like = escape_markdown_v2(str(d['main']['feels_like']))
                description = escape_markdown_v2(d['weather'][0]['description'].title())
                wind_speed = escape_markdown_v2(str(d['wind']['speed']))
                return (f"☀️ **{city_name}**\n🌡️ Sıcaklık: `{temp}°C` (Hissedilen: `{feels_like}°C`)\n☁️ Durum: *{description}*\n💨 Rüzgar: `{wind_speed} m/s`")
            elif r.status_code == 404:
                return f"`{escape_markdown_v2(city)}` diye bir yer haritada yok."
            else:
                return "Hava durumu servisine şu an ulaşılamıyor."
    except Exception as e:
        logger.error(f"Hava durumu API hatası: {e}")
        return "Hava durumu alınırken bir hata oluştu."

# Devamını istiyorsan yazabilirim. Bu dosya 1000+ satırlık olduğu için modülerle bölerek ilerlememiz daha sağlıklı olur.
