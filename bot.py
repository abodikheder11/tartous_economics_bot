import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from telegram import (
    BotCommand,
    InputFile,
    KeyboardButton,
    MenuButtonCommands,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "content_catalog.json"
BOT_TOKEN = os.getenv("BOT_TOKEN")
CONTACT_BUTTON_TEXT = "التوصية و الاستفسار"
# Set this to True if you want to force users to join the channel first.
REQUIRE_CHANNEL = True

REQUIRED_CHANNEL = "@royallibrary26"
CHANNEL_URL = "https://t.me/royallibrary26"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# =========================
# Catalog
# =========================
def load_catalog() -> Dict[str, Any]:
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(
            f"Catalog file not found: {CATALOG_PATH}. Create content_catalog.json first."
        )

    with CATALOG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


CATALOG = load_catalog()


# =========================
# Helpers
# =========================
def section_name(section: str) -> str:
    return CATALOG.get("sections", {}).get(section, section)


def get_root_nodes(section: str) -> List[Dict[str, Any]]:
    return CATALOG.get("menus", {}).get(section, [])


def get_menu_path(context: ContextTypes.DEFAULT_TYPE) -> List[str]:
    return context.user_data.get("menu_path", [])


def set_menu_path(context: ContextTypes.DEFAULT_TYPE, path: List[str]) -> None:
    context.user_data["menu_path"] = path


def current_section(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return context.user_data.get("current_section")


def reset_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["current_section"] = None
    context.user_data["menu_path"] = []


def set_section(context: ContextTypes.DEFAULT_TYPE, section: str) -> None:
    context.user_data["current_section"] = section
    context.user_data["menu_path"] = []


def find_node_by_path(section: str, path: List[str]) -> Dict[str, Any] | None:
    nodes = get_root_nodes(section)
    current_node = None

    for node_id in path:
        current_node = next((node for node in nodes if node.get("id") == node_id), None)

        if not current_node:
            return None

        nodes = current_node.get("children", [])

    return current_node


def get_current_children(section: str, path: List[str]) -> List[Dict[str, Any]]:
    if not path:
        return get_root_nodes(section)

    node = find_node_by_path(section, path)

    if not node:
        return []

    return node.get("children", [])


def get_current_items(section: str, path: List[str]) -> List[Dict[str, Any]]:
    if not path:
        return []

    node = find_node_by_path(section, path)

    if not node:
        return []

    return node.get("items", [])


def get_path_labels(section: str, path: List[str]) -> List[str]:
    labels = [section_name(section)]
    nodes = get_root_nodes(section)

    for node_id in path:
        node = next((item for item in nodes if item.get("id") == node_id), None)

        if not node:
            break

        labels.append(node.get("label", node_id))
        nodes = node.get("children", [])

    return labels


def make_download_filename(item: Dict[str, Any]) -> str:
    title = item.get("title", "Royal Library").strip()

    for ch in '<>:"/\\|?*':
        title = title.replace(ch, "-")

    title = " ".join(title.split())

    if not title.lower().endswith(".pdf"):
        title += ".pdf"

    return title


# =========================
# Keyboards
# =========================
def reply_kb(rows: List[List[str]]) -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text) for text in row] for row in rows]

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def join_required_keyboard() -> ReplyKeyboardMarkup:
    return reply_kb(
        [
            ["📢 رابط القناة", "✅ تحققت من الانضمام"],
        ]
    )


def dynamic_menu_keyboard(section: str, path: List[str]) -> ReplyKeyboardMarkup:
    children = get_current_children(section, path)
    items = get_current_items(section, path)

    rows: List[List[str]] = []

    for child in children:
        rows.append([child.get("label", "بدون عنوان")])

    for item in items:
        rows.append([item.get("title", "بدون عنوان")])

    if section == "lectures" and not path:
        rows.append([CONTACT_BUTTON_TEXT])

    rows.append(["⬅️ رجوع", "🏠 الرئيسية"])

    return reply_kb(rows)


async def show_dynamic_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    section: str,
) -> None:
    path = get_menu_path(context)
    labels = get_path_labels(section, path)

    children = get_current_children(section, path)
    items = get_current_items(section, path)

    if not children and not items:
        text = (
            " / ".join(labels)
            + "\n\n"
            + "⚠️ لا توجد ملفات متاحة حالياً في هذا القسم.\n"
            + "سيتم إضافة المحتوى قريباً إن شاء الله."
        )
    else:
        text = " / ".join(labels) + "\n\nاختر من القائمة:"

    await message.reply_text(
        text,
        reply_markup=dynamic_menu_keyboard(section, path),
    )


async def show_years_menu(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    section = "lectures"
    set_section(context, section)
    await show_dynamic_menu(message, context, section)


# =========================
# Channel membership
# =========================
async def is_user_joined(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


async def require_channel_if_enabled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not REQUIRE_CHANNEL:
        return True

    if not update.message:
        return False

    user_id = update.effective_user.id if update.effective_user else None

    if not user_id or not await is_user_joined(context.bot, user_id):
        await update.message.reply_text(
            "لاستخدام البوت يجب أولًا الانضمام إلى القناة.\n"
            "اضغط زر (📢 رابط القناة) للحصول على الرابط، ثم اضغط (✅ تحققت من الانضمام).",
            reply_markup=join_required_keyboard(),
        )
        return False

    return True


# =========================
# Startup config
# =========================
async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "بدء البوت"),
            BotCommand("help", "المساعدة"),
        ]
    )

    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


# =========================
# Commands
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reset_state(context)

    if not update.message:
        return

    if not await require_channel_if_enabled(update, context):
        return

    user = update.effective_user
    user_name = user.first_name if user else "صديقي"

    await update.message.reply_text(
        f"أهلًا {user_name} 👋\n\n"
        f"مرحبًا بك في بوت {CATALOG.get('faculty_name', 'كلية الاقتصاد - طرطوس')}"
    )

    await show_years_menu(update.message, context)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not await require_channel_if_enabled(update, context):
        return

    text = (
        "طريقة الاستخدام:\n"
        "1) اختر السنة\n"
        "2) اختر الفصل\n"
        "3) اختر المادة\n"
        "4) اختر: دورات المادة / مقررات المادة / ملخصات\n"
        "5) اختر الملف المطلوب\n\n"
        "الأوامر:\n"
        "/start - بدء البوت\n"
        "/help - المساعدة\n"
        "/reload - إعادة تحميل الفهرس"
    )

    await update.message.reply_text(text)

    await show_years_menu(update.message, context)


async def reload_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global CATALOG

    if not update.message:
        return

    allowed_admins = set(CATALOG.get("admin_user_ids", []))
    user_id = update.effective_user.id if update.effective_user else None

    if allowed_admins and user_id not in allowed_admins:
        await update.message.reply_text("ليس لديك صلاحية لاستخدام هذا الأمر.")
        return

    try:
        CATALOG = load_catalog()
        reset_state(context)

        await update.message.reply_text("تمت إعادة تحميل الفهرس بنجاح ✅")
        await show_years_menu(update.message, context)

    except Exception as exc:
        logger.exception("Failed to reload catalog")
        await update.message.reply_text(f"حدث خطأ أثناء إعادة التحميل: {exc}")


# =========================
# Main text router
# =========================
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if not message or not message.text:
        return

    text = message.text.strip()
    user_id = update.effective_user.id if update.effective_user else None

    # Channel buttons
    if REQUIRE_CHANNEL and text == "📢 رابط القناة":
        await message.reply_text(
            f"رابط القناة:\n{CHANNEL_URL}",
            reply_markup=join_required_keyboard(),
        )
        return

    if REQUIRE_CHANNEL and text == "✅ تحققت من الانضمام":
        if user_id and await is_user_joined(context.bot, user_id):
            reset_state(context)
            await message.reply_text("تم التحقق من الانضمام ✅")
            await show_years_menu(message, context)
        else:
            await message.reply_text(
                "لم يتم التحقق من الانضمام بعد.\n"
                "ادخل إلى القناة أولًا ثم اضغط الزر مرة ثانية.",
                reply_markup=join_required_keyboard(),
            )
        return

    if not await require_channel_if_enabled(update, context):
        return
    
    # Recommendation / Inquiry
    if text == CONTACT_BUTTON_TEXT:
        await message.reply_text(
            CATALOG.get("contact_text", "لا توجد معلومات حالياً."),
            reply_markup=dynamic_menu_keyboard("lectures", []),
        )
        return
    
    
    # Home
    if text in {"🚀 Start", "🏠 الرئيسية"}:
        await show_years_menu(message, context)
        return

    # Back
    if text == "⬅️ رجوع":
        section = current_section(context)
        path = get_menu_path(context)

        if section and path:
            path.pop()
            set_menu_path(context, path)
            await show_dynamic_menu(message, context, section)
            return

        await show_years_menu(message, context)
        return

    # Dynamic menu navigation
    section = current_section(context)

    if section:
        path = get_menu_path(context)

        children = get_current_children(section, path)
        selected_child = next(
            (child for child in children if child.get("label") == text),
            None,
        )

        if selected_child:
            path.append(selected_child.get("id"))
            set_menu_path(context, path)
            await show_dynamic_menu(message, context, section)
            return

        items = get_current_items(section, path)
        selected_item = next(
            (item for item in items if item.get("title") == text),
            None,
        )

        if selected_item:
            file_path = BASE_DIR / selected_item["file"]

            caption_parts = [f"📄 {selected_item.get('title', 'بدون عنوان')}"]

            if selected_item.get("description"):
                caption_parts.append(selected_item["description"])

            caption = "\n".join(caption_parts)

            if file_path.exists():
                try:
                    await message.reply_text("⏳ جاري إرسال الملف، قد يستغرق ذلك قليلًا...")

                    with file_path.open("rb") as f:
                        await message.reply_document(
                            document=InputFile(
                                f,
                                filename=make_download_filename(selected_item),
                            ),
                            caption=caption[:1024],
                            read_timeout=180,
                            write_timeout=300,
                            connect_timeout=30,
                            pool_timeout=30,
                        )

                except TimedOut:
                    await message.reply_text(
                        "⚠️ استغرق إرسال الملف وقتًا طويلًا.\n"
                        "جرّب مرة أخرى، أو حاول لاحقًا.",
                        reply_markup=dynamic_menu_keyboard(section, path),
                    )
                    return

                except NetworkError:
                    await message.reply_text(
                        "⚠️ حدثت مشكلة في الاتصال أثناء إرسال الملف.\n"
                        "جرّب مرة أخرى بعد قليل.",
                        reply_markup=dynamic_menu_keyboard(section, path),
                    )
                    return

            else:
                await message.reply_text(
                    f"{caption}\n\n⚠️ الملف غير موجود حاليًا على الخادم:\n{file_path}"
                )

            await message.reply_text(
                "اختر ملفًا آخر أو ارجع للقائمة:",
                reply_markup=dynamic_menu_keyboard(section, path),
            )
            return

    # Fallback
    await message.reply_text(
        "الخيار غير معروف. استخدم الأزرار الظاهرة في لوحة المفاتيح."
    )

    await show_years_menu(message, context)


# =========================
# Error handler
# =========================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception:", exc_info=context.error)


# =========================
# Main
# =========================
def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing. "
            "Set it before running the bot."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .connect_timeout(30)
        .read_timeout(180)
        .write_timeout(300)
        .pool_timeout(30)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reload", reload_catalog))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    application.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()