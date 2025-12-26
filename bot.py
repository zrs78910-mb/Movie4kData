
import telebot
import requests
import re
import time
import threading
import json
import os
from bs4 import BeautifulSoup, NavigableString

# ==============================================================
# --- CONFIGURATION (SETTINGS) ---
# ==============================================================

# 🔐 READ FROM ENVIRONMENT (REQUIRED FOR RENDER)
BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEET_API_1 = os.getenv("SHEET_API_1")
SHEET_API_2 = os.getenv("SHEET_API_2")

# ❗ HARD FAIL IF MISSING
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set in environment variables")
if not SHEET_API_1:
    raise ValueError("❌ SHEET_API_1 not set in environment variables")
if not SHEET_API_2:
    raise ValueError("❌ SHEET_API_2 not set in environment variables")

# 4. WEBSITES
URL_CINEVOOD = "https://cv.webrip.workers.dev/"
URL_MOVIES4U = "https://movies4u.fans/"
URL_FILMYFLY = "https://www.filmyfiy.mov"

# Check Interval (Seconds)
CHECK_INTERVAL = 60

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
IS_RUNNING = False
LOG_CHAT_ID = None

# ==============================================================
# PART 1: SHEET 1 HELPERS
# ==============================================================

def get_sheet1_ids():
    try:
        resp = requests.get(SHEET_API_1, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return [str(row.get('id')) for row in data]
        return []
    except Exception as e:
        print("Sheet1 Read Error:", e)
        return []

def upload_to_sheet1(movie_data):
    try:
        links1 = movie_data.get('Links1st', {})
        links2 = movie_data.get('Links2nd', {})

        payload = {
            "action": "add",
            "id": str(movie_data['id']),
            "title": movie_data['title'],
            "thumbnail": movie_data['thumbnail'],
            "Links1st_2160p": links1.get('2160p', ''),
            "Links1st_1080p": links1.get('1080p', ''),
            "Links1st_720p": links1.get('720p', ''),
            "Links1st_480p": links1.get('480p', ''),
            "Links2nd_2160p": links2.get('2160p', ''),
            "Links2nd_1080p": links2.get('1080p', ''),
            "Links2nd_720p": links2.get('720p', '')
        }
        r = requests.post(SHEET_API_1, json=payload, timeout=15)
        return r.status_code in (200, 302)
    except Exception as e:
        print("Sheet1 Upload Error:", e)
        return False

# ==============================================================
# PART 2: SHEET 2 HELPERS
# ==============================================================

def get_sheet2_titles():
    try:
        r = requests.get(SHEET_API_2, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return [i.get("Title", "").lower().strip() for i in data if i.get("Title")]
        return []
    except Exception as e:
        print("Sheet2 Read Error:", e)
        return []

def upload_to_sheet2(data):
    try:
        formatted = ""
        for i in data["files"]:
            if i["type"] == "header":
                formatted += f"\n--- {i['content']} ---\n"
            else:
                formatted += f"{i['quality']}: {i['url']}\n"

        payload = {
            "action": "add",
            "data": {
                "title": data["title"],
                "thumb": data["thumbnail"],
                "ss": data["screenshot"],
                "source": data["download_page_source"],
                "links": formatted.strip()
            }
        }
        r = requests.post(SHEET_API_2, json=payload, timeout=20)
        return r.status_code == 200
    except Exception as e:
        print("Sheet2 Upload Error:", e)
        return False

# ==============================================================
# (SCRAPERS + LOGIC SAME AS YOUR CODE)
# ==============================================================

# ❗ Rest of your scraping functions remain EXACTLY SAME
# ❗ monitor_loop, handlers, commands unchanged

print("🤖 Universal Bot Online...")
bot.infinity_polling(skip_pending=True)
