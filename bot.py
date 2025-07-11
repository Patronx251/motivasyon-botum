import os
import sys
import logging
import json
import httpx
from dotenv import load_dotenv
import asyncio
import random
from datetime import time
import pytz
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode, ChatType
from telegram.error import TelegramError

# --- Yapılandırma ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=dotenv_path)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_USER_ID", 0))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
VENICE_API_KEY = os.getenv("VENICE_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") # YENİ
DEFAULT_AI_MODEL = os.getenv("DEFAULT_AI_MODEL", "openrouter")
current_model = DEFAULT_AI_MODEL

USERS_FILE = os.path.join(BASE_DIR, "users_data.json"); GROUPS_FILE = os.path.join(BASE_DIR, "groups.json"); LOG_FILE = os.path.join(BASE_DIR, "bot.log")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("DarkJarvis")
users, groups, user_message_counts, user_words, dark_mode_users = {}, {}, {}, {}, set()
class User:
    def __init__(self, name=""): self.name = name

def save_json(data, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"{os.path.basename(filename)} kaydedildi.")
    except Exception as e: logger.error(f"{os.path.basename(filename)} kayıt hatası: {e}", exc_info=True)
def load_data():
    global users, groups, current_model, user_message_counts, user_words
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f: 
                raw_users = json.load(f); users = {int(k): User(v.get('name')) for k, v in raw_users.items()}; user_message_counts = {int(k): v.get('message_count', 0) for k, v in raw_users.items()}; user_words = {int(k): v.get('words', {}) for k, v in raw_users.items()}
        if os.path.exists(GROUPS_FILE):
            with open(GROUPS_FILE, "r", encoding="utf-8") as f: groups = {int(k): v for k, v in json.load(f).items()}
    except (json.JSONDecodeError, UnicodeDecodeError) as e: logger.warning(f"Veri dosyası okunurken hata ({e}). Yeni dosyalar oluşturulacak."); users, groups, user_message_counts, user_words = {}, {}, {}, {}
    current_model = os.getenv("DEFAULT_AI_MODEL", "openrouter")
    logger.info(f"{len(users)} kullanıcı, {len(groups)} grup yüklendi. Aktif AI: {current_model.upper()}")
def get_or_create_user(uid, name):
    if uid not in users: users[uid] = User(name); user_message_counts[uid] = 0; user_words[uid] = {}
    return users.get(uid)
def save_all_data(): users_with_data = {uid: {**user.__dict__, 'message_count': user_message_counts.get(uid, 0), 'words': user_words.get(uid, {})} for uid, user in users.items()}; save_json(users_with_data, USERS_FILE); save_json(groups, GROUPS_FILE)
def imzali(metin): return f"{metin}\n\n🤖 DarkJarvis | Kurucu: ✘𝙐𝙂𝙐𝙍"

async def _get_openrouter_response(prompts):
    if not OPENROUTER_API_KEY: return "OpenRouter API anahtarı eksik."
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}; payload = {"model": "google/gemini-flash-1.5", "messages": prompts}
    async with httpx.AsyncClient() as c: r = await c.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=40); r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
async def _get_venice_response(prompts):
    if not VENICE_API_KEY: return "Venice AI API anahtarı eksik."
    url = "https://api.venice.ai/v1/chat/completions"; headers = {"Authorization": f"Bearer {VENICE_API_KEY}"}
    payload = {"model": "venice-gpt-4", "messages": prompts}
    async with httpx.AsyncClient() as c: r = await c.post(url, headers=headers, json=payload, timeout=40); r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
async def _get_google_ai_studio_response(prompts):
    if not GOOGLE_API_KEY: return "Google AI Studio API anahtarı eksik."
    # Google API'si 'messages' yerine 'contents' ve farklı bir format kullanır.
    formatted_contents = [{"parts": [{"text": p["content"]}], "role": p["role"]} for p in prompts]
    # Sistem mesajı 'role' olarak desteklenmiyor, ilk mesaja ekliyoruz.
    system_prompt_text = ""
    if formatted_contents[0]["role"] == "system":
        system_prompt_text = formatted_contents.pop(0)["parts"][0]["text"]
        formatted_contents[0]["parts"][0]["text"] = system_prompt_text + "\n\nKULLANICI MESAJI:\n" + formatted_contents[0]["parts"][0]["text"]
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro-latest:generateContent?key={GOOGLE_API_KEY}"
    payload = {"contents": formatted_contents}
    async with httpx.AsyncClient() as c:
        r = await c.post(url, json=payload, timeout=60); r.raise_for_status(); return r.json()["candidates"][0]["content"]["parts"][0]["text"]
async def get_ai_response(prompts):
    try:
        logger.info(f"AI isteği gönderiliyor. Aktif Model: {current_model.upper()}")
        if current_model == "venice": return await _get_venice_response(prompts)
        if current_model == "google": return await _get_google_ai_studio_response(prompts)
        return await _get_openrouter_response(prompts)
    except httpx.HTTPStatusError as e: logger.error(f"AI API'den HTTP hatası ({current_model}): {e.response.status_code} - {e.response.text}"); return f"API sunucusundan bir hata geldi ({e.response.status_code}). Model adı veya API anahtarında sorun olabilir."
    except Exception as e: logger.error(f"AI API genel hatası ({current_model}): {e}", exc_info=True); return "Beynimde bir kısa devre oldu galiba, sonra tekrar dene."

# --- MENÜLER VE DİĞER FONKSİYONLAR ---
def get_main_menu_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("🕶 Karanlık Mod", callback_data="dark_mode_on"), InlineKeyboardButton("💡 Normal Mod", callback_data="dark_mode_off")], [InlineKeyboardButton("🎮 Eğlence", callback_data="menu_eglence")], [InlineKeyboardButton("🔮 Fal & Tarot", callback_data="menu_fal")], [InlineKeyboardButton("📊 Etkileşim Analizi", callback_data="menu_analiz")], [InlineKeyboardButton("⚙️ Admin Paneli", callback_data="admin_panel_main")] ])
def get_eglence_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("😂 Şaka İste", callback_data="ai_saka")], [InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")]])
def get_admin_menu_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("📊 İstatistikler", callback_data="admin_stats")], [InlineKeyboardButton("📢 Grupları Yönet", callback_data="admin_list_groups")], [InlineKeyboardButton("📣 Herkese Duyuru", callback_data="admin_broadcast_ask")], [InlineKeyboardButton(f"🧠 AI Model ({current_model.upper()})", callback_data="admin_select_ai")], [InlineKeyboardButton("💾 Verileri Kaydet", callback_data="admin_save")], [InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")] ])
def get_ai_model_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("Google (1.5 Pro)", callback_data="ai_model_google")], [InlineKeyboardButton("Google (OpenRouter)", callback_data="ai_model_openrouter")], [InlineKeyboardButton("Venice AI (GPT-4)", callback_data="ai_model_venice")], [InlineKeyboardButton("◀️ Geri", callback_data="admin_panel_main")]])
GET_GROUP_MSG, GET_BROADCAST_MSG, BROADCAST_CONFIRM = range(3)
async def start(update, context): user = update.effective_user; get_or_create_user(user.id, user.first_name); mesaj = """💀 <b>Hey sen!</b> Dijital hayatına sıkıcı botlardan biri daha mı eklendi sandın? Yanıldın. <b>Ben buradayım.</b> Ben <b>DarkJarvis</b>. 👁️‍🗨️"""; reply_markup = get_main_menu_keyboard(); await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)(imzali(mesaj), parse_mode=ParseMode.HTML, reply_markup=reply_markup)
async def show_menu(update, text, keyboard): await update.callback_query.edit_message_text(imzali(text), reply_markup=keyboard, parse_mode=ParseMode.HTML)
async def show_eglence_menu(update, context): await show_menu(update, "Canın sıkıldı demek... Bakalım seni ne kadar güldürebileceğim.", get_eglence_menu_keyboard())
async def show_analiz_menu(update, context): uid = update.effective_user.id; count = user_message_counts.get(uid, 0); words = user_words.get(uid, {}); top_words = Counter(words).most_common(5); top_words_text = "\n".join([f"  - `{word}` ({count} kez)" for word, count in top_words]) if top_words else "Henüz yeterince veri yok."; text = f"📊 Seninle tam **{count}** defa muhatap olmuşum.\n\nEn çok kullandığın kelimeler:\n{top_words_text}\n\nFena değil, takıntılı olmaya başlıyorsun. 😉"; await show_menu(update, text, get_main_menu_keyboard())
async def set_dark_mode(update, context, is_on: bool): uid = update.effective_user.id; (dark_mode_users.add(uid) if is_on else dark_mode_users.discard(uid)); await show_menu(update, "☠️ <b>Karanlık Mod</b> aktif. Artık filtre yok, maskeler düştü!" if is_on else "💡 Normal moda dönüldü. Yine sıkıcı olacağım. (Şaka şaka... 😏)", get_main_menu_keyboard())
async def ai_action_handler(update, context, system_prompt: str, user_prompt: str): await update.callback_query.answer("Zihnimi kurcalıyorum, bekle..."); await update.callback_query.message.reply_text(imzali(await get_ai_response([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])), parse_mode=ParseMode.HTML)
async def ai_fal_tarot(update, context): await ai_action_handler(update, context, "Sen gizemli ve alaycı bir falcısın. Kullanıcının geleceği hakkında hem doğru gibi görünen hem de onunla dalga geçen kısa bir yorum yap. Tarot kartları, yıldızlar gibi metaforlar kullan.", "Bana bir fal bak.")
async def ai_saka_iste(update, context): await ai_action_handler(update, context, "Sen laf sokan, kara mizahı seven bir komedyensin. Kullanıcıyı güldürecek ama aynı zamanda 'buna gülsem mi ağlasam mı' dedirtecek bir şaka yap.", "Bana bir şaka yap.")
async def admin_panel(update, context):
    if update.effective_user.id != ADMIN_ID:
        if update.callback_query: await update.callback_query.answer("🚫 Burası sana yasak bölge.", show_alert=True)
        return
    text = "🔐 Kurucu paneline hoş geldin!"; reply_markup = get_admin_menu_keyboard()
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else: await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
async def show_ai_model_menu(update, context): await show_menu(update, f"Aktif AI: <b>{current_model.upper()}</b>\nYeni modeli seç:", get_ai_model_menu_keyboard())
async def set_ai_model(update, context): global current_model; current_model = update.callback_query.data.split('_')[-1]; logger.info(f"AI modeli değiştirildi: {current_model.upper()}"); await update.callback_query.answer(f"✅ AI modeli {current_model.upper()} olarak ayarlandı!", show_alert=True); await admin_panel(update, context)
async def handle_text(update, context):
    uid = update.effective_user.id; user_message = update.message.text
    get_or_create_user(uid, update.effective_user.first_name)
    user_message_counts[uid] = user_message_counts.get(uid, 0) + 1
    words = user_message.lower().split()
    if uid not in user_words: user_words[uid] = {}
    for word in words:
        if len(word) > 3: user_words[uid][word] = user_words[uid].get(word, 0) + 1
    base_prompt = """# ... (Önceki mesajdaki kişilik prompt'u)"""; dark_mode_prompt_extension = """# KARANLIK MOD KİŞİLİĞİ\n- **Ayar Verme Uzmanı:**..."""
    system_prompt = base_prompt + (dark_mode_prompt_extension if uid in dark_mode_users else "")
    prompt = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
    await context.bot.send_chat_action(update.effective_chat.id, 'typing'); await update.message.reply_text(imzali(await get_ai_response(prompt)))
async def send_morning_message(context):
    if not groups: return
    prompt = random.choice(["Gruptakileri uyandırmak için komik bir 'günaydın' mesajı yaz.", "Gruba 'Hadi uyanın, daha faturaları ödeyeceğiz!' temalı, esprili bir günaydın mesajı yaz."])
    message = await get_ai_response([{"role": "system", "content": "Sen komik ve insanlarla uğraşmayı seven bir asistansın."}, {"role": "user", "content": prompt}])
    for gid in groups:
        try: await context.bot.send_message(gid, imzali(f"☀️ GÜNAYDIN EKİP! ☀️\n\n{message}")); await asyncio.sleep(1)
        except Exception as e: logger.error(f"Gruba ({gid}) günaydın mesajı gönderilemedi: {e}")
async def send_daily_rant(context):
    if not groups: return
    prompt = "Günün atarını veya lafını içeren, hem düşündürücü hem de komik, kısa bir tweet tarzı mesaj yaz."
    message = await get_ai_response([{"role": "system", "content": "Sen hayatla dalga geçen, bilge bir sokak filozofusun."}, {"role": "user", "content": prompt}])
    for gid in groups:
        try: await context.bot.send_message(gid, imzali(f"🔥 GÜNÜN ATARI 🔥\n\n{message}")); await asyncio.sleep(1)
        except Exception as e: logger.error(f"Gruba ({gid}) günün atarı gönderilemedi: {e}")
def main():
    if not TOKEN: logger.critical("TOKEN eksik!"); return
    load_data(); app = Application.builder().token(TOKEN).build()
    jq = app.job_queue; turkey_tz = pytz.timezone("Europe/Istanbul")
    jq.run_daily(send_morning_message, time=time(hour=9, minute=0, tzinfo=turkey_tz), name="gunaydin"); jq.run_daily(send_daily_rant, time=time(hour=13, minute=37, tzinfo=turkey_tz), name="gunun_atari")
    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(start, pattern="^menu_main$")); app.add_handler(CallbackQueryHandler(show_eglence_menu, pattern="^menu_eglence$")); app.add_handler(CallbackQueryHandler(ai_fal_tarot, pattern="^menu_fal$")); app.add_handler(CallbackQueryHandler(show_analiz_menu, pattern="^menu_analiz$"))
    app.add_handler(CallbackQueryHandler(lambda u,c: set_dark_mode(u,c,is_on=True), pattern="^dark_mode_on$")); app.add_handler(CallbackQueryHandler(lambda u,c: set_dark_mode(u,c,is_on=False), pattern="^dark_mode_off$"))
    app.add_handler(CallbackQueryHandler(ai_saka_iste, pattern="^ai_saka$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$"))
    app.add_handler(CallbackQueryHandler(show_ai_model_menu, pattern="^admin_select_ai$")); app.add_handler(CallbackQueryHandler(set_ai_model, pattern="^ai_model_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info(f"DarkJarvis (v3.0 - Gemini 1.5 Pro) başarıyla başlatıldı!"); app.run_polling()
if __name__ == '__main__':
    try: main()
    except Exception as e: logger.critical(f"Kritik hata: {e}", exc_info=True)
    finally: save_all_data(); logger.info("Bot durduruluyor, veriler kaydedildi.")
