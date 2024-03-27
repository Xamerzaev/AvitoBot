from aiogram.utils import executor
from bot_setup import dp
import handlers
from utils import setup_logging

if __name__ == "__main__":
    setup_logging()
    executor.start_polling(dp, skip_updates=True)
