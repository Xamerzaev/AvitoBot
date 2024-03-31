import re
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from aiogram.dispatcher.filters import Command

import asyncio

import phonenumbers

from bot_setup import dp, bot, Dispatcher
from config import MODERATOR_CHAT_ID, TELEGRAM_CHANNEL_ID
from states import AdForm, ModeratorFSM

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

media_group_handlers = {}


@dp.message_handler(Command("cancel"), state="*")
async def process_cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Действие отменено. Если хотите начать сначала, отправьте команду /start.", reply_markup=types.ReplyKeyboardRemove())


async def save_user_data(user_id: int, chat_id: int, data: dict, state: FSMContext):
    """
    Сохраняет пользовательские данные вне контекста FSM.
    """
    await state.storage.set_data(chat=chat_id, user=user_id, data=data)


async def get_user_data(user_id: int, chat_id: int, state: FSMContext):
    """
    Получает сохранённые данные пользователя.
    """
    return await state.storage.get_data(chat=chat_id, user=user_id)


@dp.message_handler(commands="start", state="*")
async def start(message: types.Message):
    await AdForm.waiting_for_title.set()
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n"
        "Добро пожаловать в наш сервис подачи объявлений. Сейчас мы проведем вас через несколько "
        "шагов, чтобы собрать всю необходимую информацию для вашего объявления.\n\n"
        "Для начала, пожалуйста, введите название вашего объявления."
        )


@dp.message_handler(state=AdForm.waiting_for_title)
async def ad_title(message: types.Message, state: FSMContext):

    if len(message.text) > 50:
        await message.answer("Название должно содержать не более 50 символов. Пожалуйста, введите короткое название.")
        return
        
    elif len(message.text) < 4 or not any(char.isalpha() for char in message.text):
        await message.answer("Название должно быть длиннее 3 символов и содержать хотя бы одну букву.")
        return
    
    async with state.proxy() as data:
        data['title'] = message.text
    await AdForm.next()
    await message.answer("Введите описание объявления или нажмите /skip, если не хотите добавлять описание.")


@dp.message_handler(state=AdForm.waiting_for_description, commands='skip')
async def ad_description_skip(message: types.Message, state: FSMContext):
    await AdForm.next()
    await message.answer("Отправьте фотографии объявления (1-10 штук, отправьте /done когда закончите):")


@dp.message_handler(state=AdForm.waiting_for_description)
async def ad_description(message: types.Message, state: FSMContext):
    if len(message.text) > 800:
        await message.reply("Описание слишком длинное. Пожалуйста, сократите текст до 800 символов.")
        return

    async with state.proxy() as data:
        data['description'] = message.text
    await AdForm.waiting_for_photos.set()
    await message.answer("Отправьте фотографии объявления (1-10 штук, отправьте /done когда закончите):")


async def handle_media_group_photos(media_group_id: str, state: FSMContext):
    """Завершение обработки медиагруппы и переход к следующему состоянию."""
    await asyncio.sleep(2)
    async with state.proxy() as data:
        photos = media_group_handlers.pop(media_group_id, [])
        data['photos'].extend(photos)

    dispatcher = Dispatcher.get_current()
    await dispatcher.bot.send_message(data['chat_id'], "Фотографии получены. Введите цену объявления:")

    await AdForm.waiting_for_price.set()


@dp.message_handler(content_types=['photo'], state=AdForm.waiting_for_photos)
async def ad_photo(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['chat_id'] = message.chat.id
        if 'photos' not in data:
            data['photos'] = []

        media_group_id = message.media_group_id
        if media_group_id:
            if media_group_id in media_group_handlers:
                media_group_handlers[media_group_id].append(message.photo[-1].file_id)
            else:
                media_group_handlers[media_group_id] = [message.photo[-1].file_id]
                asyncio.create_task(handle_media_group_photos(media_group_id, state))
        else:
            data['photos'].append(message.photo[-1].file_id)
            if len(data['photos']) >= 10:
                await message.answer("Достигнуто максимальное количество фотографий (10).")
                await AdForm.next().set()
                await message.answer("Введите цену объявления:")
            else:
                await message.answer("Фотография добавлена. Добавьте еще или отправьте /done, если закончили.")


@dp.message_handler(state=AdForm.waiting_for_photos, commands='done')
async def photos_done(message: types.Message, state: FSMContext):
    await AdForm.next()
    await message.answer("Введите цену объявления:")


@dp.message_handler(state=AdForm.waiting_for_price)
async def ad_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Цена должна содержать только цифры.")
        return

    if len(message.text) > 10:
        await message.answer("Слишком длинное значение цены. Пожалуйста, введите корректную цену.")
        return

    # Эта проверка избыточна и никогда не выполнится, потому что выше уже проверяется, что текст состоит только из цифр
    # Удалите или пересмотрите эту проверку
    if len(set(message.text)) < 3 and not message.text.isdigit():
        await message.answer("Цена не должна содержать бесконечных цифр или повторяющихся цифр.")
        return

    # Используйте переменную price для установления цены в 0, если текст начинается на 0
    if message.text.startswith('0'):
        price = '0'
    else:
        price = message.text

    # Сохраняем изменённую цену в состояние, используя переменную price
    async with state.proxy() as data:
        data['price'] = price

    # Переход к следующему состоянию
    await AdForm.next()
    await message.answer("Введите контактную информацию для связи (номер телефона):")


async def send_ad_for_moderation(ad_preview, markup, photos=None):
    # Устанавливаем состояние для модератора
    state = Dispatcher.get_current().current_state(chat=MODERATOR_CHAT_ID, user=MODERATOR_CHAT_ID)
    await state.set_state(ModeratorFSM.waiting_for_moderation)

    # Если есть фотографии, отправляем их перед текстом объявления
    if photos:
        media_group = [InputMediaPhoto(photo_id) for photo_id in photos]
        await bot.send_media_group(MODERATOR_CHAT_ID, media_group)

    await bot.send_message(MODERATOR_CHAT_ID, ad_preview, reply_markup=markup)


@dp.message_handler(state=AdForm.waiting_for_contact_info)
async def ad_contact_info(message: types.Message, state: FSMContext):
    try:
        phone_number = phonenumbers.parse(message.text, "RU")
        if not phonenumbers.is_valid_number(phone_number):
            raise ValueError
    except (phonenumbers.phonenumberutil.NumberParseException, ValueError):
        await message.reply("Пожалуйста, введите валидный номер телефона.")
        return
    async with state.proxy() as data:
        data['contact_info'] = message.text
        logger.info(f"Data saved for user {message.from_user.id}: {data}")
        await save_user_data(message.from_user.id, message.chat.id, data, state)

    ad_preview = f"Название: {data.get('title')}\nОписание: {data.get('description')}\nЦена: {data.get('price')}\nКонтакты: {data.get('contact_info')}"
    markup = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("Одобрить", callback_data=f"approve_{message.from_user.id}"),
        InlineKeyboardButton("Отклонить", callback_data=f"reject_{message.from_user.id}")
    )

    await send_ad_for_moderation(ad_preview, markup, photos=data.get('photos'))
    await message.answer("Ваше объявление успешно отправлено на модерацию.\n"
                         "Чтобы подать еще одно объявление, нажмите /start",
                         reply_markup=types.ReplyKeyboardRemove())


async def publish_ad(callback_query: types.CallbackQuery, ad_data, state: FSMContext, user_id: int):
    try:
        logger.info(f"Начало публикации объявления для user_id={user_id} с данными объявления: {ad_data}")
        if not all(key in ad_data for key in ['title', 'price', 'contact_info']):
            logger.warning(f"Отсутствуют некоторые данные объявления для user_id={user_id}. Данные: {ad_data}")
            await bot.answer_callback_query(callback_query.id, "Ошибка: Не все данные объявления найдены.")
            return

        logger.debug("Формирование текста объявления...")
        marketing_text_parts = [
            "🌟 *Новое объявление!* 🌟",
            f"📣 *{ad_data['title']}*"
        ]

        if 'description' in ad_data and ad_data['description'].strip():
            marketing_text_parts.append(f"📄 Описание: {ad_data['description']}")

        user_mention = f"[Пользователь](tg://user?id={user_id})"
        marketing_text_parts.extend([
            f"💰 Цена: {ad_data['price']} ₽",
            f"📞 Контакт: {ad_data['contact_info']}",
            f"👤 Продавец: {user_mention}"
        ])

        marketing_text = "\n\n".join(marketing_text_parts)
        logger.debug("Текст объявления сформирован.")

        if 'photos' in ad_data and ad_data['photos']:
            logger.info("Начало отправки объявления с фотографиями...")
            media = [InputMediaPhoto(photo, caption=marketing_text if i == 0 else None, parse_mode='Markdown') for i, photo in enumerate(ad_data['photos'])]
            await bot.send_media_group(TELEGRAM_CHANNEL_ID, media)
            logger.info(f"Объявление с фотографиями опубликовано для user_id={user_id}.")
        else:
            logger.info("Начало отправки объявления без фотографий...")
            await bot.send_message(TELEGRAM_CHANNEL_ID, marketing_text, parse_mode='Markdown')
            logger.info(f"Объявление без фотографий опубликовано для user_id={user_id}.")
    except Exception as e:
        logger.error(f"Ошибка при публикации объявления для user_id={user_id}. Исключение: {e}")
        await bot.send_message(user_id, "Произошла ошибка при публикации вашего объявления. Пожалуйста, попробуйте позже.")
    finally:
        try:
            logger.info("Попытка удаления сообщения модерации...")
            await bot.delete_message(MODERATOR_CHAT_ID, callback_query.message.message_id)
            logger.info("Сообщение модерации удалено.")
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение модерации для user_id={user_id}. Исключение: {e}")
        await state.finish()
        user_state = Dispatcher.get_current().current_state(chat=user_id, user=user_id)
        await user_state.finish()


@dp.callback_query_handler(lambda c: c.data.startswith('approve_') or c.data.startswith('reject_'), state=ModeratorFSM.waiting_for_moderation)
async def process_ad_decision(callback_query: types.CallbackQuery):
    user_id = callback_query.data.split('_')[1]
    action = callback_query.data.split('_')[0]
    user_state = Dispatcher.get_current().current_state(chat=user_id, user=user_id)
    ad_data = await user_state.get_data()

    if action == "approve":
        await publish_ad(callback_query, ad_data, user_state, user_id)  # Передаем user_state в publish_ad
        await bot.send_message(user_id, "Ваше объявление одобрено и опубликовано.")
    elif action == "reject":
        await bot.send_message(user_id, "Ваше объявление отклонено. Для уточнения деталей свяжитесь с модератором @mahamerz")
        await user_state.finish()  # Завершаем состояние пользователя
