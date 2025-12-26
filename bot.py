import telebot
import requests
import re
import time
import threading
import json
from bs4 import BeautifulSoup, NavigableString

# ==============================================================
# --- CONFIGURATION (SETTINGS) ---
# ==============================================================

# 1. BOT TOKEN (Render / Local ENV)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 2. SHEET 1 API (Cinevood & Movies4U)
SHEET_API_1 = os.getenv("SHEET_API_1")

# 3. SHEET 2 API (FilmyFly)
SHEET_API_2 = os.getenv("SHEET_API_2")


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

bot = telebot.TeleBot(BOT_TOKEN)
IS_RUNNING = False
LOG_CHAT_ID = None

# ==============================================================
# PART 1: SHEET 1 HELPERS (Cinevood / Movies4U)
# ==============================================================

def get_sheet1_ids():
    """Sheet 1 se existing IDs (Titles) laata hai"""
    try:
        resp = requests.get(SHEET_API_1, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return [str(row.get('id')) for row in data]
        return []
    except Exception as e:
        print(f"Sheet 1 Read Error: {e}")
        return []

def upload_to_sheet1(movie_data):
    """Cinevood/Movies4U ka data Sheet 1 me upload karta hai"""
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
            "Links1st_720p":  links1.get('720p', ''),
            "Links1st_480p":  links1.get('480p', ''),
            "Links2nd_2160p": links2.get('2160p', ''),
            "Links2nd_1080p": links2.get('1080p', ''),
            "Links2nd_720p":  links2.get('720p', '')
        }
        resp = requests.post(SHEET_API_1, json=payload, timeout=15)
        return resp.status_code == 200 or resp.status_code == 302
    except Exception as e:
        print(f"Sheet 1 Upload Error: {e}")
        return False

# ==============================================================
# PART 2: SHEET 2 HELPERS (FilmyFly)
# ==============================================================

def get_sheet2_titles():
    """Sheet 2 se existing Titles laata hai"""
    try:
        resp = requests.get(SHEET_API_2, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return [str(item.get('Title', '')).strip().lower() for item in data if item.get('Title')]
        return []
    except Exception as e:
        print(f"Sheet 2 Read Error: {e}")
        return []

def upload_to_sheet2(data):
    """FilmyFly ka data Sheet 2 me upload karta hai"""
    try:
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
        resp = requests.post(SHEET_API_2, json=payload, timeout=20)
        return resp.status_code == 200
    except Exception as e:
        print(f"Sheet 2 Upload Error: {e}")
        return False

# ==============================================================
# PART 3: COMMON SCRAPING HELPERS
# ==============================================================

def clean_title(title):
    return title.replace("Download", "").replace("Full Movie", "").strip()

def get_quality_or_size(text):
    q_match = re.search(r'(\d{3,4}p)', text, re.IGNORECASE)
    if q_match: return q_match.group(1)
    if "4k" in text.lower() or "uhd" in text.lower(): return "2160p"
    
    size_match = re.search(r'(\d+(\.\d+)?)\s*(GB|MB)', text, re.IGNORECASE)
    if size_match:
        val = float(size_match.group(1))
        unit = size_match.group(3).upper()
        mb_size = val * 1024 if unit == "GB" else val
        if mb_size > 3000: return "2160p"
        if mb_size > 1400: return "1080p"
        if mb_size > 600: return "720p"
        return "480p"
    return "720p"

def get_site_posts_generic(url, selector):
    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        elements = soup.select(selector)
        for a in elements:
            href = a.get('href')
            if href:
                if not href.startswith("http"):
                    href = url.rstrip('/') + href if href.startswith('/') else url + "/" + href
                items.append({'url': href})
    except Exception as e:
        print(f"Fetch Error {url}: {e}")
    
    unique = []
    seen = set()
    for i in items:
        if i['url'] not in seen:
            seen.add(i['url'])
            unique.append(i)
    return unique

# ==============================================================
# PART 4: SPECIFIC SITE SCRAPERS
# ==============================================================

def process_cinevood(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        h1 = soup.find("h1")
        title = clean_title(h1.text.strip()) if h1 else "Unknown"
        poster = "https://via.placeholder.com/300"
        meta_img = soup.find("meta", property="og:image")
        if meta_img: poster = meta_img.get("content")
        else:
            img = soup.select_one("div.entry-content img")
            if img: poster = img.get('src')
        
        links1, links2 = {}, {}
        targets = soup.find_all("a", href=re.compile(r"(oxxfile\.|vikingfile\.)", re.IGNORECASE))
        if not targets: targets = soup.find_all("a", href=re.compile(r"/s/[a-zA-Z0-9]+"))

        for a in targets:
            prev = a.find_previous(["h3", "h4", "h5", "h6", "p", "strong"])
            info_text = prev.get_text(" ", strip=True) if prev else a.get_text(strip=True)
            full_text = f"{info_text} {a.get_text()}"
            quality = get_quality_or_size(full_text)
            raw = a.get('href')
            final = raw
            if "/s/" in raw: final = raw.replace('/s/', '/api/s/').rstrip('/') + '/hubcloud'
            if quality not in links1: links1[quality] = final
            else: links2[quality] = final
            
        if not links1: return None
        return {"id": title, "thumbnail": poster, "title": title, "Links1st": links1, "Links2nd": links2}
    except: return None

def process_movies4u(url):
    try:
        client = requests.Session(); client.headers.update(HEADERS)
        resp = client.get(url, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        title = clean_title(soup.title.string) if soup.title else "Unknown"
        poster = "https://via.placeholder.com/300"
        meta_img = soup.find("meta", property="og:image")
        if meta_img: poster = meta_img.get("content")
        
        btn = soup.select_one('a[href*="m4ulinks.com"]')
        if not btn: return None
        link_resp = client.get(btn.get('href'), timeout=20)
        link_soup = BeautifulSoup(link_resp.text, "html.parser")
        
        links1, links2 = {}, {}
        headings = link_soup.select("div.download-links-div > h4")
        for h in headings:
            quality = get_quality_or_size(h.text.strip())
            container = h.find_next_sibling("div", class_="downloads-btns-div")
            if container:
                found = [a['href'] for a in container.find_all("a", href=True) if "hubcloud" in a['href'] or "gdflix" in a['href']]
                if found:
                    if quality not in links1:
                        links1[quality] = found[0]
                        if len(found) > 1: links2[quality] = found[1]
                    else: links2[quality] = found[0]
        if not links1: return None
        return {"id": title, "thumbnail": poster, "title": title, "Links1st": links1, "Links2nd": links2}
    except: return None

def process_filmyfly(url):
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
            r2 = requests.get(dl_link, headers=HEADERS, timeout=15)
            s2 = BeautifulSoup(r2.content, 'html.parser')
            center_div = s2.select_one('div.card center div')
            if not center_div:
                first_dlink = s2.select_one('div.dlink')
                if first_dlink: center_div = first_dlink.parent
            
            if center_div:
                for element in center_div.contents:
                    if isinstance(element, NavigableString):
                        text = element.strip()
                        clean = re.sub(r'[<•>]+', '', text).strip()
                        if clean: files_data.append({"type": "header", "content": clean})
                    elif element.name == 'div' and 'dlink' in element.get('class', []):
                        a_tag = element.find('a')
                        if a_tag:
                            link_url = a_tag.get('href', '')
                            dll_div = a_tag.find('div', class_='dll')
                            quality = dll_div.text.strip() if dll_div else a_tag.text.strip()
                            files_data.append({"type": "file", "quality": quality, "url": link_url})

        return {
            "title": movie_name,
            "thumbnail": thumbnail,
            "screenshot": screenshot,
            "download_page_source": dl_link,
            "files": files_data
        }
    except: return None

# ==============================================================
# PART 5: MAIN MONITORING LOOP
# ==============================================================

def monitor_loop():
    global IS_RUNNING
    print("🚀 All-in-One Monitor Started...")
    
    while IS_RUNNING:
        try:
            # 1. Sheet 1 Logic (Cinevood + Movies4U)
            existing_ids_1 = get_sheet1_ids()
            
            # Check Cinevood
            cv_posts = get_site_posts_generic(URL_CINEVOOD, "article.latestPost a.post-image") or get_site_posts_generic(URL_CINEVOOD, "div.post a")
            new_cv = []
            for post in cv_posts[:6]:
                data = process_cinevood(post['url'])
                if data and str(data['id']) not in existing_ids_1: new_cv.append(data)
            
            if new_cv:
                new_cv.reverse()
                if LOG_CHAT_ID: bot.send_message(LOG_CHAT_ID, f"🔥 **CineVood:** Found {len(new_cv)} new.")
                for item in new_cv:
                    if upload_to_sheet1(item):
                        existing_ids_1.append(str(item['id']))
                        if LOG_CHAT_ID: bot.send_message(LOG_CHAT_ID, f"✅ CV Upload: {item['title']}")
                    time.sleep(1)

            # Check Movies4U
            m4u_posts = get_site_posts_generic(URL_MOVIES4U, "a.post-thumbnail") or get_site_posts_generic(URL_MOVIES4U, "div.item a")
            new_m4u = []
            for post in m4u_posts[:6]:
                data = process_movies4u(post['url'])
                if data and str(data['id']) not in existing_ids_1: new_m4u.append(data)
            
            if new_m4u:
                new_m4u.reverse()
                if LOG_CHAT_ID: bot.send_message(LOG_CHAT_ID, f"🔥 **Movies4U:** Found {len(new_m4u)} new.")
                for item in new_m4u:
                    if upload_to_sheet1(item):
                        existing_ids_1.append(str(item['id']))
                        if LOG_CHAT_ID: bot.send_message(LOG_CHAT_ID, f"✅ M4U Upload: {item['title']}")
                    time.sleep(1)

            # 2. Sheet 2 Logic (FilmyFly)
            existing_titles_2 = get_sheet2_titles()
            ff_posts = get_site_posts_generic(f"{URL_FILMYFLY}/", "div.fl a") or get_site_posts_generic(f"{URL_FILMYFLY}/", "div.A10 a")
            ff_posts = [p for p in ff_posts if 'page-download' in p['url']]
            new_ff = []
            
            for post in ff_posts[:6]:
                data = process_filmyfly(post['url'])
                if data and data['title']:
                    clean_t = data['title'].strip().lower()
                    if clean_t not in existing_titles_2: new_ff.append(data)
            
            if new_ff:
                new_ff.reverse()
                if LOG_CHAT_ID: bot.send_message(LOG_CHAT_ID, f"🔥 **FilmyFly:** Found {len(new_ff)} new.")
                for item in new_ff:
                    if upload_to_sheet2(item):
                        existing_titles_2.append(item['title'].strip().lower())
                        if LOG_CHAT_ID: bot.send_message(LOG_CHAT_ID, f"✅ FF Upload: {item['title']}")
                    time.sleep(1)

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(60)

# ==============================================================
# PART 6: MANUAL LINK HANDLER (NEW FEATURE)
# ==============================================================

@bot.message_handler(func=lambda message: message.text and message.text.startswith('http') and not message.text.startswith('/'))
def handle_manual_link(message):
    url = message.text.strip()
    chat_id = message.chat.id
    
    bot.reply_to(message, "🔍 Detecting Website & Processing...")

    # 1. Detect CINEVOOD
    if "webrip.workers.dev" in url or "cinevood" in url:
        data = process_cinevood(url)
        if data:
            bot.send_message(chat_id, f"🎬 **CineVood Detected:** {data['title']}\nUploading to Sheet 1...")
            if upload_to_sheet1(data):
                bot.send_message(chat_id, "✅ Upload Success (Sheet 1)")
            else:
                bot.send_message(chat_id, "❌ Upload Failed")
        else:
            bot.send_message(chat_id, "❌ Scrape Failed or Invalid URL")

    # 2. Detect MOVIES4U
    elif "movies4u" in url:
        data = process_movies4u(url)
        if data:
            bot.send_message(chat_id, f"🎬 **Movies4U Detected:** {data['title']}\nUploading to Sheet 1...")
            if upload_to_sheet1(data):
                bot.send_message(chat_id, "✅ Upload Success (Sheet 1)")
            else:
                bot.send_message(chat_id, "❌ Upload Failed")
        else:
            bot.send_message(chat_id, "❌ Scrape Failed or Invalid URL")

    # 3. Detect FILMYFLY
    elif "filmyfiy" in url or "filmyfly" in url:
        data = process_filmyfly(url)
        if data:
            bot.send_message(chat_id, f"🎬 **FilmyFly Detected:** {data['title']}\nUploading to Sheet 2...")
            if upload_to_sheet2(data):
                bot.send_message(chat_id, "✅ Upload Success (Sheet 2)")
            else:
                bot.send_message(chat_id, "❌ Upload Failed")
        else:
            bot.send_message(chat_id, "❌ Scrape Failed or Invalid URL")
            
    else:
        bot.reply_to(message, "⚠️ Unknown Website! Please send valid links for CineVood, Movies4U, or FilmyFly.")

# ==============================================================
# BOT COMMANDS
# ==============================================================
@bot.message_handler(commands=['start'])
def start_monitor(message):
    global IS_RUNNING, LOG_CHAT_ID
    if IS_RUNNING:
        bot.reply_to(message, "⚠️ Bot is already running.")
        return
    
    IS_RUNNING = True
    LOG_CHAT_ID = message.chat.id
    bot.reply_to(message, "🟢 **Universal Scraper Started!**\n\n1. Auto-Check every 60s.\n2. **Send any URL manually** to upload instantly.")
    threading.Thread(target=monitor_loop, daemon=True).start()

@bot.message_handler(commands=['stop'])
def stop_monitor(message):
    global IS_RUNNING
    if not IS_RUNNING:
        bot.reply_to(message, "⚠️ Bot is stopped.")
        return
    
    IS_RUNNING = False
    bot.reply_to(message, "🔴 **Stopping...**")

# Start
print("🤖 Universal Bot Online...")
bot.infinity_polling()
