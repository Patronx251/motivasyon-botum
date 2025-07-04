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
def imzali(metin: str) -> str: return f"{metin}\n\n🤖 MOTİVASYON JARVIS | Kurucu: ✘𝙐𝙂𝙐𝙍"
def escape_markdown_v2(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# --- API FONKSİYONLARI ---
async def get_ai_response(prompt_messages: list, model: str = "venice-gpt-4") -> str:
    if not VENICE_API_KEY: return "API anahtarım eksik."
    headers = {"Authorization": f"Bearer {VENICE_API_KEY}"}; payload = {"model": model, "messages": prompt_messages, "censorship": "none"}
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post("https://api.venice.ai/v1/chat/completions", headers=headers, json=payload, timeout=90)
            r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
    except httpx.ReadTimeout:
        logger.error("AI API hatası: İstek zaman aşımına uğradı."); return "Yapay zeka servisi biraz yavaş kaldı."
    except Exception as e:
        logger.error(f"AI API hatası: {e}"); return "Yapay zeka servisimde bir sorun var."

async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY: return "Hava durumu servisi için API anahtarım ayarlanmamış."
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=tr"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            if r.status_code == 200:
                d = r.json(); city_name = escape_markdown_v2(d['name']); temp = escape_markdown_v2(str(d['main']['temp'])); feels_like = escape_markdown_v2(str(d['main']['feels_like'])); description = escape_markdown_v2(d['weather'][0]['description'].title()); wind_speed = escape_markdown_v2(str(d['wind']['speed']))
                return (f"☀️ **{city_name}**\n🌡️ Sıcaklık: `{temp}°C` (Hissedilen: `{feels_like}°C`)\n☁️ Durum: *{description}*\n💨 Rüzgar: `{wind_speed} m/s`")
            elif r.status_code == 404: return f"`{escape_markdown_v2(city)}` diye bir yer haritada yok."
            else: return "Hava durumu servisine şu an ulaşılamıyor."
    except Exception as e: logger.error(f"Hava durumu API hatası: {e}"); return "Hava durumu alınırken bir hata oluştu."

# --- ConversationHandler Durumları ---
(A_SELECT_GROUP, A_SHOW_SETTINGS) = range(2)
(B_ASK_PHOTO, B_ASK_CAPTION, B_CONFIRM) = range(2, 5)
(C_ASK_CITY, C_ASK_POLL, C_ASK_PLAN) = range(5, 8)

# --- MENÜLER ---
def get_main_menu_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("📌 Ne İşe Yarıyorum?", callback_data="cb_nedir")], [InlineKeyboardButton("🎮 Eğlence & Planlama", callback_data="menu_eglence")], [InlineKeyboardButton("⚙️ Yardımcı Komutlar", callback_data="menu_diger")], [InlineKeyboardButton("💬 Canlı Destek", url=f"tg://user?id={ADMIN_USER_ID}")], ])
def get_eglence_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("😂 Fıkra Anlat", callback_data="ai_fikra"), InlineKeyboardButton("📜 Şiir Oku", callback_data="ai_siir")], [InlineKeyboardButton("🎲 Zar At", callback_data="cmd_zar"), InlineKeyboardButton("📊 Anket Oluştur", callback_data="cmd_anket")], [InlineKeyboardButton("🗓️ Benim İçin Plan Yap!", callback_data="cmd_planla_menu")], [InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")]])
def get_diger_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("👤 Profilim", callback_data="cmd_profil"), InlineKeyboardButton("✨ İlham Verici Söz", callback_data="ai_alinti")], [InlineKeyboardButton("🌦️ Hava Durumu", callback_data="cmd_hava")],[InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")]])
def get_admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 İstatistikler", callback_data="admin_stats")],
        [InlineKeyboardButton("⚙️ Grup Ayarları", callback_data="admin_settings_start")],
        [InlineKeyboardButton("📣 Resimli Duyuru", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("🔄 Botu Yeniden Başlat", callback_data="admin_restart")]
    ])

# --- GENEL KULLANICI FONKSİYONLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_or_create_user(update.effective_user.id, update.effective_user.first_name)
    text = f"Merhaba <b>{user['first_name']}</b>, ben <b>Motivasyon Jarvis</b>. Yine ne istiyorsun bakalım? 😉"
    if update.callback_query: await update.callback_query.edit_message_text(imzali(text), reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    else: await update.message.reply_text(imzali(text), reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, keyboard: InlineKeyboardMarkup):
    query = update.callback_query; await query.answer(); await query.edit_message_text(imzali(text), reply_markup=keyboard, parse_mode=ParseMode.HTML)
async def show_eglence_menu(update, context): await show_menu(update, context, "Eğlenmeye mi geldin? İyi seçim. 😎 İşte planlama ve eğlence oyuncaklarım:", get_eglence_menu_keyboard())
async def show_diger_menu(update, context): await show_menu(update, context, "Meraklısın bakıyorum... İşte diğer marifetlerim:", get_diger_menu_keyboard())
async def show_nedir(update, context): await show_menu(update, context, "Ben kim miyim? Senin dijital baş belan... Ama en çok kurucum Uğur'un eseriyim. ✨", get_main_menu_keyboard())
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check if we are in a callback query context
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("İşlem iptal edildi.")
    else:
        await update.message.reply_text("İşlem iptal edildi.")
    context.user_data.clear()
    return ConversationHandler.END

# --- EYLEM FONKSİYONLARI (AI, KOMUTLAR) ---
async def ai_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, system_prompt: str, user_prompt: str):
    query = update.callback_query; await query.answer("İki dakika bekle, ilham perilerimle toplantıdayım...");
    prompt = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    response = await get_ai_response(prompt)
    await query.message.reply_text(imzali(response), parse_mode=ParseMode.HTML)
async def ai_fikra_anlat(update, context): await ai_handler(update, context, "Sen komik, zeki ve biraz da laf sokan bir stand-up komedyenisin. Modern ve kısa bir fıkra anlat.", "Anlat bakalım bir fıkra, güldür beni.")
async def ai_siir_oku(update, context): await ai_handler(update, context, "Sen modern, duygusal ama aynı zamanda biraz da esprili bir şairsin. Kullanıcının isteğine göre kısa, etkileyici bir şiir yaz.", "Bana bir şiir patlat.")
async def ai_alinti_gonder(update, context): await ai_handler(update, context, "Sen hayatın içinden konuşan, bilge ama aynı zamanda 'giderli' bir abisin/ablasın. Hem ilham veren hem de 'akıllı ol' diyen bir söz söyle.", "Bana gaz ver biraz.")
async def cmd_zar_at(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); await context.bot.send_dice(chat_id=query.message.chat_id)
async def cmd_profil_goster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.message.reply_text(imzali(f"👤 Profilin: {query.from_user.first_name}. Benden daha havalı olamazsın, boşuna uğraşma. 😉"))

# --- CONVERSATION HANDLER FONKSİYONLARI ---
async def weather_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); await query.edit_message_text("Hangi şehrin hava durumunu merak ediyorsun?"); return C_ASK_CITY
async def weather_command_get(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    city = update.message.text; await update.message.reply_text("Bakıyorum hemen..."); weather_report = await get_weather(city)
    await update.message.reply_text(imzali(weather_report), parse_mode=ParseMode.MARKDOWN_V2); return ConversationHandler.END

async def poll_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); await query.edit_message_text('Anketini şu formatta yaz:\n`"Soru" "Seçenek 1" "Seçenek 2" ...`'); return C_ASK_POLL
async def poll_command_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        parts = shlex.split(update.message.text); question, options = parts[0], parts[1:]
        if len(options) < 2 or len(options) > 10: await update.message.reply_text("En az 2, en fazla 10 seçenek olmalı."); return C_ASK_POLL
        await context.bot.send_poll(update.effective_chat.id, question, options, is_anonymous=False)
    except Exception: await update.message.reply_text(f"Hatalı format! Örnek:\n`/anket \"En iyi takım?\" \"GS\" \"FB\"`")
    return ConversationHandler.END

async def plan_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Harika! Ne hakkında bir plan yapmamı istersin?\nÖrnek: `Cumartesi akşamı arkadaşlarla dışarı çıkmak için fikir ver`")
    return C_ASK_PLAN
async def plan_command_get_and_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_request = update.message.text; user_memory = db.get_user_memory(update.effective_user.id)
    system_prompt = """Sen bir planlama uzmanı yapay zekasısın. Kullanıcının isteği doğrultusunda, detaylı ve ilham verici bir plan öner. Planını kısa ve etkileyici olarak sun."""
    await update.message.reply_text("Zihin işlemcilerimi çalıştırıyorum... 🤖")
    response = await get_ai_response([{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Kullanıcının planlama isteği: {user_request}"}])
    await update.message.reply_text(imzali(response)); return ConversationHandler.END

# --- GRUP YÖNETİMİ & OTOMATİK EYLEMLER ---
async def record_activity_and_get_settings(update: Update) -> dict | None:
    if not update.message or update.effective_chat.type == ChatType.PRIVATE: return None
    group = db.get_or_create_group(update.effective_chat.id, update.effective_chat.title)
    db.record_user_activity(update.effective_chat.id, update.effective_user.id, update.message.date.timestamp())
    return group.get('settings', db.DEFAULT_SETTINGS)

async def welcome_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = await record_activity_and_get_settings(update)
    if not settings or not settings.get('welcome_message', True): return
    for member in update.message.new_chat_members:
        if member.is_bot: continue; db.get_or_create_user(member.id, member.first_name)
        system_prompt = "Sen bir grubun komik ve 'abisi' konumundaki yapay zekasısın..."; user_prompt = f"Gruba '{member.first_name}' adında yeni bir üye katıldı..."
        welcome_text = await get_ai_response([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]); await update.message.reply_text(imzali(welcome_text))

async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = await record_activity_and_get_settings(update)
    if not settings or not settings.get('goodbye_message', True): return
    member = update.message.left_chat_member
    if member and not member.is_bot:
        system_prompt = "Sen bir grubun komik ve 'giderli' yapay zekasısın..."; user_prompt = f"Gruptan '{member.first_name}' adında bir üye ayrıldı..."
        goodbye_text = await get_ai_response([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]); await context.bot.send_message(chat_id=update.effective_chat.id, text=imzali(goodbye_text))

async def comment_on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = await record_activity_and_get_settings(update)
    if not settings or not settings.get('image_comment', True): return
    try:
        file_id = update.message.photo[-1].file_id; file = await context.bot.get_file(file_id); photo_url = file.file_path
        system_prompt = "Sen alaycı ve komik bir sanat eleştirmenisin..."
        prompt_messages = [{"role": "user", "content": [{"type": "text", "text": "Bu resim hakkında ne düşünüyorsun?"}, {"type": "image_url", "image_url": {"url": photo_url}}]}]
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
        response = await get_ai_response(prompt_messages, model="google/gemini-pro-vision")
        await update.message.reply_text(imzali(response))
    except Exception as e: logger.error(f"Resim yorumlama hatası: {e}")

async def comment_on_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = await record_activity_and_get_settings(update)
    if not settings or not settings.get('sticker_comment', True): return
    if update.message.sticker and update.message.sticker.emoji:
        emoji
