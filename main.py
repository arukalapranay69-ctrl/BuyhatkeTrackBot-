import os
import time
import telebot
from threading import Thread
from flask import Flask
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==========================================
# CONFIGURATION & SETUP
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
ERP_LOGIN_URL = "https://erp.sandipuniversity.com/"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
user_session = {}

app = Flask(__name__)

@app.route('/')
def home():
    return "Interactive Manual OTP Bot is awake!"

def keep_alive():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# ==========================================
# TELEGRAM BOT COMMANDS
# ==========================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🎓 *SANDIP UNIVERSITY ASSISTANT* 🎓\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 *Step 1:* Type /login to save your credentials.\n"
        "📌 *Step 2:* Request your data.\n\n"
        "👉 /attendance - Fetch your latest attendance\n"
        "👉 /assignment - Check for new assignments"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['login'])
def login_start(message):
    msg = bot.reply_to(message, "👤 *Setup Step 1/2*\n\nPlease enter your *PRN Number*:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_prn_step)

def process_prn_step(message):
    chat_id = message.chat.id
    user_session[chat_id] = {'prn': message.text}
    msg = bot.reply_to(message, "🔒 *Setup Step 2/2*\n\nPlease enter your *Password*:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_password_step)

def process_password_step(message):
    chat_id = message.chat.id
    user_session[chat_id]['password'] = message.text 
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass 
    bot.send_message(chat_id, "✅ *Credentials saved!* \nYou can now use /attendance or /assignment.", parse_mode="Markdown")

def capture_otp_input(message):
    """Grabs the OTP from the user and saves it so the waiting browser can use it."""
    chat_id = message.chat.id
    user_session[chat_id]['current_otp'] = message.text

# ==========================================
# THE CORE BROWSER ENGINE
# ==========================================
def trigger_action(message, action_type):
    chat_id = message.chat.id
    if chat_id not in user_session or 'password' not in user_session[chat_id]:
        bot.reply_to(message, "⚠️ Please type /login first to set your credentials!", parse_mode="Markdown")
        return

    bot.send_message(chat_id, "⏳ *Waking up the portal...* Please wait.", parse_mode="Markdown")
    
    driver = None 

    try:
        # THE FIX: This tells Render to automatically download Chrome for you!
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new') 
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu') 

        driver = webdriver.Chrome(options=options) 
        
        driver.get(ERP_LOGIN_URL)
        wait = WebDriverWait(driver, 15)
        
        # 1. Enter Credentials
        username_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Username']")))
        username_input.send_keys(user_session[chat_id]['prn'])
        
        password_input = driver.find_element(By.XPATH, "//input[@placeholder='Password']")
        password_input.send_keys(user_session[chat_id]['password'])
        
        send_otp_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Send OTP')]")
        send_otp_btn.click()
        
        # Clear any old OTP from memory
        user_session[chat_id]['current_otp'] = None
        
        # Ask user for OTP
        msg = bot.send_message(chat_id, "📩 *OTP Sent!* \nPlease check your Email/SMS and type the OTP here:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, capture_otp_input)
        
        # Synchronous Wait Loop (Holds the browser open)
        bot.send_message(chat_id, "_Waiting for your OTP (60 seconds)..._", parse_mode="Markdown")
        timer = 60
        while user_session[chat_id].get('current_otp') is None and timer > 0:
            time.sleep(1)
            timer -= 1
            
        if timer == 0:
            bot.send_message(chat_id, "⏳ *Timeout!* You took too long to enter the OTP. Please try again.", parse_mode="Markdown")
            return 
            
        # We got the OTP! Proceed with login.
        bot.send_message(chat_id, "🔐 *Verifying OTP and fetching data...*", parse_mode="Markdown")
        otp_code = user_session[chat_id]['current_otp']
        
        otp_input = driver.find_element(By.XPATH, "//input[@placeholder='Enter OTP']")
        otp_input.send_keys(otp_code)
        
        submit_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'SIGN IN')]")
        submit_btn.click()
        time.sleep(5) 
        
        # Route to the correct scraper
        if action_type == 'attendance':
            scrape_attendance(chat_id, driver)
        elif action_type == 'assignment':
            scrape_assignment(chat_id, driver)
            
    except Exception as e:
        error_msg = str(e)[:300] 
        bot.send_message(chat_id, f"❌ *System/Portal Error:* \n`{error_msg}`", parse_mode="Markdown")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

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

@bot.message_handler(commands=['attendance'])
def handle_attendance(message):
    trigger_action(message, 'attendance')

@bot.message_handler(commands=['assignment'])
def handle_assignment(message):
    trigger_action(message, 'assignment')

if __name__ == "__main__":
    Thread(target=keep_alive).start()
    bot.infinity_polling()
    
