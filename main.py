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

# A temporary dictionary to hold your credentials AND the open browser session
user_session = {}

# ==========================================
# FLASK SERVER (KEEPS RENDER AWAKE)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Interactive Manual OTP Bot is awake!"

def keep_alive():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# ==========================================
# TELEGRAM BOT COMMANDS & CONVERSATION
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """The Professional Welcome Dashboard"""
    welcome_text = (
        "🎓 *SANDIP UNIVERSITY ASSISTANT* 🎓\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome! I am your interactive student portal bot.\n\n"
        "📌 *Step 1:* Type /login to save your credentials.\n"
        "📌 *Step 2:* Request your data. I will ask for the OTP, log in, and fetch it!\n\n"
        "👉 /attendance - Fetch your latest attendance\n"
        "👉 /assignment - Check for new assignments"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

# --- LOGIN CREDENTIALS FLOW ---
@bot.message_handler(commands=['login'])
def login_start(message):
    msg = bot.reply_to(message, "👤 *Setup Step 1/2*\n\nPlease enter your *PRN Number*:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_prn_step) # Waits for user to type PRN

def process_prn_step(message):
    chat_id = message.chat.id
    user_session[chat_id] = {'prn': message.text}
    
    msg = bot.reply_to(message, "🔒 *Setup Step 2/2*\n\nPlease enter your *Password*:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_password_step) # Waits for user to type Password

def process_password_step(message):
    chat_id = message.chat.id
    user_session[chat_id]['password'] = message.text 
    
    # Delete the password message from the chat for security!
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass 
        
    bot.send_message(chat_id, "✅ *Credentials saved!* \nYou can now use /attendance or /assignment.", parse_mode="Markdown")


# --- TRIGGERING THE BROWSER & OTP FLOW ---
def trigger_action(message, action_type):
    """Starts the browser, enters credentials, clicks Send OTP, and asks user for the OTP."""
    chat_id = message.chat.id
    if chat_id not in user_session or 'password' not in user_session[chat_id]:
        bot.reply_to(message, "⚠️ Please type /login first to set your credentials!", parse_mode="Markdown")
        return

    bot.send_message(chat_id, "⏳ *Waking up the portal...* Please wait.", parse_mode="Markdown")
    
    # Setup invisible browser
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        driver.get(ERP_LOGIN_URL)
        wait = WebDriverWait(driver, 15)
        
        # --- MOCK LOGIN STEPS (Update XPATHs based on your college portal) ---
        # 1. Enter PRN/Username
        username_input = driver.find_element(By.XPATH, "//input[@placeholder='Username']")
        username_input.send_keys(user_session[chat_id]['prn'])
        
        # 2. Enter Password
        password_input = driver.find_element(By.XPATH, "//input[@placeholder='Password']")
        password_input.send_keys(user_session[chat_id]['password'])
        
        # 3. Click 'Send OTP' (Update XPATH to match the actual button)
        send_otp_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Send OTP')]")
        send_otp_btn.click()
        
        # Save the open browser AND the requested action so we can use them after the user gives the OTP
        user_session[chat_id]['driver'] = driver
        user_session[chat_id]['action'] = action_type
        
        # Ask user for the OTP in Telegram
        msg = bot.send_message(chat_id, "📩 *OTP Sent!* \nPlease check your Email/SMS and type the OTP here:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_manual_otp) # Waits for user to type OTP
        
    except Exception as e:
        bot.send_message(chat_id, "❌ *Error reaching the login page.* The portal might be down.", parse_mode="Markdown")
        driver.quit()

# --- RECEIVING THE OTP & FETCHING DATA ---
def process_manual_otp(message):
    """Takes the OTP from the user, finishes logging in, and gets the data."""
    chat_id = message.chat.id
    otp_code = message.text
    
    driver = user_session[chat_id].get('driver')
    action_type = user_session[chat_id].get('action')
    
    if not driver:
        bot.send_message(chat_id, "⚠️ Browser session expired. Please try your command again.")
        return

    bot.send_message(chat_id, "🔐 *Verifying OTP and fetching data...*", parse_mode="Markdown")
    
    try:
        # 4. Enter the user's OTP into the browser
        otp_input = driver.find_element(By.XPATH, "//input[@placeholder='Enter OTP']")
        otp_input.send_keys(otp_code)
        
        # 5. Click Sign In
        submit_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'SIGN IN')]")
        submit_btn.click()
        time.sleep(5) # Wait for dashboard to load
        
        # 6. Route to the correct action
        if action_type == 'attendance':
            scrape_attendance(chat_id, driver)
        elif action_type == 'assignment':
            scrape_assignment(chat_id, driver)
            
    except Exception as e:
        bot.send_message(chat_id, "❌ *Login Failed!* Incorrect OTP or portal timeout.", parse_mode="Markdown")
    finally:
        # ALWAYS close the browser when done to save cloud memory!
        driver.quit()
        user_session[chat_id]['driver'] = None

# --- THE SCRAPERS ---
def scrape_attendance(chat_id, driver):
    driver.get(ERP_LOGIN_URL + "attendance")
    time.sleep(5)
    total_percentage = driver.find_element(By.XPATH, "//tr[last()]/td[last()]").text
    
    report = (
        "📑 *OFFICIAL ATTENDANCE REPORT* 📑\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Student PRN:* `{user_session[chat_id]['prn']}`\n\n"
        f"📈 *Total Attendance:* *{total_percentage}*\n\n"
        "💡 _Tip: Maintain above 75% to avoid penalties!_"
    )
    bot.send_message(chat_id, report, parse_mode="Markdown")

def scrape_assignment(chat_id, driver):
    driver.get(ERP_LOGIN_URL + "assignments")
    time.sleep(5)
    title = driver.find_element(By.XPATH, "//table/tbody/tr[1]/td[2]").text
    date = driver.find_element(By.XPATH, "//table/tbody/tr[1]/td[3]").text
    
    report = (
        "🔔 *LATEST ASSIGNMENT UPDATE* 🔔\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📖 *Subject:* {title}\n"
        f"📅 *Upload Date:* {date}\n\n"
        "⚠️ _Please check the portal for submission deadlines!_"
    )
    bot.send_message(chat_id, report, parse_mode="Markdown")


# --- COMMAND ROUTERS ---
@bot.message_handler(commands=['attendance'])
def handle_attendance(message):
    trigger_action(message, 'attendance')

@bot.message_handler(commands=['assignment'])
def handle_assignment(message):
    trigger_action(message, 'assignment')

# ==========================================
# BOOT UP SEQUENCE
# ==========================================
if __name__ == "__main__":
    Thread(target=keep_alive).start()
    print("Interactive Bot is listening...")
    bot.infinity_polling()
    
