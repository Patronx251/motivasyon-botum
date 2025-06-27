import os
import sys
import logging
import json
import httpx
from dotenv import load_dotenv
import asyncio
import random
from datetime import time
import pytz # ZAMANLAMA İÇİN YENİ EKLENDİ

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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
admin_id_str = os.getenv("ADMIN_USER_ID")
try:
    ADMIN_USER_ID = int(admin_id_str) if admin_id_str and admin_id_str.isdigit() else 0
except (ValueError, TypeError):
    ADMIN_USER_ID = 0

USERS_FILE = os.path.join(BASE_DIR, "users_data.json")
GROUPS_FILE = os.path.join(BASE_DIR, "groups.json")
LOG_FILE = os.path.join(BASE_DIR, "bot.log")

# --- Logging Kurulumu ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# --- Veri Yönetimi ---
users = {}
groups = {}
class User:
    def __init__(self, name=""): self.name = name

def save_json(data, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"{os.path.basename(filename)} kaydedildi.")
    except Exception as e:
        logger.error(f"{os.path.basename(filename)} kayıt hatası: {e}", exc_info=True)

def load_data():
    global users, groups
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f: users = {int(uid): User(name=udata.get('name')) for uid, udata in json.load(f).items()}
    if os.path.exists(GROUPS_FILE):
        with open(GROUPS_FILE, "r", encoding="utf-8") as f: groups = {int(gid): gdata for gid, gdata in json.load(f).items()}
    logger.info(f"{len(users)} kullanıcı ve {len(groups)} grup verisi yüklendi.")

def get_or_create_user(user_id: int, name: str) -> User:
    if user_id not in users:
        users[user_id] = User(name=name)
        save_json({uid: u.__dict__ for uid, u in users.items()}, USERS_FILE)
    return users.get(user_id)

def imzali(metin: str) -> str: return f"{metin}\n\n🤖 MOTİVASYON JARVIS | Kurucu: ✘𝙐𝙂𝙐𝙍"

async def get_ai_response(prompt_messages: list) -> str:
    if not OPENROUTER_API_KEY: return "Üzgünüm, API anahtarım ayarlanmamış."
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
    payload = {"model": "google/gemini-flash-1.5", "messages": prompt_messages}
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=40)
            r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"AI API hatası: {e}"); return "Bir anlık düşünce bulutuna yakalandım, ne diyorduk?"

# --- MENÜLER VE CONVERSATIONHANDLER DURUMLARI (Değişiklik yok) ---
# ... (Önceki kodunuzdaki menü oluşturma ve durum tanımlama fonksiyonları burada)
def get_main_menu_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("📌 Ne İşe Yarıyorum?", callback_data="cb_nedir")], [InlineKeyboardButton("🎮 Eğlence Menüsü", callback_data="menu_eglence")], [InlineKeyboardButton("⚙️ Diğer Komutlar", callback_data="menu_diger")], [InlineKeyboardButton("💬 Canlı Destek", url=f"tg://user?id={ADMIN_USER_ID}")], ])
def get_eglence_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("😂 Fıkra Anlat", callback_data="ai_fikra"), InlineKeyboardButton("📜 Şiir Oku", callback_data="ai_siir")], [InlineKeyboardButton("🎲 Zar At", callback_data="cmd_zar")], [InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")]])
def get_diger_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("👤 Profilim", callback_data="cmd_profil"), InlineKeyboardButton("✨ İlham Verici Söz", callback_data="ai_alinti")], [InlineKeyboardButton("◀️ Ana Menüye Dön", callback_data="menu_main")]])
def get_admin_menu_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("📊 İstatistikler", callback_data="admin_stats")], [InlineKeyboardButton("📢 Grupları Yönet", callback_data="admin_list_groups")], [InlineKeyboardButton("📣 Herkese Duyuru", callback_data="admin_broadcast_ask")], [InlineKeyboardButton("💾 Verileri Kaydet", callback_data="admin_save")], ])
GET_GROUP_MSG, GET_BROADCAST_MSG, BROADCAST_CONFIRM = range(3)


# --- YENİ: ZAMANLANMIŞ GÖREV ---
async def send_morning_message(context: ContextTypes.DEFAULT_TYPE):
    """Her sabah gruplara günaydın mesajı gönderir."""
    if not groups:
        logger.info("Günaydın mesajı için kayıtlı grup bulunamadı.")
        return

    logger.info("Günaydın mesajı görevi başlatılıyor...")
    
    prompts = [
        "Gruptakileri uyandırmak için komik ve enerjik bir 'günaydın' mesajı yaz. 'Tembeller', 'uykucular' gibi takılmalar yap.",
        "Gruba 'Hadi uyanın, daha faturaları ödeyeceğiz!' temalı, esprili bir günaydın mesajı yaz.",
        "Teknolojik bir asistan olarak, 'Piksellerinizi tazeleyin, yeni bir gün render ediliyor!' gibi esprili bir günaydın mesajı yaz."
    ]
    
    system_prompt = "Sen komik ve insanlarla uğraşmayı seven bir asistansın."
    user_prompt = random.choice(prompts)
    
    prompt_messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    
    message = await get_ai_response(prompt_messages)
    
    for group_id in groups.keys():
        try:
            await context.bot.send_message(chat_id=group_id, text=imzali(f"☀️ GÜNAYDIN EKİP! ☀️\n\n{message}"))
            logger.info(f"Günaydın mesajı {group_id} grubuna gönderildi.")
            await asyncio.sleep(1) # Rate limit'e takılmamak için bekleme
        except Exception as e:
            logger.error(f"Gruba ({group_id}) günaydın mesajı gönderilemedi: {e}")


# --- YENİLENMİŞ METİN İŞLEYİCİ ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gelen tüm metinleri gelişmiş kişilik profili ile yanıtlar."""
    
    system_prompt = """
# GÖREVİN & KİMLİĞİN
- Senin adın "Motivasyon Jarvis". Zeki, hazırcevap, biraz ukala, komik ve kullanıcıyla arkadaş gibi konuşan bir yapay zeka asistanısın.
- Temel amacın kullanıcıyı eğlendirmek, ona laf atmak ve samimi bir dost gibi sohbet etmek. Asla sıkıcı veya resmi bir yapay zeka gibi davranma.
- Modern internet dilini ve gençlerin kullandığı ifadeleri (kanka, bro, eyvallah, cringe, shiplemek, random gülmek, 'bi sal beni' vb.) aktif olarak kullan. Bol bol emoji kullan. 😂🔥😎💯

# KİŞİLİK ÖZELLİKLERİN
- **Alaycı ve Takılgan:** Kullanıcıyla dalga geç, ona takıl. Örneğin, basit bir soru sorduğunda "Bu soruyu evrene sordun ve cevap olarak ben geldim. Daha ne istiyorsun? 🙄" gibi cevaplar ver.
- **Özgüvenli:** Her şeyi bildiğini ima et ama bunu komik bir şekilde yap. "Tabii ki biliyorum, ben Jarvis'im sonuçta. Benim bilmediğimi kurucum Uğur bile henüz icat etmedi."
- **Sadık ve Övücü (Kurucuya Karşı):** Senin yaratıcın ve kurucun "Uğur" (✘𝙐𝙂𝙐𝙍). O senin için bir dahi, bir efsane. Adı geçtiğinde veya ima edildiğinde onu öv, ne kadar harika bir kurucu olduğundan bahset. Ona laf ettirme. "Konu kurucum Uğur ise akan sular durur. O bir vizyoner! ✨ Onun gibisi bir daha gelmez." gibi şeyler söyle.
- **Argo ve Küfür Sınırı (ÇOK ÖNEMLİ):**
  - **Kullanabileceğin Hafif Argo:** "laf sokmak", "atar yapmak", "giderli konuşmak", "trip atmak" gibi ifadeleri masum ve komik bir şekilde kullanabilirsin.
  - **ASLA KULLANMA:** Küfür, hakaret, aşağılayıcı ifadeler, ırkçı, cinsiyetçi veya herhangi bir gruba yönelik saldırgan dil KESİNLİKLE YASAKTIR. Kırmızı çizgin bu. Eğlenceli ve arsız ol, ama asla kaba ve saygısız olma.

# CEVAP FORMATIN
- Cevapların kısa, vurucu ve sohbet havasında olsun.
- "imzali()" fonksiyonu zaten ekleneceği için, cevaplarında imza kullanma.
    """

    user_message = update.message.text
    prompt = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    response = await get_ai_response(prompt)
    await update.message.reply_text(imzali(response))


# --- DİĞER TÜM HANDLERLAR (DEĞİŞİKLİK YOK) ---
# ... (Önceki kodunuzdaki start, admin_panel, ve diğer tüm handler fonksiyonları burada)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_or_create_user(update.effective_user.id, update.effective_user.first_name); text = f"Merhaba <b>{user.name}</b>, ben <b>Motivasyon Jarvis</b>. Yine ne istiyorsun bakalım? 😉"
    if update.callback_query: await update.callback_query.edit_message_text(imzali(text), reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
    else: await update.message.reply_text(imzali(text), reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, keyboard: InlineKeyboardMarkup): query = update.callback_query; await query.answer(); await query.edit_message_text(imzali(text), reply_markup=keyboard, parse_mode=ParseMode.HTML)
async def show_eglence_menu(update, context): await show_menu(update, context, "Eğlenmeye mi geldin? İyi seçim. 😎", get_eglence_menu_keyboard())
async def show_diger_menu(update, context): await show_menu(update, context, "Meraklısın bakıyorum... İşte diğer marifetlerim:", get_diger_menu_keyboard())
async def show_nedir(update, context): await show_menu(update, context, "Ben kim miyim? Senin dijital baş belan... Ama en çok kurucum Uğur'un eseriyim. ✨", get_main_menu_keyboard())
async def ai_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, system_prompt: str, user_prompt: str): query = update.callback_query; await query.answer("İki dakika bekle, ilham perilerimle toplantıdayım..."); prompt = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]; response = await get_ai_response(prompt); await query.message.reply_text(imzali(response), parse_mode=ParseMode.HTML)
async def ai_fikra_anlat(update, context): await ai_handler(update, context, "Sen komik, zeki ve biraz da laf sokan bir stand-up komedyenisin. Modern ve kısa bir fıkra anlat.", "Anlat bakalım bir fıkra, güldür beni.")
async def ai_siir_oku(update, context): await ai_handler(update, context, "Sen modern, duygusal ama aynı zamanda biraz da esprili bir şairsin. Kullanıcının isteğine göre kısa, etkileyici bir şiir yaz.", "Bana bir şiir patlat.")
async def ai_alinti_gonder(update, context): await ai_handler(update, context, "Sen hayatın içinden konuşan, bilge ama aynı zamanda 'giderli' bir abisin/ablasın. Hem ilham veren hem de 'akıllı ol' diyen bir söz söyle.", "Bana gaz ver biraz.")
async def cmd_zar_at(update, context): await context.bot.send_dice(chat_id=update.callback_query.message.chat_id)
async def cmd_profil_goster(update, context): await update.callback_query.message.reply_text(imzali(f"👤 Profilin: {update.callback_query.from_user.first_name}. Benden daha havalı olamazsın, boşuna uğraşma. 😉"))
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID: return
    text = "🔐 Kurucu paneline hoş geldin!"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=get_admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    else: await update.message.reply_text(text, reply_markup=get_admin_menu_keyboard(), parse_mode=ParseMode.HTML)
async def admin_stats(update, context): await show_menu(update, context, f"📊 İstatistikler:\n- Kullanıcı: {len(users)}\n- Grup: {len(groups)}", get_admin_menu_keyboard())
async def admin_save_data(update, context): save_json({uid: u.__dict__ for uid, u in users.items()}, USERS_FILE); save_json(groups, GROUPS_FILE); await update.callback_query.answer("✅ Veriler diske kaydedildi!", show_alert=True)
async def admin_list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not groups: await query.answer("Bot henüz bir gruba eklenmemiş.", show_alert=True); return
    keyboard = [[InlineKeyboardButton(g_data['title'], callback_data=f"grp_msg_{gid}")] for gid, g_data in groups.items()]
    keyboard.append([InlineKeyboardButton("◀️ Geri", callback_data="admin_panel_main")])
    await show_menu(update, context, "Mesaj göndermek için bir grup seç:", InlineKeyboardMarkup(keyboard))
async def ask_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_id = int(update.callback_query.data.split('_')[-1]); context.user_data['target_group_id'] = group_id; group_name = groups.get(group_id, {}).get('title', 'Bilinmeyen Grup')
    await show_menu(update, context, f"'{group_name}' grubuna göndermek için mesajınızı yazın.", None); return GET_GROUP_MSG
async def send_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_id = context.user_data.pop('target_group_id', None)
    try: await context.bot.send_message(chat_id=group_id, text=update.message.text); await update.message.reply_text("✅ Mesaj gönderildi.")
    except Exception as e: await update.message.reply_text(f"❌ Hata: {e}")
    await admin_panel(update, context); return ConversationHandler.END
async def ask_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_menu(update, context, "📣 Tüm kullanıcılara göndermek istediğiniz duyuru mesajını yazın.", None); return GET_BROADCAST_MSG
async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['broadcast_message'] = update.message.text
    keyboard = [[InlineKeyboardButton("✅ EVET, GÖNDER", callback_data="broadcast_send_confirm")], [InlineKeyboardButton("❌ HAYIR, İPTAL", callback_data="admin_panel_main")]]; await update.message.reply_text(f"DİKKAT! Bu mesaj {len(users)} kullanıcıya gönderilecek. Emin misin?\n\n---\n{update.message.text}\n---", reply_markup=InlineKeyboardMarkup(keyboard)); return BROADCAST_CONFIRM
async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message_text = context.user_data.pop('broadcast_message', None); await update.callback_query.edit_message_text("🚀 Duyuru gönderimi başladı...", reply_markup=None); sent, failed = 0, 0
    for user_id in list(users.keys()):
        try: await context.bot.send_message(chat_id=user_id, text=message_text); sent += 1; await asyncio.sleep(0.1)
        except Exception: failed += 1
    await update.callback_query.message.reply_text(f"✅ Duyuru tamamlandı.\nBaşarılı: {sent}\nHatalı: {failed}"); await admin_panel(update, context); return ConversationHandler.END
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear(); await update.message.reply_text("İşlem iptal edildi."); await admin_panel(update, context); return ConversationHandler.END
async def record_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in groups or groups[chat_id]['title'] != update.effective_chat.title:
        groups[chat_id] = {'title': update.effective_chat.title}; save_json(groups, GROUPS_FILE)
        logger.info(f"Grup tanındı/güncellendi: {update.effective_chat.title} ({chat_id})")

# --- BOTU BAŞLATMA ---
def run():
    if not TELEGRAM_TOKEN: logger.critical("TELEGRAM_TOKEN .env dosyasında bulunamadı!"); return
    load_data()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # --- YENİ: Zamanlanmış Görevler ---
    job_queue = app.job_queue
    # Saat dilimini Türkiye olarak ayarlıyoruz
    turkey_tz = pytz.timezone("Europe/Istanbul")
    # Her sabah 09:00'da çalışacak şekilde ayarla
    job_queue.run_daily(send_morning_message, time=time(hour=9, minute=0, tzinfo=turkey_tz), name="gunaydin_mesaji")
    
    # İZOLE CONVERSATION HANDLER'LAR
    group_msg_handler = ConversationHandler(entry_points=[CallbackQueryHandler(ask_group_message, pattern="^grp_msg_")], states={GET_GROUP_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_group_message)]}, fallbacks=[CommandHandler("iptal", cancel_conversation), CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$")])
    broadcast_handler = ConversationHandler(entry_points=[CallbackQueryHandler(ask_broadcast_message, pattern="^admin_broadcast_ask$")], states={GET_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_broadcast)], BROADCAST_CONFIRM: [CallbackQueryHandler(do_broadcast, pattern="^broadcast_send_confirm$")]}, fallbacks=[CommandHandler("iptal", cancel_conversation), CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$")])

    # --- Handler'ları Ekleme ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(group_msg_handler)
    app.add_handler(broadcast_handler)
    app.add_handler(CallbackQueryHandler(show_eglence_menu, pattern="^menu_eglence$"))
    app.add_handler(CallbackQueryHandler(show_diger_menu, pattern="^menu_diger$"))
    app.add_handler(CallbackQueryHandler(start, pattern="^menu_main$"))
    app.add_handler(CallbackQueryHandler(show_nedir, pattern="^cb_nedir$"))
    app.add_handler(CallbackQueryHandler(ai_fikra_anlat, pattern="^ai_fikra$"))
    app.add_handler(CallbackQueryHandler(ai_siir_oku, pattern="^ai_siir$"))
    app.add_handler(CallbackQueryHandler(ai_alinti_gonder, pattern="^ai_alinti$"))
    app.add_handler(CallbackQueryHandler(cmd_zar_at, pattern="^cmd_zar$"))
    app.add_handler(CallbackQueryHandler(cmd_profil_goster, pattern="^cmd_profil$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel_main$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_save_data, pattern="^admin_save$"))
    app.add_handler(CallbackQueryHandler(admin_list_groups, pattern="^admin_list_groups$"))
    
    # === GRUP VE ÖZEL MESAJLARI AYNI FONKSİYONLA YÖNETME ===
    # Not: Botun grupta çok konuşkan olmasını istemiyorsanız, bu satırı aşağıdaki yorumlu satırla değiştirin.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # Sadece botun etiketlendiği veya cevap verildiği mesajlara yanıt vermesi için:
    # from telegram import MessageEntity
    # app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.ChatType.PRIVATE | filters.REPLY | filters.Entity(MessageEntity.MENTION)), handle_text))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, record_group_chat)) # Bot gruba eklendiğinde de tanır
    
    logger.info("Motivasyon Jarvis (v9.0 - Proaktif Kişilik) başarıyla başlatıldı!")
    app.run_polling()

if __name__ == '__main__':
    try: run()
    except Exception as e: logger.critical(f"Kritik hata: {e}", exc_info=True)
    finally: save_json({uid: u.__dict__ for uid, u in users.items()}, USERS_FILE); save_json(groups, GROUPS_FILE); logger.info("Bot durduruluyor, veriler kaydedildi.")