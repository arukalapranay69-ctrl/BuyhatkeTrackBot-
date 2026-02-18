from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configuration ---
BOT_TOKEN = "7986134997:AAGLmZwwj5G9gCT5ZRMC4DuOuTWeeKE7-zo"

# --- State Management ---
# In a production app, you would use a database like Redis. 
# For this tutorial, we will use simple in-memory variables.
waiting_users = []       # List of chat_ids waiting for a partner
active_chats = {}        # Dictionary mapping user_id -> partner_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when a user starts the bot."""
    await update.message.reply_text(
        "Welcome to Stranger Chat! 🕵️‍♂️\n\n"
        "Commands:\n"
        "/search - Find a random stranger to talk to\n"
        "/stop - End your current chat or leave the queue"
    )

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Puts the user in the queue or pairs them up."""
    user_id = update.message.chat_id

    # Check if they are already busy
    if user_id in active_chats:
        await update.message.reply_text("You are already in a chat! Use /stop to leave it first.")
        return
    if user_id in waiting_users:
        await update.message.reply_text("You are already in the waiting queue. Please wait...")
        return

    # If someone is waiting, pair them up!
    if waiting_users:
        partner_id = waiting_users.pop(0)
        
        # Link both users to each other
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        
        # Notify both users
        await context.bot.send_message(chat_id=user_id, text="Stranger found! Say hi 👋")
        await context.bot.send_message(chat_id=partner_id, text="Stranger found! Say hi 👋")
    else:
        # No one is waiting, so join the queue
        waiting_users.append(user_id)
        await update.message.reply_text("Waiting for a partner to join...")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ends the current chat or removes the user from the waiting queue."""
    user_id = update.message.chat_id

    if user_id in waiting_users:
        waiting_users.remove(user_id)
        await update.message.reply_text("You left the waiting queue.")
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        # Unlink both users
        del active_chats[user_id]
        del active_chats[partner_id]
        
        # Notify both users
        await update.message.reply_text("You have disconnected from the chat.")
        await context.bot.send_message(chat_id=partner_id, text="The stranger has disconnected. Use /search to find a new one.")
        return

    await update.message.reply_text("You are not currently in a chat or queue.")

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secretly copies messages between paired users."""
    user_id = update.message.chat_id

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        try:
            # We use copy_message instead of forward_message to ensure anonymity.
            # This strips the "Forwarded from" tag and supports images, voice notes, and videos!
            await context.bot.copy_message(
                chat_id=partner_id,
                from_chat_id=user_id,
                message_id=update.message.message_id
            )
        except Exception:
            # If sending fails (e.g., the partner blocked the bot), end the chat gracefully.
            await update.message.reply_text("Failed to send message. Your partner might have blocked the bot.")
            del active_chats[user_id]
            if partner_id in active_chats:
                del active_chats[partner_id]
    else:
        await update.message.reply_text("You are not chatting with anyone! Use /search to find a stranger.")

def main():
    # Initialize the bot application
    app = Application.builder().token(BOT_TOKEN).build()

    # Register commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("stop", stop))
    
    # Register a message handler to catch all standard text/media messages
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_message))

    # Turn the bot on
    print("Bot is running! Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
    
