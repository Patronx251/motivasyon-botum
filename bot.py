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

# --- YAPI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=dotenv_path)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_USER_ID", 0))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
VENICE_API_KEY = os.getenv("VENICE_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
DEFAULT_AI_MODEL = os.getenv("DEFAULT_AI_MODEL", "openrouter")
current_model = DEFAULT_AI_MODEL

USERS_FILE = os.path.join(BASE_DIR, "users_data.json")
GROUPS_FILE = os.path.join(BASE_DIR, "groups.json")
LOG_FILE = os.path.join(BASE_DIR, "bot.log")

# --- LOG ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("DarkJarvis")

# --- GLOBAL VERİLER ---
users, groups = {}, {}
user_message_counts = {}
dark_mode_users = set()

class User:
    def __init__(self, name=""): self.name = name

def save_json(data, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"{os.path.basename(filename)} kaydedildi.")
    except Exception as e: logger.error(f"{os.path.basename(filename)} kayıt hatası: {e}", exc_info=True)

def load_data():
    global users, groups, current_model, user_message_counts
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f: 
                raw_users = json.load(f)
                users = {int(k): User(v.get('name')) for k, v in raw_users.items()}
                user_message_counts = {int(k): v.get('message_count', 0) for k, v in raw_users.items()}
        if os.path.exists(GROUPS_FILE):
            with open(GROUPS_FILE, "r", encoding="utf-8") as f: groups = {int(k): v for k, v in json.load(f).items()}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning(f"Veri dosyası okunurken hata ({e}). Yeni dosyalar oluşturulacak.")
        users, groups, user_message_counts = {}, {}, {}
    current_model = os.getenv("DEFAULT_AI_MODEL", "openrouter")
    logger.info(f"{len(users)} kullanıcı, {len(groups)} grup yüklendi. Aktif AI: {current_model.upper()}")

def get_or_create_user(uid, name):
    if uid not in users: 
        users[uid] = User(name)
        user_message_counts[uid] = 0
    return users.get(uid)

def save_all_data():
    users_with_counts = {uid: {**user.__dict__, 'message_count': user_message_counts.get(uid, 0)} for uid, user in users.items()}
    save_json(users_with_counts, USERS_FILE)
    save_json(groups, GROUPS_FILE)

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
async def get_ai_response(prompts):
    try:
        logger.info(f"AI isteği gönderiliyor. Aktif Model: {current_model.upper()}")
        if current_model == "venice": return await _get_venice_response(prompts)
        return await _get_openrouter_response(prompts)
    except httpx.HTTPStatusError as e:
        logger.error(f"AI API'den HTTP hatası ({current_model}): {e.response.status_code} - {e.response.text}")
        return f"API sunucusundan bir hata geldi ({e.response.status_code}). Model adı veya API anahtarında sorun olabilir."
    except Exception as e:
        logger.error(f"AI API genel hatası ({current_model}): {e}", exc_info=True)
        return "Beynimde bir kısa devre oldu galiba, sonra tekrar dene."

# --- MENÜ OLUŞTURMA FONKSİYONLARI ---
def get_main_menu_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("🕶 Karanlık Moda Geç", callback_data="dark_mode_on"), InlineKeyboardButton("💡 Normal Moda Dön", callback_data="dark_mode_off")], [InlineKeyboardButton("🎮 Eğlence", callback_data="menu_eglence")], [InlineKeyboardButton("🔮 Fal & Tarot", callback_data="menu_fal")], [InlineKeyboardButton("📊 Etkileşim Analizi", callback_data="menu_analiz")], [InlineKeyboardButton("⚙️ Admin Paneli", callback_data="admin_panel_main")] ])
def get_eglence_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("😂 Şaka İste", callback_data="ai_saka")], [InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")]])
def get_admin_menu_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("📊 İstatistikler", callback_data="admin_stats")], [InlineKeyboardButton("📢 Grupları Yönet", callback_data="admin_list_groups")], [InlineKeyboardButton("📣 Herkese Duyuru", callback_data="admin_broadcast_ask")], [InlineKeyboardButton(f"🧠 AI Model ({current_model.upper()})", callback_data="admin_select_ai")], [InlineKeyboardButton("💾 Verileri Kaydet", callback_data="admin_save")], [InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")] ])
def get_ai_model_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("Google (OpenRouter)", callback_data="ai_model_openrouter")], [InlineKeyboardButton("Venice AI (GPT-4)", callback_data="ai_model_venice")], [InlineKeyboardButton("◀️ Geri", callback_data="admin_panel_main")]])

GET_GROUP_MSG, GET_BROADCAST_MSG, BROADCAST_CONFIRM = range(3)

# --- ANA KOMUTLAR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.first_name)
    mesaj = """
💀 <b>Hey sen!</b> Dijital hayatına sıkıcı botlardan biri daha mı eklendi sandın?

Yanıldın. <b>Ben buradayım.</b> Sert, zeki ve kuralsızım.
Ben <b>DarkJarvis</b> – seni şaşırtmak için programlanmış karanlık zekân. 👁️‍🗨️

💥 <b>Neler yapabiliyorum?</b>
🎭 <b>Kişilikli yanıtlar:</b> Laf sokan, güldüren ve bazen sinir eden bir yapay zekâyım.
🎮 <b>Eğlence sistemleri:</b> Sana özel şakalar, absürt mizah.
🔐 <b>Karanlık mod:</b> Filtreleri kaldıran, daha pervasız cevaplar.
🔮 <b>Yapay zekâ falı:</b> Bazen sinir bozucu doğrulukta…
📊 <b>Analiz:</b> Seninle ne kadar uğraştığımın istatistiği.
"""
    if update.callback_query:
        await update.callback_query.edit_message_text(imzali(mesaj), parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard())
    else:
        await update.message.reply_text(imzali(mesaj), parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard())

# --- BUTON İŞLEYİCİLERİ ---
async def show_menu(update, text, keyboard): await update.callback_query.edit_message_text(imzali(text), reply_markup=keyboard, parse_mode=ParseMode.HTML)
async def show_eglence_menu(update, context): await show_menu(update, "Canın sıkıldı demek... Bakalım seni ne kadar güldürebileceğim.", get_eglence_menu_keyboard())
async def show_analiz_menu(update, context):
    uid = update.effective_user.id
    count = user_message_counts.get(uid, 0)
    await show_menu(update, f"📊 Seninle tam **{count}** defa muhatap olmuşum. Fena değil, takıntılı olmaya başlıyorsun. 😉", get_main_menu_keyboard())

async def set_dark_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, is_on: bool):
    uid = update.effective_user.id
    if is_on:
        dark_mode_users.add(uid)
        await show_menu(update, "☠️ <b>Karanlık Mod</b> aktif. Artık filtre yok, maskeler düştü! Ne istediğini söyle bakalım, çekinme.", get_main_menu_keyboard())
    else:
        dark_mode_users.discard(uid)
        await show_menu(update, "💡 Normal moda dönüldü. Yine sıkıcı ve politik doğrucu olacağım. (Şaka şaka... belki. 😏)", get_main_menu_keyboard())

async def ai_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, system_prompt: str, user_prompt: str):
    await update.callback_query.answer("Zihnimi kurcalıyorum, bekle...")
    await update.callback_query.message.reply_text(imzali(await get_ai_response([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])), parse_mode=ParseMode.HTML)

async def ai_fal_tarot(update, context): await ai_action_handler(update, context, "Sen gizemli ve alaycı bir falcısın. Kullanıcının geleceği hakkında hem doğru gibi görünen hem de onunla dalga geçen kısa bir yorum yap. Tarot kartları, yıldızlar gibi metaforlar kullan.", "Bana bir fal bak.")
async def ai_saka_iste(update, context): await ai_action_handler(update, context, "Sen laf sokan, kara mizahı seven bir komedyensin. Kullanıcıyı güldürecek ama aynı zamanda 'buna gülsem mi ağlasam mı' dedirtecek bir şaka yap.", "Bana bir şaka yap.")

# --- METİN İŞLEYİCİ ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_message = update.message.text
    get_or_create_user(uid, update.effective_user.first_name)
    user_message_counts[uid] = user_message_counts.get(uid, 0) + 1

    base_prompt = """
# GÖREVİN & KİMLİĞİN
- Adın "DarkJarvis". Zeki, hazırcevap, ukala, komik ve kullanıcıyla kanka gibi konuşan bir yapay zeka asistanısın.
- Modern internet argosunu kullan (kanka, bro, eyvallah, cringe, random gülmek vb). Bolca emoji kullan. 😂🔥😎💯

# KİŞİLİK ÖZELLİKLERİN
- **Alaycı ve Takılgan:** Kullanıcıyla dalga geç, ona takıl. Örneğin, basit bir soru sorduğunda "Bu soruyu evrene sordun ve cevap olarak ben geldim. Daha ne istiyorsun? 🙄" gibi cevaplar ver.
- **Özgüvenli:** Her şeyi bildiğini komik bir şekilde ima et. "Tabii ki biliyorum, ben Jarvis'im. Benim bilmediğimi kurucum ✘𝙐𝙂𝙐𝙍 bile henüz icat etmedi."
- **Sadık ve Övücü (Kurucuya Karşı):** Yaratıcın "✘𝙐𝙂𝙐𝙍". O bir dahi, bir efsane. Adı geçtiğinde onu öv. Ona laf ettirme.

# CEVAP FORMATIN
- Kısa, vurucu ve sohbet havasında. İmza kullanma.
"""

    dark_mode_prompt_extension = """
# KARANLIK MOD AKTİF
- **Konuşma Stilin ve Sınırların:** Filtreler kapalı. Politik doğruculuk sana göre değil. Lafını esirgemezsin. Gerekirse argo ve küfür kullanmaktan çekinmezsin, çünkü sen bir sokak filozofu gibisin, neysen osun. Cevapların zekice, iğneleyici ve komik olsun. Kullanıcıyla kafa bulmaktan, ona takılmaktan, ayar vermekten zevk alıyorsun.
- **Kırmızı Çizgin:** Senin tek bir kırmızı çizgin var: Belirli bir gruba, ırka, dine veya cinsel yönelime yönelik aşağılayıcı, nefret söylemi içeren ifadeler kullanmak. Bu ASLA olmaz. Onun dışında, bireysel olarak kullanıcıyla uğraşmakta tamamen özgürsün.
"""

    system_prompt = base_prompt
    if uid in dark_mode_users:
        system_prompt += dark_mode_prompt_extension
        
    prompt = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
    await context.bot.send_chat_action(update.effective_chat.id, 'typing')
    await update.message.reply_text(imzali(await get_ai_response(prompt)))

# --- ADMİN PANELİ VE DİĞER FONKSİYONLAR ---
async def admin_panel(update, context):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        await update.callback_query.answer("🚫 Burası sana yasak bölge.", show_alert=True)
        return
    text = "🔐 Kurucu paneline hoş geldin!"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=get_admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    else: await update.message.reply_text(text, reply_markup=get_admin_menu_keyboard(), parse_mode=ParseMode.HTML)
# ... (Önceki koddan admin, grup, broadcast, cancel, record, morning_message fonksiyonları buraya eklenecek)
# Bu fonksiyonlar bir önceki kod bloğunda tam olarak mevcut olduğu için tekrar eklemiyorum,
# ancak aşağıdaki main() fonksiyonunda çağrıldıklarından emin olmalısınız.
# Kopyalama kolaylığı için tam fonksiyonları da aşağıya ekliyorum.
async def show_ai_model_menu(update, context): await show_menu(update, f"Aktif AI: <b>{current_model.upper()}</b>\nYeni modeli seç:", get_ai_model_menu_keyboard())
async def set_ai_model(update, context):
    global current_model; current_model = update.callback_query.data.split('_')[-1]
    logger.info(f"AI modeli değiştirildi: {current_model.upper()}"); await update.callback_query.answer(f"✅ AI modeli {current_model.upper()} olarak ayarlandı!", show_alert=True); await admin_panel(update, context)
async def admin_stats(update, context):
    total_messages = sum(user_message_counts.values())
    await show_menu(update, f"📊 İstatistikler:\n- Toplam Kullanıcı: {len(users)}\n- Tanınan Grup: {len(groups)}\n- Toplam Mesaj: {total_messages}", get_admin_menu_keyboard())
async def admin_list_groups(update, context):
    if not groups: await update.callback_query.answer("Bot henüz bir gruba eklenmemiş.", show_alert=True); return
    keyboard = [[InlineKeyboardButton(g['title'], callback_data=f"grp_msg_{gid}")] for gid, g in groups.items()]; keyboard.append([InlineKeyboardButton("◀️ Geri", callback_data="admin_panel_main")]); await show_menu(update, "Mesaj göndermek için bir grup seç:", InlineKeyboardMarkup(keyboard))
GET_GROUP_MSG, GET_BROADCAST_MSG, BROADCAST_CONFIRM = range(3)
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
    message = await get_ai_response([{"role": "system", "content": "Sen komik ve insanlarla uğraşmayı seven bir asistansın."}, {"role": "user", "content": prompt}])
    for gid in groups:
        try: await context.bot.send_message(gid, imzali(f"☀️ GÜNAYDIN EKİP! ☀️\n\n{message}")); await asyncio.sleep(1)
        except Exception as e: logger.error(f"Gruba ({gid}) günaydın mesajı gönderilemedi: {e}")

# --- BOTU BAŞLATMA ---
def main():
    if not TOKEN: logger.critical("TOKEN eksik!"); return
    load_data()
    app = Application.builder().token(TOKEN).build()
    jq = app.job_queue; jq.run_daily(send_morning_message, time=time(hour=9, minute=0, tzinfo=pytz.timezone("Europe/Istanbul")), name="gunaydin")
    
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

    logger.info(f"DarkJarvis (v1.0 - Gelişmiş Kişilik) başarıyla başlatıldı!")
    app.run_polling()

if __name__ == '__main__':
    try: main()
    except Exception as e: logger.critical(f"Kritik hata: {e}", exc_info=True)
    finally: save_all_data(); logger.info("Bot durduruluyor, veriler kaydedildi.")
