import os
import re
import logging
import threading
import aiosqlite
import requests
from bs4 import BeautifulSoup
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ==========================================
# 1. SYSTEM CONFIGURATION & LOGGING
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "REPLACE_WITH_YOUR_BOT_TOKEN")
PORT = int(os.environ.get("PORT", 10000))
DB_NAME = "price_tracker.db"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# 2. CLOUD INFRASTRUCTURE (RENDER HEALTH SERVER)
# ==========================================
app_server = Flask(__name__)

@app_server.route('/')
def home():
    return "Status: Operational. Master Price Tracker Engine is active."

def run_health_server():
    """Binds to Render's required port to prevent forceful shutdown."""
    app_server.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ==========================================
# 3. DATABASE ARCHITECTURE
# ==========================================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trackers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                url TEXT,
                target_price REAL,
                platform TEXT
            )
        """)
        await db.commit()
    logger.info("Database architecture provisioned successfully.")

async def post_init(application: Application):
    await init_db()
    logger.info("System startup sequence complete. Bot is online.")

# ==========================================
# 4. HYBRID DATA EXTRACTION ENGINE
# ==========================================
def extract_price(url: str) -> float:
    url_lower = url.lower()
    
    # --- AMAZON: DIRECT LOCAL SCRAPING ---
    if "amazon" in url_lower or "amzn" in url_lower:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        try:
            response = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            
            price_element = soup.find("span", {"class": "a-price-whole"})
            if price_element:
                return float(re.sub(r'[^\d.]', '', price_element.text))
            return None
        except Exception as e:
            logger.error(f"Amazon direct scrape failed: {e}")
            return None

    # --- FLIPKART: SCRAPER API PROXY ROUTING ---
    elif "flipkart" in url_lower or "fktr" in url_lower:
        SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY")
        if not SCRAPER_API_KEY:
            logger.error("CRITICAL: SCRAPER_API_KEY is missing. Add it to Render Environment Variables.")
            return None
            
        try:
            # STEP 1: Un-shorten mobile links safely using a Desktop User-Agent
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
            temp_response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            clean_url = temp_response.url.split('?')[0] # Strips tracking parameters
            
            # STEP 2: Send clean URL to ScraperAPI to execute JavaScript
            api_endpoint = "http://api.scraperapi.com"
            params = {
                "api_key": SCRAPER_API_KEY,
                "url": clean_url,
                "render": "true" 
            }
            
            response = requests.get(api_endpoint, params=params, timeout=60)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            
            # STEP 3: Find the price using known classes
            price_element = soup.find("div", class_=re.compile(r"Nx9bqj|_30jeq3|_16Jk6d"))
            if price_element:
                return float(re.sub(r'[^\d.]', '', price_element.text))
            
            # STEP 4: Bulletproof Fallback. Find exact Rupee text anywhere on the page.
            for tag in soup.find_all(["div", "span"]):
                text = tag.get_text(strip=True)
                if re.match(r'^₹\s*[\d,]+(\.\d+)?$', text):
                    return float(re.sub(r'[^\d.]', '', text))
                    
            return None
            
        except Exception as e:
            logger.error(f"Flipkart ScraperAPI scrape failed: {e}")
            return None
            
    return None

# ==========================================
# 5. CONVERSATIONAL STATE MACHINE
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        "Greetings! I am your automated Price Tracking Engine. 📊\n\n"
        "**How to operate:**\n"
        "Simply **paste an Amazon or Flipkart link** directly into this chat. "
        "I will intercept it, analyze the current market price, and prompt you for a target.\n\n"
        "To view your active surveillance list, type `/list`."
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.chat_id

    # PHASE 1: Target Price Input
    if context.user_data.get('awaiting_price'):
        try:
            target_price = float(text)
            url = context.user_data['pending_url']
            platform = context.user_data['pending_platform']
            current_price = context.user_data['current_price']
            
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute(
                    "INSERT INTO trackers (user_id, url, target_price, platform) VALUES (?, ?, ?, ?)",
                    (user_id, url, target_price, platform)
                )
                await db.commit()
            
            confirmation = (
                f"✅ **Surveillance Activated**\n\n"
                f"**Retailer:** {platform}\n"
                f"**Target Threshold:** ₹{target_price:,.2f}\n"
            )
            if current_price:
                confirmation += f"**Current Market Price:** ₹{current_price:,.2f}\n\n"
            else:
                confirmation += "\n"
                
            confirmation += "I will alert you the millisecond the price drops to your target."
            
            await update.message.reply_text(confirmation, parse_mode='Markdown')
            context.user_data.clear()
            return
            
        except ValueError:
            await update.message.reply_text("⚠️ Syntax Error: Please reply with a standard numeric value (e.g., 1500).")
            return

    # PHASE 2: URL Interception
    url_pattern = re.compile(r'(https?://[^\s]+)')
    match = url_pattern.search(text)
    
    if match:
        url = match.group(0)
        url_lower = url.lower()
        
        if "amazon" in url_lower or "amzn" in url_lower: 
            platform = "Amazon"
        elif "flipkart" in url_lower or "fktr" in url_lower: 
            platform = "Flipkart"
        else:
            await update.message.reply_text("System rejection: I am exclusively programmed for Amazon and Flipkart domains.")
            return

        processing_msg = await update.message.reply_text(f"🔍 Initializing handshake with {platform} servers. Please wait...")
        current_price = extract_price(url)
        
        context.user_data['awaiting_price'] = True
        context.user_data['pending_url'] = url
        context.user_data['pending_platform'] = platform
        context.user_data['current_price'] = current_price
        
        prompt = f"Link successfully authenticated as **{platform}**. "
        if current_price:
            prompt += f"Current market valuation is **₹{current_price:,.2f}**.\n\n"
        else:
            prompt += "High-security firewall detected. I could not fetch the live price, but I can still monitor it via background proxies.\n\n"
            
        prompt += "Please reply with your **Target Price** (e.g., 999):"
        
        await processing_msg.edit_text(prompt, parse_mode='Markdown')
        return

    # PHASE 3: Unrecognized Input
    await update.message.reply_text("Awaiting input: Please paste a valid Amazon or Flipkart URL.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, platform, target_price FROM trackers WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await update.message.reply_text("Database query returned 0 active monitors.")
        return
        
    msg = "📋 **Active Surveillance Roster:**\n\n"
    for row in rows:
        msg += f"• **{row[1]}** | Target: ₹{row[2]:,.2f} (Record ID: {row[0]})\n"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

# ==========================================
# 6. AUTOMATED BACKGROUND DAEMON
# ==========================================
async def check_prices_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Executing scheduled market verification cycle...")
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, user_id, url, target_price, platform FROM trackers") as cursor:
            trackers = await cursor.fetchall()
            
        for tracker in trackers:
            item_id, user_id, url, target, platform = tracker
            current_price = extract_price(url)
            
            if current_price and current_price <= target:
                alert_msg = (
                    f"🚨 **MARKET THRESHOLD BREACHED!** 🚨\n\n"
                    f"Your monitored {platform} asset has plummeted to **₹{current_price:,.2f}** "
                    f"(Target requirement was ₹{target:,.2f}).\n\n"
                    f"🔗 **Execute Purchase:** {url}"
                )
                try:
                    await context.bot.send_message(chat_id=user_id, text=alert_msg, parse_mode='Markdown')
                    await db.execute("DELETE FROM trackers WHERE id = ?", (item_id,))
                    await db.commit()
                except Exception as e:
                    logger.error(f"Failed to transmit alert payload to user {user_id}: {e}")

# ==========================================
# 7. MAIN EXECUTION THREAD
# ==========================================
def main():
    if TELEGRAM_TOKEN == "REPLACE_WITH_YOUR_BOT_TOKEN":
        logger.error("CRITICAL HALT: TELEGRAM_TOKEN environment variable is missing.")
        return

    threading.Thread(target=run_health_server, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    job_queue = application.job_queue
    job_queue.run_repeating(check_prices_job, interval=10800, first=10)

    logger.info("Core engine compiled. Initiating Telegram polling sequence...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
            
