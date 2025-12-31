import os
from dotenv import load_dotenv

# بارگذاری متغیرهای محیطی
load_dotenv()

# تنظیمات تلگرام
TELEGRAM_TOKEN = os.getenv('8492497660:AAGQgmKTjrxi4c4IaRh6xg8PF9ZEYmbnZEc')
TELEGRAM_CHAT_ID = os.getenv('138228682')

# تنظیمات مانیتورینگ
CHECK_TREND_INTERVAL = 5  # ثانیه - چک کردن روند
SEND_STATUS_INTERVAL = 300  # ثانیه - ارسال وضعیت (۵ دقیقه)
CHECK_ENTRY_INTERVAL = 10  # ثانیه - چک کردن سیگنال ورود

# تنظیمات اندیکاتورها
INDICATOR_SETTINGS = {
    'trend_tracer': {
        'length': 20,
        'st1_factor': 0.5,
        'st1_period': 10,
        'st2_factor': 0.7,
        'st2_period': 14
    },
    'nova_v2': {
        'length': 6,
        'target': 0
    }
}

# مسیرهای فایل
DATA_DIR = 'data'
SIGNALS_FILE = os.path.join(DATA_DIR, 'signals.json')
LOGS_DIR = os.path.join(DATA_DIR, 'logs')

# ایجاد پوشه‌ها اگر وجود ندارند
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)