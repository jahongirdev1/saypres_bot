import os
import django
from asgiref.sync import sync_to_async

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Saypress.settings')
django.setup()

import logging
import base64
from typing import Optional
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from main.models import Category, Question, UserQuestion, TeleUser, Company, TimeOff, MessageLog
from datetime import datetime, date
import calendar

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "7943795810:AAG0wun2bnwieW2K8Aefv9XHSXx2lFIJV8Y"
bot = Bot(token=TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)

# ---------------------------
#  States
# ---------------------------
STATE_NONE = "NONE"
STATE_CONFIRM_PENDING = "CONFIRM_PENDING"
STATE_AWAITING_CONTENT = "AWAITING_CONTENT"

# Registration states
STATE_REG_NAME = "REG_NAME"
STATE_REG_TRUCK = "REG_TRUCK"

# Inline-edit state
STATE_INLINE_EDIT = "INLINE_EDIT"

# TimeOff states
STATE_TIMEOFF_FROM = "TIMEOFF_FROM"
STATE_TIMEOFF_TILL = "TIMEOFF_TILL"
STATE_TIMEOFF_REASON = "TIMEOFF_REASON"
STATE_TIMEOFF_PAUSE = "TIMEOFF_PAUSE"

# ---------------------------
#  Global dictionaries
# ---------------------------
user_selected_category = {}  # { user_id: category_name }
user_state = {}              # { user_id: state_name }
pending_question = {}        # { user_id: {"category":..., "content_text":..., "content_photo":..., "content_voice":...} }
temp_user_data = {}          # { user_id: {...} }

DEFAULT_GENERAL_CATEGORY_NAME = "General"

# ---------------------------
#  Async wrappers for Django ORM
# ---------------------------
@sync_to_async
def get_teleuser_by_id(telegram_id):
    return TeleUser.objects.select_related('company').filter(telegram_id=telegram_id).first()

@sync_to_async
def create_teleuser(telegram_id, name, truck_number, company_id=None):
    company_obj = None
    if company_id:
        company_obj = Company.objects.get(id=company_id)
    return TeleUser.objects.create(
        telegram_id=telegram_id,
        first_name=name,
        nickname=None,
        truck_number=truck_number,
        company=company_obj
    )

@sync_to_async
def get_companies():
    return list(Company.objects.all())

@sync_to_async
def create_timeoff(teleuser_id, date_from, date_till, reason, pause):
    user = TeleUser.objects.get(id=teleuser_id)
    return TimeOff.objects.create(
        teleuser=user,
        date_from=date_from,
        date_till=date_till,
        reason=reason,
        pause_insurance=pause
    )

@sync_to_async
def get_categories_async(company_id=None):
    qs = Category.objects.all()
    if company_id:
        qs = qs.filter(company_id=company_id)
    return list(qs)

@sync_to_async
def get_questions_for_category_async(category_name: str, company_id=None):
    qs = Category.objects.all()
    if company_id:
        qs = qs.filter(company_id=company_id)
    try:
        cat = qs.get(name=category_name)
    except Category.DoesNotExist:
        return []
    return list(Question.objects.filter(category=cat))

@sync_to_async
def save_user_question_async(user_id, username, category_name, content_text, content_photo, content_voice, company_id=None, responsible_id=None, mention_id=None):
    qs = Category.objects.all()
    if company_id:
        qs = qs.filter(company_id=company_id)
    try:
        cat = qs.get(name=category_name)
    except Category.DoesNotExist:
        cat = None
    UserQuestion.objects.create(
        user_id=user_id,
        username=username,
        category=cat,
        content_text=content_text,
        content_photo=content_photo,
        content_voice=content_voice,
        responsible_id=responsible_id,
        mention_id=mention_id
    )

@sync_to_async
def get_category_for_company_async(category_name: Optional[str], company_id: Optional[int]):
    if not category_name or not company_id:
        return None
    return Category.objects.filter(name=category_name, company_id=company_id).first()


@sync_to_async
def get_or_create_category_for_company_async(company_id: Optional[int], category_name: str):
    if not company_id:
        return None
    category, _ = Category.objects.get_or_create(name=category_name, company_id=company_id)
    return category


@sync_to_async
def update_category_topic_id_async(category_id: int, topic_id: int):
    Category.objects.filter(id=category_id).update(responsible_topic_id=str(topic_id))


@sync_to_async
def create_message_log_entry_async(teleuser: TeleUser, company: Company, category: Optional[Category],
                                   from_group_id: Optional[int], to_group_id: int, topic_id: Optional[int],
                                   content_text: Optional[str], content_photo: Optional[str],
                                   content_voice: Optional[str]):
    return MessageLog.objects.create(
        teleuser=teleuser,
        company=company,
        category=category,
        from_group_id=int(from_group_id) if from_group_id is not None else 0,
        to_group_id=int(to_group_id),
        topic_id=topic_id,
        content_text=content_text or "",
        content_photo=content_photo,
        content_voice=content_voice
    )


async def ensure_category_topic(category: Category, company: Company) -> Optional[int]:
    if not category or not company or not company.manager_group_id:
        return None
    if category.responsible_topic_id:
        try:
            return int(category.responsible_topic_id)
        except (TypeError, ValueError):
            logger.warning("Invalid topic id stored for category %s: %s", category.id, category.responsible_topic_id)
    try:
        forum_topic = await bot.create_forum_topic(int(company.manager_group_id), name=category.name)
    except Exception as exc:
        logger.error("Failed to create forum topic for category %s: %s", category.id, exc)
        return None
    thread_id = forum_topic.message_thread_id
    await update_category_topic_id_async(category.id, thread_id)
    category.responsible_topic_id = str(thread_id)
    return thread_id


async def download_file_as_base64(file_id: str) -> Optional[str]:
    try:
        tg_file = await bot.get_file(file_id)
        downloaded = await bot.download_file(tg_file.file_path)
        if hasattr(downloaded, "read"):
            file_bytes = downloaded.read()
        else:
            file_bytes = downloaded.getvalue()
        return base64.b64encode(file_bytes).decode()
    except Exception as exc:
        logger.error("Failed to download media %s: %s", file_id, exc)
        return None

# ---------------------------
#  Group messages handler
# ---------------------------
@dp.message_handler(lambda message: message.chat.type in ["group", "supergroup"])
async def group_redirect(message: types.Message):
    text = message.text or ""
    bot_username = (await bot.get_me()).username.lower()
    if f"@{bot_username}" in text.lower():
        inline_kb = InlineKeyboardMarkup().add(InlineKeyboardButton("Go to Bot", url=f"https://t.me/{bot_username}"))
        await message.reply(
            "Hello! I am a bot to assist drivers. Click the button below to start a private conversation with me. Please ask an administrator to pin this message to keep it accessible.",
            reply_markup=inline_kb
        )

# ---------------------------
#  Handle bot added to group
# ---------------------------
@dp.chat_member_handler()
async def handle_bot_added_to_group(update: types.ChatMemberUpdated):
    if update.new_chat_member.status in ['member', 'administrator'] and update.old_chat_member.status == 'left':
        chat_id = update.chat.id
        bot_username = (await bot.get_me()).username
        inline_kb = InlineKeyboardMarkup().add(InlineKeyboardButton("Go to Bot", url=f"https://t.me/{bot_username}"))
        await bot.send_message(
            chat_id=chat_id,
            text="Hello! I am a bot to assist drivers. Click the button below to start a private conversation with me. Please ask an administrator to pin this message to keep it accessible.",
            reply_markup=inline_kb
        )

# ---------------------------
#  Inline Mode handler
# ---------------------------
@dp.inline_handler()
async def inline_query_echo(inline_query: types.InlineQuery):
    text = inline_query.query or "Empty question"
    result = InlineQueryResultArticle(
        id="1",
        title="Send this text",
        description=(text[:50] + "...") if len(text) > 50 else text,
        input_message_content=InputTextMessageContent(text)
    )
    await inline_query.answer([result], cache_time=1, is_personal=True)

# ---------------------------
#  /start, /help handler
# ---------------------------
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user_selected_category[user_id] = None
    user_state[user_id] = STATE_NONE

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    existing_user = await get_teleuser_by_id(user_id)
    if existing_user:
        categories = await get_categories_async(company_id=existing_user.company_id)
        for cat in categories:
            kb.add(cat.name)
        await message.answer(
            "Hello! Select a category:",
            reply_markup=kb
        )
    else:
        kb.add("Register")
        await message.answer(
            "Hello! You need to register first. Press 'Register':",
            reply_markup=kb
        )

def generate_calendar(year, month, min_date=None):
    kb = InlineKeyboardMarkup(row_width=7)
    row = []
    row.append(InlineKeyboardButton("<", callback_data=f"CALENDAR:{year}:{month}:PREV"))
    row.append(InlineKeyboardButton(f"{calendar.month_name[month]} {year}", callback_data="IGNORE"))
    row.append(InlineKeyboardButton(">", callback_data=f"CALENDAR:{year}:{month}:NEXT"))
    kb.row(*row)

    week_days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    row = [InlineKeyboardButton(day, callback_data="IGNORE") for day in week_days]
    kb.row(*row)

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.itermonthdates(year, month)
    temp_row = []
    today = date.today()
    for d in month_days:
        if d.month != month:
            btn = InlineKeyboardButton(" ", callback_data="IGNORE")
        else:
            weekday = calendar.weekday(d.year, d.month, d.day)
            if weekday in [5, 6]:  # Суббота и воскресенье
                btn = InlineKeyboardButton(str(d.day), callback_data="IGNORE")
            elif min_date and d < min_date:
                btn = InlineKeyboardButton(str(d.day), callback_data="IGNORE")
            else:
                btn = InlineKeyboardButton(str(d.day), callback_data=f"CALENDAR:{d.year}:{d.month}:{d.day}:DAY")
        temp_row.append(btn)
        if len(temp_row) == 7:
            kb.row(*temp_row)
            temp_row = []
    if temp_row:
        kb.row(*temp_row)
    return kb

@dp.callback_query_handler(lambda c: c.data.startswith("CALENDAR"))
async def process_calendar_callback(callback_query: types.CallbackQuery):
    logger.info(f"Processing calendar callback: {callback_query.data}")
    data = callback_query.data.split(":")
    year = int(data[1])
    month = int(data[2])
    action = data[-1]
    user_id = callback_query.from_user.id

    if user_id not in temp_user_data:
        temp_user_data[user_id] = {}

    st = user_state.get(user_id)
    logger.info(f"Current state for user {user_id}: {st}")

    if st == STATE_TIMEOFF_FROM:
        min_date = date.today()
    elif st == STATE_TIMEOFF_TILL:
        from_date = temp_user_data[user_id].get("timeoff_from", date.today())
        min_date = from_date
    else:
        min_date = None

    if action in ["PREV", "NEXT"]:
        logger.info(f"Navigating calendar: {action}")
        if action == "PREV":
            if min_date:
                min_yr, min_mo = min_date.year, min_date.month
                if (year < min_yr) or (year == min_yr and month <= min_mo):
                    await callback_query.answer("Cannot select previous months!", show_alert=True)
                    return
            month -= 1
            if month < 1:
                month = 12
                year -= 1
        else:
            month += 1
            if month > 12:
                month = 1
                year += 1
        kb = generate_calendar(year, month, min_date=min_date)
        await callback_query.message.edit_text("Select date:", reply_markup=kb)
        await callback_query.answer()
    elif action == "DAY":
        logger.info(f"Day selected: {data[3]}")
        day = int(data[3])
        selected_date = date(year, month, day)
        if min_date and selected_date < min_date:
            await callback_query.answer("This date is not allowed!", show_alert=True)
            return
        weekday = calendar.weekday(selected_date.year, selected_date.month, selected_date.day)
        if weekday in [5, 6]:
            await callback_query.answer("Weekends are not allowed!", show_alert=True)
            return
        if st == STATE_TIMEOFF_FROM:
            logger.info(f"FROM date selected: {selected_date}")
            temp_user_data[user_id]["timeoff_from"] = selected_date
            user_state[user_id] = STATE_TIMEOFF_TILL
            kb = generate_calendar(selected_date.year, selected_date.month, min_date=selected_date)
            await callback_query.message.edit_text(
                f"FROM date chosen: {selected_date}\nNow select TILL date (max 7 days):",
                reply_markup=kb
            )
            await callback_query.answer()
        elif st == STATE_TIMEOFF_TILL:
            logger.info(f"TILL date selected: {selected_date}")
            from_date = temp_user_data[user_id]["timeoff_from"]
            logger.info(f"Comparing FROM {from_date} with TILL {selected_date}")
            if (selected_date - from_date).days > 7:
                await callback_query.answer("Maximum period is 7 days!", show_alert=True)
                return
            weekday_to = calendar.weekday(selected_date.year, selected_date.month, selected_date.day)
            if weekday_to in [5, 6]:
                await callback_query.answer("Weekends are not allowed!", show_alert=True)
                return
            temp_user_data[user_id]["timeoff_till"] = selected_date
            user_state[user_id] = STATE_TIMEOFF_REASON
            logger.info(f"Transitioning to STATE_TIMEOFF_REASON for user {user_id}")
            try:
                await callback_query.message.delete()
                await callback_query.message.answer(
                    f"You chose time off from {from_date} to {selected_date}.\nPlease enter reason:",
                    reply_markup=ReplyKeyboardRemove()
                )
            except Exception as e:
                logger.error(f"Error while transitioning to reason step: {e}")
                await callback_query.message.answer("An error occurred. Please start over with /start.")
                user_state[user_id] = STATE_NONE
                temp_user_data[user_id] = {}
            await callback_query.answer()
        else:
            await callback_query.answer("Unexpected state!", show_alert=True)

# ---------------------------
#  Helper function to send question
# ---------------------------
async def send_question_directly(user_id: int, cat_name: str, content_text: str, content_photo: str, content_voice: str,
                                 message: types.Message, is_call_me=False):
    teleuser = await get_teleuser_by_id(user_id)
    if not teleuser:
        await message.answer("You are not registered!")
        user_state[user_id] = STATE_NONE
        return

    company = teleuser.company
    if not company:
        await message.answer("Your account is not linked to a company. Please contact an administrator.")
        return

    if cat_name:
        category = await get_category_for_company_async(cat_name, company.id)
        if not category:
            await message.answer("Selected category is not available. Please choose another one.")
            return
    else:
        category = await get_or_create_category_for_company_async(company.id, DEFAULT_GENERAL_CATEGORY_NAME)

    manager_group_id = company.manager_group_id
    if not manager_group_id:
        await message.answer("Manager group is not configured. Please contact an administrator.")
        return

    topic_id = await ensure_category_topic(category, company)
    if topic_id is None:
        await message.answer("Failed to access the discussion topic for this category.")
        return

    display_name_parts = []
    if teleuser.first_name:
        display_name_parts.append(teleuser.first_name)
    if teleuser.nickname:
        display_name_parts.append(f"({teleuser.nickname})")
    display_name = " ".join(display_name_parts).strip() or str(user_id)
    if message.from_user.username:
        display_name = f"{display_name} - @{message.from_user.username}"

    summary_lines = [
        f"📨 Message from {display_name}",
        f"Category: {category.name}",
        f"Type: {'Call request' if is_call_me else 'Message'}"
    ]
    if content_text:
        summary_lines.append(f"Text: {content_text}")
    if content_photo:
        summary_lines.append("Photo attached below.")
    if content_voice:
        summary_lines.append("Voice message attached below.")

    summary_text = "\n".join(summary_lines)

    try:
        await bot.send_message(
            int(manager_group_id),
            summary_text,
            message_thread_id=topic_id
        )
        await bot.copy_message(
            chat_id=int(manager_group_id),
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=topic_id
        )
    except Exception as exc:
        logger.error("Failed to forward message to managers: %s", exc)
        await message.answer("Failed to forward your message. Please try again later.")
        return

    photo_b64 = await download_file_as_base64(content_photo) if content_photo else None
    voice_b64 = await download_file_as_base64(content_voice) if content_voice else None

    await save_user_question_async(
        user_id,
        message.from_user.username or "",
        category.name,
        content_text or "",
        content_photo or "",
        content_voice or "",
        company_id=company.id,
        responsible_id=str(manager_group_id),
        mention_id=str(topic_id)
    )

    from_group = company.driver_group_id if company.driver_group_id is not None else message.chat.id
    await create_message_log_entry_async(
        teleuser=teleuser,
        company=company,
        category=category,
        from_group_id=from_group,
        to_group_id=int(manager_group_id),
        topic_id=topic_id,
        content_text=content_text or "",
        content_photo=photo_b64,
        content_voice=voice_b64
    )

    action = "call request" if is_call_me else "message"
    await message.answer(f"Your {action} has been saved and sent to specialists. Thank you!")
    user_state[user_id] = STATE_NONE

    updated_user = await get_teleuser_by_id(user_id)
    company_id = updated_user.company_id if updated_user else None
    cats = await get_categories_async(company_id=company_id)
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for c in cats:
        kb.add(c.name)
    kb.add("Back")
    await message.answer("Choose a category:", reply_markup=kb)

# ---------------------------
#  Main message handler
# ---------------------------
@dp.message_handler(content_types=['text', 'photo', 'voice'])
async def handle_message(message: types.Message):
    logger.info(f"Received message from user {message.from_user.id}: {message.text}")
    if message.chat.type in ["group", "supergroup"]:
        return

    text = message.caption or message.text.strip() if message.caption or message.text else None
    user_id = message.from_user.id
    current_cat = user_selected_category.get(user_id)
    current_state = user_state.get(user_id, STATE_NONE)
    logger.info(f"User {user_id} state: {current_state}, category: {current_cat}")

    # --- Обработка кнопки "Back" для Time Off ---
    if text == "Back" and current_state in [STATE_TIMEOFF_FROM, STATE_TIMEOFF_TILL, STATE_TIMEOFF_REASON, STATE_TIMEOFF_PAUSE]:
        logger.info(f"User {user_id} canceled Time Off")
        user_state[user_id] = STATE_NONE
        temp_user_data[user_id] = {}
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Request Time Off")
        teleuser = await get_teleuser_by_id(user_id)
        company_id = teleuser.company_id if teleuser else None
        questions = await get_questions_for_category_async("Safety", company_id=company_id)
        for q in questions:
            kb.add(q.question)
        kb.add("Ask your questions")
        kb.add("Back")
        await message.answer("Time-Off request canceled. You are in Safety category:", reply_markup=kb)
        user_selected_category[user_id] = "Safety"
        return

    # --- Обработка кнопки "Back" для категорий ---
    if text == "Back" and current_state == STATE_NONE:
        user_selected_category[user_id] = None
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            kb.add("Register")
        else:
            cats = await get_categories_async(company_id=teleuser.company_id)
            for c in cats:
                kb.add(c.name)
        await message.answer("You have returned to the list of categories.", reply_markup=kb)
        return

    if current_state == STATE_INLINE_EDIT:
        pending = pending_question.pop(user_id, None)
        if not pending:
            await message.answer("No pending question found.")
            user_state[user_id] = STATE_NONE
            return
        final_text = message.text
        category_name = pending["category"]
        await send_question_directly(user_id, category_name, final_text, "", "", message)
        user_state[user_id] = STATE_NONE
        return

    if current_state == STATE_CONFIRM_PENDING:
        if text == "Send":
            p = pending_question.pop(user_id, None)
            if not p:
                await message.answer("No pending question found.")
                user_state[user_id] = STATE_NONE
                return
            await send_question_directly(user_id, p["category"], p["content_text"], p["content_photo"], p["content_voice"], message)
            return
        elif text == "Edit":
            user_state[user_id] = STATE_INLINE_EDIT
            old_text = pending_question[user_id]["content_text"]
            inline_kb = InlineKeyboardMarkup()
            inline_kb.add(
                InlineKeyboardButton(
                    "Edit in inline mode",
                    switch_inline_query_current_chat=old_text
                )
            )
            await message.answer("Click below to edit your question in inline mode.", reply_markup=inline_kb)
            return
        else:
            pending_question.pop(user_id, None)
            await message.answer("Pending question canceled.")
            user_state[user_id] = STATE_NONE
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            teleuser = await get_teleuser_by_id(user_id)
            if not teleuser:
                kb.add("Register")
            company_id = teleuser.company_id if teleuser else None
            cats = await get_categories_async(company_id=company_id)
            for c in cats:
                kb.add(c.name)
            await message.answer("Choose a category:", reply_markup=kb)
            return

    if current_state == STATE_AWAITING_CONTENT and current_cat:
        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            pending_question[user_id] = {"category": current_cat, "content_text": text or "", "content_photo": "",
                                       "content_voice": ""}
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("Register")
            company_id_for_list = teleuser.company_id if teleuser else None
            cats = await get_categories_async(company_id=company_id_for_list)
            for c in cats:
                kb.add(c.name)
            await message.answer(
                "You are not registered yet. Please press 'Register' first!",
                reply_markup=kb
            )
            user_selected_category[user_id] = None
            user_state[user_id] = STATE_NONE
            return

        content_text = text or ""
        content_photo = message.photo[-1].file_id if message.photo else ""
        content_voice = message.voice.file_id if message.voice else ""

        if content_text or content_photo or content_voice:
            await send_question_directly(user_id, current_cat, content_text, content_photo, content_voice, message)
        else:
            await message.answer("Please provide a text, photo, or voice message.")
        return

    if text == "Register":
        existing_user = await get_teleuser_by_id(user_id)
        if existing_user:
            await message.answer("You are already registered!")
            return
        else:
            user_state[user_id] = STATE_REG_NAME
            temp_user_data[user_id] = {}
            await message.answer("Enter your name:", reply_markup=ReplyKeyboardRemove())
            return

    if current_state == STATE_REG_NAME:
        temp_user_data[user_id]["name"] = text
        user_state[user_id] = STATE_REG_TRUCK
        await message.answer("Enter your truck number (or 'no' if none):")
        return

    if current_state == STATE_REG_TRUCK:
        temp_user_data[user_id]["truck_number"] = text
        data = temp_user_data[user_id]
        await create_teleuser(
            user_id,
            data["name"],
            data["truck_number"],
            company_id=None
        )
        await message.answer("Registration complete!")
        user_state[user_id] = STATE_NONE
        temp_user_data[user_id] = {}

        if user_id in pending_question:
            p = pending_question[user_id]
            cat = p["category"]
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("Send", "Edit")
            kb.add("Cancel")
            await message.answer(
                f"You had a pending question in category '{cat}':\n\nText: {p['content_text'] or 'No text'}\n"
                f"Photo: {'Yes' if p['content_photo'] else 'No'}\nVoice: {'Yes' if p['content_voice'] else 'No'}\n"
                "Choose 'Send', 'Edit', or 'Cancel'.",
                reply_markup=kb
            )
            user_state[user_id] = STATE_CONFIRM_PENDING
            return

        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        new_teleuser = await get_teleuser_by_id(user_id)
        cats = await get_categories_async(company_id=new_teleuser.company_id if new_teleuser else None)
        for c in cats:
            kb.add(c.name)
        await message.answer("Now you can choose a category:", reply_markup=kb)
        return

    if text == "Request Time Off" and current_cat == "Safety":
        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            await message.answer("You are not registered. Please register first!")
            return
        if user_id not in temp_user_data:
            temp_user_data[user_id] = {}
        user_state[user_id] = STATE_TIMEOFF_FROM
        today = date.today()
        kb = generate_calendar(today.year, today.month, min_date=today)
        timeoff_kb = ReplyKeyboardMarkup(resize_keyboard=True)
        timeoff_kb.add("Back")
        await message.answer("Request Time Off", reply_markup=ReplyKeyboardRemove())
        await message.answer("Select FROM date (Mon-Fri only, max 7 days):\nUse the calendar below:", reply_markup=kb)
        await message.answer("To cancel, press 'Back'", reply_markup=timeoff_kb)
        return

    if current_state == STATE_TIMEOFF_FROM:
        await message.answer("Please select FROM date from the calendar above.")
        return

    if current_state == STATE_TIMEOFF_TILL:
        await message.answer("Please select TILL date from the calendar above.")
        return

    if current_state == STATE_TIMEOFF_REASON:
        temp_user_data[user_id]["timeoff_reason"] = text
        user_state[user_id] = STATE_TIMEOFF_PAUSE
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Yes", "No")
        kb.add("Back")
        await message.answer("Pause Insurance and ELD?", reply_markup=kb)
        return

    if current_state == STATE_TIMEOFF_PAUSE:
        p_text = text.lower()
        pause_val = (p_text == "yes")
        temp_user_data[user_id]["timeoff_pause"] = pause_val
        data = temp_user_data[user_id]
        df = data["timeoff_from"]
        dt = data["timeoff_till"]
        reason = data["timeoff_reason"]
        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            await message.answer("You are not registered! Something went wrong.")
            user_state[user_id] = STATE_NONE
            return
        await create_timeoff(teleuser.id, df, dt, reason, pause_val)
        company = teleuser.company
        if not company or not company.manager_group_id:
            await message.answer("Manager group is not configured. Please contact an administrator.")
            user_state[user_id] = STATE_NONE
            return

        user_display_name = teleuser.first_name or "Unknown"
        user_nick = teleuser.nickname or ""
        pause_text = "YES" if pause_val else "NO"
        forward_text = (
            f"New Time-Off request!\n"
            f"User: {user_display_name} ({user_nick})\n"
            f"From: {df}\n"
            f"Till: {dt}\n"
            f"Reason: {reason}\n"
            f"Pause Insurance/ELD: {pause_text}"
        )

        category = await get_category_for_company_async("Safety", company.id)
        if not category:
            category = await get_or_create_category_for_company_async(company.id, "Safety")

        topic_id = await ensure_category_topic(category, company)
        if topic_id is None:
            await message.answer("Failed to access the discussion topic for Safety category.")
            user_state[user_id] = STATE_NONE
            return

        try:
            await bot.send_message(
                int(company.manager_group_id),
                text=forward_text,
                message_thread_id=topic_id
            )
        except Exception as e:
            logger.error("Failed to send time-off request to managers: %s", e)
            await message.answer(f"Failed to send to specialists: {e}")
            return

        from_group = company.driver_group_id if company.driver_group_id is not None else message.chat.id
        await create_message_log_entry_async(
            teleuser=teleuser,
            company=company,
            category=category,
            from_group_id=from_group,
            to_group_id=int(company.manager_group_id),
            topic_id=topic_id,
            content_text=forward_text,
            content_photo=None,
            content_voice=None
        )

        await message.answer("Your Time-Off request has been saved and sent to specialists.", reply_markup=ReplyKeyboardRemove())
        user_state[user_id] = STATE_NONE
        temp_user_data[user_id] = {}
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Request Time Off")
        questions = await get_questions_for_category_async("Safety", company_id=company.id)
        for q in questions:
            kb.add(q.question)
        kb.add("Ask your questions")
        kb.add("Back")
        await message.answer("You are in Safety category:", reply_markup=kb)
        user_selected_category[user_id] = "Safety"
        return

    teleuser_for_category = await get_teleuser_by_id(user_id)
    company_id_for_category = teleuser_for_category.company_id if teleuser_for_category else None
    category_obj = await get_category_for_company_async(text, company_id_for_category)
    if category_obj:
        user_selected_category[user_id] = category_obj.name
        user_state[user_id] = STATE_NONE
        questions = await get_questions_for_category_async(category_obj.name, company_id=company_id_for_category)
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        for q in questions:
            kb.add(q.question)
        kb.add("Ask your questions")
        if category_obj.name == "Safety":
            kb.add("Request Time Off")
        kb.add("Back")
        await message.answer(
            f"Category: <b>{category_obj.name}</b>\nChoose a ready-made question or click 'Ask your questions':",
            reply_markup=kb
        )
        return

    if current_cat:
        questions = await get_questions_for_category_async(current_cat, company_id=company_id_for_category)
        found = None
        for q in questions:
            if text == q.question:
                found = q
                break
        if found:
            await message.answer(found.answer)
            return
        if text == "Ask your questions":
            user_state[user_id] = STATE_AWAITING_CONTENT
            await message.answer("Send text, photo, or voice message (or any combination):", reply_markup=ReplyKeyboardRemove())
            return
        await message.answer("I did not understand your choice. Please select a ready question, click 'Ask your questions', or 'Back'.")
        return

    await message.answer("Please choose a category or enter command /start.")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)