import aiohttp
import asyncio
import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import BOT_TOKEN, SSPOISK_API_KEY, DB_URL

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db_pool = None


async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DB_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                film_id BIGINT,
                film_title TEXT,
                timestamp TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS film_stats (
                user_id BIGINT,
                film_id BIGINT,
                film_title TEXT,
                count INT DEFAULT 1,
                PRIMARY KEY (user_id, film_id)
            );
        """)


menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/history"), KeyboardButton(text="/stats")],
        [KeyboardButton(text="/help")]
    ],
    resize_keyboard=True
)


@dp.message(F.text == "/start")
async def start_handler(message: Message):
    await message.answer(
        "Просто отправь название фильма, и я найду его на Кинопоиске!",
        reply_markup=menu_kb
    )


@dp.message(F.text == "/help")
async def help_handler(message: Message):
    await message.answer("/start — начать\n/help — помощь\n/history — история\n/stats — статистика")


async def send_history_page(user_id: int, chat_id: int, page: int):
    limit = 10
    offset = page * limit
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT film_title, timestamp FROM search_history
            WHERE user_id = $1 ORDER BY timestamp DESC
            LIMIT $2 OFFSET $3
        """, user_id, limit, offset)
        total = await conn.fetchval("""
            SELECT COUNT(*) FROM search_history WHERE user_id = $1
        """, user_id)

    if not rows:
        await bot.send_message(chat_id, "История пуста.")
        return

    text = "\n".join([f"• {r['film_title']} ({r['timestamp']})" for r in rows])
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"history:{page - 1}"))
    if (offset + limit) < total:
        buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"history:{page + 1}"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None

    await bot.send_message(chat_id, f"🕓 История (стр. {page + 1}):\n{text}", reply_markup=keyboard)


async def send_stats_page(user_id: int, chat_id: int, page: int):
    limit = 10
    offset = page * limit
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT film_title, count FROM film_stats
            WHERE user_id = $1 ORDER BY count DESC
            LIMIT $2 OFFSET $3
        """, user_id, limit, offset)
        total = await conn.fetchval("""
            SELECT COUNT(*) FROM film_stats WHERE user_id = $1
        """, user_id)

    if not rows:
        await bot.send_message(chat_id, "Нет статистики.")
        return

    text = "\n".join([f"• {r['film_title']} — {r['count']} раз(а)" for r in rows])
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"stats:{page - 1}"))
    if (offset + limit) < total:
        buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"stats:{page + 1}"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None

    await bot.send_message(chat_id, f"📊 Статистика (стр. {page + 1}):\n{text}", reply_markup=keyboard)


@dp.message(F.text == "/history")
async def history_handler(message: Message):
    await send_history_page(message.from_user.id, message.chat.id, page=0)

@dp.message(F.text == "/stats")
async def stats_handler(message: Message):
    await send_stats_page(message.from_user.id, message.chat.id, page=0)


@dp.callback_query(F.data.startswith("history:"))
async def history_page_callback(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    await call.message.delete()
    await send_history_page(call.from_user.id, call.message.chat.id, page)

@dp.callback_query(F.data.startswith("stats:"))
async def stats_page_callback(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    await call.message.delete()
    await send_stats_page(call.from_user.id, call.message.chat.id, page)


@dp.message()
async def find_movie(message: Message):
    query = message.text.strip()
    search_url = f"https://kinopoiskapiunofficial.tech/api/v2.1/films/search-by-keyword?keyword={query}"
    headers = {
        "X-API-KEY": SSPOISK_API_KEY,
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(search_url, headers=headers) as response:
            data = await response.json()
            films = data.get("films", [])
            if films:
                movie = films[0]
                title = movie.get("nameRu") or movie.get("nameEn") or "Без названия"
                year = movie.get("year", "Неизвестно")
                kp_id = movie.get("filmId")
                poster = movie.get("posterUrlPreview")

                desc_url = f"https://kinopoiskapiunofficial.tech/api/v2.2/films/{kp_id}"
                async with session.get(desc_url, headers=headers) as desc_response:
                    desc_data = await desc_response.json()
                    description = desc_data.get("description", "Описание недоступно.")

                msg = (
                    f"🎬 <b>{title}</b> ({year})\n"
                    f"📝 {description}\n"
                    f"👉 https://www.sspoisk.ru/film/{kp_id}/"
                )

                user_id = message.from_user.id
                async with db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO search_history (user_id, film_id, film_title)
                        VALUES ($1, $2, $3)
                    """, user_id, kp_id, title)
                    await conn.execute("""
                        INSERT INTO film_stats (user_id, film_id, film_title, count)
                        VALUES ($1, $2, $3, 1)
                        ON CONFLICT (user_id, film_id) DO UPDATE SET count = film_stats.count + 1
                    """, user_id, kp_id, title)

                if poster:
                    await message.answer_photo(poster, caption=msg)
                else:
                    await message.answer(msg)
            else:
                await message.answer("Фильм не найден 😕")


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
