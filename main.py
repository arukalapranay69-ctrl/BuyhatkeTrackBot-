"""
👑 ULTRA-PREMIUM ANONYMOUS CHAT BOT
Architecture: Async Python + python-telegram-bot + MongoDB + AIOHTTP
Designed for Render.com Free Tier + UptimeRobot integration.
"""

import os
import asyncio
import logging
from datetime import datetime
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)

# --- CONFIGURATION & LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# You will set these in Render's Environment Variables later
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGODB_URI_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789")) # Replace with your Telegram ID
PORT = int(os.getenv("PORT", "8080"))

# --- DATABASE MANAGEMENT (MongoDB) ---
class Database:
    def __init__(self, uri: str):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client.omegle_bot
        self.users = self.db.users
        self.active_chats = self.db.active_chats
        self.waiting_queue = self.db.waiting_queue

    async def get_user(self, user_id: int):
        return await self.users.find_one({"user_id": user_id})

    async def register_user(self, user_id: int, username: str):
        user = await self.get_user(user_id)
        if not user:
            await self.users.insert_one({
                "user_id": user_id,
                "username": username,
                "is_premium": False,
                "chats_completed": 0,
                "joined_date": datetime.utcnow()
            })
            return True
        return False

    async def make_premium(self, user_id: int):
        result = await self.users.update_one(
            {"user_id": user_id}, 
            {"$set": {"is_premium": True}}
        )
        return result.modified_count > 0

db = Database(MONGO_URI)

# --- TELEGRAM HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command 1: The Premium Welcome Screen"""
    user = update.effective_user
    await db.register_user(user.id, user.username)
    
    user_data = await db.get_user(user.id)
    is_vip = user_data.get("is_premium", False)

    if is_vip:
        text = (
            f"👑 **Welcome back, VIP {user.first_name}!**\n\n"
            "Your Ultra-Premium status is Active. You have priority queue access "
            "and all filters are unlocked."
        )
        keyboard = [
            [InlineKeyboardButton("🚀 VIP Connect (Zero Wait)", callback_data="cmd_vip_connect")],
            [InlineKeyboardButton("⚙️ VIP Dashboard", callback_data="cmd_dashboard")]
        ]
    else:
        text = (
            f"🌍 **Welcome to the Ultimate Anonymous Network!**\n\n"
            "Thousands of users are chatting right now.\n"
            "Ready to meet a stranger?"
        )
        keyboard = [
            [InlineKeyboardButton("💬 Start Random Chat", callback_data="cmd_chat")],
            [InlineKeyboardButton("💎 Unlock ULTRA Premium", callback_data="cmd_upgrade")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def add_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Command: Upgrades a user to Premium"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Access Denied. You are not an Admin.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /add_premium <user_id>")
        return

    try:
        target_id = int(context.args[0])
        success = await db.make_premium(target_id)
        if success:
            await update.message.reply_text(f"✅ User {target_id} is now a VIP Premium member!")
            # Optionally notify the user
            try:
                await context.bot.send_message(
                    chat_id=target_id, 
                    text="🎉 **Congratulations!** An Admin has upgraded your account to **ULTRA PREMIUM**! Type /start to see your new dashboard.",
                    parse_mode='Markdown'
                )
            except Exception:
                pass # User might have blocked the bot
        else:
            await update.message.reply_text("❌ User not found in the database. Have they typed /start yet?")
    except ValueError:
        await update.message.reply_text("⚠️ Invalid User ID. It must be a number.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Core Engine: Routes messages between strangers"""
    user_id = update.effective_user.id
    text = update.message.text

    # 1. Check if user is currently in a chat session
    chat_session = await db.active_chats.find_one({"$or": [{"user1": user_id}, {"user2": user_id}]})
    
    if chat_session:
        # Find the stranger's ID
        stranger_id = chat_session["user2"] if chat_session["user1"] == user_id else chat_session["user1"]
        
        # Forward the message to the stranger
        try:
            await context.bot.send_message(chat_id=stranger_id, text=f"👤 Stranger: {text}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            await update.message.reply_text("⚠️ The stranger disconnected unexpectedly. Type /chat to find someone new.")
            await db.active_chats.delete_one({"_id": chat_session["_id"]})
    else:
        await update.message.reply_text("You are not in a chat! Type /chat to find a stranger.")

# --- WEB SERVER FOR UPTIMEROBOT (Keeps bot awake 24/7) ---
async def handle_ping(request):
    """UptimeRobot will visit this URL every 14 minutes"""
    return web.Response(text="Bot is awake and running smoothly! 🟢")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

# --- MAIN RUNNER ---
async def main():
    # 1. Start the web server in the background
    await start_web_server()

    # 2. Build the Telegram Bot
    application = Application.builder().token(BOT_TOKEN).build()

    # 3. Register Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("add_premium", add_premium_command))
    
    # 4. Register Message Router (Must be last)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # 5. Start Polling
    logger.info("Bot is starting...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Keep the application running
    await asyncio.Event().wait()

if __name__ == "__main__":
    # Prevent asyncio crash on Windows environments
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        
