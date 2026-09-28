import asyncio
import html
import random
import aiosqlite
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, \
    KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

import config_7

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
router = Router()


# ================= СОСТОЯНИЯ (FSM) =================
class OrderForm(StatesGroup):
    choosing_cat = State()
    choosing_sub = State()
    choosing_extras = State()
    writing_desc = State()


class PaymentForm(StatesGroup):
    waiting_for_receipt = State()


class ArtistAction(StatesGroup):
    waiting_for_sketch = State()
    waiting_for_order_id_msg = State()
    waiting_for_message = State()


class ClientAction(StatesGroup):
    waiting_for_feedback = State()


class SupportForm(StatesGroup):
    waiting_for_msg = State()


class TechAdminFSM(StatesGroup):
    replying_to_ticket = State()
    choosing_user_for_ban = State()
    choosing_user_for_close = State()
    choosing_user_pugovka_give = State()
    choosing_user_pugovka_remove = State()
    choosing_button_to_remove = State()
    choosing_button_to_give = State()


# ================= MIDDLEWARE (АНТИ-БАН) =================
class BanCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = event.from_user.id if event.from_user else None
        if user_id:
            if user_id in config.TECH_IDS or user_id in config.ARTIST_IDS:
                return await handler(event, data)

            async with aiosqlite.connect("orders.db") as db:
                cursor = await db.execute("SELECT is_banned, lang FROM users WHERE user_id = ?", (user_id,))
                row = await cursor.fetchone()
                if row and row[0] == 1:
                    lang = row[1] if row[1] else "ru"
                    if isinstance(event, Message):
                        await event.answer(config.TEXTS[lang]["banned_msg"])
                    elif isinstance(event, CallbackQuery):
                        await event.answer(config.TEXTS[lang]["banned_msg"], show_alert=True)
                    return
        return await handler(event, data)


dp.message.middleware(BanCheckMiddleware())
dp.callback_query.middleware(BanCheckMiddleware())


# ================= БАЗА ДАННЫХ =================
async def init_db():
    async with aiosqlite.connect("orders.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                details TEXT,
                price REAL,
                status TEXT,
                used_btn_id INTEGER DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                loyal_orders_count INTEGER DEFAULT 0,
                lang TEXT DEFAULT 'ru',
                is_banned INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                button_type TEXT,
                is_used INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                question TEXT,
                answer TEXT,
                status TEXT DEFAULT 'open'
            )
        """)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
        except:
            pass
        await db.commit()


async def get_user_lang(user_id: int) -> str:
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else "ru"


async def set_user_lang(user_id: int, lang: str):
    async with aiosqlite.connect("orders.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, lang) VALUES (?, ?)", (user_id, lang))
        await db.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))
        await db.commit()


async def has_active_order(user_id: int):
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute(
            "SELECT id, status FROM orders WHERE user_id = ? AND status NOT IN ('closed', 'cancelled')", (user_id,))
        return await cursor.fetchone()


async def send_to_channel(channel_id: int, text: str, photo_id: str = None):
    if not channel_id:
        return
    try:
        if photo_id:
            await bot.send_photo(channel_id, photo=photo_id, caption=text, parse_mode="HTML")
        else:
            await bot.send_message(channel_id, text, parse_mode="HTML")
    except Exception:
        pass


# ================= ДОСЬЕ И СПИСКИ ПОЛЬЗОВАТЕЛЕЙ =================
async def get_user_dossier(user_id: int) -> str:
    async with aiosqlite.connect("orders.db") as db:
        cur = await db.execute(
            "SELECT username, lang, is_banned, loyal_orders_count FROM users WHERE user_id = ?", (user_id,))
        u = await cur.fetchone()

        cur = await db.execute(
            "SELECT id, price, status, details FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,)
        )
        orders = await cur.fetchall()

        cur = await db.execute(
            "SELECT id, button_type, is_used FROM inventory WHERE user_id = ? ORDER BY id DESC", (user_id,)
        )
        inv = await cur.fetchall()

    username = u[0] if u and u[0] else f"ID: {user_id}"
    lang = u[1] if u else "ru"
    is_banned = u[2] if u else 0
    loyal = u[3] if u else 0

    total_orders = len(orders)
    paid_orders = [o for o in orders if o[2] in ("paid", "closed")]
    total_sum = sum(o[1] or 0 for o in paid_orders)
    active_orders = [o for o in orders if o[2] in ("awaiting_payment", "paid")]

    active_btns = [b for b in inv if b[2] == 0]
    used_btns = [b for b in inv if b[2] == 1]

    banned_str = "🚫 ЗАБАНЕН" if is_banned else "✅ Активен"
    curr_sym = config.TEXTS[lang]["curr_sym"]

    text = (
        f"👤 <b>Досье пользователя</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<b>Ник:</b> {html.escape(username)}\n"
        f"<b>ID:</b> <code>{user_id}</code>\n"
        f"<b>Статус:</b> {banned_str}\n"
        f"<b>Язык:</b> {lang.upper()}\n"
        f"<b>Прогресс лояльности:</b> {loyal % 6}/6\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📦 <b>Всего заказов:</b> {total_orders}\n"
        f"✅ <b>Оплачено/закрыто:</b> {len(paid_orders)}\n"
        f"🔵 <b>Активных:</b> {len(active_orders)}\n"
        f"💰 <b>Потрачено:</b> {total_sum:g}{curr_sym}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Пуговок в наличии:</b> {len(active_btns)}\n"
        f"🗑 <b>Использовано:</b> {len(used_btns)}\n"
    )

    if active_btns:
        text += "\n<b>Активные пуговки:</b>\n"
        for b in active_btns[:10]:
            info = config.BUTTONS_INFO.get(b[1])
            if info:
                text += f"  • #{b[0]} {info['name']['ru']}\n"

    if active_orders:
        text += "\n<b>Активные заказы:</b>\n"
        for o in active_orders:
            text += f"  • №{o[0]} | {o[1]:g}{curr_sym} | {o[2]}\n"

    return text


async def get_users_list(limit: int = 30):
    """Список пользователей, которые взаимодействовали с ботом."""
    async with aiosqlite.connect("orders.db") as db:
        cur = await db.execute("""
            SELECT user_id, username, is_banned, loyal_orders_count FROM users
            UNION
            SELECT user_id, username, 0, 0 FROM orders
            ORDER BY user_id DESC LIMIT ?
        """, (limit,))
        return await cur.fetchall()


def build_users_kb(users, action_prefix: str):
    kb = []
    for u in users:
        user_id, username, is_banned, _ = u
        nick = username if username else f"ID {user_id}"
        nick = nick.replace("@", "")[:20]
        ban_mark = "🚫 " if is_banned else ""
        kb.append([InlineKeyboardButton(
            text=f"{ban_mark}{nick} | {user_id}",
            callback_data=f"{action_prefix}_{user_id}"
        )])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_tech_action")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ================= КЛАВИАТУРЫ И МЕНЮ (РОЛИ) =================
def get_main_menu_kb(user_id: int, lang: str):
    if user_id in config.TECH_IDS:
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="🎫 Открытые тикеты"), KeyboardButton(text="✅ Решенные тикеты")],
            [KeyboardButton(text="🚫 Бан / Разбан"), KeyboardButton(text="🛑 Закрыть заказ")],
            [KeyboardButton(text="🪙 Выдать пуговку"), KeyboardButton(text="🗑 Удалить пуговку")],
            [KeyboardButton(text="👤 Досье пользователя")]
        ], resize_keyboard=True)

    if user_id in config.ARTIST_IDS:
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📋 Активные заказы")],
            [KeyboardButton(text="✉️ Написать заказчику")]
        ], resize_keyboard=True)

    t = config.TEXTS[lang]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=t["btn_order"])],
        [KeyboardButton(text=t["btn_loyalty"]), KeyboardButton(text=t["btn_support"])],
        [KeyboardButton(text=t["btn_lang"])]
    ], resize_keyboard=True)


def get_lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский (RUB)", callback_data="setlang_ru")],
        [InlineKeyboardButton(text="🇬🇧 English (USD)", callback_data="setlang_en")]
    ])


def get_categories_kb(lang: str):
    kb = []
    for key, item in config.COMMISSIONS.items():
        kb.append([InlineKeyboardButton(text=item["name"][lang], callback_data=f"cat_{key}")])
    kb.append([InlineKeyboardButton(text=config.TEXTS[lang]["btn_cancel"], callback_data="cancel_draft")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_subs_kb(cat_key: str, lang: str):
    curr = config.TEXTS[lang]["curr_key"]
    sym = config.TEXTS[lang]["curr_sym"]
    kb = []
    subs = config.COMMISSIONS[cat_key]["subs"]
    for key, item in subs.items():
        price = item[curr]
        p_str = f"{price}{sym}" if curr == "rub" else f"{sym}{price}"
        kb.append([InlineKeyboardButton(text=f"{item['name']} - {p_str}", callback_data=f"sub_{key}")])
    kb.append([InlineKeyboardButton(text=config.TEXTS[lang]["btn_back"], callback_data="back_to_cat")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_extras_kb(selected_extras: list, lang: str, active_btn_type=None):
    kb = []
    curr = config.TEXTS[lang]["curr_key"]
    sym = config.TEXTS[lang]["curr_sym"]
    btn_info = config.BUTTONS_INFO.get(active_btn_type) if active_btn_type else None

    for key, item in config.EXTRAS.items():
        mark = "✅ " if key in selected_extras else ""
        if item["type"] == "percent":
            price_text = item["name"]
        else:
            disp_key = f"display_{curr}"
            price_val = item.get(disp_key, item[curr])
            p_str = f"{price_val}{sym}" if curr == "rub" else f"{sym}{price_val}"
            price_text = f"{item['name']} (+{p_str})"

        if btn_info and btn_info['type'] == 'extra' and key == btn_info['val']:
            mark = "✅ "
            price_text = f"{item['name']} (0{sym} Пуговка)"
        elif btn_info and btn_info['type'] == 'bg' and key in ['bg_hard', 'bg_easy']:
            mark = "✅ " if key in selected_extras or key == 'bg_hard' else mark
            price_text = f"{item['name']} (0{sym} Пуговка)"

        kb.append([InlineKeyboardButton(text=f"{mark}{price_text}", callback_data=f"extratgl_{key}")])

    kb.append([
        InlineKeyboardButton(text=config.TEXTS[lang]["btn_back"], callback_data="back_to_sub"),
        InlineKeyboardButton(text=config.TEXTS[lang]["btn_next"], callback_data="extra_done")
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_client_payment_kb(order_id, lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.TEXTS[lang]["btn_paid"], callback_data=f"pay_order_{order_id}")],
        [InlineKeyboardButton(text=config.TEXTS[lang]["btn_cancel_order"], callback_data=f"cancel_order_{order_id}")]
    ])


def get_artist_payment_check_kb(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплата получена", callback_data=f"confirm_pay_{order_id}")],
        [InlineKeyboardButton(text="❌ Оплата не пришла", callback_data=f"reject_pay_{order_id}")]
    ])


def get_artist_actions_kb(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить этап/скетч", callback_data=f"send_sketch_{order_id}")],
        [InlineKeyboardButton(text="✅ Закрыть заказ", callback_data=f"close_order_{order_id}")]
    ])


# ================= БАЗОВЫЕ КОМАНДЫ =================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    if message.from_user.id in config.TECH_IDS or message.from_user.id in config.ARTIST_IDS:
        await message.answer("Добро пожаловать в панель управления!",
                             reply_markup=get_main_menu_kb(message.from_user.id, "ru"))
        return

    lang = await get_user_lang(message.from_user.id)
    await message.answer(config.TEXTS[lang]["choose_lang"], reply_markup=get_lang_kb())


@router.message(F.text.in_(["⚙️ Язык / Language", "⚙️ Language / Язык"]))
async def change_lang_btn(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await message.answer(config.TEXTS[lang]["choose_lang"], reply_markup=get_lang_kb())


@router.callback_query(F.data.startswith("setlang_"))
async def process_setlang(call: CallbackQuery):
    lang = call.data.split("_")[1]
    await set_user_lang(call.from_user.id, lang)
    t = config.TEXTS[lang]
    await call.message.delete()
    await call.message.answer(t["start_text"], reply_markup=get_main_menu_kb(call.from_user.id, lang),
                              parse_mode="HTML")


# ================= ВЕТКА ИНВЕНТАРЯ (Клиент) =================
@router.message(F.text.in_(["🪙 Пуговки", "🪙 Buttons"]))
async def show_inventory(message: Message, state: FSMContext):
    if message.from_user.id in config.TECH_IDS or message.from_user.id in config.ARTIST_IDS: return
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    t = config.TEXTS[lang]

    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT id, button_type FROM inventory WHERE user_id = ? AND is_used = 0",
                                  (message.from_user.id,))
        buttons = await cursor.fetchall()
        cursor2 = await db.execute("SELECT loyal_orders_count FROM users WHERE user_id = ?", (message.from_user.id,))
        count_row = await cursor2.fetchone()
        count = count_row[0] if count_row else 0

    progress = count % 6
    text = t["pugovka_prog"].format(prog=progress)

    if not buttons:
        await message.answer(text + t["pugovka_empty"], parse_mode="HTML")
        return

    kb = []
    for btn_id, b_type in buttons:
        btn_info = config.BUTTONS_INFO.get(b_type)
        if btn_info: kb.append([InlineKeyboardButton(text=btn_info['name'][lang], callback_data=f"viewbtn_{btn_id}")])
    await message.answer(text + t["pugovka_list"], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
                         parse_mode="HTML")


@router.callback_query(F.data == "back_to_inventory")
async def back_to_inventory_call(call: CallbackQuery):
    lang = await get_user_lang(call.from_user.id)
    t = config.TEXTS[lang]
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT id, button_type FROM inventory WHERE user_id = ? AND is_used = 0",
                                  (call.from_user.id,))
        buttons = await cursor.fetchall()
    if not buttons:
        await call.message.edit_text(t["pugovka_empty"])
        return
    kb = []
    for btn_id, b_type in buttons:
        btn_info = config.BUTTONS_INFO.get(b_type)
        if btn_info: kb.append([InlineKeyboardButton(text=btn_info['name'][lang], callback_data=f"viewbtn_{btn_id}")])
    await call.message.edit_text(t["pugovka_list"], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
                                 parse_mode="HTML")


@router.callback_query(F.data.startswith("viewbtn_"))
async def view_button(call: CallbackQuery):
    lang = await get_user_lang(call.from_user.id)
    t = config.TEXTS[lang]
    btn_id = int(call.data.split("_")[1])
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT button_type, is_used FROM inventory WHERE id = ?", (btn_id,))
        row = await cursor.fetchone()
    if not row or row[1] == 1:
        await call.answer("Error", show_alert=True)
        return
    b_type = row[0]
    btn_info = config.BUTTONS_INFO.get(b_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["btn_spend"], callback_data=f"usebtn_{btn_id}_{b_type}")],
        [InlineKeyboardButton(text=t["btn_back"], callback_data="back_to_inventory")]
    ])
    await call.message.edit_text(f"🪙 <b>{btn_info['name'][lang]}</b>\n\n{btn_info['desc'][lang]}", parse_mode="HTML",
                                 reply_markup=kb)


@router.callback_query(F.data.startswith("usebtn_"))
async def use_button_start_order(call: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(call.from_user.id)
    t = config.TEXTS[lang]
    active_order = await has_active_order(call.from_user.id)
    if active_order:
        status_name = t["status_paid"] if active_order[1] == "paid" else t["status_awaiting"]
        await call.answer("У вас уже есть активный заказ!", show_alert=True)
        await call.message.answer(t["has_active_order"].format(id=active_order[0], status=status_name),
                                  parse_mode="HTML")
        return
    parts = call.data.split("_", 2)
    btn_id, b_type = parts[1], parts[2]
    await state.clear()
    await state.update_data(active_btn_id=int(btn_id), active_btn_type=b_type)
    btn_info = config.BUTTONS_INFO[b_type]
    if btn_info['type'] == 'extra':
        await state.update_data(extras=[btn_info['val']])
    elif btn_info['type'] == 'bg':
        await state.update_data(extras=['bg_hard'])

    await state.set_state(OrderForm.choosing_cat)
    msg = t["pugovka_used"].format(name=btn_info['name'][lang])
    await call.message.answer(msg, reply_markup=get_categories_kb(lang))
    await call.message.delete()


# ================= ВЕТКА ЗАКАЗА (Клиент) =================
@router.message(F.text.in_(["🎨 Заказать", "🎨 Order"]))
async def handle_order_btn(message: Message, state: FSMContext):
    if message.from_user.id in config.TECH_IDS or message.from_user.id in config.ARTIST_IDS: return
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    t = config.TEXTS[lang]
    active_order = await has_active_order(message.from_user.id)
    if active_order:
        status_name = t["status_paid"] if active_order[1] == "paid" else t["status_awaiting"]
        await message.answer(t["has_active_order"].format(id=active_order[0], status=status_name), parse_mode="HTML")
        return
    await state.set_state(OrderForm.choosing_cat)
    await message.answer(t["choose_cat"], reply_markup=get_categories_kb(lang))


@router.callback_query(F.data == "cancel_draft")
async def process_cancel_draft(call: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(call.from_user.id)
    await state.clear()
    try:
        await call.message.edit_text(config.TEXTS[lang]["draft_cancelled"])
    except:
        pass


@router.callback_query(OrderForm.choosing_sub, F.data == "back_to_cat")
async def process_back_to_cat(call: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(call.from_user.id)
    await state.set_state(OrderForm.choosing_cat)
    try:
        await call.message.edit_text(config.TEXTS[lang]["choose_cat"], reply_markup=get_categories_kb(lang))
    except:
        pass


@router.callback_query(OrderForm.choosing_extras, F.data == "back_to_sub")
async def process_back_to_sub(call: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(call.from_user.id)
    data = await state.get_data()
    cat_key = data.get("cat")
    if not cat_key: return
    await state.set_state(OrderForm.choosing_sub)
    try:
        await call.message.edit_text(config.TEXTS[lang]["choose_sub"], reply_markup=get_subs_kb(cat_key, lang))
    except:
        pass


@router.callback_query(OrderForm.choosing_cat, F.data.startswith("cat_"))
async def process_cat(call: CallbackQuery, state: FSMContext):
    cat_key = call.data.split("_", 1)[1]
    lang = await get_user_lang(call.from_user.id)
    await state.update_data(cat=cat_key)
    await state.set_state(OrderForm.choosing_sub)
    try:
        await call.message.edit_text(config.TEXTS[lang]["choose_sub"], reply_markup=get_subs_kb(cat_key, lang))
    except:
        pass


@router.callback_query(OrderForm.choosing_sub, F.data.startswith("sub_"))
async def process_sub(call: CallbackQuery, state: FSMContext):
    sub_key = call.data.split("_", 1)[1]
    lang = await get_user_lang(call.from_user.id)
    data = await state.get_data()
    active_btn_type = data.get("active_btn_type")
    extras = data.get("extras", [])

    await state.update_data(sub=sub_key, extras=extras)
    await state.set_state(OrderForm.choosing_extras)
    try:
        await call.message.edit_text(config.TEXTS[lang]["choose_extras"],
                                     reply_markup=get_extras_kb(extras, lang, active_btn_type))
    except:
        pass


@router.callback_query(OrderForm.choosing_extras, F.data.startswith("extratgl_"))
async def process_extra_toggle(call: CallbackQuery, state: FSMContext):
    key = call.data.split("_", 1)[1]
    lang = await get_user_lang(call.from_user.id)
    data = await state.get_data()
    extras = data.get("extras", [])
    active_btn_type = data.get("active_btn_type")

    if active_btn_type:
        btn_info = config.BUTTONS_INFO.get(active_btn_type)
        if btn_info and btn_info['type'] == 'extra' and key == btn_info['val']:
            await call.answer("Free / Бесплатно!", show_alert=True)
            return
        if btn_info and btn_info['type'] == 'bg' and key in ['bg_hard', 'bg_easy']:
            if key in extras:
                extras.remove(key)
            else:
                if 'bg_hard' in extras: extras.remove('bg_hard')
                if 'bg_easy' in extras: extras.remove('bg_easy')
                extras.append(key)
            await state.update_data(extras=extras)
            try:
                await call.message.edit_reply_markup(reply_markup=get_extras_kb(extras, lang, active_btn_type))
            except:
                pass
            return

    if key in extras:
        extras.remove(key)
    else:
        if key == 'bg_hard' and 'bg_easy' in extras: extras.remove('bg_easy')
        if key == 'bg_easy' and 'bg_hard' in extras: extras.remove('bg_hard')
        extras.append(key)

    await state.update_data(extras=extras)
    try:
        await call.message.edit_reply_markup(reply_markup=get_extras_kb(extras, lang, active_btn_type))
    except:
        pass


@router.callback_query(OrderForm.choosing_extras, F.data == "extra_done")
async def process_extra_done(call: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(call.from_user.id)
    await state.set_state(OrderForm.writing_desc)
    try:
        await call.message.edit_text(config.TEXTS[lang]["desc_req"])
    except:
        pass


@router.message(OrderForm.writing_desc)
async def process_desc(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = await get_user_lang(message.from_user.id)
    t = config.TEXTS[lang]

    curr = t["curr_key"]
    sym = t["curr_sym"]
    req = config.REQUISITES_RUB if curr == "rub" else config.REQUISITES_USD
    btn_id, btn_type = data.get("active_btn_id"), data.get("active_btn_type")
    btn_info = config.BUTTONS_INFO.get(btn_type) if btn_type else None

    cat_data = config.COMMISSIONS[data['cat']]
    sub_data = cat_data["subs"][data['sub']]
    extras_keys = data.get('extras', [])

    base_price = sub_data[curr]
    extras_cost = 0
    if "kinks" in extras_keys: extras_cost += base_price * config.EXTRAS["kinks"]["val"]
    for k in extras_keys:
        if k == "kinks": continue
        if btn_info and btn_info['type'] == 'extra' and k == btn_info['val']: continue
        if btn_info and btn_info['type'] == 'bg' and k in ['bg_hard', 'bg_easy']: continue
        extras_cost += config.EXTRAS[k][curr]

    total_price = base_price + extras_cost
    if btn_info and btn_info['type'] == 'discount':
        total_price = total_price * (1.0 - btn_info['val'])
    elif btn_info and btn_info['type'] == 'free_order':
        total_price = 0
    total_price = round(total_price, 2)
    price_str = f"{total_price}{sym}" if curr == "rub" else f"{sym}{total_price:.2f}"

    raw_text = message.text or message.caption or "No text"
    safe_user_text = html.escape(raw_text)

    extras_names_user = ", ".join([config.EXTRAS[k]['name'] for k in extras_keys]) if extras_keys else "None/Нет"
    used_btn_user = f"\nButton/Пуговка: <b>{btn_info['name'][lang]}</b>" if btn_info else ""
    order_details_user = f"Style: {html.escape(cat_data['name'][lang])}\nFormat: {html.escape(sub_data['name'])}\nExtras: {html.escape(extras_names_user)}\nDesc: {safe_user_text}{used_btn_user}"

    extras_names_ru = ", ".join([config.EXTRAS[k]['name'] for k in extras_keys]) if extras_keys else "Нет"
    used_btn_ru = f"\nПуговка: <b>{btn_info['name']['ru']}</b>" if btn_info else ""
    order_details_ru = f"Стиль: {html.escape(cat_data['name']['ru'])}\nФормат: {html.escape(sub_data['name'])}\nДопы: {html.escape(extras_names_ru)}\nОписание: {safe_user_text}{used_btn_ru}"

    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
    safe_username = html.escape(username)
    status = "awaiting_payment" if total_price > 0 else "paid"

    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, username, details, price, status, used_btn_id) VALUES (?, ?, ?, ?, ?, ?)",
            (message.from_user.id, username, order_details_user, total_price, status,
             int(btn_id) if btn_id else None)
        )
        order_id = cursor.lastrowid
        if btn_id:
            await db.execute("UPDATE inventory SET is_used = 1 WHERE id = ?", (int(btn_id),))
        await db.commit()

    photo_id = message.photo[-1].file_id if message.photo else None

    if status == "awaiting_payment":
        msg = t["order_done"].format(id=order_id, details=order_details_user, price=price_str, req=html.escape(req))
        await message.answer(msg, parse_mode="HTML", reply_markup=get_client_payment_kb(order_id, lang))
        await send_to_channel(config.CHANNEL_ID,
                              f"🆕 <b>Новый заказ №{order_id}</b> от {safe_username}\n\n{order_details_ru}\n\nСумма: {price_str}",
                              photo_id)
    else:
        msg = t["order_free"].format(id=order_id, details=order_details_user)
        await message.answer(msg, parse_mode="HTML")
        for a_id in config.ARTIST_IDS:
            try:
                await bot.send_message(a_id,
                                       f"🔔 <b>Новый бесплатный заказ №{order_id} (Пуговка)</b>\n\n{order_details_ru}",
                                       parse_mode="HTML", reply_markup=get_artist_actions_kb(order_id))
            except:
                pass
        await send_to_channel(config.CHANNEL_ID,
                              f"🆕 <b>Бесплатный заказ №{order_id} (пуговка)</b> от {safe_username}\n\n{order_details_ru}",
                              photo_id)

    await state.clear()


@router.callback_query(F.data.startswith("pay_order_"))
async def process_payment_click(call: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(call.from_user.id)
    order_id = call.data.split("_", 2)[2]
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT user_id, status FROM orders WHERE id = ?", (order_id,)) as cursor:
            row = await cursor.fetchone()
    if not row or row[0] != call.from_user.id:
        await call.answer("Not your order / Не ваш заказ", show_alert=True)
        return
    if row[1] != 'awaiting_payment':
        await call.answer("Этот заказ нельзя оплатить.", show_alert=True)
        return

    await state.set_state(PaymentForm.waiting_for_receipt)
    await state.update_data(pay_order_id=order_id)
    await call.message.answer(config.TEXTS[lang]["send_receipt"])


@router.callback_query(F.data.startswith("cancel_order_"))
async def client_cancel_order(call: CallbackQuery):
    lang = await get_user_lang(call.from_user.id)
    order_id = call.data.split("_", 2)[2]
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT user_id, status, used_btn_id FROM orders WHERE id = ?", (order_id,)) as cursor:
            row = await cursor.fetchone()
        if not row or row[0] != call.from_user.id or row[1] != "awaiting_payment": return
        await db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
        if row[2]: await db.execute("UPDATE inventory SET is_used = 0 WHERE id = ?", (row[2],))
        await db.commit()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    await call.message.answer(config.TEXTS[lang]["order_cancelled"].format(id=order_id))
    await send_to_channel(config.CHANNEL_ID, f"❌ <b>Клиент отменил неоплаченный заказ №{order_id}.</b>")


@router.message(PaymentForm.waiting_for_receipt, F.photo)
async def process_receipt_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = await get_user_lang(message.from_user.id)
    order_id = data.get('pay_order_id')
    if not order_id: return await state.clear()

    photo_id = message.photo[-1].file_id
    for a_id in config.ARTIST_IDS:
        try:
            await bot.send_photo(
                a_id, photo=photo_id,
                caption=f"💳 <b>Оплата по заказу №{order_id}</b>\nПроверьте поступление средств.",
                parse_mode="HTML", reply_markup=get_artist_payment_check_kb(order_id)
            )
        except:
            pass

    await send_to_channel(config.CHANNEL_ID, f"💳 <b>Клиент прикрепил чек по заказу №{order_id}</b>", photo_id=photo_id)
    await message.answer(config.TEXTS[lang]["receipt_sent"])
    try:
        await bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=message.message_id - 1,
                                            reply_markup=None)
    except:
        pass
    await state.clear()


# ================= МЕНЮ И ЛОГИКА ХУДОЖНИКА =================
@router.message(F.text == "📋 Активные заказы")
async def artist_active_orders(message: Message):
    if message.from_user.id not in config.ARTIST_IDS: return
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT id, username, price FROM orders WHERE status = 'paid'")
        rows = await cursor.fetchall()
    if not rows:
        await message.answer("Активных (оплаченных) заказов сейчас нет.")
        return
    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(text=f"Заказ #{r[0]} ({r[1]})", callback_data=f"artist_view_{r[0]}")])
    await message.answer("Активные заказы в работе:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("artist_view_"))
async def artist_view_order_details(call: CallbackQuery):
    if call.from_user.id not in config.ARTIST_IDS: return
    order_id = call.data.split("_")[2]
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT details, price FROM orders WHERE id = ?", (order_id,))
        row = await cursor.fetchone()
    if not row: return
    text = f"🎨 <b>Детали заказа #{order_id}</b>\n\n{row[0]}\n\nОплачено: {row[1]}"
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=get_artist_actions_kb(order_id))


@router.message(F.text == "✉️ Написать заказчику")
async def msg_to_customer_start(message: Message, state: FSMContext):
    if message.from_user.id not in config.ARTIST_IDS: return
    await state.set_state(ArtistAction.waiting_for_order_id_msg)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_artist_msg")]])
    await message.answer("Введите номер заказа, по которому хотите связаться с заказчиком:", reply_markup=kb)


@router.callback_query(F.data == "cancel_artist_msg")
async def msg_to_customer_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Действие отменено.")


@router.message(ArtistAction.waiting_for_order_id_msg)
async def msg_to_customer_id(message: Message, state: FSMContext):
    if message.from_user.id not in config.ARTIST_IDS: return
    if not message.text.isdigit(): return
    order_id = int(message.text)
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,))
        row = await cursor.fetchone()
    if not row:
        await message.answer("Заказ с таким номером не найден.")
        return
    await state.update_data(contact_user_id=row[0], contact_order_id=order_id)
    await state.set_state(ArtistAction.waiting_for_message)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_artist_msg")]])
    await message.answer(f"Напишите сообщение, которое получит заказчик (Заказ #{order_id}):", reply_markup=kb)


@router.message(ArtistAction.waiting_for_message)
async def msg_to_customer_send(message: Message, state: FSMContext):
    if message.from_user.id not in config.ARTIST_IDS: return
    data = await state.get_data()
    u_id = data['contact_user_id']
    o_id = data['contact_order_id']
    safe_text = html.escape(message.text or message.caption or "-")
    try:
        await bot.send_message(u_id, f"👨‍🎨 <b>Сообщение от художника (Заказ #{o_id}):</b>\n\n{safe_text}",
                               parse_mode="HTML")
        await message.answer("✅ Сообщение успешно доставлено заказчику!")
    except Exception:
        await message.answer("⚠️ Ошибка отправки. Возможно пользователь заблокировал бота.")
    await state.clear()


# ================= ДЕЙСТВИЯ С ЗАКАЗАМИ (Художник) =================
@router.callback_query(F.data.startswith("confirm_pay_"))
async def admin_confirm_payment(call: CallbackQuery):
    if call.from_user.id not in config.ARTIST_IDS and call.from_user.id not in config.TECH_IDS:
        return
    order_id = call.data.split("_", 2)[2]
    awarded_btn = None

    async with aiosqlite.connect("orders.db") as db:
        await db.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
        async with db.execute(
            "SELECT user_id, details, price, used_btn_id FROM orders WHERE id = ?", (order_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            user_id, details, price, used_btn_id = row
            lang = await get_user_lang(user_id)

            used_btn_info = None
            if used_btn_id:
                cur2 = await db.execute("SELECT button_type FROM inventory WHERE id = ?", (used_btn_id,))
                b = await cur2.fetchone()
                if b:
                    used_btn_info = config.BUTTONS_INFO.get(b[0])

            discount_str = "—"
            if used_btn_info:
                if used_btn_info['type'] == 'discount':
                    discount_str = f"{int(used_btn_info['val'] * 100)}%"
                elif used_btn_info['type'] == 'free_order':
                    discount_str = "100% (Супер-Пуговка)"
                elif used_btn_info['type'] in ('bg', 'extra'):
                    discount_str = "0 на доп"

            threshold = 1200 if lang == "ru" else 15
            if float(price) >= threshold:
                await db.execute(
                    "UPDATE users SET loyal_orders_count = loyal_orders_count + 1 WHERE user_id = ?", (user_id,)
                )
                cur_count = await db.execute(
                    "SELECT loyal_orders_count FROM users WHERE user_id = ?", (user_id,)
                )
                result = await cur_count.fetchone()
                count = result[0] if result else 0
                awarded_btn = "super_free" if count % 6 == 0 else random.choice(
                    ["discount_15", "free_bg", "free_porn"]
                )
                await db.execute(
                    "INSERT INTO inventory (user_id, button_type) VALUES (?, ?)", (user_id, awarded_btn)
                )
        await db.commit()

    if row:
        try:
            msg = f"✅ Оплата подтверждена! / Payment confirmed! Order #{order_id} in progress."
            if awarded_btn:
                btn_name = config.BUTTONS_INFO[awarded_btn]['name'][lang]
                msg += f"\n\n🎉 Вы получили пуговку: <b>{btn_name}</b>!" if lang == "ru" \
                    else f"\n\n🎉 You received a button: <b>{btn_name}</b>!"
            await bot.send_message(user_id, msg, parse_mode="HTML")
        except:
            pass

        curr_sym = config.TEXTS[lang]["curr_sym"]
        artist_msg = (
            f"🔔 <b>Оплаченный заказ №{order_id} теперь в работе!</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"<b>Клиент:</b> <code>{user_id}</code>\n"
            f"<b>Итоговая сумма:</b> {float(price):g}{curr_sym}\n"
        )
        if used_btn_info:
            artist_msg += (
                f"<b>Использована пуговка:</b> {used_btn_info['name']['ru']}\n"
                f"<b>Скидка:</b> {discount_str}\n"
            )
        else:
            artist_msg += "<b>Пуговки не использовались</b>\n"
        artist_msg += "━━━━━━━━━━━━━━━\n👇 Детали заказа:"

        await call.message.answer(
            artist_msg, parse_mode="HTML", reply_markup=get_artist_actions_kb(order_id)
        )

    current_caption = call.message.caption if call.message.caption else f"Оплата по заказу №{order_id}"
    try:
        await call.message.edit_caption(
            caption=f"{current_caption}\n\n<b>Статус: ОПЛАЧЕНО ✅</b>",
            parse_mode="HTML", reply_markup=None
        )
    except:
        pass
    await send_to_channel(config.CHANNEL_ID, f"✅ Оплата №{order_id} подтверждена.")


@router.callback_query(F.data.startswith("reject_pay_"))
async def admin_reject_payment(call: CallbackQuery):
    if call.from_user.id not in config.ARTIST_IDS and call.from_user.id not in config.TECH_IDS: return
    order_id = call.data.split("_", 2)[2]
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)) as cursor:
            row = await cursor.fetchone()
    if row:
        lang = await get_user_lang(row[0])
        try:
            await bot.send_message(row[0], "❌ Payment rejected. / Оплата не подтверждена.",
                                   reply_markup=get_client_payment_kb(order_id, lang))
        except:
            pass

    current_caption = call.message.caption if call.message.caption else f"Оплата по заказу №{order_id}"
    try:
        await call.message.edit_caption(caption=f"{current_caption}\n\n<b>Статус: ОТКЛОНЕНО ❌</b>", parse_mode="HTML",
                                        reply_markup=None)
    except:
        pass


@router.callback_query(F.data.startswith("send_sketch_"))
async def admin_send_sketch(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.ARTIST_IDS: return
    order_id = call.data.split("_")[2]
    await state.set_state(ArtistAction.waiting_for_sketch)
    await state.update_data(current_order_id=order_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_artist_msg")]])
    await call.message.answer(f"Отправь фото/скетч для заказа №{order_id}. Можно добавить текст.", reply_markup=kb)
    await call.answer()


@router.message(ArtistAction.waiting_for_sketch, F.photo)
async def admin_photo_received(message: Message, state: FSMContext):
    if message.from_user.id not in config.ARTIST_IDS: return
    data = await state.get_data()
    order_id = data.get('current_order_id')
    photo_id = message.photo[-1].file_id

    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)) as cursor:
            row = await cursor.fetchone()

    if row:
        lang = await get_user_lang(row[0])
        raw_caption = message.caption if message.caption else (
            "Review sketch / Проверьте этап" if lang == "en" else "Художник прислал этап на согласование.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Approve / Утвердить", callback_data=f"accept_sketch_{order_id}")],
            [InlineKeyboardButton(text="✍️ Request Edits / Правки", callback_data=f"decline_sketch_{order_id}")]
        ])
        try:
            await bot.send_photo(row[0], photo=photo_id, caption=html.escape(raw_caption), reply_markup=kb)
            await message.answer(f"✅ Отправлено клиенту (Заказ №{order_id}).",
                                 reply_markup=get_artist_actions_kb(order_id))
        except:
            await message.answer(f"⚠️ Клиент заблокировал бота.", reply_markup=get_artist_actions_kb(order_id))
        await send_to_channel(config.CHANNEL_ID, f"📤 <b>Художник отправил этап клиенту (Заказ №{order_id})</b>",
                              photo_id=photo_id)
    await state.clear()


@router.callback_query(F.data.startswith("accept_sketch_"))
async def client_accepts(call: CallbackQuery):
    order_id = call.data.split("_")[2]
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    await call.message.answer("✅ Отправлено художнику! / Sent to artist!")
    for a_id in config.ARTIST_IDS:
        try:
            await bot.send_message(a_id, f"✅ Клиент <b>утвердил</b> этап №{order_id}!", parse_mode="HTML",
                                   reply_markup=get_artist_actions_kb(order_id))
        except:
            pass
    await send_to_channel(config.CHANNEL_ID, f"✅ Клиент утвердил этап работы (Заказ №{order_id}).")


@router.callback_query(F.data.startswith("decline_sketch_"))
async def client_declines(call: CallbackQuery, state: FSMContext):
    order_id = call.data.split("_")[2]
    await state.set_state(ClientAction.waiting_for_feedback)
    await state.update_data(feedback_order_id=order_id)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    await call.message.answer("Напишите правки / Write your edits:")


@router.message(ClientAction.waiting_for_feedback)
async def client_feedback_received(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get('feedback_order_id')
    safe_text = html.escape(message.text or message.caption or "...")
    for a_id in config.ARTIST_IDS:
        try:
            await bot.send_message(a_id, f"⚠️ <b>Правки №{order_id}:</b>\n\n{safe_text}", parse_mode="HTML",
                                   reply_markup=get_artist_actions_kb(order_id))
        except:
            pass
    await message.answer("Передано художнику. / Edits sent to artist.")
    await send_to_channel(config.CHANNEL_ID, f"⚠️ <b>Правки от клиента (Заказ №{order_id}):</b>\n\n{safe_text}")
    await state.clear()


@router.callback_query(F.data.startswith("close_order_"))
async def close_order(call: CallbackQuery):
    if call.from_user.id not in config.ARTIST_IDS and call.from_user.id not in config.TECH_IDS: return
    order_id = call.data.split("_")[2]

    async with aiosqlite.connect("orders.db") as db:
        await db.execute("UPDATE orders SET status = 'closed' WHERE id = ?", (order_id,))
        async with db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)) as cursor:
            row = await cursor.fetchone()
        await db.commit()

    if row:
        try:
            await bot.send_message(row[0], f"🎉 Заказ завершен! Спасибо! / Order completed! Thank you!")
        except:
            pass

    current_text = call.message.text if call.message.text else f"Заказ №{order_id}"
    try:
        await call.message.edit_text(f"{html.escape(current_text)}\n\n<b>[ЗАКАЗ ЗАКРЫТ]</b>", parse_mode="HTML",
                                     reply_markup=None)
    except:
        pass
    await send_to_channel(config.CHANNEL_ID, f"🏁 <b>Заказ №{order_id} успешно закрыт художником.</b>")


# ================= ВЕТКА ТЕХПОДДЕРЖКИ =================
@router.message(F.text.in_(["🛠 Поддержка", "🛠 Support"]))
async def support_btn_handler(message: Message, state: FSMContext):
    if message.from_user.id in config.TECH_IDS or message.from_user.id in config.ARTIST_IDS: return
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await state.set_state(SupportForm.waiting_for_msg)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=config.TEXTS[lang]["btn_cancel"], callback_data="cancel_draft")]])
    await message.answer(config.TEXTS[lang]["support_prompt"], reply_markup=kb)


@router.message(SupportForm.waiting_for_msg)
async def process_support_msg(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    safe_text = html.escape(message.text or message.caption or "-")
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"

    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("INSERT INTO tickets (user_id, username, question) VALUES (?, ?, ?)",
                                  (message.from_user.id, username, safe_text))
        ticket_id = cursor.lastrowid
        await db.commit()

    await message.answer(config.TEXTS[lang]["support_sent"])
    await state.clear()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Решить / Ответить", callback_data=f"tech_reply_{ticket_id}")]])
    msg = f"🆘 <b>Новое обращение №{ticket_id}</b>\nОт: {username} (<code>{message.from_user.id}</code>)\n\nВопрос: {safe_text}"
    for t_id in config.TECH_IDS:
        try:
            await bot.send_message(t_id, msg, parse_mode="HTML", reply_markup=kb)
        except:
            pass
    await send_to_channel(config.TECH_CHANNEL_ID, msg)


# ================= МЕНЮ ТЕХ. АДМИНА =================
@router.message(F.text.in_(["🎫 Открытые тикеты", "✅ Решенные тикеты"]))
async def tech_show_tickets(message: Message):
    if message.from_user.id not in config.TECH_IDS: return
    status = "open" if "Открытые" in message.text else "closed"
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT id, username FROM tickets WHERE status = ? ORDER BY id DESC LIMIT 15",
                                  (status,))
        rows = await cursor.fetchall()

    if not rows:
        await message.answer("Тикетов в этой категории пока нет.")
        return

    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(text=f"№{r[0]} | {r[1]}", callback_data=f"tech_view_{r[0]}")])

    title = "🎫 <b>Открытые обращения:</b>" if status == "open" else "✅ <b>Решенные обращения (последние 15):</b>"
    await message.answer(title, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("tech_view_"))
async def view_ticket(call: CallbackQuery):
    if call.from_user.id not in config.TECH_IDS: return
    ticket_id = call.data.split("_")[2]
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT user_id, username, question, status, answer FROM tickets WHERE id = ?",
                                  (ticket_id,))
        row = await cursor.fetchone()

    if not row: return
    u_id, uname, q, status, ans = row

    text = f"Обращение <b>№{ticket_id}</b>\nОт: {uname} (<code>{u_id}</code>)\n\n<b>Вопрос:</b> {q}\n\n<b>Статус:</b> {status}"
    if ans: text += f"\n<b>Наш ответ:</b> {ans}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить", callback_data=f"tech_reply_{ticket_id}")]])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("tech_reply_"))
async def start_tech_reply(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.TECH_IDS: return
    ticket_id = call.data.split("_")[2]
    await state.set_state(TechAdminFSM.replying_to_ticket)
    await state.update_data(reply_ticket_id=ticket_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_tech_action")]])
    await call.message.answer(f"Напишите ответ пользователю по тикету №{ticket_id}:", reply_markup=kb)
    await call.answer()


@router.message(TechAdminFSM.replying_to_ticket)
async def process_tech_reply(message: Message, state: FSMContext):
    if message.from_user.id not in config.TECH_IDS: return
    data = await state.get_data()
    ticket_id = data.get('reply_ticket_id')
    answer_text = html.escape(message.text or message.caption or "-")

    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,))
        row = await cursor.fetchone()
        if not row: return
        user_id = row[0]
        await db.execute("UPDATE tickets SET status = 'closed', answer = ? WHERE id = ?", (answer_text, ticket_id))
        await db.commit()

    try:
        await bot.send_message(user_id, f"🛠 <b>Ответ от Тех. Поддержки:</b>\n\n{answer_text}", parse_mode="HTML")
        await message.answer(f"✅ Ответ по тикету №{ticket_id} успешно отправлен пользователю!")
        await send_to_channel(config.TECH_CHANNEL_ID,
                              f"✅ <b>Ответ на тикет №{ticket_id} (Для {user_id})</b>\n\nОтвет: {answer_text}")
    except TelegramForbiddenError:
        await message.answer("⚠️ Пользователь заблокировал бота, сообщение не доставлено. Тикет закрыт.")
    await state.clear()


# ================= ТЕХ АДМИН: ВЫБОР ПОЛЬЗОВАТЕЛЯ ИЗ СПИСКА =================
@router.message(F.text == "🚫 Бан / Разбан")
async def ask_ban_user(message: Message, state: FSMContext):
    if message.from_user.id not in config.TECH_IDS:
        return
    users = await get_users_list()
    if not users:
        await message.answer("В базе пока нет пользователей.")
        return
    await state.set_state(TechAdminFSM.choosing_user_for_ban)
    await message.answer(
        "Выберите пользователя для БАНА / РАЗБАНА:",
        reply_markup=build_users_kb(users, "tech_ban_user")
    )


@router.callback_query(TechAdminFSM.choosing_user_for_ban, F.data.startswith("tech_ban_user_"))
async def process_ban_user(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.TECH_IDS:
        return
    user_id = int(call.data.split("_")[3])

    async with aiosqlite.connect("orders.db") as db:
        cur = await db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, is_banned) VALUES (?, 1)", (user_id,))
            new_status = 1
        else:
            new_status = 0 if row[0] == 1 else 1
            await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_status, user_id))
        await db.commit()

    status_text = "ЗАБЛОКИРОВАН 🚫" if new_status == 1 else "РАЗБЛОКИРОВАН ✅"
    dossier = await get_user_dossier(user_id)
    await call.message.edit_text(
        f"Пользователь <code>{user_id}</code> теперь <b>{status_text}</b>\n\n{dossier}",
        parse_mode="HTML"
    )
    await state.clear()


@router.message(F.text == "🛑 Закрыть заказ")
async def ask_close_user(message: Message, state: FSMContext):
    if message.from_user.id not in config.TECH_IDS:
        return
    users = await get_users_list()
    if not users:
        await message.answer("В базе пока нет пользователей.")
        return
    await state.set_state(TechAdminFSM.choosing_user_for_close)
    await message.answer(
        "Выберите пользователя, чьи активные заказы нужно отменить:",
        reply_markup=build_users_kb(users, "tech_close_user")
    )


@router.callback_query(TechAdminFSM.choosing_user_for_close, F.data.startswith("tech_close_user_"))
async def process_close_user(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.TECH_IDS:
        return
    user_id = int(call.data.split("_")[3])
    async with aiosqlite.connect("orders.db") as db:
        await db.execute(
            "UPDATE orders SET status = 'cancelled' "
            "WHERE user_id = ? AND status IN ('awaiting_payment', 'paid')",
            (user_id,)
        )
        await db.commit()
    dossier = await get_user_dossier(user_id)
    await call.message.edit_text(
        f"✅ Все активные заказы пользователя <code>{user_id}</code> отменены.\n\n{dossier}",
        parse_mode="HTML"
    )
    await state.clear()


# -------- ВЫДАТЬ ПУГОВКУ --------
@router.message(F.text == "🪙 Выдать пуговку")
async def ask_give_pugovka(message: Message, state: FSMContext):
    if message.from_user.id not in config.TECH_IDS:
        return
    users = await get_users_list()
    if not users:
        await message.answer("В базе пока нет пользователей.")
        return
    await state.set_state(TechAdminFSM.choosing_user_pugovka_give)
    await message.answer(
        "Кому выдать пуговку?",
        reply_markup=build_users_kb(users, "tech_give_user")
    )


@router.callback_query(TechAdminFSM.choosing_user_pugovka_give, F.data.startswith("tech_give_user_"))
async def process_give_user(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.TECH_IDS:
        return
    user_id = int(call.data.split("_")[3])
    await state.update_data(target_user_id=user_id)
    await state.set_state(TechAdminFSM.choosing_button_to_give)

    kb = []
    for p_key, p_info in config.BUTTONS_INFO.items():
        kb.append([InlineKeyboardButton(
            text=f"➕ {p_info['name']['ru']}",
            callback_data=f"tech_givep_{user_id}_{p_key}"
        )])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_tech_action")])
    dossier = await get_user_dossier(user_id)
    await call.message.edit_text(
        f"{dossier}\n\n<b>Выберите пуговку для выдачи:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@router.callback_query(F.data.startswith("tech_givep_"))
async def tech_give_pugovka(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.TECH_IDS:
        return
    parts = call.data.split("_", 3)
    user_id = int(parts[2])
    p_key = parts[3]

    async with aiosqlite.connect("orders.db") as db:
        await db.execute("INSERT INTO inventory (user_id, button_type) VALUES (?, ?)", (user_id, p_key))
        await db.commit()

    try:
        p_name = config.BUTTONS_INFO[p_key]['name']['ru']
        await bot.send_message(
            user_id,
            f"🎉 <b>Администратор выдал вам пуговку!</b>\nТип: {p_name}\nЗайдите в раздел «🪙 Пуговки».",
            parse_mode="HTML"
        )
    except:
        pass

    dossier = await get_user_dossier(user_id)
    await call.message.edit_text(
        f"✅ Пуговка <b>{config.BUTTONS_INFO[p_key]['name']['ru']}</b> выдана!\n\n{dossier}",
        parse_mode="HTML"
    )
    await state.clear()


# -------- УДАЛИТЬ ПУГОВКУ --------
@router.message(F.text == "🗑 Удалить пуговку")
async def ask_remove_pugovka(message: Message, state: FSMContext):
    if message.from_user.id not in config.TECH_IDS:
        return
    users = await get_users_list()
    if not users:
        await message.answer("В базе пока нет пользователей.")
        return
    await state.set_state(TechAdminFSM.choosing_user_pugovka_remove)
    await message.answer(
        "У кого удалить пуговку?",
        reply_markup=build_users_kb(users, "tech_rm_user")
    )


@router.callback_query(TechAdminFSM.choosing_user_pugovka_remove, F.data.startswith("tech_rm_user_"))
async def process_rm_user(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.TECH_IDS:
        return
    user_id = int(call.data.split("_")[3])

    async with aiosqlite.connect("orders.db") as db:
        cur = await db.execute(
            "SELECT id, button_type FROM inventory WHERE user_id = ? AND is_used = 0 ORDER BY id",
            (user_id,)
        )
        btns = await cur.fetchall()

    if not btns:
        dossier = await get_user_dossier(user_id)
        await call.message.edit_text(
            f"⚠️ У пользователя нет активных пуговок.\n\n{dossier}",
            parse_mode="HTML"
        )
        await state.clear()
        return

    await state.update_data(rm_target_user_id=user_id)
    await state.set_state(TechAdminFSM.choosing_button_to_remove)

    kb = []
    for b_id, b_type in btns:
        info = config.BUTTONS_INFO.get(b_type)
        name = info['name']['ru'] if info else b_type
        kb.append([InlineKeyboardButton(
            text=f"🗑 #{b_id} {name}",
            callback_data=f"tech_rmbtn_{b_id}"
        )])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_tech_action")])

    dossier = await get_user_dossier(user_id)
    await call.message.edit_text(
        f"{dossier}\n\n<b>Выберите пуговку для удаления:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@router.callback_query(TechAdminFSM.choosing_button_to_remove, F.data.startswith("tech_rmbtn_"))
async def tech_remove_button(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.TECH_IDS:
        return
    btn_id = int(call.data.split("_")[2])
    data = await state.get_data()
    user_id = data.get("rm_target_user_id")

    async with aiosqlite.connect("orders.db") as db:
        cur = await db.execute(
            "SELECT button_type FROM inventory WHERE id = ? AND user_id = ?",
            (btn_id, user_id)
        )
        row = await cur.fetchone()
        if not row:
            await call.answer("Пуговка не найдена.", show_alert=True)
            return
        b_type = row[0]
        await db.execute("DELETE FROM inventory WHERE id = ?", (btn_id,))
        await db.commit()

    info = config.BUTTONS_INFO.get(b_type)
    b_name = info['name']['ru'] if info else b_type

    try:
        await bot.send_message(
            user_id,
            f"⚠️ <b>Администратор удалил вашу пуговку:</b> {b_name}",
            parse_mode="HTML"
        )
    except:
        pass

    dossier = await get_user_dossier(user_id)
    await call.message.edit_text(
        f"✅ Пуговка <b>{b_name}</b> удалена!\n\n{dossier}",
        parse_mode="HTML"
    )
    await state.clear()


# -------- ДОСЬЕ --------
@router.message(F.text == "👤 Досье пользователя")
async def ask_dossier(message: Message, state: FSMContext):
    if message.from_user.id not in config.TECH_IDS:
        return
    users = await get_users_list()
    if not users:
        await message.answer("В базе пока нет пользователей.")
        return
    await message.answer(
        "Выберите пользователя:",
        reply_markup=build_users_kb(users, "tech_dossier_user")
    )


@router.callback_query(F.data.startswith("tech_dossier_user_"))
async def show_dossier(call: CallbackQuery):
    if call.from_user.id not in config.TECH_IDS:
        return
    user_id = int(call.data.split("_")[3])
    dossier = await get_user_dossier(user_id)
    await call.message.edit_text(dossier, parse_mode="HTML")


@router.callback_query(F.data == "cancel_tech_action")
async def cancel_tech_action(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Действие отменено.")


# Обработчик старых/неактивных кнопок
@router.callback_query(
    F.data.in_(["extra_done"]) | F.data.startswith("cat_") | F.data.startswith("sub_") | F.data.startswith("extratgl_"))
async def old_buttons_handler(call: CallbackQuery):
    lang = await get_user_lang(call.from_user.id)
    await call.answer(config.TEXTS[lang]["old_menu"], show_alert=True)


async def main():
    await init_db()
    dp.include_router(router)
    print("Бот запущен...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())