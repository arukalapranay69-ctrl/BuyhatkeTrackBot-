import os
import re
import logging
import threading
import aiosqlite
import requests
from bs4 import BeautifulSoup
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==========================================
# 1. CONFIGURATION & SETUP
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
# 2. RENDER HEALTH CHECK SERVER
# ==========================================
app_server = Flask(__name__)

@app_server.route('/')
def home():
    return "Telegram Price Tracker Bot is Alive and Running!"

def run_health_server():
    # disabled debug and reloader to prevent threading conflicts
    app_server.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ==========================================
# 3. DATABASE MANAGEMENT
# ==========================================
async def init_db():
    """Initializes the SQLite database asynchronously."""
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
    logger.info("Database initialized successfully.")

# BUG FIX: We now use PTB's native post_init hook to safely run async startup tasks
async def post_init(application: Application):
    await init_db()
    logger.info("Startup complete. Bot is now active.")

# ==========================================
# 4. WEB SCRAPING LOGIC
# ==========================================
def extract_price(url: str) -> float:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        
        price_text = None
        
        if "amazon" in url.lower():
            price_element = soup.find("span", {"class": "a-price-whole"})
            if price_element:
                price_text = price_element.text
                
        elif "flipkart" in url.lower():
            price_element = soup.find("div", class_=re.compile(r"Nx9bqj|hl05eU"))
            if price_element:
                price_text = price_element.text
                
        if price_text:
            clean_price = re.sub(r'[^\d.]', '', price_text)
            return float(clean_price)
            
        return None
        
    except Exception as e:
        logger.error(f"Failed to scrape {url}: {e}")
        return None

# ==========================================
# 5. BOT COMMAND HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        "👋 Welcome to the Price Tracker Bot!\n\n"
        "I can track prices on Amazon and Flipkart.\n"
        "Usage: `/track <url> <target_price>`\n"
        "Example: `/track https://amazon.in/product 999`\n\n"
        "Use `/list` to see your tracked items."
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) != 2:
            await update.message.reply_text("⚠️ Invalid format.\nUsage: `/track <url> <target_price>`", parse_mode='Markdown')
            return
            
        url = context.args[0]
        target_price = float(context.args[1])
        user_id = update.message.chat_id
        
        platform = "Unknown"
        if "amazon" in url.lower(): platform = "Amazon"
        elif "flipkart" in url.lower(): platform = "Flipkart"
        else:
            await update.message.reply_text("⚠️ Please provide a valid Amazon or Flipkart link.")
            return

        current_price = extract_price(url)
        if current_price is None:
            await update.message.reply_text("⚠️ Could not read the price right now (the site might be blocking bots). I will still save it and try tracking it in the background!")
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO trackers (user_id, url, target_price, platform) VALUES (?, ?, ?, ?)",
                (user_id, url, target_price, platform)
            )
            await db.commit()
            
        msg = f"✅ Tracking added!\n**Platform:** {platform}\n**Target:** ₹{target_price}"
        if current_price:
            msg += f"\n**Current Price:** ₹{current_price}"
            
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except ValueError:
        await update.message.reply_text("⚠️ Target price must be a valid number.")
    except Exception as e:
        logger.error(f"Error in track_command: {e}")
        await update.message.reply_text("⚠️ An unexpected error occurred.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, platform, target_price FROM trackers WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await update.message.reply_text("You are not tracking any items right now.")
        return
        
    msg = "📋 **Your Tracked Items:**\n\n"
    for row in rows:
        msg += f"ID: {row[0]} | {row[1]} | Target: ₹{row[2]}\n"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

# ==========================================
# 6. BACKGROUND SCHEDULER
# ==========================================
async def check_prices_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running scheduled price check...")
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, user_id, url, target_price, platform FROM trackers") as cursor:
            trackers = await cursor.fetchall()
            
        for tracker in trackers:
            item_id, user_id, url, target, platform = tracker
            current_price = extract_price(url)
            
            if current_price and current_price <= target:
                alert_msg = f"🎉 **PRICE DROP ALERT!** 🎉\n\nYour {platform} item has dropped to **₹{current_price}** (Target was ₹{target}).\n\nBuy here: {url}"
                try:
                    await context.bot.send_message(chat_id=user_id, text=alert_msg, parse_mode='Markdown')
                    await db.execute("DELETE FROM trackers WHERE id = ?", (item_id,))
                    await db.commit()
                except Exception as e:
                    logger.error(f"Failed to send message to {user_id}: {e}")

# ==========================================
# 7. MAIN STARTUP LOGIC
# ==========================================
def main():
    if TELEGRAM_TOKEN == "REPLACE_WITH_YOUR_BOT_TOKEN":
        logger.error("Please set your TELEGRAM_TOKEN environment variable!")
        return

    # 1. Start Flask Health Check in background thread
    threading.Thread(target=run_health_server, daemon=True).start()

    # 2. Build Bot and attach the async post_init hook so the database builds properly
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # 3. Register Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("track", track_command))
    application.add_handler(CommandHandler("list", list_command))

    # 4. Schedule Job
    job_queue = application.job_queue
    job_queue.run_repeating(check_prices_job, interval=10800, first=10)

    logger.info("Bot is starting polling...")
    
    # 5. Start Polling
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    
