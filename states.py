from aiogram.dispatcher.filters.state import State, StatesGroup


class AdForm(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_photos = State()
    waiting_for_price = State()
    waiting_for_contact_info = State()
