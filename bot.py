import os
import django
from asgiref.sync import sync_to_async

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Saypress.settings')
django.setup()

import logging
import base64
from typing import Dict, List, Optional, Tuple, Union
from django.db.models import Q
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultArticle,
    InputTextMessageContent,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeAllGroupChats,
)
from aiogram.utils.exceptions import BadRequest
from aiogram.dispatcher.handler import SkipHandler

from main.models import (
    Category,
    Question,
    UserQuestion,
    TeleUser,
    Company,
    TimeOff,
    MessageLog,
    TopicMap,
    ManagerGroup,
    ManagerTopic,
)
from datetime import datetime, date
import calendar

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _normalize_topic_key(name: Optional[str]) -> Optional[str]:
    """Return a normalized key for topic name comparisons."""

    if not name:
        return None
    normalized = " ".join(str(name).split()).strip()
    return normalized.casefold() if normalized else None


class StoredTopicInfo:
    """Lightweight container to mimic Telegram forum topic attributes."""

    __slots__ = ("message_thread_id",)

    def __init__(self, thread_id: Optional[int]):
        self.message_thread_id = thread_id

    @property
    def thread_id(self) -> Optional[int]:
        """Alias to keep compatibility with helpers that expect ``thread_id`` attribute."""

        return self.message_thread_id


class StoredManagerTopicInfo:
    """Represents a topic stored for a specific manager group."""

    __slots__ = ("thread_id", "topic_name", "category_name")

    def __init__(self, thread_id: int, topic_name: str, category_name: str):
        self.thread_id = int(thread_id)
        self.topic_name = topic_name
        self.category_name = category_name

TOKEN = "7640503340:AAFQTJquUcNYwBK4EVSFcErX52BhTjbWKAA"
bot = Bot(token=TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)


async def setup_commands(bot_instance: Bot) -> None:
    """Register bot commands for both private and group chats."""
    commands = [
        BotCommand(command="run", description="create topics in manager group"),
        BotCommand(command="sync", description="synchronize topics without creating duplicates"),
        BotCommand(command="get", description="show group id"),
    ]

    try:
        await bot_instance.set_my_commands(commands, scope=BotCommandScopeDefault())
        await bot_instance.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
    except Exception as exc:
        logger.error("Failed to set bot commands: %s", exc)
    else:
        logger.info("Bot commands registered successfully")

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
        qs = qs.filter(Q(company_id=company_id) | Q(company__isnull=True))
    return list(qs)

@sync_to_async
def get_questions_for_category_async(category_name: str, company_id=None):
    qs = Category.objects.all()
    if company_id:
        qs = qs.filter(Q(company_id=company_id) | Q(company__isnull=True))
    try:
        cat = qs.get(name=category_name)
    except Category.DoesNotExist:
        return []
    return list(Question.objects.filter(category=cat))

@sync_to_async
def save_user_question_async(user_id, username, category_name, content_text, content_photo, content_voice, company_id=None, responsible_id=None, mention_id=None):
    qs = Category.objects.all()
    if company_id:
        qs = qs.filter(Q(company_id=company_id) | Q(company__isnull=True))
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
    if not category_name:
        return None
    qs = Category.objects.filter(name=category_name)
    if company_id:
        qs = qs.filter(Q(company_id=company_id) | Q(company__isnull=True))
    return qs.first()


@sync_to_async
def get_or_create_category_for_company_async(company_id: Optional[int], category_name: str):
    if not category_name:
        return None
    filters = {"name": category_name}
    qs = Category.objects.filter(**filters)
    if company_id:
        qs = qs.filter(Q(company_id=company_id) | Q(company__isnull=True))
    category = qs.first()
    if category:
        return category
    defaults = {}
    if company_id:
        defaults["company_id"] = company_id
    category, _ = Category.objects.get_or_create(name=category_name, defaults=defaults)
    if company_id and category.company_id != company_id:
        category.company_id = company_id
        category.save(update_fields=["company"])
    return category


@sync_to_async
def create_message_log_entry_async(
    teleuser: TeleUser,
    company: Optional[Company],
    category: Optional[Category],
    from_group_id: Optional[int],
    to_group_id: Optional[int],
    topic_id: Optional[int],
    content_text: Optional[str],
    content_photo: Optional[str],
    content_voice: Optional[str],
    *,
    driver_group_id: Optional[int] = None,
    manager_group_id: Optional[int] = None,
    category_name: Optional[str] = None,
):
    return MessageLog.objects.create(
        teleuser=teleuser,
        company=company,
        category=category,
        category_name=category_name or (category.name if category else None),
        from_group_id=int(from_group_id) if from_group_id is not None else None,
        to_group_id=int(to_group_id) if to_group_id is not None else None,
        topic_id=topic_id,
        content_text=content_text or "",
        content_photo=content_photo,
        content_voice=content_voice,
        driver_group_id=int(driver_group_id) if driver_group_id is not None else None,
        manager_group_id=int(manager_group_id) if manager_group_id is not None else None,
    )


@sync_to_async
def get_topic_map_async(teleuser_id: int, category_id: int):
    return TopicMap.objects.filter(teleuser_id=teleuser_id, category_id=category_id).first()


@sync_to_async
def create_topic_map_async(teleuser: TeleUser, category: Category, topic_id: int):
    try:
        obj, _ = TopicMap.objects.update_or_create(
            teleuser=teleuser,
            category=category,
            defaults={"topic_id": topic_id},
        )
        return obj
    except Exception as exc:
        logger.error("Failed to create topic map for %s (%s): %s", teleuser.id, category.name, exc)
        return None


@sync_to_async
def update_category_topic_link(category_id: int, thread_id: int) -> None:
    try:
        Category.objects.filter(pk=category_id).update(responsible_topic_id=str(thread_id))
    except Exception as exc:
        logger.error(
            "Failed to persist topic link for category %s with thread %s: %s",
            category_id,
            thread_id,
            exc,
        )


@sync_to_async
def get_manager_topics_map_async(group_id: int) -> dict:
    group, _ = ManagerGroup.objects.get_or_create(group_id=group_id)
    by_name = {}
    by_id = {}
    for topic in group.topics.all().order_by("-created_at"):
        info = StoredManagerTopicInfo(
            thread_id=topic.thread_id,
            topic_name=topic.topic_name or topic.category_name,
            category_name=topic.category_name,
        )
        if topic.category_id and topic.category_id not in by_id:
            by_id[topic.category_id] = info
        normalized_name = _normalize_topic_key(topic.category_name)
        if topic.category_name and normalized_name and normalized_name not in by_name:
            by_name[normalized_name] = info
        topic_name_key = _normalize_topic_key(topic.topic_name)
        if topic.topic_name and topic_name_key and topic_name_key not in by_name:
            by_name[topic_name_key] = info
    return {"by_name": by_name, "by_id": by_id}


@sync_to_async
def fetch_manager_topic_async(group_id: int, category: Optional[Category], category_name: str) -> Optional[StoredManagerTopicInfo]:
    qs = ManagerTopic.objects.filter(group__group_id=group_id)
    if category and category.id:
        topic = qs.filter(category_id=category.id).order_by("-created_at").first()
        if topic:
            return StoredManagerTopicInfo(
                thread_id=topic.thread_id,
                topic_name=topic.topic_name or topic.category_name,
                category_name=topic.category_name,
            )
    normalized_name = (category_name or "").strip()
    topic = (
        ManagerTopic.objects.filter(group__group_id=group_id, category_name__iexact=normalized_name)
        .order_by("-created_at")
        .first()
    )
    if topic:
        return StoredManagerTopicInfo(
            thread_id=topic.thread_id,
            topic_name=topic.topic_name or topic.category_name,
            category_name=topic.category_name,
        )
    return None


@sync_to_async
def store_manager_topic_async(
    group_id: int,
    *,
    category: Optional[Category],
    thread_id: int,
    topic_name: Optional[str] = None,
) -> StoredManagerTopicInfo:
    group, _ = ManagerGroup.objects.get_or_create(group_id=group_id)
    base_category_name = category.name if category else (topic_name or "Topic")
    category_name = (base_category_name or "Topic").strip()
    topic_title = (topic_name or category_name).strip()
    thread_id = int(thread_id)
    defaults = {
        "topic_name": topic_title,
        "category": category,
        "thread_id": thread_id,
    }
    manager_topic, created = ManagerTopic.objects.update_or_create(
        group=group,
        category_name=category_name,
        defaults=defaults,
    )

    updates = {}
    if manager_topic.thread_id != thread_id:
        updates["thread_id"] = thread_id
    if manager_topic.topic_name != topic_title:
        updates["topic_name"] = topic_title
    if category and manager_topic.category_id != category.id:
        updates["category_id"] = category.id
    if updates:
        ManagerTopic.objects.filter(pk=manager_topic.pk).update(**updates)

    return StoredManagerTopicInfo(
        thread_id=thread_id,
        topic_name=topic_title,
        category_name=category_name,
    )


@sync_to_async
def get_topic_by_category(category_name: str, chat_id: int) -> Optional[StoredTopicInfo]:
    """Fetch stored topic information for a category within a manager group."""

    try:
        category = Category.objects.get(name=category_name)
    except Category.DoesNotExist:
        return None

    manager_topic = (
        ManagerTopic.objects.filter(group__group_id=chat_id, category=category)
        .order_by("-created_at")
        .first()
    )
    if not manager_topic:
        manager_topic = (
            ManagerTopic.objects.filter(group__group_id=chat_id, category_name__iexact=category_name.strip())
            .order_by("-created_at")
            .first()
        )
    if manager_topic and manager_topic.thread_id:
        try:
            thread_id = int(manager_topic.thread_id)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid thread id '%s' stored for manager group %s and category %s",
                manager_topic.thread_id,
                chat_id,
                category.id,
            )
        else:
            return StoredTopicInfo(thread_id)

    mapping = (
        TopicMap.objects.filter(
            teleuser__manager_group_id=chat_id,
            category=category,
        )
        .order_by("-created_at")
        .first()
    )
    if mapping and mapping.topic_id:
        try:
            thread_id = int(mapping.topic_id)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid topic id '%s' stored in TopicMap %s for category %s",
                mapping.topic_id,
                mapping.id,
                category.id,
            )
        else:
            return StoredTopicInfo(thread_id)

    stored_thread_id = category.responsible_topic_id
    if stored_thread_id:
        try:
            thread_id = int(stored_thread_id)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid responsible topic id '%s' for category %s",
                stored_thread_id,
                category.id,
            )
        else:
            return StoredTopicInfo(thread_id)

    return None


async def safe_get_forum_topic(
    chat_id: Union[int, str],
    *,
    message_thread_id: Optional[int] = None,
    name: Optional[str] = None,
) -> Optional[types.ForumTopic]:
    """Safely fetch a forum topic by thread id or name."""

    if message_thread_id is None and name is None:
        raise ValueError("Either message_thread_id or name must be provided")

    method = getattr(bot, "get_forum_topic", None)

    if method:
        kwargs = {"chat_id": chat_id}
        if message_thread_id is not None:
            kwargs["message_thread_id"] = message_thread_id
        if name is not None:
            kwargs["name"] = name

        try:
            return await method(**kwargs)
        except TypeError:
            logger.debug("Bot.get_forum_topic does not accept provided parameters")
        except BadRequest as exc:
            error_text = str(exc).lower()
            if "not found" in error_text or ("topic" in error_text and "exist" in error_text):
                return None
            raise
        except Exception as exc:
            logger.error("Unexpected error while fetching forum topic: %s", exc)
            return None

    request_payload: Dict[str, Union[int, str]] = {"chat_id": chat_id}

    if message_thread_id is not None:
        try:
            request_payload["message_thread_id"] = int(message_thread_id)
        except (TypeError, ValueError):
            logger.error(
                "Invalid thread id '%s' supplied when requesting forum topic in chat %s",
                message_thread_id,
                chat_id,
            )
            return None

        try:
            response = await bot.request("getForumTopic", request_payload)
        except BadRequest as exc:
            if "not found" in str(exc).lower():
                return None
            logger.error(
                "Failed to request getForumTopic by thread id %s in chat %s: %s",
                message_thread_id,
                chat_id,
                exc,
            )
            return None
        except Exception as exc:
            logger.error(
                "Unexpected error while requesting forum topic %s in chat %s: %s",
                message_thread_id,
                chat_id,
                exc,
            )
            return None
        else:
            if isinstance(response, types.ForumTopic):
                return response
            try:
                return types.ForumTopic.de_json(response, bot)
            except Exception as exc:
                logger.error("Unable to parse forum topic response: %s", exc)
                return None

    if name is not None:
        request_payload_with_name = dict(request_payload)
        request_payload_with_name.pop("message_thread_id", None)
        request_payload_with_name["name"] = name

        try:
            response = await bot.request("getForumTopic", request_payload_with_name)
        except BadRequest as exc:
            if "not found" in str(exc).lower():
                return None
            logger.error(
                "Failed to request getForumTopic by name '%s' in chat %s: %s",
                name,
                chat_id,
                exc,
            )
            return None
        except Exception as exc:
            logger.error("Failed to request getForumTopic by name: %s", exc)
            return None
        else:
            if isinstance(response, types.ForumTopic):
                return response
            try:
                return types.ForumTopic.de_json(response, bot)
            except Exception as exc:
                logger.error("Unable to parse forum topic response: %s", exc)
                return None

    return None


async def list_forum_topics(chat_id: int) -> List[types.ForumTopic]:
    """Fetch all available forum topics for the provided chat."""

    method = getattr(bot, "get_forum_topics", None)
    if not method:
        logger.debug("Bot instance does not expose get_forum_topics; skipping pre-fetch")
        return []

    try:
        response = await method(chat_id=chat_id)
    except BadRequest as exc:
        logger.error("Failed to load forum topics for chat %s: %s", chat_id, exc)
        return []
    except Exception as exc:
        logger.error("Unexpected error while loading forum topics for chat %s: %s", chat_id, exc)
        return []

    raw_topics = getattr(response, "forum_topics", None)
    if raw_topics is None:
        if isinstance(response, dict):
            raw_topics = response.get("forum_topics", [])
        elif isinstance(response, (list, tuple)):
            raw_topics = response
        else:
            raw_topics = []

    topics: List[types.ForumTopic] = []
    for entry in raw_topics or []:
        if isinstance(entry, types.ForumTopic):
            topics.append(entry)
            continue
        try:
            topics.append(types.ForumTopic.de_json(entry, bot))
        except Exception as exc:
            logger.warning("Unable to parse forum topic entry for chat %s: %s", chat_id, exc)

    return topics


async def find_existing_topic_for_category(chat_id: int, category: Category) -> Optional[types.ForumTopic]:
    stored_topic = await fetch_manager_topic_async(chat_id, category, category.name)
    if stored_topic:
        topic: Optional[types.ForumTopic] = None
        thread_id = getattr(stored_topic, "thread_id", None)
        if thread_id is not None:
            topic = await safe_get_forum_topic(chat_id, message_thread_id=thread_id)
        if not topic and getattr(stored_topic, "topic_name", None):
            topic = await safe_get_forum_topic(chat_id, name=stored_topic.topic_name)
        if topic:
            thread_id = getattr(topic, "message_thread_id", thread_id)
            if thread_id is not None:
                await update_category_topic_link(category.id, thread_id)
                await store_manager_topic_async(
                    chat_id,
                    category=category,
                    thread_id=thread_id,
                    topic_name=getattr(topic, "name", None) or stored_topic.topic_name,
                )
            return topic

    try:
        topic = await bot.get_forum_topic(chat_id=chat_id, name=category.name)
    except TypeError:
        logger.debug("Bot.get_forum_topic does not support lookup by name; falling back")
    except BadRequest as exc:
        if "not found" not in str(exc).lower():
            logger.error("Failed to lookup topic '%s' in chat %s: %s", category.name, chat_id, exc)
        topic = None
    except Exception as exc:
        logger.error("Unexpected error while fetching topic '%s' in chat %s: %s", category.name, chat_id, exc)
        topic = None
    else:
        if topic:
            thread_id = getattr(topic, "message_thread_id", None)
            if thread_id is not None:
                await update_category_topic_link(category.id, thread_id)
                await store_manager_topic_async(
                    chat_id,
                    category=category,
                    thread_id=thread_id,
                    topic_name=getattr(topic, "name", None) or category.name,
                )
            return topic

    stored_thread_id = category.responsible_topic_id
    if stored_thread_id:
        try:
            thread_id = int(stored_thread_id)
        except (TypeError, ValueError):
            logger.warning("Invalid stored topic id '%s' for category %s", stored_thread_id, category.id)
        else:
            topic = await safe_get_forum_topic(chat_id, message_thread_id=thread_id)
            if topic:
                await store_manager_topic_async(
                    chat_id,
                    category=category,
                    thread_id=thread_id,
                    topic_name=getattr(topic, "name", None) or category.name,
                )
                return topic

    stored_mapping = await get_topic_by_category(category.name, chat_id)
    if stored_mapping and stored_mapping.message_thread_id is not None:
        topic = await safe_get_forum_topic(chat_id, message_thread_id=stored_mapping.message_thread_id)
        if topic:
            await update_category_topic_link(category.id, stored_mapping.message_thread_id)
            await store_manager_topic_async(
                chat_id,
                category=category,
                thread_id=stored_mapping.message_thread_id,
                topic_name=getattr(topic, "name", None) or category.name,
            )
            return topic

    topic = await safe_get_forum_topic(chat_id, name=category.name)
    if topic:
        thread_id = getattr(topic, "message_thread_id", None)
        if thread_id is not None:
            await update_category_topic_link(category.id, thread_id)
            await store_manager_topic_async(
                chat_id,
                category=category,
                thread_id=thread_id,
                topic_name=getattr(topic, "name", None) or category.name,
            )
        return topic

    return None


async def ensure_category_topic(chat_id: int, category: Category) -> Tuple[Optional[types.ForumTopic], bool]:
    existing_topic = await find_existing_topic_for_category(chat_id, category)
    if existing_topic:
        return existing_topic, False

    logger.warning(
        "Forum topic for category '%s' was requested in chat %s but does not exist",
        category.name,
        chat_id,
    )
    return None, False


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


async def send_to_manager_topic(
    teleuser: TeleUser,
    category_name: str,
    content_text: Optional[str],
    content_photo: Optional[str],
    content_voice: Optional[str],
    message: types.Message,
):
    manager_group_id = teleuser.manager_group_id
    if not manager_group_id:
        await message.answer("❌ Failed to deliver your message to managers.")
        logger.error("Manager group is not configured for teleuser %s", teleuser.id)
        return None

    try:
        category = await sync_to_async(Category.objects.get)(name=category_name)
    except Category.DoesNotExist:
        await message.answer("❌ Topic does not exist. Please try again.")
        return None

    stored_topic = await get_topic_by_category(category.name, int(manager_group_id))
    topic_id: Optional[int] = None
    if stored_topic:
        raw_thread_id = getattr(stored_topic, "thread_id", None) or getattr(
            stored_topic, "message_thread_id", None
        )
        if raw_thread_id is not None:
            try:
                topic_id = int(raw_thread_id)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid stored thread id '%s' for manager group %s and category %s",
                    raw_thread_id,
                    manager_group_id,
                    category.id,
                )

    topic: Optional[types.ForumTopic] = None
    if topic_id is None:
        topic, _ = await ensure_category_topic(int(manager_group_id), category)
        if topic:
            raw_thread_id = getattr(topic, "message_thread_id", None)
            if raw_thread_id is not None:
                try:
                    topic_id = int(raw_thread_id)
                except (TypeError, ValueError):
                    logger.error(
                        "Forum topic returned invalid thread id %s for category %s in group %s",
                        raw_thread_id,
                        category.id,
                        manager_group_id,
                    )
                    topic_id = None
        if topic_id is None:
            await message.answer("❌ Topic does not exist. Please try again.")
            return None

    topic_record = await get_topic_map_async(teleuser.id, category.id)
    if not topic_record:
        await create_topic_map_async(teleuser, category, topic_id)

    driver_name = teleuser.first_name or teleuser.nickname or str(teleuser.telegram_id)
    truck_number = teleuser.truck_number or "N/A"
    summary = f"📨 From: {driver_name} ({truck_number})\nCategory: {category.name}"

    try:
        await bot.send_message(int(manager_group_id), summary, message_thread_id=topic_id)
        await bot.copy_message(
            chat_id=int(manager_group_id),
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=topic_id,
        )
    except Exception as exc:
        logger.error("Failed to forward message to topic %s: %s", topic_id, exc)
        await message.answer("❌ Failed to deliver your message to managers.")
        return None

    photo_b64 = await download_file_as_base64(content_photo) if content_photo else None
    voice_b64 = await download_file_as_base64(content_voice) if content_voice else None
    from_group = teleuser.driver_group_id if teleuser.driver_group_id is not None else message.chat.id

    await create_message_log_entry_async(
        teleuser=teleuser,
        company=teleuser.company,
        category=category,
        from_group_id=from_group,
        to_group_id=int(manager_group_id),
        topic_id=topic_id,
        content_text=content_text or "",
        content_photo=photo_b64,
        content_voice=voice_b64,
        driver_group_id=teleuser.driver_group_id,
        manager_group_id=teleuser.manager_group_id,
        category_name=category.name,
    )

    await message.answer("✅ Your message has been sent to managers.")
    return topic_id


# ---------------------------
#  Group messages handler
# ---------------------------
@dp.message_handler(lambda message: message.chat.type in ["group", "supergroup"])
async def group_redirect(message: types.Message):
    logger.debug("Received group message in chat %s", message.chat.id)
    if message.is_command():
        logger.debug("Skipping redirect handling for command %s in chat %s", message.text, message.chat.id)
        raise SkipHandler()

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


async def prepare_group_for_topic_sync(message: types.Message) -> Optional[Tuple[int, List[Category]]]:
    """Validate permissions and fetch categories for topic synchronization."""

    logger.info("Preparing topic synchronization in chat %s by user %s", message.chat.id, message.from_user.id)

    try:
        user_membership = await bot.get_chat_member(message.chat.id, message.from_user.id)
    except Exception as exc:
        logger.error("Failed to check user permissions in chat %s: %s", message.chat.id, exc)
        await message.reply("❌ Unable to verify your permissions. Please try again later.")
        return None

    if user_membership.status not in ("creator", "administrator"):
        await message.reply("❌ Only group administrators can use this command.")
        return None

    chat_id = message.chat.id

    try:
        chat_info = await bot.get_chat(chat_id)
    except Exception as exc:
        logger.error("Failed to load chat info for %s: %s", chat_id, exc)
        await message.reply(f"❌ Unable to load chat information: {exc}")
        return None

    if chat_info.type != "supergroup" or not getattr(chat_info, "is_forum", False):
        await message.reply("⚠️ This command must be used inside a forum (supergroup with Topics enabled).")
        return None

    try:
        bot_user = await bot.get_me()
        membership = await bot.get_chat_member(chat_id, bot_user.id)
    except Exception as exc:
        logger.error("Unable to check bot permissions for chat %s: %s", chat_id, exc)
        await message.reply(f"⚠️ Failed to check bot permissions: {exc}")
        return None

    can_manage_topics = False
    if membership.status in ("creator", "administrator"):
        can_manage_topics = membership.status == "creator" or bool(getattr(membership, "can_manage_topics", False))

    if not can_manage_topics:
        await message.reply("❌ Bot must be admin with “Manage Topics” permission.")
        return None

    try:
        categories = await sync_to_async(list)(Category.objects.all())
    except Exception as exc:
        logger.error("Failed to fetch categories for chat %s: %s", chat_id, exc)
        await message.answer(f"❌ Failed to load categories: {exc}")
        return None

    if not categories:
        await message.answer("⚠️ No categories found in database.")
        return None

    return chat_id, categories


def _cache_forum_topic(
    forum_topic: Optional[types.ForumTopic],
    *,
    by_name: Dict[str, types.ForumTopic],
    by_thread: Dict[int, types.ForumTopic],
):
    if not forum_topic:
        return

    topic_name = getattr(forum_topic, "name", None)
    normalized_name = _normalize_topic_key(topic_name)
    if topic_name and normalized_name:
        by_name[normalized_name] = forum_topic

    thread_id_value = getattr(forum_topic, "message_thread_id", None)
    if thread_id_value is None:
        return

    try:
        by_thread[int(thread_id_value)] = forum_topic
    except (TypeError, ValueError):
        logger.debug("Unable to normalize thread id %s for caching", thread_id_value)


def _update_stored_topic_caches(
    *,
    category: Category,
    info: Optional[StoredManagerTopicInfo],
    by_id: Dict[int, StoredManagerTopicInfo],
    by_name: Dict[str, StoredManagerTopicInfo],
    by_thread: Dict[int, StoredManagerTopicInfo],
):
    if not info:
        return

    if category.id:
        by_id[category.id] = info

    for value in (info.category_name, info.topic_name, category.name):
        normalized = _normalize_topic_key(value)
        if normalized:
            by_name[normalized] = info

    try:
        by_thread[int(info.thread_id)] = info
    except (TypeError, ValueError):
        logger.debug("Unable to cache stored topic with invalid thread id %s", info.thread_id)


async def synchronize_manager_topics(
    chat_id: int,
    *,
    categories: List[Category],
    create_missing: bool = True,
) -> Dict[str, List[str]]:
    """Synchronize manager topics between Telegram and the database."""

    manager_group, _ = await sync_to_async(ManagerGroup.objects.get_or_create)(group_id=chat_id)

    stored_topics = await sync_to_async(list)(manager_group.topics.all())
    stored_by_id: Dict[int, StoredManagerTopicInfo] = {}
    stored_by_name: Dict[str, StoredManagerTopicInfo] = {}
    stored_by_thread: Dict[int, StoredManagerTopicInfo] = {}

    for topic in stored_topics:
        info = StoredManagerTopicInfo(
            thread_id=topic.thread_id,
            topic_name=topic.topic_name or topic.category_name,
            category_name=topic.category_name,
        )
        if topic.category_id:
            stored_by_id[topic.category_id] = info
        for value in (topic.category_name, topic.topic_name):
            normalized = _normalize_topic_key(value)
            if normalized and normalized not in stored_by_name:
                stored_by_name[normalized] = info
        try:
            stored_by_thread[int(topic.thread_id)] = info
        except (TypeError, ValueError):
            logger.debug("Skipping cached manager topic with invalid thread id %s", topic.thread_id)

    existing_forum_topics = await list_forum_topics(chat_id)
    existing_by_name: Dict[str, types.ForumTopic] = {}
    existing_by_thread: Dict[int, types.ForumTopic] = {}
    for forum_topic in existing_forum_topics:
        _cache_forum_topic(forum_topic, by_name=existing_by_name, by_thread=existing_by_thread)

    created_topics: List[str] = []
    linked_topics: List[str] = []
    skipped_topics: List[str] = []
    missing_topics: List[str] = []
    failed_topics: List[str] = []

    for category in categories:
        name_key = _normalize_topic_key(category.name)
        stored_info = stored_by_id.get(category.id)
        if not stored_info and name_key:
            stored_info = stored_by_name.get(name_key)

        candidate_name_keys: List[str] = []
        if name_key:
            candidate_name_keys.append(name_key)
        if stored_info:
            for value in (stored_info.topic_name, stored_info.category_name):
                normalized = _normalize_topic_key(value)
                if normalized and normalized not in candidate_name_keys:
                    candidate_name_keys.append(normalized)

        existing_topic: Optional[types.ForumTopic] = None
        for key in candidate_name_keys:
            existing_topic = existing_by_name.get(key)
            if existing_topic:
                break

        thread_id_hint: Optional[int] = None
        if stored_info and getattr(stored_info, "thread_id", None) is not None:
            try:
                thread_id_hint = int(stored_info.thread_id)
            except (TypeError, ValueError):
                logger.debug("Invalid thread hint '%s' for category %s", stored_info.thread_id, category.id)
                thread_id_hint = None

        if not existing_topic and thread_id_hint is not None:
            existing_topic = existing_by_thread.get(thread_id_hint)
            if not existing_topic:
                existing_topic = await safe_get_forum_topic(chat_id, message_thread_id=thread_id_hint)
                _cache_forum_topic(existing_topic, by_name=existing_by_name, by_thread=existing_by_thread)

        if not existing_topic and category.responsible_topic_id:
            try:
                resolved_thread = int(category.responsible_topic_id)
            except (TypeError, ValueError):
                resolved_thread = None
            else:
                existing_topic = existing_by_thread.get(resolved_thread)
                if not existing_topic:
                    existing_topic = await safe_get_forum_topic(chat_id, message_thread_id=resolved_thread)
                    _cache_forum_topic(existing_topic, by_name=existing_by_name, by_thread=existing_by_thread)

        if not existing_topic and category.name:
            existing_topic = await safe_get_forum_topic(chat_id, name=category.name)
            _cache_forum_topic(existing_topic, by_name=existing_by_name, by_thread=existing_by_thread)

        if existing_topic:
            had_stored_topic = stored_info is not None
            thread_id_value = getattr(existing_topic, "message_thread_id", None)
            topic_title = getattr(existing_topic, "name", None) or category.name

            new_info: Optional[StoredManagerTopicInfo] = None
            if thread_id_value is not None:
                await update_category_topic_link(category.id, thread_id_value)
                new_info = await store_manager_topic_async(
                    chat_id,
                    category=category,
                    thread_id=thread_id_value,
                    topic_name=topic_title,
                )
                _update_stored_topic_caches(
                    category=category,
                    info=new_info,
                    by_id=stored_by_id,
                    by_name=stored_by_name,
                    by_thread=stored_by_thread,
                )

            entry = f"- {category.name}"
            if thread_id_value is not None:
                entry += f" (thread {thread_id_value})"

            if had_stored_topic:
                skipped_topics.append(f"{entry} (already exists)")
            else:
                linked_topics.append(f"{entry} (linked from Telegram)")

            logger.info(
                "Topic '%s' already exists in chat %s with thread %s; skipping creation",
                category.name,
                chat_id,
                thread_id_value,
            )
            continue

        if not create_missing:
            missing_topics.append(f"- {category.name} (missing in Telegram)")
            logger.info(
                "Category '%s' has no forum topic in chat %s during sync",
                category.name,
                chat_id,
            )
            continue

        try:
            forum_topic = await bot.create_forum_topic(chat_id=chat_id, name=category.name)
        except BadRequest as exc:
            failed_topics.append(f"- {category.name} — {exc}")
            logger.error(
                "BadRequest while creating topic '%s' in chat %s: %s",
                category.name,
                chat_id,
                exc,
            )
            continue
        except Exception as exc:
            failed_topics.append(f"- {category.name} — {exc}")
            logger.error(
                "Unexpected error while creating topic '%s' in chat %s: %s",
                category.name,
                chat_id,
                exc,
            )
            continue

        thread_id_value = getattr(forum_topic, "message_thread_id", None)
        topic_title = getattr(forum_topic, "name", None) or category.name
        _cache_forum_topic(forum_topic, by_name=existing_by_name, by_thread=existing_by_thread)

        if thread_id_value is not None:
            await update_category_topic_link(category.id, thread_id_value)
            stored_info = await store_manager_topic_async(
                chat_id,
                category=category,
                thread_id=thread_id_value,
                topic_name=topic_title,
            )
            _update_stored_topic_caches(
                category=category,
                info=stored_info,
                by_id=stored_by_id,
                by_name=stored_by_name,
                by_thread=stored_by_thread,
            )

        entry = f"- {category.name}"
        if thread_id_value is not None:
            entry += f" (thread {thread_id_value})"
        created_topics.append(entry)

        logger.info(
            "Created forum topic '%s' (thread %s) in chat %s",
            category.name,
            thread_id_value,
            chat_id,
        )

    return {
        "created": created_topics,
        "linked": linked_topics,
        "skipped": skipped_topics,
        "missing": missing_topics,
        "failed": failed_topics,
    }


@dp.message_handler(commands=['run'], chat_type=['group', 'supergroup'])
async def cmd_run(message: types.Message):
    logger.info("/run command received in chat %s by user %s", message.chat.id, message.from_user.id)

    preparation = await prepare_group_for_topic_sync(message)
    if not preparation:
        return

    chat_id, categories = preparation

    results = await synchronize_manager_topics(chat_id, categories=categories, create_missing=True)

    created_topics = results["created"]
    linked_topics = results["linked"]
    skipped_topics = results["skipped"]
    failed_topics = results["failed"]

    if not created_topics and not linked_topics and not failed_topics:
        await message.answer("⚙️ All topics are already created for this group.")
        return

    result_lines: List[str] = []
    if created_topics:
        result_lines.append("✅ Topics created:")
        result_lines.extend(created_topics)
    if linked_topics:
        if result_lines:
            result_lines.append("")
        result_lines.append("🔗 Topics linked from Telegram:")
        result_lines.extend(linked_topics)
    if skipped_topics:
        if result_lines:
            result_lines.append("")
        result_lines.append("⚠️ Skipped:")
        result_lines.extend(skipped_topics)
    if failed_topics:
        if result_lines:
            result_lines.append("")
        result_lines.append("❌ Failed to create topics:")
        result_lines.extend(failed_topics)

    await message.answer("\n".join(result_lines))


@dp.message_handler(commands=['sync'], chat_type=['group', 'supergroup'])
async def cmd_sync(message: types.Message):
    logger.info("/sync command received in chat %s by user %s", message.chat.id, message.from_user.id)

    preparation = await prepare_group_for_topic_sync(message)
    if not preparation:
        return

    chat_id, categories = preparation

    results = await synchronize_manager_topics(chat_id, categories=categories, create_missing=False)

    created_topics = results["created"]
    linked_topics = results["linked"]
    skipped_topics = results["skipped"]
    missing_topics = results["missing"]
    failed_topics = results["failed"]

    if not created_topics and not linked_topics and not missing_topics and not failed_topics:
        await message.answer("⚙️ All topics are already created for this group.")
        return

    result_lines: List[str] = []
    if linked_topics:
        result_lines.append("🔗 Topics linked from Telegram:")
        result_lines.extend(linked_topics)
    if skipped_topics:
        if result_lines:
            result_lines.append("")
        result_lines.append("⚠️ Skipped:")
        result_lines.extend(skipped_topics)
    if missing_topics:
        if result_lines:
            result_lines.append("")
        result_lines.append("ℹ️ Topics missing in Telegram:")
        result_lines.extend(missing_topics)
    if failed_topics:
        if result_lines:
            result_lines.append("")
        result_lines.append("❌ Failed actions:")
        result_lines.extend(failed_topics)

    await message.answer("\n".join(result_lines))


@dp.message_handler(commands=['get'], chat_type=['group', 'supergroup'])
async def cmd_get(message: types.Message):
    logger.info("/get command received in chat %s", message.chat.id)
    chat_id = message.chat.id
    await message.answer(f"🆔 Group ID: {chat_id}")

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

    if cat_name:
        category = await get_category_for_company_async(cat_name, company.id if company else None)
        if not category:
            await message.answer("Selected category is not available. Please choose another one.")
            return
    else:
        category = await get_or_create_category_for_company_async(company.id if company else None, DEFAULT_GENERAL_CATEGORY_NAME)

    category_name = category.name if category else DEFAULT_GENERAL_CATEGORY_NAME
    topic_id = await send_to_manager_topic(
        teleuser=teleuser,
        category_name=category_name,
        content_text=content_text,
        content_photo=content_photo,
        content_voice=content_voice,
        message=message,
    )
    if topic_id is None:
        return

    await save_user_question_async(
        user_id,
        message.from_user.username or "",
        category_name,
        content_text or "",
        content_photo or "",
        content_voice or "",
        company_id=company.id if company else None,
        responsible_id=str(teleuser.manager_group_id) if teleuser.manager_group_id is not None else "",
        mention_id=str(topic_id)
    )

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
@dp.message_handler(content_types=['text', 'photo', 'voice', 'document'])
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

    # --- Обработка кнопки "Back" в режиме ввода собственного вопроса ---
    if text == "Back" and current_state == STATE_AWAITING_CONTENT:
        user_state[user_id] = STATE_NONE
        current_category = user_selected_category.get(user_id)
        if current_category:
            teleuser = await get_teleuser_by_id(user_id)
            company_id = teleuser.company_id if teleuser else None
            questions = await get_questions_for_category_async(current_category, company_id=company_id)
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            for q in questions:
                kb.add(q.question)
            kb.add("Ask your questions")
            if current_category == "Safety":
                kb.add("Request Time Off")
            kb.add("Back")
            await message.answer(f"You returned to category: {current_category}", reply_markup=kb)
        else:
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
        content_photo = ""
        if message.document and getattr(message.document, "mime_type", None) and message.document.mime_type.startswith("image/"):
            content_photo = message.document.file_id
        elif message.photo:
            content_photo = message.photo[-1].file_id
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
        manager_group_id = teleuser.manager_group_id
        if not manager_group_id:
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

        company = teleuser.company
        category = await get_category_for_company_async("Safety", company.id if company else None)
        if not category:
            category = await get_or_create_category_for_company_async(company.id if company else None, "Safety")
        if not category:
            await message.answer("Safety category is not available. Please contact an administrator.")
            user_state[user_id] = STATE_NONE
            return

        topic, _ = await ensure_category_topic(int(manager_group_id), category)
        if not topic:
            await message.answer("Failed to send to specialists. Please try again later.")
            user_state[user_id] = STATE_NONE
            return

        topic_id = getattr(topic, "message_thread_id", None)
        if topic_id is None:
            logger.error("Forum topic missing thread id for time-off category %s", category.id)
            await message.answer("Failed to send to specialists. Please try again later.")
            user_state[user_id] = STATE_NONE
            return

        topic_record = await get_topic_map_async(teleuser.id, category.id)
        if not topic_record:
            await create_topic_map_async(teleuser, category, topic_id)

        try:
            await bot.send_message(int(manager_group_id), text=forward_text, message_thread_id=topic_id)
        except Exception as e:
            logger.error("Failed to send time-off request to managers: %s", e)
            await message.answer(f"Failed to send to specialists: {e}")
            return

        from_group = teleuser.driver_group_id if teleuser.driver_group_id is not None else message.chat.id
        await create_message_log_entry_async(
            teleuser=teleuser,
            company=company,
            category=category,
            from_group_id=from_group,
            to_group_id=int(manager_group_id),
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
        questions = await get_questions_for_category_async("Safety", company_id=company.id if company else None)
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
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("Back")
            await message.answer(
                "Send text, photo, or voice message.\nPress 'Back' if you changed your mind.",
                reply_markup=kb
            )
            return
        await message.answer("I did not understand your choice. Please select a ready question, click 'Ask your questions', or 'Back'.")
        return

    await message.answer("Please choose a category or enter command /start.")

async def on_startup(dispatcher: Dispatcher):
    await setup_commands(dispatcher.bot)
    logger.info("Startup tasks completed")


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=False, on_startup=on_startup)
