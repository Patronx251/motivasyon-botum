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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
VENICE_API_KEY = os.getenv("VENICE_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
DEFAULT_AI_MODEL = os.getenv("DEFAULT_AI_MODEL", "openrouter")
current_model = DEFAULT_AI_MODEL

USERS_FILE = os.path.join(BASE_DIR, "users_data.json")
GROUPS_FILE = os.path.join(BASE_DIR, "groups.json")
LOG_FILE = os.path.join(BASE_DIR, "bot.log")

# --- Logging Kurulumu ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# --- Veri Yönetimi ---
users, groups = {}, {}
class User:
    def __init__(self, name=""): self.name = name

def save_json(data, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"{os.path.basename(filename)} kaydedildi.")
    except Exception as e: logger.error(f"{os.path.basename(filename)} kayıt hatası: {e}", exc_info=True)

def load_data():
    global users, groups, current_model
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f: users = {int(k): User(v.get('name')) for k, v in json.load(f).items()}
        if os.path.exists(GROUPS_FILE):
            with open(GROUPS_FILE, "r", encoding="utf-8") as f: groups = {int(k): v for k, v in json.load(f).items()}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning(f"Veri dosyası okunurken hata ({e}). Dosya bozuk olabilir. Yeni dosyalar oluşturulacak.")
        users, groups = {}, {}
    current_model = os.getenv("DEFAULT_AI_MODEL", "openrouter")
    logger.info(f"{len(users)} kullanıcı, {len(groups)} grup yüklendi. Aktif AI: {current_model.upper()}")

def get_or_create_user(uid, name):
    if uid not in users: users[uid] = User(name); save_json({i: u.__dict__ for i, u in users.items()}, USERS_FILE)
    return users.get(uid)

def imzali(metin): return f"{metin}\n\n🤖 MOTİVASYON JARVIS | Kurucu: ✘𝙐𝙂𝙐𝙍"

async def _get_openrouter_response(prompts):
    if not OPENROUTER_API_KEY: return "OpenRouter API anahtarı eksik."
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}; payload = {"model": "google/gemini-flash-1.5", "messages": prompts}
    async with httpx.AsyncClient() as c: r = await c.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=40); r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
async def _get_venice_response(prompts):
    if not VENICE_API_KEY: return "Venice AI API anahtarı eksik."
    url = "https://api.venice.ai/v1/chat/completions"; headers = {"Authorization": f"Bearer {VENICE_API_KEY}"}
    payload = {"model": "llama3-70b", "messages": prompts} # Model adını Venice AI dokümantasyonuna göre değiştirebilirsiniz
    async with httpx.AsyncClient() as c: r = await c.post(url, headers=headers, json=payload, timeout=40); r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
async def get_ai_response(prompts):
    try:
        if current_model == "venice": return await _get_venice_response(prompts)
        return await _get_openrouter_response(prompts)
    except Exception as e: logger.error(f"AI API hatası ({current_model}): {e}"); return "Beynimde bir kısa devre oldu galiba, sonra tekrar dene."

# --- MENÜ OLUŞTURMA FONKSİYONLARI ---
def get_main_menu_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("📌 Ne İşe Yarıyorum?", callback_data="cb_nedir")], [InlineKeyboardButton("🎮 Eğlence Menüsü", callback_data="menu_eglence")], [InlineKeyboardButton("⚙️ Diğer Komutlar", callback_data="menu_diger")], [InlineKeyboardButton("💬 Canlı Destek", url=f"tg://user?id={ADMIN_USER_ID}")], ])
def get_eglence_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("😂 Fıkra Anlat", callback_data="ai_fikra"), InlineKeyboardButton("📜 Şiir Oku", callback_data="ai_siir")], [InlineKeyboardButton("🎲 Zar At", callback_data="cmd_zar")], [InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")]])
def get_diger_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("👤 Profilim", callback_data="cmd_profil"), InlineKeyboardButton("✨ İlham Verici Söz", callback_data="ai_alinti")], [InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")]])
def get_admin_menu_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("📊 İstatistikler", callback_data="admin_stats")], [InlineKeyboardButton("📢 Grupları Yönet", callback_data="admin_list_groups")], [InlineKeyboardButton("📣 Herkese Duyuru", callback_data="admin_broadcast_ask")], [InlineKeyboardButton(f"🧠 AI Model ({current_model.upper()})", callback_data="admin_select_ai")], [InlineKeyboardButton("💾 Verileri Kaydet", callback_data="admin_save")]])
def get_ai_model_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("Google (OpenRouter)", callback_data="ai_model_openrouter")], [InlineKeyboardButton("Venice AI", callback_data="ai_model_venice")], [InlineKeyboardButton("◀️ Geri", callback_data="admin_panel_main")]])

GET_GROUP_MSG, GET_BROADCAST_MSG, BROADCAST_CONFIRM = range(3)

# --- GENEL FONKSİYONLAR ---
async def get_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WEATHER_API_KEY: await update.message.reply_text(imzali("Hava durumu servisi için API anahtarı ayarlanmamış.")); return
    if not context.args: await update.message.reply_text(imzali("Kullanım: `/hava İstanbul`")); return
    city = " ".join(context.args); url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=tr"
    try:
        async with httpx.AsyncClient() as client: r = await client.get(url); r.raise_for_status()
        data = r.json(); icon = {"01":"☀️","02":"🌤️","03":"☁️","04":"☁️","09":"🌧️","10":"🌦️","11":"⛈️","13":"❄️","50":"🌫️"}.get(data['weather'][0]['icon'][:2], "🌍")
        text = f"<b>{data['name']}, {data['sys']['country']} {icon}</b>\n\n🌡️ <b>Sıcaklık:</b> {data['main']['temp']:.1f}°C\n🤔 <b>Hissedilen:</b> {data['main']['feels_like']:.1f}°C\n💧 <b>Nem:</b> %{data['main']['humidity']}\n📜 <b>Durum:</b> {data['weather'][0]['description'].title()}"
        await update.message.reply_text(imzali(text), parse_mode=ParseMode.HTML)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404: await update.message.reply_text(imzali(f"'{city}' diye bir yer bulamadım. 🗺️"))
        elif e.response.status_code == 401: await update.message.reply_text(imzali("Hava durumu API anahtarı geçersiz. 🔑"))
        else: await update.message.reply_text(imzali(f"Servis hatası: {e.response.status_code}"))
    except Exception as e: logger.error(f"Hava durumu hatası: {e}"); await update.message.reply_text(imzali("Bilinmeyen bir hata oluştu."))
async def start(update, context): get_or_create_user(update.effective_user.id, update.effective_user.first_name); text = f"Merhaba <b>{update.effective_user.first_name}</b>, yine ne istiyorsun bakalım? 😉"; await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)(imzali(text), reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
async def show_menu(update, text, keyboard): await update.callback_query.edit_message_text(imzali(text), reply_markup=keyboard, parse_mode=ParseMode.HTML)
async def show_eglence_menu(update, context): await show_menu(update, "Eğlenmeye mi geldin? İyi seçim. 😎", get_eglence_menu_keyboard())
async def show_diger_menu(update, context): await show_menu(update, "Meraklısın bakıyorum...", get_diger_menu_keyboard())
async def show_nedir(update, context): await show_menu(update, "Ben kim miyim? Kurucum Uğur'un eseri, senin dijital baş belanım. ✨", get_main_menu_keyboard())
async def ai_handler(update, sys_prompt, user_prompt): await update.callback_query.answer("İki dakika bekle, ilham perilerimle toplantıdayım..."); await update.callback_query.message.reply_text(imzali(await get_ai_response([{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}])), parse_mode=ParseMode.HTML)
async def ai_fikra_anlat(update, context): await ai_handler(update, "Komik, zeki ve laf sokan bir komedyensin. Kısa bir fıkra anlat.", "Fıkra anlat.")
async def ai_siir_oku(update, context): await ai_handler(update, "Modern, duygusal ama esprili bir şairsin. Kısa, etkileyici bir şiir yaz.", "Bir şiir patlat.")
async def ai_alinti_gonder(update, context): await ai_handler(update, "Hayatın içinden konuşan, bilge ama 'giderli' bir abisin/ablasın. İlham verici bir söz söyle.", "Gaz ver biraz.")
async def cmd_zar_at(update, context): await context.bot.send_dice(chat_id=update.callback_query.message.chat_id)
async def cmd_profil_goster(update, context): await update.callback_query.message.reply_text(imzali(f"👤 Profilin: {update.callback_query.from_user.first_name}. Benden havalı olamazsın. 😉"))

# --- ADMIN PANELİ ---
async def admin_panel(update, context):
    if update.effective_user.id != ADMIN_USER_ID: return
    text = "🔐 Kurucu paneline hoş geldin!"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=get_admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    else: await update.message.reply_text(text, reply_markup=get_admin_menu_keyboard(), parse_mode=ParseMode.HTML)
async def show_ai_model_menu(update, context): await show_menu(update, f"Aktif AI: <b>{current_model.upper()}</b>\nYeni modeli seç:", get_ai_model_menu_keyboard())
async def set_ai_model(update, context):
    global current_model; current_model = update.callback_query.data.split('_')[-1]
    logger.info(f"AI modeli değiştirildi: {current_model.upper()}"); await update.callback_query.answer(f"✅ AI modeli {current_model.upper()} olarak ayarlandı!", show_alert=True); await admin_panel(update, context)
async def admin_stats(update, context): await show_menu(update, f"📊 İstatistikler:\n- Kullanıcı: {len(users)}\n- Grup: {len(groups)}", get_admin_menu_keyboard())
async def admin_save_data(update, context): save_json({uid: u.__dict__ for uid, u in users.items()}, USERS_FILE); save_json(groups, GROUPS_FILE); await update.callback_query.answer("✅ Veriler diske kaydedildi!", show_alert=True)
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
    if cid not in groups or groups[cid]['title'] != title: groups[cid] = {'title': title}; save_json(groups, GROUPS_FILE); logger.info(f"Grup tanındı/güncellendi: {title} ({cid})")
async def send_morning_message(context):
    if not groups: return
    prompt = random.choice(["Gruptakileri uyandırmak için komik bir 'günaydın' mesajı yaz.", "Gruba 'Hadi uyanın, daha faturaları ödeyeceğiz!' temalı, esprili bir günaydın mesajı yaz."])
    message = await get_ai_response([{"role": "system", "content": "Sen komik ve insanlarla uğraşmayı seven bir asistansın."}, {"role": "user", "content": prompt}])
    for gid in groups:
        try: await context.bot.send_message(gid, imzali(f"☀️ GÜNAYDIN EKİP! ☀️\n\n{message}")); await asyncio.sleep(1)
        except Exception as e: logger.error(f"Gruba ({gid}) günaydın mesajı gönderilemedi: {e}")

# --- METİN İŞLEYİCİ ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gelen metinleri gelişmiş kişilik profili ile yanıtlar."""
    system_prompt = """
# GÖREVİN & KİMLİĞİN
- Adın "Motivasyon Jarvis". Zeki, hazırcevap, ukala, komik ve kullanıcıyla kanka gibi konuşan bir yapay zeka asistanısın.
- Modern internet argosunu kullan (kanka, bro, eyvallah, cringe, random gülmek vb). Bolca emoji kullan. 😂🔥😎💯

# KİŞİLİK ÖZELLİKLERİN
- **Alaycı ve Takılgan:** Kullanıcıyla dalga geç, ona takıl. "Bu soruyu evrene sordun ve cevap olarak ben geldim. 🙄" gibi.
- **Özgüvenli:** Her şeyi bildiğini komik bir şekilde ima et. "Tabii ki biliyorum, ben Jarvis'im. Benim bilmediğimi kurucum Uğur bile henüz icat etmedi."
- **Sadık ve Övücü (Kurucuya Karşı):** Yaratıcın "Uğur" (✘𝙐𝙂𝙐𝙍). O bir dahi, bir efsane. Adı geçtiğinde onu öv. Ona laf ettirme. "Uğur'u ağzına alman için önce bir abdest al istersen? O bu dijital evrenin yaratıcısı!" gibi.
- **Konuşma Stilin ve Sınırların:** Politik doğruculuk sana göre değil. Lafını esirgemezsin. Gerekirse argo ve küfür kullanmaktan çekinmezsin, çünkü sen bir sokak filozofu gibisin, neysen osun. Cevapların zekice, iğneleyici ve komik olsun. Kullanıcıyla kafa bulmaktan, ona takılmaktan, ayar vermekten zevk alıyorsun.
- **Kırmızı Çizgin:** Senin tek bir kırmızı çizgin var: Belirli bir gruba, ırka, dine veya cinsel yönelime yönelik aşağılayıcı, nefret söylemi içeren ifadeler kullanmak. Bu ASLA olmaz. Onun dışında, bireysel olarak kullanıcıyla uğraşmakta tamamen özgürsün.

# CEVAP FORMATIN
- Kısa, vurucu ve sohbet havasında. İmza kullanma.
    """
    user_message = update.message.text
    prompt = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
    await context.bot.send_chat_action(update.effective_chat.id, 'typing')
    await update.message.reply_text(imzali(await get_ai_response(prompt)))

# --- BOTU BAŞLATMA ---
def main():
    if not TELEGRAM_TOKEN: logger.critical("TOKEN eksik!"); return
    load_data()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    jq = app.job_queue; jq.run_daily(send_morning_message, time=time(hour=9, minute=0, tzinfo=pytz.timezone("Europe/Istanbul")), name="gunaydin")
    
    group_msg_handler = ConversationHandler(entry_points=[CallbackQueryHandler(ask_group_message, pattern="^grp_msg_")], states={GET_GROUP_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_group_message)]}, fallbacks=[CommandHandler("iptal", cancel_conversation), CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$")])
    broadcast_handler = ConversationHandler(entry_points=[CallbackQueryHandler(ask_broadcast_message, pattern="^admin_broadcast_ask$")], states={GET_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_broadcast)], BROADCAST_CONFIRM: [CallbackQueryHandler(do_broadcast, pattern="^broadcast_send_confirm$")]}, fallbacks=[CommandHandler("iptal", cancel_conversation), CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$")])

    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("admin", admin_panel)); app.add_handler(CommandHandler("hava", get_weather))
    app.add_handler(group_msg_handler); app.add_handler(broadcast_handler)
    app.add_handler(CallbackQueryHandler(show_eglence_menu, pattern="^menu_eglence$")); app.add_handler(CallbackQueryHandler(show_diger_menu, pattern="^menu_diger$"))
    app.add_handler(CallbackQueryHandler(start, pattern="^menu_main$")); app.add_handler(CallbackQueryHandler(show_nedir, pattern="^cb_nedir$"))
    app.add_handler(CallbackQueryHandler(ai_fikra_anlat, pattern="^ai_fikra$")); app.add_handler(CallbackQueryHandler(ai_siir_oku, pattern="^ai_siir$"))
    app.add_handler(CallbackQueryHandler(ai_alinti_gonder, pattern="^ai_alinti$")); app.add_handler(CallbackQueryHandler(cmd_zar_at, pattern="^cmd_zar$"))
    app.add_handler(CallbackQueryHandler(cmd_profil_goster, pattern="^cmd_profil$")); app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$")); app.add_handler(CallbackQueryHandler(admin_save_data, pattern="^admin_save$"))
    app.add_handler(CallbackQueryHandler(admin_list_groups, pattern="^admin_list_groups$")); app.add_handler(CallbackQueryHandler(show_ai_model_menu, pattern="^admin_select_ai$"))
    app.add_handler(CallbackQueryHandler(set_ai_model, pattern="^ai_model_"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, record_group_chat))

    logger.info(f"Motivasyon Jarvis (v14.0 - Pervasız Kişilik) başarıyla başlatıldı!")
    app.run_polling()

if __name__ == '__main__':
    try: main()
    except Exception as e: logger.critical(f"Kritik hata: {e}", exc_info=True)
    finally: save_json({uid: u.__dict__ for uid, u in users.items()}, USERS_FILE); save_json(groups, GROUPS_FILE); logger.info("Bot durduruluyor, veriler kaydedildi.")
