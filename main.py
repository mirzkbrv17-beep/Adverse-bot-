import asyncio
import glob
import logging
import os
import re
import shutil
import tempfile

import aiohttp
import yt_dlp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiohttp import web

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
COOKIES_FILE = "cookies.txt"  # ixtiyoriy: Instagram/YouTube uchun
MAX_SIZE = 50 * 1024 * 1024  # Telegram bot limiti 50 MB

router = Router()
mode: dict[int, str | None] = {}
chat_hist: dict[int, list] = {}
audio_counter: dict[int, int] = {}
cache: dict[tuple, dict] = {}
sem = asyncio.Semaphore(2)

# ---------------- Matnlar ----------------
TXT_START = "Assalomu alaykum! 👋\nBotimizga xush kelibsiz. Bo'limlarni ochish uchun «📋 Menyu» tugmasini bosing 👇"
TXT_DL = "Assalomu aleykum iltimos instagram youtube va pinterestdan havola yuboring men sizga video media fayl va captionni yuklab beraman 🥹🦋"
TXT_CHAT = "🤖 Chat bot ishga tushdi. Xohlagan savolingizni yozing, men javob beraman.\nChiqish uchun «⬅️ Orqaga» tugmasini bosing."
TXT_MUSIC = "Assalomu aleykum menga audio yoki qoshiq nomini yuboring men sizga yuklab beraman 😍😎"
TXT_DATE = (
    "Assalomu aleykum sz bu guruhga qoshilib dostlar ortdirishingiz mumkin va agar taqdir bolsa "
    "taqdirdagi juftligingiz bilan tanishishingiz mumkin sizga omad: ❤️❤️\n\n"
    "Guruh silkasi: https://t.me/o11jannah"
)
DUOLAR = (
    "📿 Duolar\n\n"
    "🍽 Ovqatdan oldin:\nBismillah.\n\n"
    "🍽 Ovqatdan keyin:\nAlhamdulillahilladhi at'amana va saqona va ja'alana minal muslimin.\n\n"
    "😴 Uxlashdan oldin:\nAllohumma bismika amutu va ahya."
)

# Shahar: (ko'rsatiladigan nom, API nomi, lat, lon)
CITIES = [
    ("Toshkent", "Tashkent", 41.2995, 69.2401),
    ("Samarqand", "Samarkand", 39.6270, 66.9750),
    ("Buxoro", "Bukhara", 39.7747, 64.4286),
    ("Andijon", "Andijan", 40.7821, 72.3442),
    ("Namangan", "Namangan", 41.0011, 71.6683),
    ("Farg'ona", "Fergana", 40.3842, 71.7843),
    ("Nukus", "Nukus", 42.4531, 59.6103),
    ("Urganch", "Urgench", 41.5500, 60.6333),
]

# ---------------- Tugmalar ----------------
MAIN_KB = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Menyu")]], resize_keyboard=True)
BACK_KB = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Orqaga")]], resize_keyboard=True)


def menu_kb():
    rows = [
        [InlineKeyboardButton(text="📥 Instagram hesh teg / yuklovchi", callback_data="sec:dl")],
        [InlineKeyboardButton(text="🤖 Chat bot", callback_data="sec:chat")],
        [InlineKeyboardButton(text="🎵 Musiqa bot", callback_data="sec:music")],
        [InlineKeyboardButton(text="💞 Tanishuv bot", callback_data="sec:date")],
        [InlineKeyboardButton(text="🕌 Islamic bot", callback_data="sec:islam")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def islam_kb():
    rows = [
        [InlineKeyboardButton(text="🕌 Namoz vaqtlari", callback_data="isl:pt")],
        [InlineKeyboardButton(text="📿 Duolar", callback_data="isl:du")],
        [InlineKeyboardButton(text="🧭 Qibla yo'nalishi", callback_data="isl:qb")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def city_kb(prefix):
    rows, row = [], []
    for i, c in enumerate(CITIES):
        row.append(InlineKeyboardButton(text=c[0], callback_data=f"{prefix}:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Islomiy menyu", callback_data="isl:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_menu(m: Message):
    await m.answer("Bo'limni tanlang 👇", reply_markup=menu_kb())


# ---------------- Start / menyu ----------------
@router.message(CommandStart())
async def start(m: Message):
    mode.pop(m.from_user.id, None)
    await m.answer(TXT_START, reply_markup=MAIN_KB)


@router.message(F.text == "📋 Menyu")
async def menu_btn(m: Message):
    mode.pop(m.from_user.id, None)
    await show_menu(m)


@router.message(F.text == "⬅️ Orqaga")
async def back_btn(m: Message):
    mode.pop(m.from_user.id, None)
    await m.answer("🏠 Bosh sahifa", reply_markup=MAIN_KB)
    await show_menu(m)


@router.callback_query(F.data.startswith("sec:"))
async def section(c: CallbackQuery):
    sec, uid = c.data[4:], c.from_user.id
    await c.answer()
    if sec == "dl":
        mode[uid] = "dl"
        await c.message.answer(TXT_DL, reply_markup=BACK_KB)
    elif sec == "chat":
        mode[uid] = "chat"
        chat_hist[uid] = []
        await c.message.answer(TXT_CHAT, reply_markup=BACK_KB)
    elif sec == "music":
        mode[uid] = "music"
        await c.message.answer(TXT_MUSIC, reply_markup=BACK_KB)
    elif sec == "date":
        mode[uid] = None
        await c.message.answer(TXT_DATE, reply_markup=BACK_KB)
    elif sec == "islam":
        mode[uid] = None
        await c.message.answer("🕌 Islomiy bo'lim", reply_markup=BACK_KB)
        await c.message.answer("Kerakli bo'limni tanlang:", reply_markup=islam_kb())


# ---------------- Islamic bo'lim ----------------
async def http_json(url: str, **kw):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        async with s.get(url, **kw) as r:
            return await r.json()


@router.callback_query(F.data.startswith("isl:"))
async def islam(c: CallbackQuery):
    act = c.data[4:]
    await c.answer()
    if act == "home":
        await c.message.answer("Kerakli bo'limni tanlang:", reply_markup=islam_kb())
    elif act == "pt":
        await c.message.answer("Shaharni tanlang:", reply_markup=city_kb("pt"))
    elif act == "qb":
        await c.message.answer("Shaharni tanlang:", reply_markup=city_kb("qb"))
    elif act == "du":
        await c.message.answer(DUOLAR)


@router.callback_query(F.data.startswith("pt:"))
async def prayer(c: CallbackQuery):
    await c.answer()
    name, api, _, _ = CITIES[int(c.data[3:])]
    try:
        d = await http_json(
            "https://api.aladhan.com/v1/timingsByCity",
            params={"city": api, "country": "Uzbekistan", "method": 3, "school": 1},
        )
        t = d["data"]["timings"]
        g = lambda k: t[k].split()[0]
        date = d["data"]["date"]["readable"]
        text = (
            f"🕌 {name} — {date}\n\n"
            f"🌙 Bomdod: {g('Fajr')}\n🌅 Quyosh: {g('Sunrise')}\n☀️ Peshin: {g('Dhuhr')}\n"
            f"🌤 Asr: {g('Asr')}\n🌇 Shom: {g('Maghrib')}\n🌃 Xufton: {g('Isha')}"
        )
    except Exception:
        logging.exception("prayer")
        text = "❌ Namoz vaqtlarini olib bo'lmadi, keyinroq urinib ko'ring."
    await c.message.answer(text)


@router.callback_query(F.data.startswith("qb:"))
async def qibla(c: CallbackQuery):
    await c.answer()
    name, _, lat, lon = CITIES[int(c.data[3:])]
    try:
        d = await http_json(f"https://api.aladhan.com/v1/qibla/{lat}/{lon}")
        deg = round(d["data"]["direction"], 1)
        text = f"🧭 {name} uchun qibla: shimoldan soat strelkasi bo'yicha {deg}°"
    except Exception:
        logging.exception("qibla")
        text = "❌ Qibla ma'lumotini olib bo'lmadi."
    await c.message.answer(text)


# ---------------- yt-dlp yordamchilari ----------------
def base_opts(outdir):
    o = {
        "outtmpl": f"{outdir}/%(id)s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if os.path.exists(COOKIES_FILE):
        o["cookiefile"] = COOKIES_FILE
    return o


def dl_video(url, outdir):
    caption = ""
    path = None
    for h in (720, 480, 360):
        for f in glob.glob(f"{outdir}/*"):
            os.remove(f)
        o = base_opts(outdir)
        o["format"] = f"best[height<={h}][ext=mp4]/bv*[height<={h}]+ba/best[height<={h}]/best"
        o["merge_output_format"] = "mp4"
        with yt_dlp.YoutubeDL(o) as y:
            info = y.extract_info(url, download=True)
        caption = (info.get("description") or info.get("title") or "").strip()
        files = [f for f in glob.glob(f"{outdir}/*") if not f.endswith((".part", ".ytdl"))]
        path = max(files, key=os.path.getsize) if files else None
        if path and os.path.getsize(path) <= MAX_SIZE:
            break
    return path, caption


def dl_audio(url, outdir):
    o = base_opts(outdir)
    o["format"] = "bestaudio/best"
    o["postprocessors"] = [
        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
    ]
    with yt_dlp.YoutubeDL(o) as y:
        info = y.extract_info(url, download=True)
    files = glob.glob(f"{outdir}/*.mp3")
    return (files[0] if files else None), info.get("title") or "audio"


def yt_search(q):
    o = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(o) as y:
        info = y.extract_info(f"ytsearch5:{q}", download=False)
    return [e for e in (info.get("entries") or []) if e and e.get("id")]


# ---------------- Yuklovchi ----------------
URL_RE = re.compile(r"https?://\S+")


async def handle_dl(m: Message):
    mt = URL_RE.search(m.text or "")
    if not mt:
        return await m.answer("❗ Iltimos, havola (link) yuboring.")
    url = mt.group(0)
    wait = await m.answer("⏳ Yuklanmoqda...")
    tmp = tempfile.mkdtemp()
    try:
        async with sem:
            path, caption = await asyncio.to_thread(dl_video, url, tmp)
        if not path:
            logging.error("Fayl yuklanmadi: %s", url)
            return await m.answer("❌ Video yuklanmadi (fayl hosil bo'lmadi).")
        if os.path.getsize(path) > MAX_SIZE:
            return await m.answer("❌ Video 360p da ham 50 MB dan katta, Telegram yubora olmaydi.")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="#️⃣ Hesh teg", callback_data="h"),
                InlineKeyboardButton(text="🎵 Audio", callback_data="a"),
            ]]
        )
        sent = await m.answer_video(FSInputFile(path), reply_markup=kb)
        cache[(m.chat.id, sent.message_id)] = {"url": url, "caption": caption}
        if len(cache) > 500:
            cache.pop(next(iter(cache)))
    except Exception:
        logging.exception("dl")
        await m.answer("❌ Yuklab bo'lmadi. Havolani tekshiring yoki keyinroq urinib ko'ring.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            await wait.delete()
        except Exception:
            pass


@router.callback_query(F.data == "h")
async def cb_hashtag(c: CallbackQuery):
    await c.answer()
    item = cache.get((c.message.chat.id, c.message.message_id))
    if not item:
        return await c.message.answer("❌ Ma'lumot eskirgan, havolani qayta yuboring.")
    cap = item["caption"]
    if not cap:
        return await c.message.answer("Bu postda caption yo'q.")
    for i in range(0, len(cap), 4000):
        await c.message.answer(cap[i:i + 4000])


@router.callback_query(F.data == "a")
async def cb_audio(c: CallbackQuery):
    await c.answer("⏳ Audio tayyorlanmoqda...")
    item = cache.get((c.message.chat.id, c.message.message_id))
    if not item:
        return await c.message.answer("❌ Ma'lumot eskirgan, havolani qayta yuboring.")
    tmp = tempfile.mkdtemp()
    try:
        async with sem:
            path, title = await asyncio.to_thread(dl_audio, item["url"], tmp)
        if not path or os.path.getsize(path) > MAX_SIZE:
            return await c.message.answer("❌ Audio topilmadi yoki juda katta.")
        uid = c.from_user.id
        audio_counter[uid] = audio_counter.get(uid, 0) + 1
        name = f"Abu.{audio_counter[uid]}.mp3"
        await c.message.answer_audio(FSInputFile(path, filename=name), title=name)
    except Exception:
        logging.exception("audio")
        await c.message.answer("❌ Audioni yuklab bo'lmadi.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------- Chat bot (Gemini) ----------------
async def handle_chat(m: Message):
    if not GEMINI_API_KEY:
        return await m.answer("❌ GEMINI_API_KEY sozlanmagan.")
    uid = m.from_user.id
    hist = chat_hist.setdefault(uid, [])
    hist.append({"role": "user", "parts": [{"text": m.text}]})
    del hist[:-20]
    await m.bot.send_chat_action(m.chat.id, "typing")
    body = {
        "systemInstruction": {
            "parts": [{"text": "Sen foydali yordamchisan. Foydalanuvchi qaysi tilda yozsa, shu tilda aniq va xatosiz javob ber."}]
        },
        "contents": hist,
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
            async with s.post(url, json=body, headers={"x-goog-api-key": GEMINI_API_KEY}) as r:
                data = await r.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        hist.append({"role": "model", "parts": [{"text": text}]})
        for i in range(0, len(text), 4000):
            await m.answer(text[i:i + 4000])
    except Exception:
        logging.exception("chat")
        hist.pop()
        await m.answer("❌ Javob olib bo'lmadi, qayta urinib ko'ring.")


# ---------------- Musiqa bot ----------------
async def handle_music_query(m: Message, query: str):
    wait = await m.answer("🔎 Qidirilmoqda...")
    try:
        res = await asyncio.to_thread(yt_search, query)
    except Exception:
        logging.exception("search")
        res = []
    try:
        await wait.delete()
    except Exception:
        pass
    if not res:
        return await m.answer("❌ Hech narsa topilmadi.")
    rows = []
    for e in res:
        d = int(e.get("duration") or 0)
        title = f"🎵 {e.get('title', '')[:45]} [{d // 60}:{d % 60:02d}]"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"m:{e['id']}")])
    await m.answer("Topilgan variantlar:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("m:"))
async def cb_music(c: CallbackQuery):
    await c.answer("⏳ Yuklanmoqda...")
    vid = c.data[2:]
    tmp = tempfile.mkdtemp()
    try:
        async with sem:
            path, title = await asyncio.to_thread(dl_audio, f"https://www.youtube.com/watch?v={vid}", tmp)
        if not path or os.path.getsize(path) > MAX_SIZE:
            return await c.message.answer("❌ Fayl topilmadi yoki juda katta.")
        safe = re.sub(r'[\\/:*?"<>|]', "", title)[:60] or "audio"
        await c.message.answer_audio(FSInputFile(path, filename=f"{safe}.mp3"), title=title)
    except Exception:
        logging.exception("music")
        await c.message.answer("❌ Yuklab bo'lmadi.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.message(F.audio)
async def on_audio(m: Message):
    if mode.get(m.from_user.id) != "music":
        return
    a = m.audio
    q = " ".join(x for x in [a.performer, a.title] if x) or (a.file_name or "")
    if not q:
        return await m.answer("❗ Qo'shiq nomini yozib yuboring.")
    await handle_music_query(m, q)


# ---------------- Umumiy matn ----------------
@router.message(F.text)
async def on_text(m: Message):
    md = mode.get(m.from_user.id)
    if md == "dl":
        await handle_dl(m)
    elif md == "chat":
        await handle_chat(m)
    elif md == "music":
        await handle_music_query(m, m.text)
    else:
        await m.answer("Bo'limlarni ochish uchun «📋 Menyu» tugmasini bosing 👇", reply_markup=MAIN_KB)


# ---------------- Ishga tushirish ----------------
async def health(_):
    return web.Response(text="OK")


async def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN o'rnatilmagan")
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)

    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000"))).start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
