# DarkJarvis - Gelişmiş Karanlık Kişilikli Telegram Botu

import os
import sys
import logging
import json
import httpx
import asyncio
import random
from datetime import time
import pytz

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode

# --- YAPI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_USER_ID", 0))

# --- LOG ---
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("DarkJarvis")

# --- GLOBAL VERİLER ---
kullanicilar = {}
kullanici_mesaj_sayisi = {}
aktif_karanlik = set()
grups = {}

# --- ARAÇLAR ---
def imzali(metin):
    return f"{metin}\n\n🤖 DarkJarvis | Kurucu: ✘𝙐𝙂𝙐𝙍"

def get_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕶 Karanlık Moda Geç", callback_data="karanlik")],
        [InlineKeyboardButton("🎮 Eğlence", callback_data="eglence")],
        [InlineKeyboardButton("🔮 Fal & Tarot", callback_data="fal")],
        [InlineKeyboardButton("🎵 Müzik Ara", callback_data="muzik")],
        [InlineKeyboardButton("📊 Etkileşim Analizi", callback_data="analiz")],
        [InlineKeyboardButton("⚙️ Admin Paneli", callback_data="admin")]
    ])

def get_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Herkese Duyuru", callback_data="duyuru")],
        [InlineKeyboardButton("📣 Grupları Yönet", callback_data="gruplar")],
        [InlineKeyboardButton("💬 Mesaj Gönder", callback_data="mesaj_gonder"), InlineKeyboardButton("📷 Fotoğraf Gönder", callback_data="foto_gonder")],
        [InlineKeyboardButton("💾 Verileri Kaydet", callback_data="veri_kaydet")],
        [InlineKeyboardButton("🧠 AI Model Seç", callback_data="ai_model")],
        [InlineKeyboardButton("◀️ Geri", callback_data="geri")]
    ])

# --- KOMUTLAR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    kullanicilar[uid] = update.effective_user.first_name
    kullanici_mesaj_sayisi[uid] = 0
    mesaj = """
💀 <b>Hey sen!</b> Dijital hayatına sıkıcı botlardan biri daha mı eklendi sandın?

Yanıldın. <b>Ben buradayım.</b> Sert, zeki ve kuralsızım.
Ben <b>DarkJarvis</b> – seni şaşırtmak için programlanmış karanlık zekân. 👁️‍🗨️

💥 <b>Neler yapabiliyorum?</b>
🎭 <b>Kişiliği olan yanıtlar:</b> Laf sokan, güldüren ve bazen sinir eden bir yapay zekâyım.
🎮 <b>Eğlence sistemleri:</b> Şaka, caps, şans oyunu, mini testler.
🔐 <b>Karanlık mod:</b> Filtreleri kaldıran, gizli anahtarla açılan özel cevap modu.
📜 <b>Yapay zekâ falı:</b> Bazen sinir bozucu doğrulukta…
📡 <b>Canlı destek:</b> Sahte ama gerçek gibi konuşan biri.
🎵 <b>Müzik:</b> Şarkı ara, çal, stalkla. (YouTube destekli)
📊 <b>Analiz:</b> Sohbet ve etkileşim istatistikleri, eğlenceli yorumlarla.
"""
    await update.message.reply_text(imzali(mesaj), parse_mode=ParseMode.HTML, reply_markup=get_keyboard())

# --- CALLBACKLER ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "karanlik":
        aktif_karanlik.add(uid)
        await query.message.reply_text(imzali("☠️ <b>Karanlık Mod</b> aktif edildi. Artık filtre yok, maskeler düştü!"), parse_mode=ParseMode.HTML)

    elif query.data == "admin":
        if uid != ADMIN_ID:
            await query.message.reply_text(imzali("🚫 Bu menü sadece kurucu ✘𝙐𝙂𝙐𝙍'a açık."), parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text(imzali("🔧 Admin paneline hoş geldin."), reply_markup=get_admin_keyboard(), parse_mode=ParseMode.HTML)

    elif query.data == "duyuru":
        await query.message.reply_text(imzali("📢 Duyuru özelliği aktif! Henüz veri girişi kısmı eklenmedi."), parse_mode=ParseMode.HTML)

    elif query.data == "gruplar":
        await query.message.reply_text(imzali("📣 Gruplar listeleniyor... (aktif kullanıcılar grubu algılandığında burada listelenecek)"), parse_mode=ParseMode.HTML)

    elif query.data == "mesaj_gonder":
        await query.message.reply_text(imzali("💬 Mesaj gönderme ekranı yakında aktif olacak. Admin panelinden içerik girilecektir."), parse_mode=ParseMode.HTML)

    elif query.data == "foto_gonder":
        await query.message.reply_text(imzali("📷 Fotoğraf gönderme ekranı yakında aktif olacak. PNG/JPG desteklenecek."), parse_mode=ParseMode.HTML)

    elif query.data == "veri_kaydet":
        await query.message.reply_text(imzali("💾 Veriler JSON dosyasına yazıldı (demo amaçlı)."), parse_mode=ParseMode.HTML)

    elif query.data == "ai_model":
        await query.message.reply_text(imzali("🧠 AI modeli: Venice/OpenRouter/OpenAI - Seçim menüsü hazırlanıyor."), parse_mode=ParseMode.HTML)

    elif query.data == "geri":
        await query.message.reply_text(imzali("◀️ Ana menüye dönüldü."), reply_markup=get_keyboard(), parse_mode=ParseMode.HTML)

    else:
        await query.message.reply_text(imzali("🚧 Bu özellik henüz yapım aşamasında."), parse_mode=ParseMode.HTML)

# --- METİN ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    kullanici_mesaj_sayisi[uid] = kullanici_mesaj_sayisi.get(uid, 0) + 1

    mesaj = update.message.text.lower()
    if uid in aktif_karanlik:
        yanitlar = [
            f"💀 '{mesaj}' mı dedin? Hay senin mantığına algoritma yazayım...",
            f"☠️ Bu ne la? Kod bile bundan daha mantıklı olurdu.",
            f"😈 Seninle uğraşmak, bilgisayar virüsü yazmaktan daha keyifli."
        ]
    else:
        yanitlar = [
            f"Hımm... {mesaj.capitalize()} diyorsun demek... Not ettim bro!",
            f"Kurucum ✘𝙐𝙂𝙐𝙍 olmasa, bu saçmalığa cevap vermezdim. Şanslısın.",
            f"Bu mu şimdi yazacak şey? Düşün, tekrar gel."
        ]
    await update.message.reply_text(imzali(random.choice(yanitlar)), parse_mode=ParseMode.HTML)

# --- MAIN ---
def main():
    if not TOKEN:
        print("TOKEN eksik")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("DarkJarvis başlatıldı!")
    app.run_polling()

if __name__ == '__main__':
    main()
