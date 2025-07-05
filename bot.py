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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ContextTypes
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

# --- ARAÇLAR ---
def imzali(metin):
    return f"{metin}\n\n🤖 DarkJarvis | Kurucu: ✘𝙐𝙂𝙐𝙍"

def get_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕶 Karanlık Moda Geç", callback_data="karanlik")],
        [InlineKeyboardButton("🎮 Eğlence", callback_data="eglence")],
        [InlineKeyboardButton("🔮 Fal & Tarot", callback_data="fal")],
        [InlineKeyboardButton("🎵 Müzik Ara", callback_data="muzik")],
        [InlineKeyboardButton("📊 Etkileşim Analizi", callback_data="analiz")]
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
        await query.edit_message_text(imzali("☠️ <b>Karanlık Mod</b> aktif edildi. Artık filtre yok, maskeler düştü!"), parse_mode=ParseMode.HTML)

    elif query.data == "eglence":
        metin = random.choice([
            "😂 Doktor: Sigarayı bırakman lazım. Hasta: Yerine ne içeyim hocam?",
            "🤣 Hayat kısa, gülümsemeye çalış... ama çok da değil, saçma olur.",
            "😎 Random şaka: Neden bilgisayar asla acıkmaz? Çünkü hep çerez var."
        ])
        await query.edit_message_text(imzali(metin), parse_mode=ParseMode.HTML)

    elif query.data == "fal":
        yorum = random.choice([
            "✨ Bugün biri seni stalklayabilir. Ama kötü niyetli değil, meraklı. 😏",
            "🔮 Para konusu gündeme geliyor. Ya çok kazanacaksın ya çok harcayacaksın.",
            "💌 Kalp işaretleri artıyor. Eski bir kişi mesaj atabilir."
        ])
        await query.edit_message_text(imzali(f"Fal kartın: {yorum}"), parse_mode=ParseMode.HTML)

    elif query.data == "muzik":
        await query.edit_message_text(imzali("🎵 Müzik özelliği yakında aktif olacak! YouTube'dan şarkı arayıp link vereceğim. (API'siz scraping destekli)"), parse_mode=ParseMode.HTML)

    elif query.data == "analiz":
        toplam = sum(kullanici_mesaj_sayisi.values())
        en_aktif = max(kullanici_mesaj_sayisi.items(), key=lambda x: x[1], default=("Kimse", 0))
        analiz = f"📊 Sohbet Verileri:\n- Toplam Mesaj: {toplam}\n- En Aktif: {kullanicilar.get(en_aktif[0], 'Bilinmeyen')} ({en_aktif[1]} mesaj)"
        await query.edit_message_text(imzali(analiz), parse_mode=ParseMode.HTML)

# --- METİN ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    kullanici_mesaj_sayisi[uid] = kullanici_mesaj_sayisi.get(uid, 0) + 1

    mesaj = update.message.text.lower()
    if uid in aktif_karanlik:
        yanitlar = [
            "Heh, işte beklediğim kirli sorulardan biri...", 
            "Bu soruya vereceğim cevabı sansürlesem daha iyi olurdu ama... işte bu! 💀",
            "DarkJarvis filtresiz konuşur, sen sadece dinle."
        ]
    else:
        yanitlar = [
            "Hmm... Bu konuda bilgi verebilirim ama önce biraz eğlenelim mi? 😏",
            "Yine mi bu soru? Neyse, bu seferlik cevaplayayım...",
            "Kurucum ✘𝙐𝙂𝙐𝙍 olmasa, bu saçma sorulara cevap vermem. 😎"
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
