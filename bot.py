import logging
import requests
import json
import re
import asyncio
from bs4 import BeautifulSoup, NavigableString
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
BOT_TOKEN = "8231679051:AAFoqLilEuYVXe8oXFNZmIDvHydE5EzqvyU"

# ✅ NEW APPS SCRIPT URL
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycby_0-q2cYNG7QatU0ypGwA32z1w4m8hXxnHv-wuJPoPKNyxsd0TCdWyuyaYW5RKMy0H/exec"

# Website Config
BASE_URL = "https://www.filmyfiy.mov"
CHECK_INTERVAL = 60  # Seconds (1 Minute)

# Global control flag
is_running = False

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# ---------------------------------------------------------
# API FUNCTIONS (Google Sheet)
# ---------------------------------------------------------

def fetch_existing_titles():
    """Sheet से पुराने Titles लाता है (Comparison के लिए)"""
    try:
        response = requests.get(APPS_SCRIPT_URL, timeout=20)
        if response.status_code == 200:
            data = response.json()
            # सभी Titles का List (lowercase में ताकि duplicate न हो)
            if isinstance(data, list):
                titles = [str(item.get('Title', '')).strip().lower() for item in data if item.get('Title')]
                return titles
        return []
    except Exception as e:
        print(f"⚠️ API Read Error: {e}")
        return []

def upload_to_sheet(data):
    """नये डेटा को Sheet में Upload करता है"""
    try:
        # Links Formatting
        formatted_links = ""
        for item in data['files']:
            if item.get("type") == "header":
                formatted_links += f"\n--- {item['content']} ---\n"
            elif item.get("type") == "file":
                formatted_links += f"{item['quality']}: {item['url']}\n"
        
        payload = {
            "action": "add",
            "data": {
                "title": data['title'],
                "thumb": data['thumbnail'],
                "ss": data['screenshot'],
                "source": data['download_page_source'],
                "links": formatted_links.strip()
            }
        }

        response = requests.post(APPS_SCRIPT_URL, json=payload, timeout=20)
        if response.status_code == 200:
            res = response.json()
            if res.get("status") == "success":
                return True
        return False
    except Exception as e:
        print(f"⚠️ Upload Error: {e}")
        return False

# ---------------------------------------------------------
# SCRAPING FUNCTIONS
# ---------------------------------------------------------

def scrape_download_page_links(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return []
        soup = BeautifulSoup(response.content, 'html.parser')
        content_list = []
        
        center_div = soup.select_one('div.card center div')
        if not center_div:
            first_dlink = soup.select_one('div.dlink')
            if first_dlink: center_div = first_dlink.parent
            
        if center_div:
            for element in center_div.contents:
                if isinstance(element, NavigableString):
                    text = element.strip()
                    clean = re.sub(r'[<•>]+', '', text).strip()
                    if clean: content_list.append({"type": "header", "content": clean})
                elif element.name == 'div' and 'dlink' in element.get('class', []):
                    a_tag = element.find('a')
                    if a_tag:
                        link_url = a_tag.get('href', '')
                        dll_div = a_tag.find('div', class_='dll')
                        quality = dll_div.text.strip() if dll_div else a_tag.text.strip()
                        content_list.append({"type": "file", "quality": quality, "url": link_url})
        return content_list
    except: return []

def scrape_movie_details(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return None
        soup = BeautifulSoup(response.content, 'html.parser')
        
        name_tag = soup.select_one('div.fname > div.colora') or soup.select_one('div.A1 h2')
        movie_name = name_tag.text.strip() if name_tag else "Unknown"

        thumb_tag = soup.select_one('div.movie-thumb img')
        thumbnail = thumb_tag['src'] if thumb_tag else ""
        
        ss_tag = soup.select_one('div.ss img')
        screenshot = ss_tag['src'] if ss_tag else ""
        
        dl_tag = soup.select_one('div.dlbtn a')
        dl_link = dl_tag['href'] if dl_tag else None

        files_data = []
        if dl_link and dl_link.startswith("http"):
            files_data = scrape_download_page_links(dl_link)

        return {
            "title": movie_name,
            "thumbnail": thumbnail,
            "screenshot": screenshot,
            "download_page_source": dl_link,
            "files": files_data
        }
    except: return None

def get_page1_links():
    url = f"{BASE_URL}/"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return []
        soup = BeautifulSoup(response.content, 'html.parser')
        links = []
        seen = set()
        
        for a in soup.select('div.fl a, div.A10 a'):
            href = a.get('href')
            if href and 'page-download' in href:
                full_link = href if href.startswith("http") else f"{BASE_URL}{href}"
                if full_link not in seen:
                    links.append(full_link)
                    seen.add(full_link)
        return links
    except Exception as e:
        print(f"⚠️ Page 1 Error: {e}")
        return []

# ---------------------------------------------------------
# BOT LOOP LOGIC
# ---------------------------------------------------------

async def monitoring_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running
    chat_id = update.effective_chat.id
    
    await context.bot.send_message(chat_id, f"🚀 **Auto-Scraper Started!**\nChecking Page 1 every {CHECK_INTERVAL} seconds...", parse_mode=ParseMode.HTML)

    while is_running:
        try:
            print("--- Checking for updates ---")
            
            # 1. Fetch Existing Data (Source of Truth)
            existing_titles = fetch_existing_titles()
            
            # 2. Fetch Website Page 1
            page1_links = get_page1_links()
            
            new_items_temp = []

            # 3. Identify New Items
            # हम Page 1 के लिंक्स को चेक करेंगे।
            # Note: Efficiency के लिए हम सिर्फ Top 5-10 चेक कर सकते हैं, पर यहाँ पूरा Page 1 चेक कर रहे हैं।
            
            for link in page1_links:
                if not is_running: break
                
                # डिटेल पेज स्क्रैप करें टाइटल चेक करने के लिए
                data = scrape_movie_details(link)
                
                if data and data['title']:
                    clean_title = data['title'].strip().lower()
                    
                    # अगर टाइटल शीट में नहीं है -> नया है
                    if clean_title not in existing_titles:
                        print(f"New Found: {data['title']}")
                        new_items_temp.append(data)
                    else:
                        # जैसे ही कोई पुराना आइटम मिला, मतलब इसके नीचे सब पुराने हैं
                        # (Website क्रम: Newest Top) -> Loop Break कर सकते हैं Time बचाने के लिए
                        break 
                
                await asyncio.sleep(1) # Gentle scraping

            # 4. Upload Logic
            if new_items_temp:
                count = len(new_items_temp)
                await context.bot.send_message(chat_id, f"🔥 **Found {count} New Movies!** Uploading...", parse_mode=ParseMode.HTML)
                
                # IMPORTANT: Reverse List
                # Website: [A(New), B, C] -> Scraper gets [A, B, C]
                # We need to upload C first, then B, then A so A stays at top of sheet.
                new_items_temp.reverse()

                success_count = 0
                for item in new_items_temp:
                    if not is_running: break
                    
                    if upload_to_sheet(item):
                        success_count += 1
                        await context.bot.send_message(chat_id, f"✅ Uploaded: <b>{item['title']}</b>", parse_mode=ParseMode.HTML)
                    else:
                        await context.bot.send_message(chat_id, f"❌ Failed: {item['title']}", parse_mode=ParseMode.HTML)
                    
                    await asyncio.sleep(2) # API Rate Limit Safety
                
                # Update local cache logic not needed as we fetch fresh sheet data every loop
            
            else:
                print("No new movies found.")

        except Exception as e:
            print(f"Loop Error: {e}")
            await context.bot.send_message(chat_id, f"⚠️ Error in loop: {str(e)}")
        
        # Wait for next cycle
        if is_running:
            await asyncio.sleep(CHECK_INTERVAL)

    await context.bot.send_message(chat_id, "🛑 **Scraper Stopped.**")

# ---------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running
    if is_running:
        await update.message.reply_text("⚠️ Scraper is already running!")
        return
    
    is_running = True
    # Start the loop as a background task
    asyncio.create_task(monitoring_loop(update, context))

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running
    if not is_running:
        await update.message.reply_text("⚠️ Scraper is not running.")
        return
    
    is_running = False
    await update.message.reply_text("🛑 Stopping... (Waiting for current process to finish)")

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
if __name__ == '__main__':
    print("Bot is starting...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    
    print("Bot is running...")
    app.run_polling()
