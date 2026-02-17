import os
import time
import telebot
from threading import Thread
from flask import Flask
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# CONFIGURATION & SETUP
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
ERP_LOGIN_URL = "https://erp.sandipuniversity.com/"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# A temporary dictionary to hold your credentials while the bot works
user_session = {}

# ==========================================
# FLASK SERVER (KEEPS RENDER AWAKE)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Interactive Student Bot is awake!"

def keep_alive():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# ==========================================
# BROWSER & SCRAPING LOGIC
# ==========================================
def setup_browser():
    """Sets up the invisible Chrome browser."""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def perform_login(chat_id):
    """Logs into the university portal using the provided PRN and Password."""
    prn = user_session.get(chat_id, {}).get('prn')
    password = user_session.get(chat_id, {}).get('password')
    
    bot.send_message(chat_id, "⏳ *Logging into Sandip ERP...* Please wait.", parse_mode="Markdown")
    
    driver = setup_browser()
    driver.get(ERP_LOGIN_URL)
    wait = WebDriverWait(driver, 15)
    
    try:
        # --- MOCK LOGIN STEPS (Update XPATHs based on your college portal) ---
        # 1. Enter PRN/Username
        username_input = driver.find_element(By.XPATH, "//input[@placeholder='Username']")
        username_input.send_keys(prn)
        
        # 2. Enter Password
        password_input = driver.find_element(By.XPATH, "//input[@placeholder='Password']")
        password_input.send_keys(password)
        
        # 3. Handle Auto-OTP or Checkbox here (If required by your specific flow)
        # ...
        
        # 4. Click Sign In
        submit_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'SIGN IN')]")
        submit_btn.click()
        time.sleep(5) 
        
        return driver # Return the logged-in browser
    except Exception as e:
        bot.send_message(chat_id, "❌ *Login Failed!* The portal might be down or credentials are wrong.", parse_mode="Markdown")
        driver.quit()
        return None

# ==========================================
# TELEGRAM BOT COMMANDS & CONVERSATION
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """The Professional Welcome Dashboard"""
    welcome_text = (
        "🎓 *SANDIP UNIVERSITY ASSISTANT* 🎓\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome! I am your automated student portal bot.\n\n"
        "📌 *Available Commands:*\n"
        "👉 /login - Connect your Sandip ERP account\n"
        "👉 /attendance - Fetch your latest attendance\n"
        "👉 /assignment - Check for new assignments\n\n"
        "_Please run /login first to authenticate!_"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

# --- LOGIN FLOW ---
@bot.message_handler(commands=['login'])
def login_start(message):
    msg = bot.reply_to(message, "👤 *Authentication Step 1/2*\n\nPlease enter your *PRN Number*:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_prn_step)

def process_prn_step(message):
    chat_id = message.chat.id
    user_session[chat_id] = {'prn': message.text} # Save PRN temporarily
    
    msg = bot.reply_to(message, "🔒 *Authentication Step 2/2*\n\nPlease enter your *Password*:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_password_step)

def process_password_step(message):
    chat_id = message.chat.id
    user_session[chat_id]['password'] = message.text # Save Password temporarily
    
    # Delete the password message from the chat for security!
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass 
        
    bot.send_message(chat_id, "✅ *Credentials saved for this session!*\nYou can now use /attendance or /assignment.", parse_mode="Markdown")

# --- ATTENDANCE COMMAND ---
@bot.message_handler(commands=['attendance'])
def fetch_attendance(message):
    chat_id = message.chat.id
    if chat_id not in user_session or 'password' not in user_session[chat_id]:
        bot.reply_to(message, "⚠️ Please type /login first!", parse_mode="Markdown")
        return
        
    driver = perform_login(chat_id)
    if driver:
        try:
            bot.send_message(chat_id, "📊 *Analyzing Attendance Records...*", parse_mode="Markdown")
            driver.get(ERP_LOGIN_URL + "attendance")
            time.sleep(5)
            
            # Scrape the percentage
            total_percentage = driver.find_element(By.XPATH, "//tr[last()]/td[last()]").text
            
            # Professional Formatting Output
            report = (
                "📑 *OFFICIAL ATTENDANCE REPORT* 📑\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *Student PRN:* `{user_session[chat_id]['prn']}`\n\n"
                f"📈 *Total Attendance:* *{total_percentage}*\n\n"
                "💡 _Tip: Maintain above 75% to avoid penalties!_"
            )
            bot.send_message(chat_id, report, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(chat_id, f"⚠️ Error reading attendance page.", parse_mode="Markdown")
        finally:
            driver.quit()

# --- ASSIGNMENT COMMAND ---
@bot.message_handler(commands=['assignment'])
def fetch_assignments(message):
    chat_id = message.chat.id
    if chat_id not in user_session or 'password' not in user_session[chat_id]:
        bot.reply_to(message, "⚠️ Please type /login first!", parse_mode="Markdown")
        return
        
    driver = perform_login(chat_id)
    if driver:
        try:
            bot.send_message(chat_id, "📚 *Scanning for new assignments...*", parse_mode="Markdown")
            driver.get(ERP_LOGIN_URL + "assignments")
            time.sleep(5)
            
            # Scrape the first/newest assignment row
            title = driver.find_element(By.XPATH, "//table/tbody/tr[1]/td[2]").text
            date = driver.find_element(By.XPATH, "//table/tbody/tr[1]/td[3]").text
            
            # Professional Formatting Output
            report = (
                "🔔 *LATEST ASSIGNMENT UPDATE* 🔔\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"📖 *Subject:* {title}\n"
                f"📅 *Upload Date:* {date}\n\n"
                "⚠️ _Please check the portal for submission deadlines!_"
            )
            bot.send_message(chat_id, report, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(chat_id, f"⚠️ No assignments found or error reading page.", parse_mode="Markdown")
        finally:
            driver.quit()

# ==========================================
# BOOT UP SEQUENCE
# ==========================================
if __name__ == "__main__":
    # 1. Start Flask (Keeps Render awake)
    Thread(target=keep_alive).start()
    
    # 2. Start Bot (Listens for your messages 24/7)
    print("Bot is listening...")
    bot.infinity_polling()
    
