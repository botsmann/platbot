from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes
import os
import logging
from datetime import datetime
from typing import Optional
from database import Database
from config import MANAGER_CODE, STATUS_NEW, STATUS_COMPLETED, STATUS_APPROVED, STATUS_REDO

logger = logging.getLogger(__name__)
db = Database()
PHOTOS_DIR = "photos"


def ensure_photos_dir():
    """Создать директорию для фотографий если её нет"""
    if not os.path.exists(PHOTOS_DIR):
        os.makedirs(PHOTOS_DIR)


def format_tasks_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} задача"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} задачи"
    return f"{n} задач"


def build_category_keyboard():  
    categories = [
        ("Касса", "💰"),
        ("Саладет", "🥗"),
        ("Панировка", "🍞"),
        ("Улица", "🚶"),
        ("Зал", "🪑"),
        ("Прочее", "📦"),
    ]
    keyboard = [[InlineKeyboardButton("👔 Меню менеджера", callback_data="become_manager")]]
    for name, emoji in categories:
        count = len(db.get_tasks(status=STATUS_NEW, category=name)) + len(db.get_tasks(status=STATUS_REDO, category=name))
        keyboard.append([InlineKeyboardButton(f"{emoji} {name} - {format_tasks_word(count)}", callback_data=f"set_category_{name}")])
    return keyboard


def format_task_details(task: dict) -> str:
    creator = "неизвестно"
    if task.get('created_by'):
        username = db.get_username(task['created_by'])
        creator = f"@{username}" if username else f"ID {task['created_by']}"
    lines = [
        f"📋 Задача #{task['task_id']}",
        f"Категория: {task.get('category', '—')}",
        f"Статус: {task['status']}",
        f"Создал: {creator}",
        "",
        f"Описание: {task['comment'] or '—'}"
    ]
    return "\n".join(lines)


def format_tasks_accusative(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "задачу"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "задачи"
    return "задач"


CATEGORY_EMOJIS = {
    "Касса": "💰",
    "Саладет": "🥗",
    "Панировка": "🍞",
    "Улица": "🚶",
    "Зал": "🪑",
    "Прочее": "📦",
}


async def render_executor_tasks_list(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: Optional[int], base_message=None, allow_new_message: bool = True):
    """Показать исполнителю список задач его категории"""
    logger.debug(f"render_executor_tasks_list вызвана, user_id={user_id}, chat_id={chat_id}")
    if chat_id is None:
        logger.error("chat_id is None")
        return
    category = db.get_user_category(user_id)
    logger.debug(f"category={category}")
    if not category:
        logger.error("category is None")
        return
    new_tasks = db.get_tasks(status=STATUS_NEW, category=category)
    redo_tasks = db.get_tasks(status=STATUS_REDO, category=category)
    tasks = new_tasks + redo_tasks
    logger.debug(f"найдено задач: {len(tasks)}")
    if tasks:
        keyboard = [
            [InlineKeyboardButton(
                f"{CATEGORY_EMOJIS.get(task.get('category'), '')} Задача #{task['task_id']} - {(task.get('comment') or '')[:30]}...",
                callback_data=f"task_{task['task_id']}"
            )]
            for task in tasks
        ]
        keyboard.append([InlineKeyboardButton("🚪 Выйти", callback_data="restart")])
        text = f"Необходимо выполнить {len(tasks)} {format_tasks_accusative(len(tasks))}\n\n📋 Выберите задачу:"
    else:
        keyboard = [[InlineKeyboardButton("◀️ В начало", callback_data="restart")]]
        text = "📭 Нет доступных задач."
    reply_markup = InlineKeyboardMarkup(keyboard)
    logger.debug("Пытаюсь отредактировать/отправить сообщение")
    if base_message:
        try:
            logger.debug("Пытаюсь отредактировать base_message")
            await base_message.edit_text(text, reply_markup=reply_markup)
            context.user_data['executor_list_message_id'] = base_message.message_id
            logger.debug("base_message отредактировано успешно")
            return
        except Exception as e:
            logger.error(f"Не удалось отредактировать base_message: {e}", exc_info=True)
    list_message_id = context.user_data.get('executor_list_message_id')
    if list_message_id:
        try:
            logger.debug(f"Пытаюсь отредактировать сообщение по message_id={list_message_id}")
            await context.bot.edit_message_text(chat_id=chat_id, message_id=list_message_id, text=text, reply_markup=reply_markup)
            context.user_data['executor_list_message_id'] = list_message_id
            logger.debug("Сообщение отредактировано успешно")
            return
        except Exception as e:
            logger.error(f"Не удалось отредактировать сообщение по message_id: {e}", exc_info=True)
    if allow_new_message:
        try:
            logger.debug("Отправляю новое сообщение")
            sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            context.user_data['executor_list_message_id'] = sent.message_id
            logger.debug(f"Новое сообщение отправлено, message_id={sent.message_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить новое сообщение: {e}", exc_info=True)


async def cleanup_executor_task_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: Optional[int], task_id: Optional[int] = None):
    """Удалить сообщения с фотографиями/кнопками текущей задачи исполнителя"""
    if chat_id is None:
        return
    task_msgs = context.user_data.get('executor_task_message_ids', {})
    if not task_msgs:
        return
    keys = [str(task_id)] if task_id else list(task_msgs.keys())
    for key in keys:
        ids = task_msgs.get(key, [])
        for mid in ids:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass
        task_msgs.pop(key, None)
    if task_msgs:
        context.user_data['executor_task_message_ids'] = task_msgs
    else:
        context.user_data.pop('executor_task_message_ids', None)
    current_id = context.user_data.get('current_executor_task_id')
    if task_id and current_id == task_id:
        context.user_data.pop('current_executor_task_id', None)
    if task_id is None:
        context.user_data.pop('current_executor_task_id', None)




async def send_category_selection(message_target, username: str):
    keyboard = build_category_keyboard()
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message_target.reply_text(
        f"👋 Добро пожаловать, {username}!\n\nВыберите, где делать отмывки:",
        reply_markup=reply_markup
    )


async def render_manager_tasks_list(update: Update, context: ContextTypes.DEFAULT_TYPE, base_message=None):
    tasks = db.get_tasks()
    context.user_data['return_to'] = 'manager_menu'
    if not tasks:
        keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = "📭 Нет задач."
    else:
        text = "📊 Все задачи:\n\n"
        keyboard = []
        for task in tasks:
            status_emoji = "🟢" if task['status'] == STATUS_APPROVED else "🟡" if task['status'] == STATUS_COMPLETED else "🔴" if task['status'] == STATUS_REDO else "⚪"
            text += f"{status_emoji} Задача #{task['task_id']}\n"
            text += f"   Статус: {task['status']}\n"
            creator_username = db.get_username(task['created_by']) if task.get('created_by') else None
            if creator_username:
                text += f"   Создал: @{creator_username}\n"
            elif task.get('created_by'):
                text += f"   Создал: ID {task['created_by']}\n"
            comment = task.get('comment') or ''
            comment_preview = comment[:50] + "..." if len(comment) > 50 else comment
            text += f"   Описание: {comment_preview}\n\n"
            keyboard.append([InlineKeyboardButton(
                f"📷 Задача #{task['task_id']} - {task['status']}",
                callback_data=f"view_task_photo_{task['task_id']}"
            )])
        keyboard.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_to_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
    chat_id = update.effective_chat.id if update.effective_chat else None
    # Сначала пробуем редактировать сообщение, с которого пришёл запрос
    if base_message:
        try:
            await base_message.edit_text(text, reply_markup=reply_markup)
            context.user_data['manager_list_message_id'] = base_message.message_id
            return
        except Exception:
            pass
    list_msg_id = context.user_data.get('manager_list_message_id')
    if list_msg_id and chat_id:
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=list_msg_id, text=text, reply_markup=reply_markup)
            context.user_data['manager_list_message_id'] = list_msg_id
            return
        except Exception:
            pass
    if chat_id:
        sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        context.user_data['manager_list_message_id'] = sent.message_id


async def cleanup_manager_task_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: Optional[int], task_id: int):
    if chat_id is None:
        return
    task_msgs = context.user_data.get('task_view_message_ids', {})
    ids = task_msgs.get(str(task_id), [])
    for mid in ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    if str(task_id) in task_msgs:
        task_msgs.pop(str(task_id), None)
        context.user_data['task_view_message_ids'] = task_msgs


async def cleanup_review_task_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: Optional[int], task_id: int):
    if chat_id is None:
        return
    review_msgs = context.user_data.get('review_message_ids', {})
    ids = review_msgs.get(str(task_id), [])
    for mid in ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    if str(task_id) in review_msgs:
        review_msgs.pop(str(task_id), None)
        context.user_data['review_message_ids'] = review_msgs
    if context.user_data.get('last_review_task_id') == task_id:
        context.user_data.pop('last_review_task_id', None)


def purge_task_files(task_id: int, task: Optional[dict] = None):
    if task is None:
        task = db.get_task(task_id)
    if not task:
        return
    if task.get('photo_before_path') and os.path.exists(task['photo_before_path']):
        try:
            os.remove(task['photo_before_path'])
        except OSError as e:
            logger.error(f"Ошибка при удалении фото до: {e}")
    if task.get('photo_after_path') and os.path.exists(task['photo_after_path']):
        try:
            os.remove(task['photo_after_path'])
        except OSError as e:
            logger.error(f"Ошибка при удалении фото после: {e}")
    for p in db.get_task_photos(task_id):
        if p.get('file_path') and os.path.exists(p['file_path']):
            try:
                os.remove(p['file_path'])
            except OSError as e:
                logger.error(f"Ошибка при удалении фото задачи: {e}")
    db.delete_all_task_photos(task_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Пользователь"
    # Очищаем данные пользователя
    context.user_data.clear()
    # Автоматически устанавливаем роль "исполнитель" и очищаем категорию
    db.set_user_role(user_id, username, "executor", None)
    # Выводим начальное меню выбора категории
    await send_category_selection(update.message, username)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    if not query:
        return
    
    user_id = query.from_user.id
    username = query.from_user.username or "Пользователь"
    data = query.data
    
    # Логируем для отладки
    logger.debug(f"button_handler вызван, callback_data={data}, user_id={user_id}")
    
    if not data:
        logger.error("пустой callback_data")
        try:
            await query.answer("❌ Ошибка: пустой callback_data")
        except:
            pass
        return
    
    # Получаем роль пользователя из базы данных
    role = db.get_user_role(user_id)
    if not role:
        role = "executor"  # По умолчанию исполнитель
    logger.debug(f"button_handler - user_id={user_id}, role={role}, callback_data={data}")
    
    # Отвечаем на callback сразу
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Не удалось ответить на callback: {e}")

    if data.startswith("set_category_"):
        logger.debug(f"Обработка set_category_, data={data}")
        try:
            category = data.replace("set_category_", "")
            logger.debug(f"category={category}")
            # Всегда устанавливаем роль исполнителя при выборе категории
            # set_user_role уже сохраняет категорию, если она передана
            db.set_user_role(user_id, username, "executor", category)
            logger.debug("Роль и категория установлены через set_user_role")
            # Проверяем, что категория сохранилась
            saved_category = db.get_user_category(user_id)
            logger.debug(f"Проверка сохраненной категории: {saved_category}")
            if saved_category != category:
                logger.error(f"Категория не сохранилась! Ожидалось: {category}, получено: {saved_category}")
                # Пытаемся сохранить еще раз через set_user_category
                db.set_user_category(user_id, username, category)
                saved_category = db.get_user_category(user_id)
                logger.debug(f"После set_user_category: {saved_category}")
            # Показываем список задач исполнителя
            chat_id = query.message.chat_id if query.message else update.effective_chat.id
            logger.debug(f"chat_id={chat_id}, вызываю render_executor_tasks_list")
            await render_executor_tasks_list(context, user_id, chat_id, base_message=query.message)
            logger.debug("render_executor_tasks_list завершен")
        except Exception as e:
            logger.error(f"Ошибка в set_category_: {e}", exc_info=True)
            try:
                await query.message.reply_text(f"❌ Ошибка при выборе категории: {str(e)}")
            except:
                pass
        return

    if data == "become_manager":
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="restart")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(
                "🔐 Введите код доступа для менеджера:",
                reply_markup=reply_markup
            )
        except:
            await query.message.reply_text(
                "🔐 Введите код доступа для менеджера:",
                reply_markup=reply_markup
            )
        context.user_data['waiting_for_code'] = True
        return

    if data == "broadcast_start":
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        # Включаем режим ввода текста для рассылки
        context.user_data['broadcasting'] = True
        # Возврат должен вести в меню менеджера
        context.user_data['return_to'] = 'manager_menu'
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text("✉️ Введите текст для рассылки всем исполнителям:", reply_markup=reply_markup)
        except:
            await query.message.reply_text("✉️ Введите текст для рассылки всем исполнителям:", reply_markup=reply_markup)
        return

    if data == "select_category":
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        keyboard = [
            [InlineKeyboardButton("💰 Касса", callback_data="create_task_Касса")],
            [InlineKeyboardButton("🥗 Саладет", callback_data="create_task_Саладет")],
            [InlineKeyboardButton("🍞 Панировка", callback_data="create_task_Панировка")],
            [InlineKeyboardButton("🚶 Улица", callback_data="create_task_Улица")],
            [InlineKeyboardButton("🪑 Зал", callback_data="create_task_Зал")],
            [InlineKeyboardButton("📦 Прочее", callback_data="create_task_Прочее")],
            [InlineKeyboardButton("◀️ Главное меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(
                "📂 Выберите категорию для задачи:",
                reply_markup=reply_markup
            )
        except:
            try:
                await query.message.edit_text(
                    "📂 Выберите категорию для задачи:",
                    reply_markup=reply_markup
                )
            except:
                await query.message.reply_text(
                    "📂 Выберите категорию для задачи:",
                    reply_markup=reply_markup
                )
        return

    if data.startswith("create_task_"):
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        category = data.replace("create_task_", "")
        keyboard = [[InlineKeyboardButton("🔄 Изменить категорию", callback_data="select_category")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"📸 Отправьте фотографию места, которое нужно почистить.\n"
            f"Можно одно фото или несколько фото ОДНИМ сообщением (альбомом). Все фото прикрепляйте в одном сообщении.\n\n"
            f"Категория: {category}",
            reply_markup=reply_markup
        )
        context.user_data['creating_task'] = True
        context.user_data['task_step'] = "photo"
        context.user_data['task_category'] = category
        # Для альбомов фиксируем текущий альбом (сбрасываем)
        context.user_data.pop('album_id', None)
        context.user_data.pop('album_task_id', None)
        return

    if data == "view_tasks_manager":
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            await query.message.reply_text("❌ У вас нет доступа к этой функции.")
            return
        # Удаляем все сообщения текущей задачи, если они есть
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        if chat_id:
            # Удаляем все сообщения задач (фото, кнопки)
            task_msgs = context.user_data.get('task_view_message_ids', {})
            for task_id_str, msg_ids in task_msgs.items():
                for mid in msg_ids:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                    except Exception:
                        pass
            # Очищаем сохраненные сообщения
            context.user_data['task_view_message_ids'] = {}
            # Удаляем текущее сообщение с кнопками, если оно не является списком задач
            manager_list_id = context.user_data.get('manager_list_message_id')
            if query.message and manager_list_id != query.message.message_id:
                try:
                    await query.message.delete()
                except Exception:
                    pass
        # Редактируем сообщение списка задач обратно
        manager_list_id = context.user_data.get('manager_list_message_id')
        if manager_list_id and chat_id:
            # Пытаемся отредактировать сохраненное сообщение списка
            try:
                await render_manager_tasks_list(update, context, None)
                return
            except Exception:
                pass
        # Если не получилось, пробуем отредактировать текущее сообщение
        base_message = query.message
        await render_manager_tasks_list(update, context, base_message)
        return

    if data == "view_tasks_executor":
        user_category = db.get_user_category(user_id)
        if not user_category:
            await query.answer("Сначала выберите категорию.")
            if query.message:
                await send_category_selection(query.message, username)
            return
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        current_task_id = context.user_data.get('current_executor_task_id')
        if current_task_id and chat_id:
            await cleanup_executor_task_messages(context, chat_id, current_task_id)
        list_id = context.user_data.get('executor_list_message_id')
        use_current_message = query.message and list_id == query.message.message_id
        base_message = query.message if use_current_message else None
        await render_executor_tasks_list(context, user_id, chat_id, base_message=base_message)
        if query.message and not use_current_message:
            try:
                await query.message.delete()
            except Exception:
                pass
        return

    if data == "review_tasks":
        if role != "manager":
            try:
                await query.edit_message_text("❌ У вас нет доступа к этой функции.")
            except:
                await query.message.edit_text("❌ У вас нет доступа к этой функции.")
            return
        # Удаляем из чата сообщения открытой задачи (шапка/альбом "до" и "после", кнопки), если они были
        try:
            chat_id = query.message.chat_id if query.message else update.effective_chat.id
            last_task_id = context.user_data.get('last_review_task_id')
            if last_task_id is not None:
                review_msgs = context.user_data.get('review_message_ids', {})
                ids = review_msgs.get(str(last_task_id), [])
                for mid in ids:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                    except:
                        pass
                if str(last_task_id) in review_msgs:
                    review_msgs.pop(str(last_task_id), None)
                    context.user_data['review_message_ids'] = review_msgs
                context.user_data.pop('last_review_task_id', None)
        except:
            pass
        tasks = db.get_tasks(status=STATUS_COMPLETED)
        all_tasks = db.get_tasks()
        approved_tasks = db.get_tasks(status=STATUS_APPROVED)
        if not tasks:
            keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # Возврат из этого экрана должен вести в меню менеджера
            context.user_data['return_to'] = 'manager_menu'
            try:
                await query.edit_message_text("📭 Нет задач на проверку.", reply_markup=reply_markup)
                context.user_data['review_list_message_id'] = query.message.message_id
            except:
                # Если текущее сообщение медиа — редактируем сохранённый список и удаляем текущее
                list_id = context.user_data.get('review_list_message_id')
                chat_id = query.message.chat_id if query.message else update.effective_chat.id
                if list_id:
                    try:
                        await context.bot.edit_message_text(chat_id=chat_id, message_id=list_id, text="📭 Нет задач на проверку.", reply_markup=reply_markup)
                        try:
                            await query.message.delete()
                        except:
                            pass
                    except:
                        await query.message.edit_text("📭 Нет задач на проверку.", reply_markup=reply_markup)
                        context.user_data['review_list_message_id'] = query.message.message_id
                else:
                    await query.message.edit_text("📭 Нет задач на проверку.", reply_markup=reply_markup)
                    context.user_data['review_list_message_id'] = query.message.message_id
            return
        
        keyboard = []
        for task in tasks:
            keyboard.append([InlineKeyboardButton(
                f"Задача #{task['task_id']}",
                callback_data=f"review_{task['task_id']}"
            )])
        keyboard.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_to_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Возврат из этого экрана должен вести в меню менеджера
        context.user_data['return_to'] = 'manager_menu'
        try:
            await query.edit_message_text(
                f"✅ Выберите задачу для проверки:\n"
                f"Всего задач: {len(all_tasks)} | На проверке: {len(tasks)} | Завершено: {len(approved_tasks)}",
                reply_markup=reply_markup
            )
            context.user_data['review_list_message_id'] = query.message.message_id
        except:
            # Если нажали «Назад» с сообщения-фото — редактируем сохранённый список
            list_id = context.user_data.get('review_list_message_id')
            chat_id = query.message.chat_id if query.message else update.effective_chat.id
            if list_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=list_id,
                        text=f"✅ Выберите задачу для проверки:\nВсего задач: {len(all_tasks)} | На проверке: {len(tasks)} | Завершено: {len(approved_tasks)}",
                        reply_markup=reply_markup
                    )
                    try:
                        await query.message.delete()
                    except:
                        pass
                except:
                    await query.message.edit_text(
                        f"✅ Выберите задачу для проверки:\n"
                        f"Всего задач: {len(all_tasks)} | На проверке: {len(tasks)} | Завершено: {len(approved_tasks)}",
                        reply_markup=reply_markup
                    )
                    context.user_data['review_list_message_id'] = query.message.message_id
            else:
                await query.message.edit_text(
                    f"✅ Выберите задачу для проверки:\n"
                    f"Всего задач: {len(all_tasks)} | На проверке: {len(tasks)} | Завершено: {len(approved_tasks)}",
                    reply_markup=reply_markup
                )
                context.user_data['review_list_message_id'] = query.message.message_id
        return

    if data.startswith("view_task_photo_"):
        task_id = int(data.split("_")[-1])
        task = db.get_task(task_id)
        if not task:
            await query.answer("❌ Задача не найдена.")
            await query.message.reply_text("❌ Задача не найдена.")
            return
        
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            await query.message.reply_text("❌ У вас нет доступа к этой функции.")
            return
        
        # Подготавливаем кнопки в зависимости от статуса задачи
        if task['status'] == STATUS_APPROVED:
            # Для завершенных задач - кнопка "Фото для отчета" и удаление без подтверждения
            keyboard = [
                [InlineKeyboardButton("📸 Фото для отчета", callback_data=f"report_photo_{task_id}")],
                [InlineKeyboardButton("🗑️ Удалить задачу", callback_data=f"delete_approved_{task_id}")],
                [InlineKeyboardButton("◀️ Назад к списку задач", callback_data="view_tasks_manager")]
            ]
        else:
            # Для незавершенных задач - обычные кнопки редактирования
            keyboard = [
                [InlineKeyboardButton("✏️ Изменить комментарий", callback_data=f"edit_comment_{task_id}")],
                [InlineKeyboardButton("📷 Изменить фото", callback_data=f"edit_photo_{task_id}")],
                [InlineKeyboardButton("🗑️ Удалить задачу", callback_data=f"delete_task_{task_id}")],
                [InlineKeyboardButton("◀️ Назад к списку задач", callback_data="view_tasks_manager")]
            ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Собираем все фото "до" из расширенной таблицы
        before_photos = [p for p in db.get_task_photos(task_id) if p.get('kind') == 'before' and p.get('file_path') and os.path.exists(p['file_path'])]
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        # Отправляем альбом "до" (если есть)
        if before_photos:
            # Сначала изменяем сообщение "Все задачи:" на заголовок выбранной задачи
            try:
                await query.edit_message_text(f"📷 Задача #{task_id}")
            except:
                pass
            # Запоминаем id сообщения-списка, чтобы по кнопке "Назад" редактировать именно его
            try:
                context.user_data['manager_list_message_id'] = query.message.message_id
            except:
                pass
            media = []
            files = []
            for idx, ph in enumerate(before_photos):
                f = open(ph['file_path'], 'rb')
                files.append(f)
                if idx == 0:
                    caption = format_task_details(task)
                    media.append(InputMediaPhoto(media=f, caption=caption))
                else:
                    media.append(InputMediaPhoto(media=f))
            try:
                sent_messages = await context.bot.send_media_group(chat_id=chat_id, media=media)
                # Сохраняем отправленные message_id для возможного удаления при "Удалить задачу"
                task_msgs = context.user_data.get('task_view_message_ids', {})
                ids = [m.message_id for m in sent_messages]
                task_msgs[str(task_id)] = ids
                context.user_data['task_view_message_ids'] = task_msgs
            finally:
                for f in files:
                    try:
                        f.close()
                    except:
                        pass
        else:
            # Если фото нет, просто текст с описанием задачи
            text = format_task_details(task) + "\n\n⚠️ Фото не найдено."
            try:
                await query.edit_message_text(text)
            except:
                await query.message.edit_text(text)
        # Отдельным сообщением — кнопки управления
        action_msg = await query.message.reply_text("Выберите действие:", reply_markup=reply_markup)
        # Сохраним и это сообщение-кнопки чтобы удалить при удалении задачи
        task_msgs = context.user_data.get('task_view_message_ids', {})
        btn_ids = task_msgs.get(str(task_id), [])
        btn_ids.append(action_msg.message_id)
        task_msgs[str(task_id)] = btn_ids
        context.user_data['task_view_message_ids'] = task_msgs
        return

    if data.startswith("edit_comment_"):
        task_id = int(data.split("_")[-1])
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        context.user_data['editing_comment'] = True
        context.user_data['task_id'] = task_id
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data=f"view_task_photo_{task_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"✏️ Введите новый комментарий для задачи #{task_id}:",
            reply_markup=reply_markup
        )
        return

    if data.startswith("edit_photo_"):
        task_id = int(data.split("_")[-1])
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        context.user_data['editing_photo'] = True
        context.user_data['task_id'] = task_id
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data=f"view_task_photo_{task_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"📷 Отправьте новое фото для задачи #{task_id}:",
            reply_markup=reply_markup
        )
        return

    if data.startswith("delete_task_"):
        task_id = int(data.split("_")[-1])
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        
        # Проверяем, существует ли задача
        task = db.get_task(task_id)
        if not task:
            await query.answer("❌ Задача не найдена.")
            await query.edit_message_text("❌ Задача не найдена.")
            return
        
        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{task_id}")],
            [InlineKeyboardButton("❌ Оставить задачу", callback_data=f"keep_task_{task_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"⚠️ Вы уверены, что хотите удалить задачу #{task_id}?\n\nЭто действие нельзя отменить!"
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except Exception:
            await query.message.edit_text(text, reply_markup=reply_markup)
        return

    if data.startswith("keep_task_"):
        task_id = int(data.split("_")[-1])
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        try:
            await query.message.delete()
        except Exception:
            pass
        if chat_id:
            await cleanup_manager_task_messages(context, chat_id, task_id)
        await render_manager_tasks_list(update, context)
        keyboard = [[InlineKeyboardButton("◀️ Назад к списку задач", callback_data="view_tasks_manager")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❎ Задача #{task_id} сохранена. Возвращаюсь к списку задач.",
            reply_markup=reply_markup
        )
        return

    if data.startswith("delete_approved_"):
        # Удаление завершенной задачи без подтверждения
        task_id = int(data.split("_")[-1])
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        task = db.get_task(task_id)
        purge_task_files(task_id, task)
        db.delete_task(task_id)
        if chat_id:
            await cleanup_manager_task_messages(context, chat_id, task_id)
            await cleanup_review_task_messages(context, chat_id, task_id)
        try:
            await query.message.delete()
        except Exception:
            pass
        await render_manager_tasks_list(update, context)
        keyboard = [[InlineKeyboardButton("◀️ Назад к списку задач", callback_data="view_tasks_manager")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Задача #{task_id} удалена.",
            reply_markup=reply_markup
        )
        return

    if data.startswith("confirm_delete_"):
        task_id = int(data.split("_")[-1])
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        task = db.get_task(task_id)
        purge_task_files(task_id, task)
        db.delete_task(task_id)
        if chat_id:
            await cleanup_manager_task_messages(context, chat_id, task_id)
        try:
            await query.message.delete()
        except Exception:
            pass
        await render_manager_tasks_list(update, context)
        keyboard = [[InlineKeyboardButton("◀️ Назад к списку задач", callback_data="view_tasks_manager")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Задача #{task_id} успешно удалена.",
            reply_markup=reply_markup
        )
        return

    if data.startswith("report_photo_"):
        # Показываем фото исполнителя для отчета
        task_id = int(data.split("_")[-1])
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        
        task = db.get_task(task_id)
        if not task:
            await query.answer("❌ Задача не найдена.")
            return
        
        if task['status'] != STATUS_APPROVED:
            await query.answer("❌ Эта функция доступна только для завершенных задач.")
            return
        
        # Отправляем весь альбом фото исполнителя (kind='after') из расширенной таблицы
        after_list = [p for p in db.get_task_photos(task_id) if p.get('kind') == 'after' and p.get('file_path') and os.path.exists(p['file_path'])]
        keyboard = [
            [InlineKeyboardButton("🗑️ Удалить задачу", callback_data=f"delete_approved_{task_id}")],
            [InlineKeyboardButton("◀️ Назад к списку задач", callback_data="view_tasks_manager")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        if after_list:
            if task['completed_by']:
                username = db.get_username(task['completed_by'])
                if username:
                    caption = f"📸 Фото для отчета - Задача #{task_id}\nИсполнитель: @{username}"
                else:
                    caption = f"📸 Фото для отчета - Задача #{task_id}\nИсполнитель ID: {task['completed_by']}"
            else:
                caption = f"📸 Фото для отчета - Задача #{task_id}"
            media = []
            files = []
            for idx, ph in enumerate(after_list):
                f = open(ph['file_path'], 'rb')
                files.append(f)
                if idx == 0:
                    media.append(InputMediaPhoto(media=f, caption=caption))
                else:
                    media.append(InputMediaPhoto(media=f))
            try:
                sent_group = await context.bot.send_media_group(chat_id=chat_id, media=media)
                # После альбома отправим кнопки отдельным сообщением
                btn_msg = await context.bot.send_message(chat_id=chat_id, text="Действия:", reply_markup=reply_markup)
                # Сохраняем id сообщений для последующего удаления
                try:
                    task_msgs = context.user_data.get('task_view_message_ids', {})
                    ids = task_msgs.get(str(task_id), [])
                    if sent_group and len(sent_group) > 0:
                        ids.extend([m.message_id for m in sent_group])
                    ids.append(btn_msg.message_id)
                    task_msgs[str(task_id)] = ids
                    context.user_data['task_view_message_ids'] = task_msgs
                except:
                    pass
            finally:
                for f in files:
                    try:
                        f.close()
                    except:
                        pass
            # Убираем кнопки у исходного сообщения
            try:
                await query.edit_message_caption(caption=query.message.caption, reply_markup=None)
            except:
                pass
        else:
            await query.message.reply_text("⚠️ Фото исполнителя не найдено.", reply_markup=reply_markup)
        return

    if data.startswith("task_"):
        task_id = int(data.split("_")[1])
        task = db.get_task(task_id)
        if not task:
            await query.answer("❌ Задача не найдена.")
            await query.edit_message_text("❌ Задача не найдена.")
            return
        executor_task_msgs = context.user_data.get('executor_task_message_ids', {}) or {}
        executor_task_msgs.pop(str(task_id), None)
        task_message_ids = []
        
        # Подготавливаем кнопки действий
        keyboard = [
            [InlineKeyboardButton("✅ Выполнено", callback_data=f"complete_{task_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="view_tasks_executor")],
            [InlineKeyboardButton("🚪 Выйти", callback_data="restart")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Собираем все фото "до" и отправляем как альбом
        before_photos = [p for p in db.get_task_photos(task_id) if p.get('kind') == 'before' and p.get('file_path') and os.path.exists(p['file_path'])]
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        sent_any = False
        if before_photos:
            media = []
            files = []
            for idx, ph in enumerate(before_photos):
                f = open(ph['file_path'], 'rb')
                files.append(f)
                if idx == 0:
                    caption = f"📋 Задача #{task_id}\n\n{task['comment']}\n\nСтатус: {task['status']}"
                    media.append(InputMediaPhoto(media=f, caption=caption))
                else:
                    media.append(InputMediaPhoto(media=f))
            try:
                sent_group = await context.bot.send_media_group(chat_id=chat_id, media=media)
                task_message_ids.extend([m.message_id for m in sent_group])
                sent_any = True
            finally:
                for f in files:
                    try:
                        f.close()
                    except:
                        pass
        # Если фото нет, отправим текст
        if not sent_any:
            try:
                await query.edit_message_text(
                    f"📋 Задача #{task_id}\n\n{task['comment']}\n\nСтатус: {task['status']}"
                )
            except:
                await query.message.edit_text(
                    f"📋 Задача #{task_id}\n\n{task['comment']}\n\nСтатус: {task['status']}"
                )
        # Кнопки действия отдельным сообщением
        action_msg = await query.message.reply_text("Выберите действие:", reply_markup=reply_markup)
        task_message_ids.append(action_msg.message_id)
        executor_task_msgs[str(task_id)] = task_message_ids
        context.user_data['executor_task_message_ids'] = executor_task_msgs
        context.user_data['current_executor_task_id'] = task_id
        return

    if data.startswith("complete_"):
        task_id = int(data.split("_")[1])
        context.user_data['completing_task'] = True
        context.user_data['task_id'] = task_id
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        if chat_id:
            await cleanup_executor_task_messages(context, chat_id, task_id)

        keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(
            "📸 Отправьте фотографию выполненной работы.\n"
            "Можно одно фото или несколько фото ОДНИМ сообщением (альбомом). Все фото прикрепляйте в одном сообщении.",
            reply_markup=reply_markup
        )
        return

    if data.startswith("review_"):
        task_id = int(data.split("_")[1])
        task = db.get_task(task_id)
        if not task:
            await query.message.reply_text("❌ Задача не найдена.")
            return
        # Помечаем возврат в меню менеджера
        context.user_data['return_to'] = 'manager_menu'
        # Сохраняем id последней открытой задачи для последующей очистки сообщений
        context.user_data['last_review_task_id'] = task_id
        review_msgs = context.user_data.get('review_message_ids', {}) or {}
        task_msg_ids = review_msgs.get(str(task_id), [])
        
        # Подготавливаем кнопки действий
        keyboard = [
            [InlineKeyboardButton("✅ Задача завершена", callback_data=f"approve_{task_id}")],
            [InlineKeyboardButton("❌ Переделать", callback_data=f"redo_{task_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="review_tasks")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Заголовок
        header_text = f"📋 Задача #{task_id}\n\nКомментарий: {task['comment']}\nСтатус: {task['status']}"
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        # Альбомы "до" (менеджер) и "после" (исполнитель) из расширенной таблицы
        before_list = [p for p in db.get_task_photos(task_id) if p.get('kind') == 'before' and p.get('file_path') and os.path.exists(p['file_path'])]
        after_list = [p for p in db.get_task_photos(task_id) if p.get('kind') == 'after' and p.get('file_path') and os.path.exists(p['file_path'])]
        # Отправляем "до"
        if before_list:
            media = []
            files = []
            for idx, ph in enumerate(before_list):
                f = open(ph['file_path'], 'rb')
                files.append(f)
                if idx == 0:
                    media.append(InputMediaPhoto(media=f, caption=header_text))
                else:
                    media.append(InputMediaPhoto(media=f))
            try:
                sent_group = await context.bot.send_media_group(chat_id=chat_id, media=media)
                if sent_group:
                    task_msg_ids.extend([m.message_id for m in sent_group])
            finally:
                for f in files:
                    try:
                        f.close()
                    except:
                        pass
        else:
            # Нет фото "до" — отправим шапку
            header_msg = await query.message.reply_text(header_text)
            task_msg_ids.append(header_msg.message_id)
        # Отправляем "после"
        if after_list:
            if task['completed_by']:
                username = db.get_username(task['completed_by'])
                if username:
                    after_caption = f"Исполнитель @{username} прикрепил фото к задаче #{task_id}"
                else:
                    after_caption = f"Исполнитель (ID: {task['completed_by']}) прикрепил фото к задаче #{task_id}"
            else:
                after_caption = f"Исполнитель прикрепил фото к задаче #{task_id}"
            media = []
            files = []
            for idx, ph in enumerate(after_list):
                f = open(ph['file_path'], 'rb')
                files.append(f)
                if idx == 0:
                    media.append(InputMediaPhoto(media=f, caption=after_caption))
                else:
                    media.append(InputMediaPhoto(media=f))
            try:
                sent_after = await context.bot.send_media_group(chat_id=chat_id, media=media)
                if sent_after:
                    task_msg_ids.extend([m.message_id for m in sent_after])
            finally:
                for f in files:
                    try:
                        f.close()
                    except:
                        pass
            # Сообщение с кнопками отдельно
            sent_btn = await context.bot.send_message(chat_id=chat_id, text="Выберите действие:", reply_markup=reply_markup)
            task_msg_ids.append(sent_btn.message_id)
        else:
            # Нет фото "после" — отправляем предупреждение с кнопками
            sent = await query.message.reply_text("⚠️ Исполнитель не прикрепил фото результата.", reply_markup=reply_markup)
            task_msg_ids.append(sent.message_id)
        review_msgs[str(task_id)] = task_msg_ids
        context.user_data['review_message_ids'] = review_msgs
        
        # Редактируем старое сообщение (убираем кнопки)
        try:
            await query.edit_message_caption(
                caption=query.message.caption,
                reply_markup=None
            )
        except:
            pass
        return

    if data.startswith("approve_"):
        task_id = int(data.split("_")[1])
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        if chat_id:
            await cleanup_review_task_messages(context, chat_id, task_id)
            await cleanup_manager_task_messages(context, chat_id, task_id)
        
        db.update_task_status(task_id, STATUS_APPROVED)
        
        # Предлагаем выбор - удалить задачу или нет
        keyboard = [
            [InlineKeyboardButton("🗑️ Удалить задачу", callback_data=f"delete_approved_{task_id}")],
            [InlineKeyboardButton("❌ Оставить задачу", callback_data="review_tasks")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_message.reply_text(
            f"✅ Задача #{task_id} помечена как завершенная.\n\n"
            "Хотите удалить задачу?",
            reply_markup=reply_markup
        )
        return

    if data.startswith("redo_"):
        task_id = int(data.split("_")[1])
        if role != "manager":
            await query.answer("❌ У вас нет доступа к этой функции.")
            return
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        if chat_id:
            await cleanup_review_task_messages(context, chat_id, task_id)
        
        # Устанавливаем флаг ожидания комментария для переделки
        context.user_data['redoing_task'] = True
        context.user_data['task_id'] = task_id
        
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data=f"review_{task_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"✏️ Введите комментарий, что нужно сделать по задаче #{task_id}:",
            reply_markup=reply_markup
        )
        return

    if data == "restart":
        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        await cleanup_executor_task_messages(context, chat_id, context.user_data.get('current_executor_task_id'))
        # Очищаем все данные пользователя
        context.user_data.clear()
        
        # Сбрасываем роль и категорию: делаем пользователя исполнителем без категории
        username = query.from_user.username or "Пользователь"
        db.set_user_role(user_id, username, "executor", None)
        
        keyboard = build_category_keyboard()
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(
                f"👋 Добро пожаловать, {username}!\n\n"
                "Выберите, где делать отмывки:",
                reply_markup=reply_markup
            )
        except Exception:
            await query.message.reply_text(
                f"👋 Добро пожаловать, {username}!\n\n"
                "Выберите, где делать отмывки:",
                reply_markup=reply_markup
            )
        return

    if data == "back_to_menu":
        # Очищаем состояние создания задачи, если оно было активно
        context.user_data['creating_task'] = False
        context.user_data['task_step'] = None
        context.user_data['task_id'] = None
        context.user_data['task_category'] = None
        # Отменяем режим рассылки, если он был активен
        if context.user_data.get('broadcasting'):
            context.user_data['broadcasting'] = False
        # Удаляем сообщение, под которым нажали кнопку "Главное меню"
        try:
            await query.message.delete()
        except:
            pass
        
        # Проверяем роль пользователя
        role = db.get_user_role(user_id)
        return_to = context.user_data.pop('return_to', None)
        
        # Показываем меню менеджера только если пользователь действительно менеджер
        if return_to == 'manager_menu' and role == "manager":
            keyboard = [
                [InlineKeyboardButton("📋 Создать задачу", callback_data="select_category")],
                [InlineKeyboardButton("📊 Просмотреть задачи", callback_data="view_tasks_manager")],
                [InlineKeyboardButton("✅ Проверить выполненные", callback_data="review_tasks")],
                [InlineKeyboardButton("📨 Создать рассылку", callback_data="broadcast_start")],
                [InlineKeyboardButton("🏠 В начало", callback_data="restart")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text(
                f"👋 Добро пожаловать, менеджер {username}!\n\nВыберите действие:",
                reply_markup=reply_markup
            )
        else:
            # Всегда делаем пользователя исполнителем при выходе в главное меню
            if role == "manager":
                username = query.from_user.username or "Пользователь"
                db.set_user_role(user_id, username, "executor", None)
                role = "executor"
            keyboard = [
                [InlineKeyboardButton("📋 Мои задачи", callback_data="view_tasks_executor")],
                [InlineKeyboardButton("🏠 В начало", callback_data="restart")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text(
                f"👋 Добро пожаловать, {username}!\n\nВы исполнитель. Выберите действие:",
                reply_markup=reply_markup
            )
        return
    
    # Обработка неизвестных callback_data
    logger.warning(f"Неизвестный callback_data: {data}")
    try:
        await query.answer("❌ Неизвестная команда. Попробуйте /start")
    except:
        pass


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Пользователь"
    text = update.message.text

    # Проверка кода доступа
    if context.user_data.get('waiting_for_code'):
        if text == MANAGER_CODE:
            # Устанавливаем роль менеджера
            db.set_user_role(user_id, username, "manager")
            # Проверяем, что роль сохранилась
            saved_role = db.get_user_role(user_id)
            logger.debug(f"Пароль введен правильно, роль установлена: {saved_role}")
            if saved_role != "manager":
                logger.error(f"Роль не сохранилась! Ожидалось: manager, получено: {saved_role}")
                await update.message.reply_text("❌ Ошибка при установке роли менеджера. Попробуйте еще раз.")
                return
            context.user_data['waiting_for_code'] = False
            keyboard = [
                [InlineKeyboardButton("📋 Создать задачу", callback_data="select_category")],
                [InlineKeyboardButton("📊 Просмотреть задачи", callback_data="view_tasks_manager")],
                [InlineKeyboardButton("✅ Проверить выполненные", callback_data="review_tasks")],
                [InlineKeyboardButton("📨 Создать рассылку", callback_data="broadcast_start")],
                [InlineKeyboardButton("🏠 В начало", callback_data="restart")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "✅ Вы стали менеджером!",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text("❌ Неверный код доступа.")
        return

    # Режим рассылки
    if context.user_data.get('broadcasting'):
        broadcast_text = text
        executors = db.get_all_executors()
        sent = 0
        disclaimer = "\n\nЭто сообщение создано автоматически. Не нужно на него отвечать."
        for executor_id in executors:
            try:
                await context.bot.send_message(executor_id, f"📢 Сообщение от менеджера:\n\n{broadcast_text}{disclaimer}")
                sent += 1
            except Exception as e:
                logger.error(f"Не удалось отправить рассылку пользователю {executor_id}: {e}")
        context.user_data['broadcasting'] = False
        keyboard = [
            [InlineKeyboardButton("📋 Создать задачу", callback_data="select_category")],
            [InlineKeyboardButton("📊 Просмотреть задачи", callback_data="view_tasks_manager")],
            [InlineKeyboardButton("✅ Проверить выполненные", callback_data="review_tasks")],
            [InlineKeyboardButton("📨 Создать рассылку", callback_data="broadcast_start")],
            [InlineKeyboardButton("🏠 В начало", callback_data="restart")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"✅ Рассылка отправлена {sent} исполнителям.", reply_markup=reply_markup)
        return

    # Создание задачи - комментарий
    if context.user_data.get('creating_task') and context.user_data.get('task_step') == "comment":
        task_id = context.user_data.get('task_id')
        category = context.user_data.get('task_category', 'Не указана')
        
        # Обновляем комментарий в задаче
        db.update_task_comment(task_id, text)
        
        # Получаем список исполнителей для этой категории
        if category == "Прочее":
            # Для "Прочее" - все пользователи
            executors = db.get_all_executors()
            executor_usernames = []
            for executor_id in executors:
                username = db.get_username(executor_id)
                if username:
                    executor_usernames.append(f"@{username}")
        else:
            # Для других категорий - только пользователи этой категории
            users = db.get_users_by_category(category)
            executor_usernames = [f"@{user['username']}" for user in users if user.get('username')]
        
        executors_text = ", ".join(executor_usernames) if executor_usernames else "Нет исполнителей"
        
        # Формируем сообщение о созданной задаче
        message_text = f"✅ Задача #{task_id} создана!\n\n"
        message_text += f"📂 Категория: {category}\n"
        message_text += f"👥 Исполнители: {executors_text}\n\n"
        message_text += f"📝 Комментарий: {text}"
        
        await update.message.reply_text(message_text)
        
        # Сразу начинаем создание следующей задачи в той же категории
        context.user_data['task_id'] = None
        context.user_data['task_step'] = "photo"
        # Сохраняем категорию для следующей задачи
        
        keyboard = [[InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Возврат из этого шага должен вести в меню менеджера
        context.user_data['return_to'] = 'manager_menu'
        await update.message.reply_text(
            f"📸 Отправьте фотографию для следующей задачи.\n"
            f"Можно одно фото или несколько фото ОДНИМ сообщением (альбомом). Все фото прикрепляйте в одном сообщении.\n\n"
            f"Категория: {category}",
            reply_markup=reply_markup
        )
        return

    # Комментарий для переделки задачи
    if context.user_data.get('redoing_task'):
        task_id = context.user_data.get('task_id')
        task = db.get_task(task_id)
        
        if not task:
            await update.message.reply_text("❌ Задача не найдена.")
            context.user_data['redoing_task'] = False
            context.user_data['task_id'] = None
            return
        
        # Обновляем комментарий задачи, добавляя новый комментарий менеджера в новой строке
        manager_username = update.effective_user.username or "Менеджер"
        new_comment = f"{task['comment']}\n\n⚠️ Переделать - @{manager_username}: {text}"
        db.update_task_comment(task_id, new_comment)
        
        # Обновляем статус задачи на "Переделать"
        db.update_task_status(task_id, STATUS_REDO)
        
        # Уведомляем всех исполнителей с комментарием менеджера
        executors = db.get_all_executors()
        
        # Кнопка для быстрого возврата к задаче
        keyboard = [
            [InlineKeyboardButton(f"📋 Перейти к задаче #{task_id}", callback_data=f"task_{task_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for executor_id in executors:
            try:
                await context.bot.send_message(
                    executor_id,
                    f"⚠️ Задача #{task_id} требует переделки!\n\n"
                    f"Комментарий менеджера @{manager_username}:\n{text}\n\n"
                    f"Пожалуйста, выполните задачу заново.",
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {executor_id}: {e}")
        
        context.user_data['redoing_task'] = False
        context.user_data['task_id'] = None
        
        keyboard = [
            [InlineKeyboardButton("✅ Проверить выполненные", callback_data="review_tasks")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"❌ Задача #{task_id} помечена как требующая переделки.\n\n"
            f"Комментарий добавлен к задаче и отправлен всем исполнителям.",
            reply_markup=reply_markup
        )
        return

    # Редактирование комментария задачи
    if context.user_data.get('editing_comment'):
        task_id = context.user_data.get('task_id')
        task = db.get_task(task_id)
        db.update_task_comment(task_id, text)
        context.user_data['editing_comment'] = False
        context.user_data['task_id'] = None
        
        # Если задача была выполнена - сбрасываем в статус "Новая" и удаляем фото после
        if task and (task['status'] == STATUS_COMPLETED or task['status'] == STATUS_APPROVED):
            # Удаляем фото после, если оно существует
            if task.get('photo_after_path') and os.path.exists(task['photo_after_path']):
                try:
                    os.remove(task['photo_after_path'])
                except Exception as e:
                    logger.error(f"Ошибка при удалении фото после: {e}")
            
            # Сбрасываем задачу в статус "Новая"
            db.reset_task_to_new(task_id)
            
            # Уведомляем всех исполнителей
            executors = db.get_all_executors()
            manager_username = update.effective_user.username or "Менеджер"
            for executor_id in executors:
                try:
                    await context.bot.send_message(
                        executor_id,
                        f"🔄 Задача #{task_id} была изменена менеджером @{manager_username}.\n\n"
                        f"Задача возвращена в работу. Новый комментарий: {text}"
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {executor_id}: {e}")
        
        keyboard = [
            [InlineKeyboardButton("📊 Просмотреть задачи", callback_data="view_tasks_manager")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"✅ Комментарий задачи #{task_id} обновлен!",
            reply_markup=reply_markup
        )
        return

    await update.message.reply_text("Используйте кнопки меню для навигации.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик фотографий"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Пользователь"
    role = db.get_user_role(user_id)
    if not role:
        role = "executor"
    ensure_photos_dir()
    media_group_id = update.message.media_group_id
    # Если продолжается альбом (как при создании, так и при выполнении), добавляем фото к уже созданной задаче
    if media_group_id and context.user_data.get('album_id') == media_group_id and context.user_data.get('album_task_id') and context.user_data.get('album_kind') in ('before','after'):
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        kind = context.user_data['album_kind']
        task_id = context.user_data['album_task_id']
        suffix = "before" if kind == "before" else f"after_{task_id}"
        photo_path = os.path.join(PHOTOS_DIR, f"{suffix}_{photo.file_id}.jpg")
        await file.download_to_drive(photo_path)
        db.add_task_photo(task_id, kind, photo.file_id, photo_path)
        return

    # Создание задачи - фото
    if context.user_data.get('creating_task') and context.user_data.get('task_step') == "photo":
        photo = update.message.photo[-1]  # Берем фото наибольшего размера
        file = await context.bot.get_file(photo.file_id)
        
        photo_path = os.path.join(PHOTOS_DIR, f"before_{photo.file_id}.jpg")
        await file.download_to_drive(photo_path)
        
        category = context.user_data.get('task_category', 'Прочее')
        media_group_id = update.message.media_group_id
        
        # Проверяем, есть ли текст в сообщении с фото (caption)
        caption = update.message.caption
        if caption and caption.strip():
            # Если есть комментарий - создаем задачу сразу
            # Если это часть альбома и задача уже создана под этот альбом — просто добавим фото
            if media_group_id and context.user_data.get('album_id') == media_group_id and context.user_data.get('album_task_id'):
                task_id = context.user_data['album_task_id']
                db.add_task_photo(task_id, 'before', photo.file_id, photo_path)
            else:
                task_id = db.create_task(user_id, photo.file_id, photo_path, caption, category)
                # Сохраняем это фото как дополнительное тоже для списка
                db.add_task_photo(task_id, 'before', photo.file_id, photo_path)
                if media_group_id:
                    context.user_data['album_id'] = media_group_id
                    context.user_data['album_task_id'] = task_id
                    context.user_data['album_kind'] = 'before'
            
            # Получаем список исполнителей для этой категории
            if category == "Прочее":
                # Для "Прочее" - все пользователи
                executors = db.get_all_executors()
                executor_usernames = []
                for executor_id in executors:
                    username = db.get_username(executor_id)
                    if username:
                        executor_usernames.append(f"@{username}")
            else:
                # Для других категорий - только пользователи этой категории
                users = db.get_users_by_category(category)
                executor_usernames = [f"@{user['username']}" for user in users if user.get('username')]
            
            executors_text = ", ".join(executor_usernames) if executor_usernames else "Нет исполнителей"
            
            # Формируем сообщение о созданной задаче
            message_text = f"✅ Задача #{task_id} создана!\n\n"
            message_text += f"📂 Категория: {category}\n"
            message_text += f"👥 Исполнители: {executors_text}\n\n"
            message_text += f"📝 Комментарий: {caption}"
            
            await update.message.reply_text(message_text)
            
            # Сразу начинаем создание следующей задачи в той же категории
            context.user_data['task_step'] = "photo"
            # Сохраняем категорию для следующей задачи
            
            keyboard = [[InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # Возврат из этого шага должен вести в меню менеджера
            context.user_data['return_to'] = 'manager_menu'
            await update.message.reply_text(
                f"📸 Отправьте фотографию для следующей задачи.\n"
                f"Можно одно фото или несколько фото ОДНИМ сообщением (альбомом). Все фото прикрепляйте в одном сообщении.\n\n"
                f"Категория: {category}",
                reply_markup=reply_markup
            )
        else:
            # Если комментария нет - просим его добавить
            # Если это продолжение альбома без подписи и уже есть задача — просто добавим фото
            if media_group_id and context.user_data.get('album_id') == media_group_id and context.user_data.get('album_task_id'):
                task_id = context.user_data['album_task_id']
                db.add_task_photo(task_id, 'before', photo.file_id, photo_path)
                return
            else:
                task_id = db.create_task(user_id, photo.file_id, photo_path, "Введите комментарий...", category)
            context.user_data['task_id'] = task_id
            context.user_data['photo_id'] = photo.file_id
            context.user_data['photo_path'] = photo_path
            context.user_data['task_step'] = "comment"
            # Дополнительно сохраняем фото в расширенную таблицу
            db.add_task_photo(task_id, 'before', photo.file_id, photo_path)
            if media_group_id:
                context.user_data['album_id'] = media_group_id
                context.user_data['album_task_id'] = task_id
                context.user_data['album_kind'] = 'before'
            await update.message.reply_text(
                f"📝 Отправьте комментарий к задаче:\n"
                "(Где это сфотографировано и что нужно сделать)\n\n"
                f"Категория: {category}"
            )
        return

    # Выполнение задачи - фото после
    if context.user_data.get('completing_task'):
        task_id = context.user_data.get('task_id')
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        photo_path = os.path.join(PHOTOS_DIR, f"after_{task_id}_{photo.file_id}.jpg")
        await file.download_to_drive(photo_path)
        
        media_group_id = update.message.media_group_id
        # Если альбом: на первой фотке меняем статус, остальные просто добавляем
        if media_group_id and (context.user_data.get('album_id') != media_group_id or not context.user_data.get('album_task_id')):
            db.update_task_status(task_id, STATUS_COMPLETED, user_id, photo.file_id, photo_path)
            context.user_data['album_id'] = media_group_id
            context.user_data['album_task_id'] = task_id
            context.user_data['album_kind'] = 'after'
        elif not media_group_id:
            db.update_task_status(task_id, STATUS_COMPLETED, user_id, photo.file_id, photo_path)
        # Всегда добавляем фото в расширенную таблицу
        db.add_task_photo(task_id, 'after', photo.file_id, photo_path)
        # Сообщение подтверждения и возврат к списку задач показываем:
        # - для одиночного фото
        # - для первой фотографии альбома
        should_notify = (not media_group_id) or (media_group_id and context.user_data.get('album_kind') == 'after' and context.user_data.get('album_id') == media_group_id and context.user_data.get('album_task_id') == task_id)
        if not media_group_id:
            # Сбрасываем состояние сразу
            context.user_data['completing_task'] = False
            context.user_data['task_id'] = None
            context.user_data.pop('album_id', None)
            context.user_data.pop('album_task_id', None)
            context.user_data.pop('album_kind', None)
        
        # Получаем информацию о задаче для уведомления
        task = db.get_task(task_id)
        executor_username = update.effective_user.username or "Исполнитель"
        
        # Отправляем уведомления всем менеджерам
        managers = db.get_all_managers()
        for manager_id in managers:
            try:
                keyboard = [
                    [InlineKeyboardButton("✅ Проверить задачу", callback_data=f"review_{task_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                message_text = f"✅ Задача #{task_id} была выполнена исполнителем @{executor_username}.\n\n"
                if task:
                    message_text += f"Комментарий: {task['comment']}"
                await context.bot.send_message(
                    manager_id,
                    message_text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление менеджеру {manager_id}: {e}")
        
        # Сообщение пользователю:
        if should_notify:
            await update.message.reply_text(
                f"✅ Задача #{task_id} отмечена как выполненная! Ожидайте проверки менеджером."
            )
            chat_id = update.effective_chat.id if update.effective_chat else update.message.chat_id
            await render_executor_tasks_list(context, user_id, chat_id)
        return

    # Редактирование фото задачи
    if context.user_data.get('editing_photo'):
        task_id = context.user_data.get('task_id')
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        # Получаем задачу перед изменением
        task = db.get_task(task_id)
        
        # Удаляем старое фото если оно существует
        if task and task['photo_before_path'] and os.path.exists(task['photo_before_path']):
            try:
                os.remove(task['photo_before_path'])
            except:
                pass
        
        photo_path = os.path.join(PHOTOS_DIR, f"before_{task_id}_{photo.file_id}.jpg")
        await file.download_to_drive(photo_path)
        
        db.update_task_photo(task_id, photo.file_id, photo_path)
        context.user_data['editing_photo'] = False
        context.user_data['task_id'] = None
        
        # Если задача была выполнена - сбрасываем в статус "Новая" и удаляем фото после
        if task and (task['status'] == STATUS_COMPLETED or task['status'] == STATUS_APPROVED):
            # Удаляем фото после, если оно существует
            if task.get('photo_after_path') and os.path.exists(task['photo_after_path']):
                try:
                    os.remove(task['photo_after_path'])
                except Exception as e:
                    logger.error(f"Ошибка при удалении фото после: {e}")
            
            # Сбрасываем задачу в статус "Новая"
            db.reset_task_to_new(task_id)
            
            # Уведомляем всех исполнителей
            executors = db.get_all_executors()
            manager_username = update.effective_user.username or "Менеджер"
            for executor_id in executors:
                try:
                    await context.bot.send_message(
                        executor_id,
                        f"🔄 Задача #{task_id} была изменена менеджером @{manager_username}.\n\n"
                        f"Фотография задачи была обновлена. Задача возвращена в работу."
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {executor_id}: {e}")
        
        keyboard = [
            [InlineKeyboardButton("📊 Просмотреть задачи", callback_data="view_tasks_manager")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"✅ Фото задачи #{task_id} обновлено!",
            reply_markup=reply_markup
        )
        return

    await update.message.reply_text("Пожалуйста, используйте кнопки меню для работы с фотографиями.")

