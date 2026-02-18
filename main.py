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
# 1. CONFIGURATION & LOGGING
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
    return "Status: Operational. Price Tracker Bot is active."

def run_health_server():
    app_server.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ==========================================
# 3. DATABASE INITIALIZATION
# ==========================================
async def init_db():
    """Initializes the SQLite database asynchronously to store tracking data."""
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

async def post_init(application: Application):
    """Hook to execute background tasks safely before the bot starts polling."""
    await init_db()
    logger.info("System startup sequence complete. Bot is online.")

# ==========================================
# 4. DATA EXTRACTION ENGINE
# ==========================================
def extract_price(url: str) -> float:
    """Fetches the webpage and extracts the current price dynamically."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Resolve short links to their full destination URL
        final_url = response.url.lower()
        soup = BeautifulSoup(response.content, "html.parser")
        price_text = None
        
        if "amazon" in final_url or "amzn" in final_url:
            price_element = soup.find("span", {"class": "a-price-whole"})
            if price_element:
                price_text = price_element.text
                
        elif "flipkart" in final_url or "fktr" in final_url:
            price_element = soup.find("div", class_=re.compile(r"Nx9bqj|hl05eU"))
            if price_element:
                price_text = price_element.text
                
        if price_text:
            clean_price = re.sub(r'[^\d.]', '', price_text)
            return float(clean_price)
            
        return None
        
    except Exception as e:
        logger.error(f"Extraction failed for {url}: {e}")
        return None

# ==========================================
# 5. CONVERSATIONAL HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provides professional onboarding for new users."""
    welcome_message = (
        "Greetings! I am your automated Price Tracking Assistant. 📊\n\n"
        "**How to use me:**\n"
        "Simply paste an **Amazon** or **Flipkart** product link directly into this chat. "
        "I will analyze the product and ask you for your target price.\n\n"
        "To view all your active monitors, type `/list`."
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Intelligently processes plain text messages (URLs or Price inputs)."""
    text = update.message.text.strip()
    user_id = update.message.chat_id

    # Step 1: Check if the bot is currently waiting for the user to reply with a target price
    if context.user_data.get('awaiting_price'):
        try:
            target_price = float(text)
            url = context.user_data['pending_url']
            platform = context.user_data['pending_platform']
            current_price = context.user_data['current_price']
            
            # Save the tracker to the database
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute(
                    "INSERT INTO trackers (user_id, url, target_price, platform) VALUES (?, ?, ?, ?)",
                    (user_id, url, target_price, platform)
                )
                await db.commit()
            
            # Formulate the confirmation response
            confirmation = (
                f"✅ **Tracking Activated**\n\n"
                f"**Platform:** {platform}\n"
                f"**Target Price:** ₹{target_price:,.2f}\n"
            )
            if current_price:
                confirmation += f"**Current Price:** ₹{current_price:,.2f}\n\n"
            else:
                confirmation += "\n"
                
            confirmation += "I will notify you instantly when the price drops to or below your target."
            
            await update.message.reply_text(confirmation, parse_mode='Markdown')
            
            # Clear the temporary user data
            context.user_data.clear()
            return
            
        except ValueError:
            await update.message.reply_text("⚠️ Please enter a valid number for your target price (e.g., 999).")
            return

    # Step 2: If the bot is not waiting for a price, check if the text contains a URL
    url_pattern = re.compile(r'(https?://[^\s]+)')
    match = url_pattern.search(text)
    
    if match:
        url = match.group(0)
        url_lower = url.lower()
        
        # Identify platform
        if "amazon" in url_lower or "amzn" in url_lower: 
            platform = "Amazon"
        elif "flipkart" in url_lower or "fktr" in url_lower: 
            platform = "Flipkart"
        else:
            await update.message.reply_text("I currently only support monitoring for Amazon and Flipkart links.")
            return

        # Fetch current price dynamically
        processing_msg = await update.message.reply_text(f"🔍 Analyzing {platform} link...")
        current_price = extract_price(url)
        
        # Store context for the next step of the conversation
        context.user_data['awaiting_price'] = True
        context.user_data['pending_url'] = url
        context.user_data['pending_platform'] = platform
        context.user_data['current_price'] = current_price
        
        prompt = f"Link recognized as **{platform}**. "
        if current_price:
            prompt += f"The current price is **₹{current_price:,.2f}**.\n\n"
        else:
            prompt += "I couldn't fetch the live price right now, but I can still track it in the background.\n\n"
            
        prompt += "Please reply with your **Target Price** (e.g., 999):"
        
        # Replace the processing message with the actual prompt
        await processing_msg.edit_text(prompt, parse_mode='Markdown')
        return

    # Step 3: If it's not a URL and we aren't waiting for a price, guide the user.
    await update.message.reply_text("Please paste an Amazon or Flipkart link to begin tracking.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retrieves and displays all active tracking tasks for the user."""
    user_id = update.message.chat_id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, platform, target_price FROM trackers WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await update.message.reply_text("You currently have no active price monitors.")
        return
        
    msg = "📋 **Active Price Monitors:**\n\n"
    for row in rows:
        msg += f"• **{row[1]}** | Target: ₹{row[2]:,.2f} (ID: {row[0]})\n"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

# ==========================================
# 6. AUTOMATED BACKGROUND WORKER
# ==========================================
async def check_prices_job(context: ContextTypes.DEFAULT_TYPE):
    """Background task that iteratively checks the database against live prices."""
    logger.info("Executing scheduled price verification cycle...")
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, user_id, url, target_price, platform FROM trackers") as cursor:
            trackers = await cursor.fetchall()
            
        for tracker in trackers:
            item_id, user_id, url, target, platform = tracker
            current_price = extract_price(url)
            
            if current_price and current_price <= target:
                alert_msg = (
                    f"🎉 **PRICE DROP DETECTED!** 🎉\n\n"
                    f"Your monitored {platform} item has dropped to **₹{current_price:,.2f}** "
                    f"(Your target was ₹{target:,.2f}).\n\n"
                    f"🔗 **Purchase Link:** {url}"
                )
                try:
                    await context.bot.send_message(chat_id=user_id, text=alert_msg, parse_mode='Markdown')
                    # Automatically conclude tracking once target is met
                    await db.execute("DELETE FROM trackers WHERE id = ?", (item_id,))
                    await db.commit()
                except Exception as e:
                    logger.error(f"Failed to dispatch alert to {user_id}: {e}")

# ==========================================
# 7. SYSTEM ENTRY POINT
# ==========================================
def main():
    if TELEGRAM_TOKEN == "REPLACE_WITH_YOUR_BOT_TOKEN":
        logger.error("CRITICAL: TELEGRAM_TOKEN environment variable is missing.")
        return

    # Initialize the Render Web Server in a daemon thread
    threading.Thread(target=run_health_server, daemon=True).start()

    # Construct the Bot Application
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Register Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("list", list_command))
    # This handler replaces /track. It catches all standard text messages.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Initialize the Background Scheduler (Checks every 3 hours)
    job_queue = application.job_queue
    job_queue.run_repeating(check_prices_job, interval=10800, first=10)

    logger.info("Application successfully configured. Commencing polling phase...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
            
