import os
import time
import imaplib
import email
import re
import schedule
import telebot
from threading import Thread
from flask import Flask
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# 1. CONFIGURATION & SECRET KEYS
# ==========================================
# These will be set securely in Render's Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID") 
MONGO_URI = os.environ.get("MONGO_URI", "YOUR_MONGODB_URL")
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS", "your_email@gmail.com")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD", "your_gmail_app_password")
ERP_LOGIN_URL = "https://erp.sandipuniversity.com/" # ERP Login Portal

# Initialize Telegram Bot & MongoDB
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
db_client = MongoClient(MONGO_URI)
db = db_client["sandip_university"]
assignments_collection = db["assignments"]

# ==========================================
# 2. FLASK SERVER (THE CAFFEINE PILL)
# ==========================================
# This keeps the Render server awake 24/7 when UptimeRobot pings it
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is fully awake and running!"

def keep_alive():
    app.run(host="0.0.0.0", port=8080)

# ==========================================
# 3. THE EMAIL DETECTIVE (GETTING THE OTP)
# ==========================================
def get_latest_otp():
    """Logs into Gmail invisibly, finds the newest email from Sandip, and extracts the OTP."""
    try:
        # Connect to Gmail's hidden backdoor
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        mail.select("inbox")

        # Search for the most recent email
        status, messages = mail.search(None, 'ALL')
        latest_email_id = messages[0].split()[-1]
        
        status, msg_data = mail.fetch(latest_email_id, '(RFC822)')
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                email_body = str(msg.get_payload(decode=True))
                
                # Look for a 4 or 6 digit number in the email text
                otp_match = re.search(r'\b\d{4,6}\b', email_body)
                if otp_match:
                    return otp_match.group(0)
    except Exception as e:
        print(f"Error reading email: {e}")
    return None

# ==========================================
# 4. THE INVISIBLE BROWSER (LOGIN PROCESS)
# ==========================================
def setup_browser():
    """Sets up a stealthy, invisible Chrome browser for the cloud server."""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless') # Runs invisibly
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    # Auto-installs the correct Chrome Driver
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver

def login_to_portal(driver):
    """Navigates the Sandip portal, clicks 'Email Login', and enters the OTP."""
    driver.get(ERP_LOGIN_URL)
    wait = WebDriverWait(driver, 15)

    try:
        # 1. Click 'Login using Email ID' radio button (Update XPATH if needed)
        email_radio = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='radio' and contains(@value, 'email')]")))
        email_radio.click()

        # 2. Enter Email
        email_input = driver.find_element(By.XPATH, "//input[@placeholder='Email']")
        email_input.send_keys(EMAIL_ADDRESS)

        # 3. Click 'Send OTP'
        send_otp_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Send OTP')]")
        send_otp_btn.click()

        # 4. Wait 10 seconds for the email to arrive, then grab the OTP
        time.sleep(10)
        otp = get_latest_otp()

        # 5. Enter OTP and submit
        if otp:
            otp_input = driver.find_element(By.XPATH, "//input[@placeholder='Enter OTP']")
            otp_input.send_keys(otp)
            submit_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'SIGN IN')]")
            submit_btn.click()
            time.sleep(5) # Wait for dashboard to load

            # 6. Close the Sandip Care Popup
            try:
                close_popup = driver.find_element(By.XPATH, "//button[@class='close-popup-x']") # Update XPATH
                close_popup.click()
            except:
                pass # Popup didn't appear today
            
            return True
    except Exception as e:
        print(f"Login failed: {e}")
        return False

# ==========================================
# 5. THE BOT'S MISSIONS (ASSIGNMENTS & ATTENDANCE)
# ==========================================
def check_assignments():
    """Hourly mission: Checks for new assignments and saves them to MongoDB."""
    print("Starting Hourly Assignment Check...")
    driver = setup_browser()
    if login_to_portal(driver):
        try:
            # Navigate to Assignments page
            driver.get(ERP_LOGIN_URL + "assignments") # Update with actual assignments URL
            time.sleep(5)

            # Scrape the assignment rows (Update XPATH to match your table)
            rows = driver.find_elements(By.XPATH, "//table/tbody/tr")
            for row in rows:
                title = row.find_element(By.XPATH, "./td[2]").text
                created_date = row.find_element(By.XPATH, "./td[3]").text
                
                # Ask MongoDB if we have seen this before
                exists = assignments_collection.find_one({"title": title})
                if not exists:
                    # It's NEW! Send Telegram message and save to DB
                    msg = f"🚨 *NEW ASSIGNMENT UPLOADED!*\n\n*Subject:* {title}\n*Date:* {created_date}"
                    bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode="Markdown")
                    
                    assignments_collection.insert_one({"title": title, "date": created_date})
        except Exception as e:
            print(f"Assignment check error: {e}")
    driver.quit()

def check_attendance():
    """Daily 7 PM mission: Scrapes attendance and messages you."""
    print("Starting Daily 7 PM Attendance Check...")
    driver = setup_browser()
    if login_to_portal(driver):
        try:
            # Navigate to Attendance page
            driver.get(ERP_LOGIN_URL + "attendance") # Update with actual attendance URL
            time.sleep(5)

            # Look at the bottom row of the table for the final percentage
            total_percentage = driver.find_element(By.XPATH, "//tr[last()]/td[last()]").text
            
            msg = f"📊 *DAILY ATTENDANCE UPDATE*\n\nYour total attendance is currently: *{total_percentage}*"
            bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Attendance check error: {e}")
    driver.quit()

# ==========================================
# 6. THE MASTER ALARM CLOCK
# ==========================================
def start_scheduling():
    # Set the 1-hour alarm for assignments
    schedule.every(1).hours.do(check_assignments)
    
    # Set the 7:00 PM alarm for attendance (Use 24-hour time)
    schedule.every().day.at("19:00").do(check_attendance)

    while True:
        schedule.run_pending()
        time.sleep(30)

# ==========================================
# 7. BOOT UP SEQUENCE
# ==========================================
if __name__ == "__main__":
    # Start the Flask web server in the background
    Thread(target=keep_alive).start()
    
    # Start the Alarm Clocks
    start_scheduling()
