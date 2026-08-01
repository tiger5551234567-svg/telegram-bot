import os
import logging
import json
import uuid
import random
import platform
import html
import re
import asyncio
import traceback
import aiosqlite
import aiogram
from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ReplyKeyboardRemove
)
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

API_TOKEN = os.getenv("API_TOKEN", "8801853413:AAHO6rkMZLICKRyFF4AAiv0PUnHl1VVQZmA")
if not API_TOKEN:
    raise ValueError("❌ ОШИБКА: Токен бота не задан!")

IPC_CHAT_ID = int(os.getenv("IPC_CHAT_ID", "0"))
MY_ID = 8393374655
DB_PATH = "sentinel_core.db"
BAN_WORDS = ["продаю", "купить", "гарант", "скам", "казино", "крипта"]

SECRETARY_ROASTS = [
    "Связь с администрацией — это привилегия, а не право, {name}. Твой высер принят.",
    "Очередное гениальное послание от {name}. Передано операторам, пусть порвут живот со смеху.",
    "Твое сообщение отправлено в архив... то есть в мусорную корзину к твоим амбициям, {name}.",
    "Интересная мысль, {name}. Жаль, что системе на неё абсолютно плевать, но я зафиксировал.",
    "Сигнал принят и успешно проигнорирован. Попробуй еще раз, вдруг повезет.",
    "Текст зашифрован, проанализирован и признан занудным. Передано в штаб чисто поржать.",
    "Поток бессмыслицы от агента {name} успешно зафиксирован в наших логах."
]

SENTINEL_REPLIES = [
    "Я здесь, система держит руку на пульсе. Периметр под контролем, Босс.",
    "Чего изволите, Босс? Мои процессоры полностью к вашим услугам.",
    "Системы активны. Если это не по делу — лучше молчите, хотя я весь вниманию.",
    "На связи. Все узлы сети работают как швейцарские часы.",
    "Жду приказов, Босс. Защитный контур готов к работе.",
    "Ядра разогреты до предела. Что нужно сделать?",
    "Сканирование пространства завершено. Всё спокойно."
]

class AdminStates(StatesGroup):
    waiting_for_reply = State()

boss_inline_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="menu_status"),
            InlineKeyboardButton(text="📈 Метрики", callback_data="menu_metrics")
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu_boss_profile"),
            InlineKeyboardButton(text="🚫 Чёрный список", callback_data="menu_blacklist")
        ],
        [
            InlineKeyboardButton(text="📜 История переписок", callback_data="menu_users_history")
        ],
        [
            InlineKeyboardButton(text="🚀 Команды", callback_data="menu_commands"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")
        ],
        [
            InlineKeyboardButton(text="🏓 Пинг", callback_data="menu_ping"),
            InlineKeyboardButton(text="🚨 Lockdown", callback_data="menu_lockdown")
        ],
        [
            InlineKeyboardButton(text="🛠 Техобслуживание", callback_data="menu_maint")
        ]
    ]
)

user_inline_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать администрации", callback_data="user_write")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="user_profile")]
    ]
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("sentinel_system.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=MemoryStorage())

message_cache = {}
user_last_message_time = {}
flood_counter = {}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                messages_sent INTEGER DEFAULT 0,
                spam_detected INTEGER DEFAULT 0,
                warnings INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                notifications INTEGER DEFAULT 1,
                stealth_mode INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS keys_storage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                api_key TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_chats (
                chat_id INTEGER PRIMARY KEY
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_states (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                sender_type TEXT,
                message_text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def get_system_state(key: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM system_states WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False

async def set_system_state(key: str, value: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO system_states (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, 1 if value else 0)
        )
        await db.commit()

async def log_chat_history(user_id: int, sender_type: str, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, sender_type, message_text) VALUES (?, ?, ?)",
            (user_id, sender_type, text)
        )
        await db.commit()

async def get_chat_history_for_user(user_id: int, limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT sender_type, message_text, timestamp 
            FROM chat_history 
            WHERE user_id = ? 
            ORDER BY id DESC 
            LIMIT ?
            """,
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return rows[::-1]

async def get_all_users_for_admin(limit: int = 25):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT user_id, first_name, username, messages_sent, is_banned 
            FROM users 
            ORDER BY messages_sent DESC 
            LIMIT ?
            """,
            (limit,)
        ) as cursor:
            return await cursor.fetchall()

async def get_user_stats(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT first_name, username, messages_sent, spam_detected, warnings, is_banned FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "first_name": row[0],
                    "username": row[1],
                    "messages_sent": row[2],
                    "spam_detected": row[3],
                    "warnings": row[4],
                    "is_banned": row[5]
                }
            return None

async def get_user_by_identifier(identifier: str):
    async with aiosqlite.connect(DB_PATH) as db:
        if identifier.isdigit():
            async with db.execute("SELECT user_id, first_name, username, messages_sent, spam_detected, warnings, is_banned FROM users WHERE user_id = ?", (int(identifier),)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {"user_id": row[0], "first_name": row[1], "username": row[2], "messages_sent": row[3], "spam_detected": row[4], "warnings": row[5], "is_banned": row[6]}
        
        clean_username = identifier.lstrip('@')
        async with db.execute("SELECT user_id, first_name, username, messages_sent, spam_detected, warnings, is_banned FROM users WHERE username LIKE ?", (f"%{clean_username}%",)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"user_id": row[0], "first_name": row[1], "username": row[2], "messages_sent": row[3], "spam_detected": row[4], "warnings": row[5], "is_banned": row[6]}
                
    return None

async def update_user_stats(user_id: int, first_name: str, username: str, inc_msg=0, inc_spam=0, inc_warn=0, set_ban=None, clear_warns=False):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, first_name, username, messages_sent, spam_detected, warnings, is_banned)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = excluded.first_name,
                username = excluded.username,
                messages_sent = messages_sent + ?,
                spam_detected = spam_detected + ?,
                warnings = warnings + ?
        """, (user_id, first_name, username, inc_msg, inc_spam, inc_warn, inc_msg, inc_spam, inc_warn))
        
        if set_ban is not None:
            await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (1 if set_ban else 0, user_id))
        
        if clear_warns:
            await db.execute("UPDATE users SET warnings = 0 WHERE user_id = ?", (user_id,))
            
        await db.commit()

async def track_activity(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO active_chats (chat_id) VALUES (?)", (message.chat.id,))
        await db.commit()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await track_activity(message)
    user_id = message.from_user.id
    name = message.from_user.first_name or "Странник"
    username = message.from_user.username or ""

    stats = await get_user_stats(user_id)
    if stats and stats["is_banned"] and user_id != MY_ID:
        return

    if not stats and user_id != MY_ID:
        try:
            await message.bot.send_message(
                MY_ID,
                f"🔔 <b>Новый агент в системе!</b>\n\n• Имя: {html.escape(name)}\n• ID: <code>{user_id}</code>\n• Username: @{html.escape(username) if username else 'отсутствует'}"
            )
        except Exception:
            pass

    await update_user_stats(user_id, name, username)
    clean_markup = ReplyKeyboardRemove()

    await bot.send_chat_action(message.chat.id, "typing")
    await asyncio.sleep(0.6)

    if message.chat.type == "private":
        if user_id == MY_ID:
            text = "🛡 <b>Командный центр активирован, Босс.</b>\n\nИспользуйте интерактивную панель ниже:"
            await message.answer(text, reply_markup=clean_markup)
            await message.answer("🛠 <b>Панель управления:</b>", reply_markup=boss_inline_menu)
        else:
            text = f"😎 <b>Здарова, {html.escape(name)}. Я Sentinel — автономный защитный страж.</b>\n\nВыберите действие в меню:"
            await message.answer(text, reply_markup=clean_markup)
            await message.answer("👇 Доступные действия:", reply_markup=user_inline_menu)
    else:
        await message.answer("🛡 <b>Sentinel активирован в этом чате. Периметр под защитой.</b>", reply_markup=clean_markup)

@dp.message(
    lambda message: (message.text or message.caption)
    and ("🚨 ОТЧЕТ БЕЗОПАСНОСТИ: НОВЫЙ БЛОК" in (message.text or message.caption))
)
async def handle_block_report(message: Message):
    text_to_check = message.text or message.caption or ""
    logging.info(f"[BOT_RECEIVED] Получен отчёт безопасности от пользователя ID: {message.from_user.id}")
    
    match = re.search(r"(?:ID|Telegram ID):\s*(\d+)", text_to_check)
    target_id = int(match.group(1)) if match else 0
    
    if target_id:
        message_cache[message.message_id] = target_id

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔓 Разблокировать", callback_data=f"rep_unblock_{target_id}"),
                InlineKeyboardButton(text="➕ Добавить в контакты", callback_data=f"rep_contact_{target_id}")
            ],
            [
                InlineKeyboardButton(text="❌ Проигнорировать", callback_data="rep_ignore")
            ]
        ]
    )
    
    sent_msg = await message.answer("Принято, выберите действие:", reply_markup=keyboard)
    if target_id:
        message_cache[sent_msg.message_id] = target_id
    
    logging.info(f"[BOT_PROCESSED] Отчёт безопасности обработан, клавиатура добавлена (Target ID: {target_id})")

@dp.callback_query()
async def callback_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = callback.data
    request_id = uuid.uuid4().hex

    if user_id == MY_ID:
        if data.startswith("admin_hist_"):
            try:
                target_id = int(data.split("_")[2])
            except (IndexError, ValueError):
                await callback.answer("⚠️ Ошибка ID.", show_alert=True)
                return

            history = await get_chat_history_for_user(target_id, limit=10)
            if not history:
                await callback.message.edit_text(
                    f"📭 История диалога с агентом <code>{target_id}</code> пуста.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад к списку", callback_data="menu_users_history")]])
                )
                await callback.answer()
                return

            text = f"📜 <b>История диалога с агентом <code>{target_id}</code>:</b>\n\n"
            for sender_type, msg_text, timestamp in history:
                prefix = "👤 <b>Пользователь:</b>" if sender_type == "user" else "👑 <b>Админ:</b>"
                safe_text = html.escape(msg_text)
                if len(safe_text) > 200:
                    safe_text = safe_text[:200] + "..."
                text += f"{prefix} <i>({timestamp})</i>\n{safe_text}\n\n"

            back_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад к списку", callback_data="menu_users_history")]])
            await callback.message.edit_text(text, reply_markup=back_markup)
            await callback.answer()
            return

        if data == "menu_users_history":
            users = await get_all_users_for_admin(limit=25)
            if not users:
                await callback.answer("📭 В базе пока нет ни одного агента.", show_alert=True)
                return

            buttons = []
            for uid, fname, uname, msgs, banned in users:
                banned_icon = "🚫 " if banned else "✅ "
                username_str = f"@{uname}" if uname else f"ID:{uid}"
                btn_text = f"{banned_icon}{fname or 'Без имени'} | {username_str} ({msgs} сообщ.)"
                buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_hist_{uid}")])

            buttons.append([InlineKeyboardButton(text="« Главное меню", callback_data="menu_back_main")])
            
            users_markup = InlineKeyboardMarkup(inline_keyboard=buttons)
            await callback.message.edit_text("👥 <b>Выберите агента для просмотра истории переписки:</b>", reply_markup=users_markup)
            await callback.answer()
            return

        if data == "menu_back_main":
            await callback.message.edit_text("🛠 <b>Панель управления:</b>", reply_markup=boss_inline_menu)
            await callback.answer()
            return

        if data.startswith("rep_"):
            try:
                action, target_id_str = data.rsplit("_", 1)
                target_id = int(target_id_str)
            except (ValueError, AttributeError):
                if data == "rep_ignore":
                    await callback.message.edit_reply_markup(reply_markup=None)
                    await callback.message.answer("❌ Отчёт проигнорирован.")
                    await callback.answer()
                    return
                await callback.answer("⚠️ Ошибка обработки.", show_alert=True)
                return

            if action == "rep_reply":
                await state.set_state(AdminStates.waiting_for_reply)
                await state.update_data(target_id=target_id)
                await callback.message.answer(f"💬 Введите ответ для пользователя <code>{target_id}</code> следующим сообщением:")
                await callback.answer()
                
            elif action == "rep_ban":
                stats = await get_user_stats(target_id)
                fname = stats["first_name"] if stats else "Unknown"
                uname = stats["username"] if stats else ""
                await update_user_stats(target_id, fname, uname, set_ban=True)
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.answer(f"🚫 Пользователь <code>{target_id}</code> успешно заблокирован через уведомление.")
                await callback.answer()
                
            elif action == "rep_unblock":
                await callback.message.edit_reply_markup(reply_markup=None)
                payload = {"type": "command", "action": "unblock", "user_id": target_id, "request_id": request_id}
                if IPC_CHAT_ID != 0:
                    await bot.send_message(IPC_CHAT_ID, json.dumps(payload, ensure_ascii=False))
                await callback.message.answer(f"🔓 Команда разблокировки отправлена (ID: <code>{request_id[:8]}</code>)")
                await callback.answer()
                
            elif action == "rep_contact":
                await callback.message.edit_reply_markup(reply_markup=None)
                payload = {"type": "command", "action": "add_contact", "user_id": target_id, "request_id": request_id}
                if IPC_CHAT_ID != 0:
                    await bot.send_message(IPC_CHAT_ID, json.dumps(payload, ensure_ascii=False))
                await callback.message.answer(f"➕ Команда добавления в контакты отправлена (ID: <code>{request_id[:8]}</code>)")
                await callback.answer()
            return

        if data == "menu_status":
            await callback.message.edit_text(
                "🛡 <b>Статус защитного ядра Sentinel:</b>\n\n• Режим защиты: <b>Активно 🔒</b>\n• Статус сети: <b>Онлайн / БД активна ✅</b>",
                reply_markup=boss_inline_menu
            )
        elif data == "menu_metrics":
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*), SUM(messages_sent), SUM(spam_detected) FROM users") as cursor:
                    res = await cursor.fetchone()
                    total_users, total_msgs, total_violations = res[0] or 0, res[1] or 0, res[2] or 0
            await callback.message.edit_text(
                f"📊 <b>Метрики сети Sentinel:</b>\n\n• Уникальных агентов: <code>{total_users}</code>\n• Всего сообщений: <code>{total_msgs}</code>\n• Отражено атак: <code>{total_violations}</code>",
                reply_markup=boss_inline_menu
            )
        elif data == "menu_boss_profile":
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT SUM(messages_sent), SUM(spam_detected) FROM users") as cursor:
                    res = await cursor.fetchone()
                    global_msgs, global_spam = res[0] or 0, res[1] or 0
            await callback.message.edit_text(
                f"👤 <b>Профиль Главного Администратора (Босса):</b>\n\n"
                f"• ID: <code>{MY_ID}</code>\n"
                f"• Статус: <b>Создатель / Высший узел 👑</b>\n"
                f"• Глобальная репутация: <b>Безупречна ⭐</b>\n"
                f"• Проконтролировано сообщений в сети: <code>{global_msgs}</code>\n"
                f"• Всего пресечено угроз/спама: <code>{global_spam}</code>",
                reply_markup=boss_inline_menu
            )
        elif data == "menu_blacklist":
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id, first_name, username FROM users WHERE is_banned = 1") as cursor:
                    banned_users = await cursor.fetchall()
            
            if not banned_users:
                text = "🚫 <b>Чёрный список пуст.</b> Заблокированных агентов нет."
            else:
                text = "🚫 <b>Список заблокированных агентов:</b>\n\n"
                for uid, fname, uname in banned_users:
                    username_str = f"@{uname}" if uname else "нет username"
                    text += f"• <code>{uid}</code> | {html.escape(fname or 'Без имени')} ({username_str})\n"
            
            await callback.message.edit_text(text, reply_markup=boss_inline_menu)
        elif data == "menu_settings":
            await callback.message.edit_text("⚙️ <b>Системные настройки:</b> база данных работает в штатном режиме.", reply_markup=boss_inline_menu)
        elif data == "menu_ping":
            await callback.answer("🏓 Шлюз функционирует стабильно!", show_alert=True)
            return
        elif data == "menu_commands":
            commands_text = (
                "🚀 <b>Хранилище административных команд:</b>\n\n"
                "• /status — Проверка статуса ядра\n"
                "• /metrics — Сводка метрик из базы данных\n"
                "• /profile — Просмотр профиля\n"
                "• /ping — Тест задержки отклика\n"
                "• /sysinfo — Информация о системе и ОС\n"
                "• /lookup &lt;id / @username&gt; — Глубокая пробивка агента\n"
                "• /warn &lt;id / @username&gt; — Выдать предупреждение\n"
                "• /ban &lt;id / @username&gt; — Заблокировать агента\n"
                "• /unban &lt;id / @username&gt; — Разблокировать агента\n"
                "• /clearwarns &lt;id / @username&gt; — Сбросить предупреждения\n"
                "• /broadcast &lt;текст&gt; — Рассылка по всем чатам и ЛС"
            )
            await callback.message.answer(commands_text)
        elif data == "menu_lockdown":
            current_lockdown = await get_system_state("lockdown_mode")
            new_lockdown = not current_lockdown
            await set_system_state("lockdown_mode", new_lockdown)
            await callback.answer(f"🔒 Lockdown: {'ВКЛ' if new_lockdown else 'ВЫКЛ'}", show_alert=True)
            return
        elif data == "menu_maint":
            current_maint = await get_system_state("maintenance_mode")
            new_maint = not current_maint
            await set_system_state("maintenance_mode", new_maint)
            await callback.answer(f"🛠 Техобслуживание: {'ВКЛ' if new_maint else 'ВЫКЛ'}", show_alert=True)
            return
    else:
        if data == "user_write":
            await callback.message.answer("💬 Введите ваше сообщение (текст или медиа), и оно будет передано администрации.")
        elif data == "user_profile":
            stats = await get_user_stats(user_id)
            history = await get_chat_history_for_user(user_id, limit=5)
            
            profile_text = f"👤 <b>Ваш цифровой профиль:</b>\n\n• Сообщений отправлено: <code>{stats['messages_sent'] if stats else 0}</code>\n• Нарушений: <code>{stats['spam_detected'] if stats else 0}</code>\n• Варны: <b>{stats['warnings'] if stats else 0} / 3</b>\n\n"
            
            if history:
                profile_text += "📜 <b>Ваши последние сообщения:</b>\n"
                for sender_type, msg_text, timestamp in history:
                    prefix = "Вы:" if sender_type == "user" else "Админ:"
                    profile_text += f"• <i>{timestamp}</i> [{prefix}] {html.escape(msg_text[:50])}\n"
            else:
                profile_text += "📭 История сообщений пуста."

            await callback.message.answer(profile_text)
    await callback.answer()

@dp.message(Command("status"))
async def cmd_status(message: Message):
    await track_activity(message)
    await bot.send_chat_action(message.chat.id, "typing")
    await asyncio.sleep(0.4)
    await message.answer("🛡 <b>Защитное ядро Sentinel функционирует стабильно (SQLite БД активна).</b>")

@dp.message(Command("metrics"))
async def cmd_metrics(message: Message):
    await track_activity(message)
    await bot.send_chat_action(message.chat.id, "typing")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), SUM(messages_sent), SUM(spam_detected) FROM users") as cursor:
            res = await cursor.fetchone()
            total_users, total_msgs, total_violations = res[0] or 0, res[1] or 0, res[2] or 0
    await asyncio.sleep(0.4)
    await message.answer(f"📊 <b>Метрики базы данных:</b>\n\n• Всего агентов: <code>{total_users}</code>\n• Сообщений: <code>{total_msgs}</code>\n• Нарушений: <code>{total_violations}</code>")

@dp.message(Command("profile"))
async def cmd_user_profile(message: Message):
    await track_activity(message)
    await bot.send_chat_action(message.chat.id, "typing")
    user = message.from_user
    stats = await get_user_stats(user.id)
    await asyncio.sleep(0.4)
    if not stats:
        await message.answer("👤 Профиль не найден в базе.")
        return
    await message.answer(f"👤 <b>Профиль:</b>\n• Сообщений: <code>{stats['messages_sent']}</code>\n• Нарушений: <code>{stats['spam_detected']}</code>\n• Варны: <b>{stats['warnings']} / 3</b>")

@dp.message(Command("ping"))
async def cmd_ping(message: Message):
    loop = asyncio.get_running_loop()
    start = loop.time()
    sent = await message.answer("🏓 Проверка отклика...")
    end = loop.time()
    await sent.edit_text(f"🏓 <b>Понг!</b> Задержка: <code>{int((end - start) * 1000)} мс</code>")

@dp.message(Command("sysinfo"))
async def cmd_sysinfo(message: Message):
    if message.from_user.id != MY_ID:
        return
    await bot.send_chat_action(message.chat.id, "typing")
    await asyncio.sleep(0.4)
    await message.answer(f"💻 <b>ОС:</b> {platform.system()} {platform.release()}\n• <b>Python:</b> {platform.python_version()}\n• <b>Aiogram:</b> {aiogram.__version__}")

@dp.message(Command("lookup"))
async def cmd_lookup(message: Message):
    if message.from_user.id != MY_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Укажите ID или юзернейм: <code>/lookup &lt;id / @username&gt;</code>")
        return
    
    await bot.send_chat_action(message.chat.id, "typing")
    target = args[1]
    stats = await get_user_by_identifier(target)
    await asyncio.sleep(0.4)
    if not stats:
        await message.answer(f"❌ Агент <code>{html.escape(target)}</code> не найден в базе данных.")
        return
    
    status_str = "🚫 Заблокирован" if stats["is_banned"] else "✅ Активен"
    profile_info = (
        f"🔍 <b>Глубокая пробивка агента:</b>\n\n"
        f"• ID: <code>{stats['user_id']}</code>\n"
        f"• Имя: {html.escape(stats['first_name'] or 'Неизвестно')}\n"
        f"• Username: @{html.escape(stats['username'] if stats['username'] else 'отсутствует')}\n"
        f"• Статус в системе: <b>{status_str}</b>\n"
        f"• Отправлено сообщений: <code>{stats['messages_sent']}</code>\n• Нарушений (спам): <code>{stats['spam_detected']}</code>\n"
        f"• Получено варнов: <b>{stats['warnings']} / 3</b>"
    )
    await message.answer(profile_info)

@dp.message(Command("warn"))
async def cmd_warn_user(message: Message):
    if message.from_user.id != MY_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Укажите ID или юзернейм: <code>/warn &lt;id / @username&gt;</code>")
        return
    
    target = args[1]
    stats = await get_user_by_identifier(target)
    if not stats:
        await message.answer(f"❌ Агент <code>{html.escape(target)}</code> не найден в базе данных.")
        return
    
    target_id = stats["user_id"]
    new_warns = stats["warnings"] + 1
    if new_warns >= 3:
        await update_user_stats(target_id, stats["first_name"], stats["username"], inc_warn=1, set_ban=True)
        await message.answer(f"⚠️ Агенту <code>{target_id}</code> (@{stats['username'] or 'нет'}) выписан варн. Лимит исчерпан (3/3), агент <b>автоматически заблокирован</b>.")
    else:
        await update_user_stats(target_id, stats["first_name"], stats["username"], inc_warn=1)
        await message.answer(f"⚠️ Агенту <code>{target_id}</code> (@{stats['username'] or 'нет'}) выписан варн. Текущие варны: <b>{new_warns} / 3</b>.")

@dp.message(Command("ban"))
async def cmd_ban_user(message: Message):
    if message.from_user.id != MY_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Укажите ID или юзернейм: <code>/ban &lt;id / @username&gt;</code>")
        return
    
    target = args[1]
    stats = await get_user_by_identifier(target)
    if not stats:
        if target.isdigit():
            target_id = int(target)
            await update_user_stats(target_id, "Unknown", "", set_ban=True)
            await message.answer(f"🚫 Пользователь <code>{target_id}</code> заблокирован в базе.")
        else:
            await message.answer(f"❌ Агент <code>{html.escape(target)}</code> не найден в базе данных.")
        return
    
    await update_user_stats(stats["user_id"], stats["first_name"], stats["username"], set_ban=True)
    await message.answer(f"🚫 Пользователь <code>{stats['user_id']}</code> (@{stats['username'] or 'нет'}) заблокирован в базе.")

@dp.message(Command("unban"))
async def cmd_unban_user(message: Message):
    if message.from_user.id != MY_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Укажите ID или юзернейм: <code>/unban &lt;id / @username&gt;</code>")
        return
    
    target = args[1]
    stats = await get_user_by_identifier(target)
    if not stats:
        if target.isdigit():
            target_id = int(target)
            await update_user_stats(target_id, "Unknown", "", set_ban=False, clear_warns=True)
            await message.answer(f"✅ Пользователь <code>{target_id}</code> разблокирован, варны сброшены.")
        else:
            await message.answer(f"❌ Агент <code>{html.escape(target)}</code> не найден в базе данных.")
        return
    
    await update_user_stats(stats["user_id"], stats["first_name"], stats["username"], set_ban=False, clear_warns=True)
    await message.answer(f"✅ Пользователь <code>{stats['user_id']}</code> (@{stats['username'] or 'нет'}) разблокирован, варны сброшены.")

@dp.message(Command("clearwarns"))
async def cmd_clear_warns(message: Message):
    if message.from_user.id != MY_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Укажите ID или юзернейм: <code>/clearwarns &lt;id / @username&gt;</code>")
        return
    
    target = args[1]
    stats = await get_user_by_identifier(target)
    if not stats:
        if target.isdigit():
            target_id = int(target)
            await update_user_stats(target_id, "Unknown", "", clear_warns=True)
            await message.answer(f"🧹 Варны пользователя <code>{target_id}</code> сброшены до нуля.")
        else:
            await message.answer(f"❌ Агент <code>{html.escape(target)}</code> не найден в базе данных.")
        return
    
    await update_user_stats(stats["user_id"], stats["first_name"], stats["username"], clear_warns=True)
    await message.answer(f"🧹 Варны пользователя <code>{stats['user_id']}</code> (@{stats['username'] or 'нет'}) успешно сброшены до нуля.")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != MY_ID:
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Укажите текст рассылки: <code>/broadcast Ваш текст</code>")
        return
    text_to_send = args[1]
    success, fail = 0, 0
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id FROM active_chats") as cursor:
            chats = await cursor.fetchall()
            for (cid,) in chats:
                if cid == MY_ID:
                    continue
                try:
                    await message.bot.send_message(cid, text_to_send)
                    success += 1
                except Exception:
                    fail += 1
    await message.answer(f"📢 <b>Рассылка завершена.</b>\n• Успешно: <code>{success}</code>\n• Ошибок: <code>{fail}</code>")

async def main():
    await init_db()
    logging.info("[SYSTEM] База данных инициализирована. Запуск бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
