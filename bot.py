import aiohttp
import asyncio
import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
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

@dp.message(F.text == "/start")
async def start_handler(message: Message):
    await message.answer("Просто отправь название фильма, и я найду его на Кинопоиске!")

@dp.message(F.text == "/help")
async def help_handler(message: Message):
    await message.answer("/start — начать\n/help — помощь\n/history — история\n/stats — статистика")

@dp.message(F.text == "/history")
async def history_handler(message: Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT film_title, timestamp FROM search_history
            WHERE user_id = $1 ORDER BY timestamp DESC LIMIT 10
        """, user_id)
    if not rows:
        await message.answer("История пуста.")
    else:
        text = "\n".join([f"• {r['film_title']} ({r['timestamp']})" for r in rows])
        await message.answer(f"🕓 История:\n{text}")

@dp.message(F.text == "/stats")
async def stats_handler(message: Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT film_title, count FROM film_stats
            WHERE user_id = $1 ORDER BY count DESC LIMIT 10
        """, user_id)
    if not rows:
        await message.answer("Нет статистики.")
    else:
        text = "\n".join([f"• {r['film_title']} — {r['count']} раз(а)" for r in rows])
        await message.answer(f"📊 Статистика:\n{text}")

@dp.message()
async def find_movie(message: Message):
    query = message.text.strip()
    url = f"https://kinopoiskapiunofficial.tech/api/v2.1/films/search-by-keyword?keyword={query}"
    headers = {
        "X-API-KEY": SSPOISK_API_KEY,
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            films = data.get("films", [])
            if films:
                movie = films[0]
                title = movie.get("nameRu") or movie.get("nameEn") or "Без названия"
                year = movie.get("year", "Неизвестно")
                kp_id = movie.get("filmId")
                poster = movie.get("posterUrlPreview")
                msg = f"🎬 <b>{title}</b> ({year})\n👉 https://www.sspoisk.ru/film/{kp_id}/"

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
