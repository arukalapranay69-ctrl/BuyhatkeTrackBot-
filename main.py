import os
import threading
from flask import Flask
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- 1. Environment Variables ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
AMAZON_TAG = os.getenv("AMAZON_TAG")
FLIPKART_ID = os.getenv("FLIPKART_ID")
# Render automatically assigns a PORT. Default to 10000 if testing locally.
PORT = int(os.getenv("PORT", 10000))

# --- 2. Database Setup (MongoDB) ---
client = MongoClient(MONGO_URI)
db = client["price_tracker_db"]
trackings = db["trackings"]

# --- 3. Flask Dummy Server (Keeps Render Awake) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is awake and running!"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# --- 4. Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Hello! I am your Price Tracker Bot. 🛒\n\n"
        "Send me a link and a target price.\n"
        "Format: /track <url> <target_price>\n"
        "Example: /track https://amazon.in/dp/B08... 499"
    )
    await update.message.reply_text(welcome_text)

async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("⚠️ Usage: /track <url> <target_price>")
            return
        
        url = args[0]
        target_price = float(args[1])
        chat_id = update.message.chat_id
        
        # Save tracking request to database
        trackings.insert_one({
            "chat_id": chat_id,
            "url": url,
            "target_price": target_price
        })
        
        await update.message.reply_text(f"✅ Tracking started! I will alert you when the price drops to or below ₹{target_price}.")
    except ValueError:
        await update.message.reply_text("⚠️ Error: Make sure your target price is a number.")

# --- 5. Scraping & Affiliate Link Logic ---
def generate_affiliate_link(url):
    """
    Placeholder logic: You will need to extract the ASIN or PID 
    and reconstruct a clean link with your tags.
    """
    if "amazon" in url:
        # Example of appending a tag, though extracting ASIN is better
        return f"{url}&tag={AMAZON_TAG}" if "?" in url else f"{url}?tag={AMAZON_TAG}"
    elif "flipkart" in url:
        return f"{url}&affid={FLIPKART_ID}" if "?" in url else f"{url}?affid={FLIPKART_ID}"
    return url

async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    """Background task that runs periodically to check prices."""
    for item in trackings.find():
        url = item["url"]
        
        # TODO: Implement your Beautifulsoup/requests scraping logic here
        # current_price = scrape_price_from_web(url)
        
        # --- MOCK DATA FOR TESTING ---
        # We are simulating a price drop to trigger the alert
        current_price = item["target_price"] - 10 
        
        if current_price <= item["target_price"]:
            aff_link = generate_affiliate_link(url)
            message = (
                f"🚨 **PRICE DROP ALERT!** 🚨\n\n"
                f"The price has dropped to ₹{current_price}!\n"
                f"🛒 Buy it here: {aff_link}"
            )
            
            # Send alert to user
            await context.bot.send_message(chat_id=item["chat_id"], text=message, parse_mode='Markdown')
            
            # Remove item from tracking so it doesn't spam them forever
            trackings.delete_one({"_id": item["_id"]})

# --- 6. Main Execution ---
def main():
    # Start Flask server in a separate background thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Start the Telegram Bot
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("track", track))
    
    # Run the price checker background job every 1 hour (3600 seconds)
    job_queue = application.job_queue
    job_queue.run_repeating(check_prices, interval=3600, first=10)

    # Start listening for messages
    print("Bot is polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
    
