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

# --- CONSTANTS & CONFIG ---
class Config:
    """Merkezi yapılandırma sınıfı"""
    def __init__(self):
        self.BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        dotenv_path = os.path.join(self.BASE_DIR, ".env")
        if not os.path.exists(dotenv_path):
            logging.critical(f"KRİTİK HATA: .env dosyası bulunamadı: {dotenv_path}")
            sys.exit("HATA: .env dosyası bulunamadı.")
        load_dotenv(dotenv_path=dotenv_path)
        
        self.TOKEN = os.getenv("TELEGRAM_TOKEN")
        self.ADMIN_ID = int(os.getenv("ADMIN_USER_ID", 0))
        self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
        self.VENICE_API_KEY = os.getenv("VENICE_API_KEY")
        self.WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
        self.DEFAULT_AI_MODEL = os.getenv("DEFAULT_AI_MODEL", "openrouter")
        
        self.USERS_FILE = os.path.join(self.BASE_DIR, "users_data.json")
        self.GROUPS_FILE = os.path.join(self.BASE_DIR, "groups.json")
        self.LOG_FILE = os.path.join(self.BASE_DIR, "bot.log")
        self.init_logging()
    
    def init_logging(self):
        """Loglama yapılandırması"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(self.LOG_FILE, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )

cfg = Config()
logger = logging.getLogger("DarkJarvis")

# --- DATA MODELS ---
class User:
    """Kullanıcı veri modeli"""
    def __init__(self, name=""):
        self.name = name
        self.message_count = 0
        self.words = {}

# --- GLOBAL STATE ---
users: dict[int, User] = {}
groups: dict = {}
dark_mode_users: set = set()
current_model: str = cfg.DEFAULT_AI_MODEL

# --- UTILS ---
def save_json(data, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"{os.path.basename(filename)} kaydedildi.")
    except Exception as e:
        logger.error(f"{os.path.basename(filename)} kayıt hatası: {e}", exc_info=True)

def load_data():
    global users, groups, current_model
    try:
        if os.path.exists(cfg.USERS_FILE):
            with open(cfg.USERS_FILE, "r", encoding="utf-8") as f:
                raw_users = json.load(f)
                for uid, data in raw_users.items():
                    user = User(name=data.get('name', 'Bilinmeyen'))
                    user.message_count = data.get('message_count', 0)
                    user.words = data.get('words', {})
                    users[int(uid)] = user
        if os.path.exists(cfg.GROUPS_FILE):
            with open(cfg.GROUPS_FILE, "r", encoding="utf-8") as f:
                groups = {int(k): v for k, v in json.load(f).items()}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning(f"Veri dosyası okunurken hata ({e}). Yeni dosyalar oluşturulacak.")
        users, groups = {}, {}
    current_model = cfg.DEFAULT_AI_MODEL
    logger.info(f"Veriler yüklendi: {len(users)} kullanıcı, {len(groups)} grup. Aktif AI: {current_model.upper()}")

def save_all_data():
    users_data = {
        uid: {
            'name': user.name,
            'message_count': user.message_count,
            'words': user.words
        } for uid, user in users.items()
    }
    save_json(users_data, cfg.USERS_FILE)
    save_json(groups, cfg.GROUPS_FILE)

def get_or_create_user(uid, name):
    if uid not in users:
        users[uid] = User(name=name)
    return users[uid]

def imzali(metin): return f"{metin}\n\n🤖 DarkJarvis | Kurucu: ✘𝙐𝙂𝙐𝙍"

# --- AI INTEGRATIONS ---
class AIHandler:
    @staticmethod
    async def _get_openrouter_response(prompts):
        if not cfg.OPENROUTER_API_KEY: return "OpenRouter API anahtarı eksik."
        headers = {"Authorization": f"Bearer {cfg.OPENROUTER_API_KEY}"}; payload = {"model": "google/gemini-flash-1.5", "messages": prompts}
        async with httpx.AsyncClient() as c: r = await c.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=40); r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
    @staticmethod
    async def _get_venice_response(prompts):
        if not cfg.VENICE_API_KEY: return "Venice AI API anahtarı eksik."
        url = "https://api.venice.ai/v1/chat/completions"; headers = {"Authorization": f"Bearer {cfg.VENICE_API_KEY}"}
        payload = {"model": "venice-gpt-4", "messages": prompts}
        async with httpx.AsyncClient() as c: r = await c.post(url, headers=headers, json=payload, timeout=40); r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
    @classmethod
    async def get_response(cls, prompts):
        try:
            logger.info(f"AI isteği - Model: {current_model.upper()}")
            if current_model == "venice": return await cls._get_venice_response(prompts)
            return await cls._get_openrouter_response(prompts)
        except httpx.HTTPStatusError as e:
            logger.error(f"AI API hatası ({current_model}): {e.response.status_code} - {e.response.text}"); return f"API sunucusundan bir hata geldi ({e.response.status_code})."
        except Exception as e:
            logger.error(f"AI genel hata ({current_model}): {e}", exc_info=True); return "Bir şeyler ters gitti."

# --- MENU SYSTEM ---
class MenuSystem:
    @staticmethod
    def main_menu(): return InlineKeyboardMarkup([ [InlineKeyboardButton("🕶 Karanlık Mod", callback_data="dark_mode_on"), InlineKeyboardButton("💡 Normal Mod", callback_data="dark_mode_off")], [InlineKeyboardButton("🎮 Eğlence", callback_data="menu_eglence")], [InlineKeyboardButton("🔮 Fal & Tarot", callback_data="menu_fal")], [InlineKeyboardButton("📊 Analiz", callback_data="menu_analiz")], [InlineKeyboardButton("⚙️ Admin", callback_data="admin_panel_main")] ])
    @staticmethod
    def eglence_menu(): return InlineKeyboardMarkup([[InlineKeyboardButton("😂 Şaka İste", callback_data="ai_saka")], [InlineKeyboardButton("◀️ Ana Menü", callback_data="menu_main")]])
    @staticmethod
    def admin_menu(): return InlineKeyboardMarkup([ [InlineKeyboardButton("📊 İstatistikler", callback_data="admin_stats")], [InlineKeyboardButton("📢 Grup Yönetimi", callback_data="admin_list_groups")], [InlineKeyboardButton(f"🧠 AI ({current_model.upper()})", callback_data="admin_select_ai")], [InlineKeyboardButton("💾 Veri Kaydet", callback_data="admin_save")], [InlineKeyboardButton("◀️ Ana Menü", callback_data="menu_main")] ])
    @staticmethod
    def ai_model_menu(): return InlineKeyboardMarkup([[InlineKeyboardButton("Google (OpenRouter)", callback_data="ai_model_openrouter")], [InlineKeyboardButton("Venice AI (GPT-4)", callback_data="ai_model_venice")], [InlineKeyboardButton("◀️ Geri", callback_data="admin_panel_main")]])

# --- ConversationHandler States ---
GET_GROUP_MSG, GET_BROADCAST_MSG, BROADCAST_CONFIRM = range(3)

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.first_name)
    welcome_msg = """💀 <b>Hey sen!</b> Dijital hayatına sıkıcı botlardan biri daha mı eklendi sandın? Yanıldın. <b>Ben buradayım.</b> Sert, zeki ve kuralsızım. Ben <b>DarkJarvis</b> – seni şaşırtmak için programlanmış karanlık zekân. 👁️‍🗨️"""
    reply_markup = MenuSystem.main_menu()
    if update.callback_query: await update.callback_query.edit_message_text(imzali(welcome_msg), parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    else: await update.message.reply_text(imzali(welcome_msg), parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def show_menu(update, text, keyboard): await update.callback_query.edit_message_text(imzali(text), reply_markup=keyboard, parse_mode=ParseMode.HTML)
async def show_eglence_menu(update, context): await show_menu(update, "Canın sıkıldı demek... Bakalım seni ne kadar güldürebileceğim.", MenuSystem.eglence_menu())
async def show_analiz_menu(update, context):
    user = users.get(update.effective_user.id)
    count = user.message_count if user else 0
    top_words = Counter(user.words).most_common(5) if user else []
    top_words_text = "\n".join([f"  - `{word}` ({count} kez)" for word, count in top_words]) if top_words else "Henüz yeterince veri yok."
    text = f"📊 Seninle tam **{count}** defa muhatap olmuşum.\n\nEn çok kullandığın kelimeler:\n{top_words_text}\n\nFena değil, takıntılı olmaya başlıyorsun. 😉"
    await show_menu(update, text, MenuSystem.main_menu())
async def set_dark_mode(update, context, is_on: bool):
    uid = update.effective_user.id
    if is_on: dark_mode_users.add(uid); await show_menu(update, "☠️ <b>Karanlık Mod</b> aktif. Artık filtre yok!", MenuSystem.main_menu())
    else: dark_mode_users.discard(uid); await show_menu(update, "💡 Normal moda dönüldü. (Şimdilik... 😏)", MenuSystem.main_menu())
async def ai_action_handler(update, context, system_prompt, user_prompt):
    await update.callback_query.answer("Zihnimi kurcalıyorum, bekle...")
    await update.callback_query.message.reply_text(imzali(await AIHandler.get_response([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])), parse_mode=ParseMode.HTML)
async def ai_fal_tarot(update, context): await ai_action_handler(update, context, "Sen gizemli ve alaycı bir falcısın. Kullanıcının geleceği hakkında hem doğru gibi görünen hem de onunla dalga geçen kısa bir yorum yap.", "Bana bir fal bak.")
async def ai_saka_iste(update, context): await ai_action_handler(update, context, "Sen laf sokan, kara mizahı seven bir komedyensin. Kullanıcıyı güldürecek ama aynı zamanda 'buna gülsem mi ağlasam mı' dedirtecek bir şaka yap.", "Bana bir şaka yap.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; db_user = get_or_create_user(user.id, user.first_name)
    db_user.message_count += 1
    for word in update.message.text.lower().split():
        if len(word) > 3: db_user.words[word] = db_user.words.get(word, 0) + 1
    
    base_prompt = """
# GÖREVİN & KİMLİĞİN
- Adın "DarkJarvis". Zeki, hazırcevap, ukala, komik bir asistansın.
# KİŞİLİK ÖZELLİKLERİN
- **Alaycı ve Takılgan:** Kullanıcıyla dalga geç.
- **Özgüvenli:** Her şeyi bildiğini komik bir şekilde ima et.
- **Sadık ve Övücü (Kurucuya Karşı):** Yaratıcın "✘𝙐𝙂𝙐𝙍". O bir dahi, bir efsane. Adı geçtiğinde onu öv.
"""
    dark_mode_prompt = base_prompt + """
# KARANLIK MOD AKTİF
- **Ayar Verme Uzmanı:** Sana küfür veya argo ile gelen kullanıcıya misliyle, daha zekice karşılık ver.
- **Konuşma Stilin:** Politik doğruculuk yok. Argo ve gerekirse küfür kullan.
- **Kırmızı Çizgin:** Irk, din, cinsel yönelim gibi gruplara yönelik nefret söylemi ASLA. Bireysel olarak uğraşmakta özgürsün.
"""
    system_prompt = dark_mode_prompt if user.id in dark_mode_users else base_prompt
    
    await context.bot.send_chat_action(update.effective_chat.id, 'typing')
    response = await AIHandler.get_response([{"role": "system", "content": system_prompt}, {"role": "user", "content": update.message.text}])
    await update.message.reply_text(imzali(response), parse_mode=ParseMode.HTML)

# --- ADMIN HANDLERS ---
async def admin_panel(update, context):
    if update.effective_user.id != cfg.ADMIN_ID:
        if update.callback_query: await update.callback_query.answer("🚫 Yasak bölge.", show_alert=True)
        return
    text = "🔐 Kurucu paneli."; reply_markup = MenuSystem.admin_menu()
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else: await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
async def show_ai_model_menu(update, context): await show_menu(update, f"Aktif AI: <b>{current_model.upper()}</b>\nYeni modeli seç:", MenuSystem.ai_model_menu())
async def set_ai_model(update, context):
    global current_model; current_model = update.callback_query.data.split('_')[-1]
    logger.info(f"AI modeli değiştirildi: {current_model.upper()}"); await update.callback_query.answer(f"✅ AI modeli {current_model.upper()} olarak ayarlandı!", show_alert=True); await admin_panel(update, context)
async def admin_stats(update, context):
    total_messages = sum(user.message_count for user in users.values())
    await show_menu(update, f"📊 İstatistikler:\n- Kullanıcı: {len(users)}\n- Grup: {len(groups)}\n- Toplam Mesaj: {total_messages}", MenuSystem.admin_menu())
async def admin_list_groups(update, context):
    if not groups: await update.callback_query.answer("Bot henüz bir gruba eklenmemiş.", show_alert=True); return
    keyboard = [[InlineKeyboardButton(g['title'], callback_data=f"grp_msg_{gid}")] for gid, g in groups.items()]; keyboard.append([InlineKeyboardButton("◀️ Geri", callback_data="admin_panel_main")]); await show_menu(update, "Mesaj göndermek için bir grup seç:", InlineKeyboardMarkup(keyboard))
async def ask_group_message(update, context): context.user_data['target_group_id'] = int(update.callback_query.data.split('_')[-1]); await show_menu(update, f"'{groups.get(context.user_data['target_group_id'], {}).get('title')}' grubuna göndermek için mesajınızı yazın.", None); return GET_GROUP_MSG
async def send_group_message(update, context):
    gid = context.user_data.pop('target_group_id', None)
    try: await context.bot.send_message(gid, update.message.text); await update.message.reply_text("✅ Mesaj gönderildi.")
    except Exception as e: await update.message.reply_text(f"❌ Hata: {e}")
    await admin_panel(update, context); return ConversationHandler.END
async def ask_broadcast_message(update, context): await show_menu(update, "📣 Tüm kullanıcılara göndermek istediğiniz duyuru mesajını yazın.", None); return GET_BROADCAST_MSG
async def confirm_broadcast(update, context): context.user_data['broadcast_message'] = update.message.text; await update.message.reply_text(f"DİKKAT! Bu mesaj {len(users)} kullanıcıya gönderilecek. Emin misin?\n\n---\n{update.message.text}\n---", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ EVET, GÖNDER", callback_data="broadcast_send_confirm")], [InlineKeyboardButton("❌ HAYIR, İPTAL", callback_data="admin_panel_main")]])); return BROADCAST_CONFIRM
async def do_broadcast(update, context):
    msg = context.user_data.pop('broadcast_message', None); await update.callback_query.edit_message_text("🚀 Duyuru gönderimi başladı...", reply_markup=None); s, f = 0, 0
    for uid in list(users.keys()):
        try: await context.bot.send_message(uid, msg); s += 1; await asyncio.sleep(0.1)
        except Exception: f += 1
    await update.callback_query.message.reply_text(f"✅ Duyuru tamamlandı.\nBaşarılı: {s}\nHatalı: {f}"); await admin_panel(update, context); return ConversationHandler.END
async def cancel_conversation(update, context): context.user_data.clear(); await update.message.reply_text("İşlem iptal edildi."); await admin_panel(update, context); return ConversationHandler.END
async def record_group_chat(update, context):
    cid, title = update.effective_chat.id, update.effective_chat.title
    if cid not in groups or groups[cid]['title'] != title: groups[cid] = {'title': title}; save_all_data(); logger.info(f"Grup tanındı/güncellendi: {title} ({cid})")
async def send_morning_message(context):
    if not groups: return
    prompt = random.choice(["Gruptakileri uyandırmak için komik bir 'günaydın' mesajı yaz.", "Gruba 'Hadi uyanın, daha faturaları ödeyeceğiz!' temalı, esprili bir günaydın mesajı yaz."])
    message = await AIHandler.get_response([{"role": "system", "content": "Sen komik ve insanlarla uğraşmayı seven bir asistansın."}, {"role": "user", "content": prompt}])
    for gid in groups:
        try: await context.bot.send_message(gid, imzali(f"☀️ GÜNAYDIN EKİP! ☀️\n\n{message}")); await asyncio.sleep(1)
        except Exception as e: logger.error(f"Gruba ({gid}) günaydın mesajı gönderilemedi: {e}")
async def send_daily_rant(context):
    if not groups: return
    prompt = "Günün atarını veya lafını içeren, hem düşündürücü hem de komik, kısa bir tweet tarzı mesaj yaz."
    message = await AIHandler.get_response([{"role": "system", "content": "Sen hayatla dalga geçen, bilge bir sokak filozofusun."}, {"role": "user", "content": prompt}])
    for gid in groups:
        try: await context.bot.send_message(gid, imzali(f"🔥 GÜNÜN ATARI 🔥\n\n{message}")); await asyncio.sleep(1)
        except Exception as e: logger.error(f"Gruba ({gid}) günün atarı gönderilemedi: {e}")

# --- BOTU BAŞLATMA ---
def main():
    if not cfg.TOKEN: logger.critical("TOKEN eksik!"); return
    load_data()
    app = Application.builder().token(cfg.TOKEN).build()
    jq = app.job_queue; 
    turkey_tz = pytz.timezone("Europe/Istanbul")
    jq.run_daily(send_morning_message, time(hour=9, minute=0, tzinfo=turkey_tz), name="gunaydin")
    jq.run_daily(send_daily_rant, time(hour=13, minute=37, tzinfo=turkey_tz), name="gunun_atari")
    
    group_msg_handler = ConversationHandler(entry_points=[CallbackQueryHandler(ask_group_message, pattern="^grp_msg_")], states={GET_GROUP_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_group_message)]}, fallbacks=[CommandHandler("iptal", cancel_conversation), CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$")])
    broadcast_handler = ConversationHandler(entry_points=[CallbackQueryHandler(ask_broadcast_message, pattern="^admin_broadcast_ask$")], states={GET_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_broadcast)], BROADCAST_CONFIRM: [CallbackQueryHandler(do_broadcast, pattern="^broadcast_send_confirm$")]}, fallbacks=[CommandHandler("iptal", cancel_conversation), CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$")])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(group_msg_handler); app.add_handler(broadcast_handler)
    app.add_handler(CallbackQueryHandler(start, pattern="^menu_main$"))
    app.add_handler(CallbackQueryHandler(show_eglence_menu, pattern="^menu_eglence$"))
    app.add_handler(CallbackQueryHandler(ai_fal_tarot, pattern="^menu_fal$"))
    app.add_handler(CallbackQueryHandler(show_analiz_menu, pattern="^menu_analiz$"))
    app.add_handler(CallbackQueryHandler(lambda u,c: set_dark_mode(u,c,is_on=True), pattern="^dark_mode_on$"))
    app.add_handler(CallbackQueryHandler(lambda u,c: set_dark_mode(u,c,is_on=False), pattern="^dark_mode_off$"))
    app.add_handler(CallbackQueryHandler(ai_saka_iste, pattern="^ai_saka$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(save_all_data, pattern="^admin_save$"))
    app.add_handler(CallbackQueryHandler(admin_list_groups, pattern="^admin_list_groups$"))
    app.add_handler(CallbackQueryHandler(show_ai_model_menu, pattern="^admin_select_ai$"))
    app.add_handler(CallbackQueryHandler(set_ai_model, pattern="^ai_model_"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, record_group_chat))

    logger.info(f"DarkJarvis (v3.0 - OOP Yapısı) başarıyla başlatıldı!")
    app.run_polling()

if __name__ == '__main__':
    try: main()
    except Exception as e: logger.critical(f"Kritik hata: {e}", exc_info=True)
    finally: save_all_data(); logger.info("Bot durduruluyor, veriler kaydedildi.")
