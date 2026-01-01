"""
ربات نهایی با اندیکاتورهای دقیق نسخه کامل شده
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import asyncio

# ==================== تنظیمات ====================
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_TOKEN="8492497660:AAGQgmKTjrxi4c4IaRh6xg8PF9ZEYmbnZEc"
TELEGRAM_CHAT_ID="138228682"

# ==================== لیست ارزها ====================
CRYPTO_PAIRS = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "BNB": "BNBUSDT",
    "SOL": "SOLUSDT", "XRP": "XRPUSDT", "ADA": "ADAUSDT",
    "AVAX": "AVAXUSDT", "DOT": "DOTUSDT", "DOGE": "DOGEUSDT",
    "SHIB": "SHIBUSDT", "MATIC": "MATICUSDT", "LTC": "LTCUSDT",
    "UNI": "UNIUSDT", "LINK": "LINKUSDT", "ATOM": "ATOMUSDT",
    "ETC": "ETCUSDT", "XLM": "XLMUSDT", "ALGO": "ALGOUSDT",
    "VET": "VETUSDT", "PUMP": "PUMPUSDT"
}

# ==================== متغیرهای سراسری ====================
analysis_system = None
current_symbol = None
is_monitoring = False
CHECK_INTERVAL = 10  # مقدار پیش‌فرض برای تاخیر

# ==================== اندیکاتور ۱: Tren ====================
class TrendTracerIndicator:
    """پیاده‌سازی دقیق Tren"""
    
    def __init__(self, length=20, st1_factor=0.5, st1_period=10, 
                 st2_factor=0.7, st2_period=14):
        self.length = length
        self.st1_factor = st1_factor
        self.st1_period = st1_period
        self.st2_factor = st2_factor
        self.st2_period = st2_period
        self.last_signal = None
    
    def calculate_atr(self, source, atr_length):
        """محاسبه ATR مشابه TradingView"""
        highest_high = source.rolling(atr_length).max()
        lowest_low = source.rolling(atr_length).min()
        
        true_range = pd.Series(index=source.index, dtype=float)
        
        for i in range(1, len(source)):
            if pd.isna(highest_high.iloc[i-1]):
                true_range.iloc[i] = highest_high.iloc[i] - lowest_low.iloc[i]
            else:
                tr1 = highest_high.iloc[i] - lowest_low.iloc[i]
                tr2 = abs(highest_high.iloc[i] - source.iloc[i-1])
                tr3 = abs(lowest_low.iloc[i] - source.iloc[i-1])
                true_range.iloc[i] = max(tr1, tr2, tr3)
        
        # RMA (Relative Moving Average)
        return true_range.ewm(alpha=1/atr_length, adjust=False).mean()
    
    def calculate_supertrend(self, df, factor, atr_period, source_col='close'):
        """محاسبه سوپرترند"""
        source = df[source_col]
        atr = self.calculate_atr(source, atr_period)
        
        upper_band = source + factor * atr
        lower_band = source - factor * atr
        
        supertrend = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(index=df.index, dtype=int)  # 1 = صعودی, -1 = نزولی
        
        # مقداردهی اولیه
        if len(df) > 0:
            supertrend.iloc[0] = upper_band.iloc[0]
            direction.iloc[0] = -1
        
        for i in range(1, len(df)):
            # تنظیم باندها
            if lower_band.iloc[i] > lower_band.iloc[i-1] or source.iloc[i-1] < lower_band.iloc[i-1]:
                lower_band.iloc[i] = lower_band.iloc[i]
            else:
                lower_band.iloc[i] = lower_band.iloc[i-1]
                
            if upper_band.iloc[i] < upper_band.iloc[i-1] or source.iloc[i-1] > upper_band.iloc[i-1]:
                upper_band.iloc[i] = upper_band.iloc[i]
            else:
                upper_band.iloc[i] = upper_band.iloc[i-1]
            
            # تعیین جهت
            if pd.isna(atr.iloc[i-1]):
                direction.iloc[i] = 1
            elif supertrend.iloc[i-1] == upper_band.iloc[i-1]:
                direction.iloc[i] = -1 if source.iloc[i] > upper_band.iloc[i] else 1
            else:
                direction.iloc[i] = 1 if source.iloc[i] < lower_band.iloc[i] else -1
            
            # مقدار سوپرترند
            supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == -1 else upper_band.iloc[i]
        
        return supertrend, direction
    
    def analyze(self, df):
        """آنالیز کامل با Trend Tracer"""
        if len(df) < max(self.length, self.st1_period, self.st2_period) + 10:
            return None
        
        # محاسبه basis
        lower = df['low'].rolling(self.length).min()
        upper = df['high'].rolling(self.length).max()
        basis = (upper + lower) / 2
        
        # سوپرترند اول
        df_temp = df.copy()
        df_temp['basis'] = basis
        st1, dir1 = self.calculate_supertrend(df_temp, self.st1_factor, 
                                             self.st1_period, 'basis')
        
        # سوپرترند دوم (روی نتیجه اول)
        df_temp['st1'] = st1
        st2, dir2 = self.calculate_supertrend(df_temp, self.st2_factor,
                                             self.st2_period, 'st1')
        
        # تشخیص سیگنال
        if len(dir2) > 1:
            current_dir = dir2.iloc[-1]
            prev_dir = dir2.iloc[-2]
            
            # سیگنال خرید: کراس از منفی به مثبت
            if prev_dir < 0 and current_dir > 0:
                self.last_signal = 'خرید'
                signal_type = 'خرید'
                trend = 'صعودی'
            
            # سیگنال فروش: کراس از مثبت به منفی
            elif prev_dir > 0 and current_dir < 0:
                self.last_signal = 'فروش'
                signal_type = 'فروش'
                trend = 'نزولی'
            
            else:
                signal_type = 'خنثی'
                trend = 'صعودی' if current_dir > 0 else 'نزولی'
            
            return {
                'signal': signal_type,
                'trend': trend,
                'value': float(st2.iloc[-1]) if len(st2) > 0 else 0,
                'direction': int(current_dir),
                'name': 'Trend Tracer'
            }
        
        return None

# ==================== اندیکاتور ۲: Super ====================
class SupertrendIndicator:
    """پیاده‌سازی دقیق Super"""
    
    def __init__(self, period=10, multiplier=3.0, source='hl2'):
        self.period = period
        self.multiplier = multiplier
        self.source = source
    
    def analyze(self, df):
        """آنالیز با Super"""
        if len(df) < self.period + 5:
            return None
        
        # انتخاب منبع قیمت
        if self.source == 'hl2':
            src = (df['high'] + df['low']) / 2
        elif self.source == 'close':
            src = df['close']
        else:
            src = (df['high'] + df['low']) / 2
        
        # محاسبه ATR
        def calculate_atr_simple(high, low, close, period):
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            return tr.rolling(period).mean()
        
        atr = calculate_atr_simple(df['high'], df['low'], df['close'], self.period)
        
        # محاسبه باندها
        up = src - (self.multiplier * atr)
        dn = src + (self.multiplier * atr)
        
        # محاسبه سوپرترند
        trend = pd.Series(1, index=df.index)
        supertrend = pd.Series(0.0, index=df.index)
        
        for i in range(1, len(df)):
            # به‌روزرسانی باندها
            if df['close'].iloc[i-1] > up.iloc[i-1]:
                up.iloc[i] = max(up.iloc[i], up.iloc[i-1])
            else:
                up.iloc[i] = up.iloc[i]
                
            if df['close'].iloc[i-1] < dn.iloc[i-1]:
                dn.iloc[i] = min(dn.iloc[i], dn.iloc[i-1])
            else:
                dn.iloc[i] = dn.iloc[i]
            
            # تشخیص روند
            if trend.iloc[i-1] == -1 and df['close'].iloc[i] > dn.iloc[i-1]:
                trend.iloc[i] = 1
            elif trend.iloc[i-1] == 1 and df['close'].iloc[i] < up.iloc[i-1]:
                trend.iloc[i] = -1
            else:
                trend.iloc[i] = trend.iloc[i-1]
            
            # مقدار سوپرترند
            supertrend.iloc[i] = up.iloc[i] if trend.iloc[i] == 1 else dn.iloc[i]
        
        # تشخیص سیگنال
        if len(trend) > 1:
            current_trend = trend.iloc[-1]
            prev_trend = trend.iloc[-2]
            
            if prev_trend == -1 and current_trend == 1:
                signal = 'خرید'
            elif prev_trend == 1 and current_trend == -1:
                signal = 'فروش'
            else:
                signal = 'خنثی'
            
            return {
                'signal': signal,
                'trend': 'صعودی' if current_trend == 1 else 'نزولی',
                'value': float(supertrend.iloc[-1]) if len(supertrend) > 0 else 0,
                'name': 'Supertrend'
            }
        
        return None

# ==================== اندیکاتور ۳: Nov ====================
class NovaV2Indicator:
    """پیاده‌سازی دقیق Nov"""
    
    def __init__(self, length=6, target=0):
        self.length = length
        self.target = target
    
    def calculate_atr_simple(self, high, low, close, period):
        """محاسبه ساده ATR"""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()
    
    def analyze(self, df):
        """آنالیز با Nova_v2"""
        if len(df) < self.length + 10:
            return None
        
        # محاسبه ATR
        atr_value = self.calculate_atr_simple(df['high'], df['low'], df['close'], 50)
        atr_value = atr_value.rolling(50).mean() * 0.8
        
        # میانگین‌های متحرک
        ema_high = df['high'].ewm(span=self.length, adjust=False).mean() + atr_value
        ema_low = df['low'].ewm(span=self.length, adjust=False).mean() - atr_value
        
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2] if len(df) > 1 else current_close
        
        current_sma_high = ema_high.iloc[-1]
        prev_sma_high = ema_high.iloc[-2] if len(ema_high) > 1 else current_sma_high
        
        current_sma_low = ema_low.iloc[-1]
        prev_sma_low = ema_low.iloc[-2] if len(ema_low) > 1 else current_sma_low
        
        # تشخیص سیگنال
        signal = None
        if prev_close <= prev_sma_high and current_close > current_sma_high:
            signal = 'خرید'
        elif prev_close >= prev_sma_low and current_close < current_sma_low:
            signal = 'فروش'
        
        return {
            'signal': signal or 'خنثی',
            'value': float(current_close),
            'sma_high': float(current_sma_high),
            'sma_low': float(current_sma_low),
            'atr': float(atr_value.iloc[-1]) if not atr_value.empty else 0,
            'name': 'Nova_v2'
        }

# ==================== سیستم تحلیل ترکیبی ====================
class CombinedAnalysis:
    """ترکیب نتایج ۳ اندیکاتور"""
    
    def __init__(self):
        self.trend_tracer = TrendTracerIndicator()
        self.supertrend = SupertrendIndicator()
        self.nova = NovaV2Indicator()
        self.signals_history = []
    
    def fetch_data(self, symbol, interval='5m', limit=100):
        """دریافت داده از صرافی"""
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            numeric_cols = ['open', 'high', 'low', 'close']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
            
        except Exception as e:
            print(f"خطا در دریافت داده: {e}")
            return None
    
    def analyze_all(self, symbol):
        """تحلیل با هر ۳ اندیکاتور"""
        df = self.fetch_data(symbol, '5m', 100)
        if df is None or len(df) < 50:
            return None
        
        results = {
            'symbol': symbol,
            'price': float(df['close'].iloc[-1]),
            'time': datetime.now().strftime('%H:%M:%S'),
            'indicators': {},
            'signals': []
        }
        
        # تحلیل با Tren
        tt_result = self.trend_tracer.analyze(df)
        if tt_result:
            results['indicators']['Trend_Tracer'] = tt_result
            if tt_result['signal'] != 'خنثی':
                results['signals'].append({
                    'indicator': 'Trend_Tracer',
                    'signal': tt_result['signal'],
                    'strength': 'قوی'
                })
        
        # تحلیل با Super
        st_result = self.supertrend.analyze(df)
        if st_result:
            results['indicators']['Supertrend'] = st_result
            if st_result['signal'] != 'خنثی':
                results['signals'].append({
                    'indicator': 'Supertrend',
                    'signal': st_result['signal'],
                    'strength': 'متوسط'
                })
        
        # تحلیل با Nov
        nova_result = self.nova.analyze(df)
        if nova_result:
            results['indicators']['Nova_v2'] = nova_result
            if nova_result['signal'] != 'خنثی':
                results['signals'].append({
                    'indicator': 'Nova_v2',
                    'signal': nova_result['signal'],
                    'strength': 'قوی'
                })
        
        # تصمیم نهایی
        buy_count = len([s for s in results['signals'] if s['signal'] == 'خرید'])
        sell_count = len([s for s in results['signals'] if s['signal'] == 'فروش'])
        
        if buy_count >= 2:
            results['final_signal'] = 'خرید قوی 🟢'
            results['signal_strength'] = 'قوی'
        elif sell_count >= 2:
            results['final_signal'] = 'فروش قوی 🔴'
            results['signal_strength'] = 'قوی'
        elif buy_count == 1 and sell_count == 0:
            results['final_signal'] = 'خرید ضعیف 🟡'
            results['signal_strength'] = 'ضعیف'
        elif sell_count == 1 and buy_count == 0:
            results['final_signal'] = 'فروش ضعیف 🟠'
            results['signal_strength'] = 'ضعیف'
        else:
            results['final_signal'] = 'بدون سیگنال ⚪'
            results['signal_strength'] = 'خنثی'
        
        return results

# ==================== ایجاد نمونه ====================
analysis_system = CombinedAnalysis()

# ==================== کیبوردهای شیشه‌ای ====================
def get_main_menu():
    """منوی اصلی"""
    keyboard = [
        [InlineKeyboardButton("🎯 انتخاب ارز", callback_data="select_crypto")],
        [InlineKeyboardButton("📊 وضعیت اندیکاتورها", callback_data="indicators_status")],
        [InlineKeyboardButton("▶️ شروع مانیتورینگ", callback_data="start_monitoring")],
        [InlineKeyboardButton("⏸ توقف مانیتورینگ", callback_data="stop_monitoring")],
        [InlineKeyboardButton("📈 گزارش سیگنال‌ها", callback_data="signals_report")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_crypto_selection_menu():
    """منوی انتخاب ارز"""
    keyboard = []
    
    # لیست همه دکمه‌ها
    all_buttons = []
    for name, symbol in CRYPTO_PAIRS.items():
        all_buttons.append(InlineKeyboardButton(name, callback_data=f"crypto_{symbol}"))
    
    # تقسیم به ردیف‌های ۴ تایی
    for i in range(0, len(all_buttons), 4):
        row = all_buttons[i:i+4]
        keyboard.append(row)
    
    # دکمه بازگشت
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(keyboard)

# ==================== ارسال پیام با تلاش مجدد ====================
async def send_telegram_message(text):
    """ارسال پیام به تلگرام با تلاش مجدد و تنظیم خودکار"""
    global CHECK_INTERVAL
    
    max_retries = 3
    base_delay = 2  # ثانیه
    
    for attempt in range(max_retries):
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = {
                'chat_id': CHAT_ID,
                'text': text
            }
            
            # تاخیر پویا بر اساس شماره تلاش
            delay = base_delay * (attempt + 1)
            if attempt > 0:
                print(f"⏳ تلاش مجدد {attempt}/{max_retries} پس از {delay} ثانیه...")
                await asyncio.sleep(delay)
            
            response = requests.post(url, data=data, timeout=15)
            
            if response.status_code == 200:
                # موفق - تاخیر عادی
                CHECK_INTERVAL = max(10, CHECK_INTERVAL - 1)  # کمی سریعتر
                return True
            else:
                print(f"⚠️ خطای HTTP {response.status_code} در تلاش {attempt+1}")
                
        except requests.exceptions.Timeout:
            print(f"⏱️ تایم‌اوت در تلاش {attempt+1}")
            CHECK_INTERVAL = min(30, CHECK_INTERVAL + 5)  # تاخیر بیشتر
        except requests.exceptions.ConnectionError:
            print(f"🔌 خطای اتصال در تلاش {attempt+1}")
            CHECK_INTERVAL = min(30, CHECK_INTERVAL + 3)
        except Exception as e:
            print(f"❌ خطای ناشناخته در تلاش {attempt+1}: {type(e).__name__}")
    
    print(f"🚫 ارسال پیام پس از {max_retries} تلاش ناموفق بود")
    
    # اگر همه تلاش‌ها شکست خورد، تاخیر زیاد
    CHECK_INTERVAL = 30  # 30 ثانیه
    return False

# ==================== وظیفه مانیتورینگ ====================
async def monitoring_task():
    """مانیتورینگ خودکار"""
    global is_monitoring, current_symbol
    
    last_report_time = datetime.now()
    
    while is_monitoring and current_symbol:
        try:
            results = analysis_system.analyze_all(current_symbol)
            
            if results:
                # اگر سیگنال قوی داشتیم
                if results['signal_strength'] == 'قوی' and results['final_signal'] != 'بدون سیگنال ⚪':
                    # ذخیره در تاریخچه
                    signal_data = {
                        'time': results['time'],
                        'symbol': results['symbol'],
                        'price': results['price'],
                        'final_signal': results['final_signal'],
                        'indicators': results['indicators']
                    }
                    analysis_system.signals_history.append(signal_data)
                    
                    # ارسال اعلان
                    message = f"""🚨 سیگنال قوی از اندیکاتورها!

🎯 ارز: {results['symbol']}
📊 سیگنال: {results['final_signal']}
💰 قیمت: ${results['price']:,.2f}

📋 اندیکاتورهای تأییدکننده:"""
                    
                    for indicator_name, indicator_data in results['indicators'].items():
                        if indicator_data['signal'] != 'خنثی':
                            message += f"\n• {indicator_data['name']}: {indicator_data['signal']}"
                    
                    message += f"\n\n🕐 زمان: {results['time']}"
                    
                    await send_telegram_message(message)
                
                # گزارش هر ۵ دقیقه
                current_time = datetime.now()
                if (current_time - last_report_time).seconds >= 300:
                    report = f"""📊 گزارش وضعیت مانیتورینگ

🎯 ارز: {current_symbol}
💰 قیمت: ${results['price']:,.2f}
🚨 سیگنال فعلی: {results['final_signal']}
📋 سیگنال‌های امروز: {len(analysis_system.signals_history)}
🕐 زمان: {current_time.strftime('%H:%M')}

✅ سیستم در حال کار است"""
                    
                    await send_telegram_message(report)
                    last_report_time = current_time
            
            await asyncio.sleep(CHECK_INTERVAL)  # تاخیر پویا
            
        except Exception as e:
            print(f"خطا در مانیتورینگ: {e}")
            CHECK_INTERVAL = min(60, CHECK_INTERVAL + 10)  # تاخیر زیاد در صورت خطا
            await asyncio.sleep(30)

# ==================== دستورات تلگرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع ربات"""
    welcome_text = """🤖 ربات تحلیلگر با اندیکاتورها

📊 اندیکاتورهای فعال:
1. 🎯 Tren (تشخیص روند اصلی)
2. 📈 Super (تأیید سیگنال)
3. ⚡ No (شکست‌های قیمتی)

🔗 منطق ترکیبی:
• سیگنال قوی: وقتی ۲ یا ۳ اندیکاتور هم‌جهت شوند
• مانیتورینگ: هر ۱۰ ثانیه
• گزارش: هر ۵ دقیقه

از منوی زیر انتخاب کن:"""
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت کلیک روی دکمه‌ها"""
    global current_symbol, is_monitoring
    
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "select_crypto":
        await query.edit_message_text(
            "🎯 لطفاً یک ارز انتخاب کن:",
            reply_markup=get_crypto_selection_menu()
        )
    
    elif data == "indicators_status":
        if not current_symbol:
            await query.edit_message_text(
                "⚠️ هیچ ارزی انتخاب نشده!\n\nلطفاً اول از منوی '🎯 انتخاب ارز' یک ارز انتخاب کن.",
                reply_markup=get_main_menu()
            )
            return
        
        await query.edit_message_text(
            "🔍 در حال تحلیل با اندیکاتورها...",
            reply_markup=None
        )
        
        results = analysis_system.analyze_all(current_symbol)
        
        if results:
            status_text = f"""📊 وضعیت اندیکاتورها برای {current_symbol}

💰 قیمت فعلی: ${results['price']:,.2f}
🕐 زمان تحلیل: {results['time']}
🚨 سیگنال نهایی: {results['final_signal']}

📋 جزئیات هر اندیکاتور:"""
            
            for indicator_name, indicator_data in results['indicators'].items():
                status_text += f"\n\n🎯 {indicator_data['name']}:"
                status_text += f"\n   سیگنال: {indicator_data['signal']}"
                status_text += f"\n   روند: {indicator_data.get('trend', '—')}"
                
                if 'value' in indicator_data:
                    if indicator_name == 'Tren':
                        status_text += f"\n   مقدار: ${indicator_data['value']:,.2f}"
                    elif indicator_name == 'Super':
                        status_text += f"\n   مقدار: ${indicator_data['value']:,.2f}"
                    elif indicator_name == 'Nov':
                        status_text += f"\n   قیمت: ${indicator_data['value']:,.2f}"
                        status_text += f"\n   SMA بالا: ${indicator_data['sma_high']:,.2f}"
                        status_text += f"\n   SMA پایین: ${indicator_data['sma_low']:,.2f}"
            
            status_text += f"\n\n📊 سیگنال‌های فعال: {len(results['signals'])}"
            
            await query.edit_message_text(
                status_text,
                reply_markup=get_main_menu()
            )
        else:
            await query.edit_message_text(
                "❌ خطا در تحلیل!\n\nلطفاً دوباره تلاش کن یا ارز دیگری انتخاب کن.",
                reply_markup=get_main_menu()
            )
    
    elif data == "start_monitoring":
        if not current_symbol:
            await query.edit_message_text(
                "⚠️ هیچ ارزی انتخاب نشده!\n\nلطفاً اول یک ارز انتخاب کن.",
                reply_markup=get_main_menu()
            )
            return
        
        is_monitoring = True
        await query.edit_message_text(
            f"✅ مانیتورینگ شروع شد\n\n"
            f"🎯 ارز: {current_symbol}\n"
            f"📊 اندیکاتورها: Tren, Super, Nov\n"
            f"⏰ چک: هر {CHECK_INTERVAL} ثانیه\n"
            f"📈 گزارش: هر ۵ دقیقه\n\n"
            f"ربات در حال مانیتورینگ است...",
            reply_markup=get_main_menu()
        )
        
        asyncio.create_task(monitoring_task())
    
    elif data == "stop_monitoring":
        is_monitoring = False
        await query.edit_message_text(
            "⏸ مانیتورینگ متوقف شد\n\nبرای شروع مجدد، دکمه شروع را بزن.",
            reply_markup=get_main_menu()
        )
    
    elif data == "signals_report":
        if not analysis_system.signals_history:
            await query.edit_message_text(
                "📭 هیچ سیگنالی ثبت نشده\n\nپس از شروع مانیتورینگ، سیگنال‌ها اینجا نمایش داده می‌شوند.",
                reply_markup=get_main_menu()
            )
            return
        
        total = len(analysis_system.signals_history)
        buy_signals = [s for s in analysis_system.signals_history if 'خرید' in s.get('final_signal', '')]
        sell_signals = [s for s in analysis_system.signals_history if 'فروش' in s.get('final_signal', '')]
        
        report_text = f"""📈 گزارش سیگنال‌های اندیکاتورها

📊 آمار کلی:
• کل سیگنال‌ها: {total}
• سیگنال خرید: {len(buy_signals)}
• سیگنال فروش: {len(sell_signals)}

🎯 ارز فعلی: {current_symbol or 'ندارد'}
🔄 مانیتورینگ: {'فعال ✅' if is_monitoring else 'غیرفعال ⏸'}

📋 آخرین سیگنال‌ها:"""
        
        for i, signal in enumerate(analysis_system.signals_history[-5:], 1):
            report_text += f"\n{i}. {signal.get('time', '')} - {signal.get('symbol', '')}"
            report_text += f" - {signal.get('final_signal', '')}"
            if 'price' in signal:
                report_text += f" (${signal['price']:,.2f})"
        
        await query.edit_message_text(
            report_text,
            reply_markup=get_main_menu()
        )
    
    elif data == "help":
        help_text = """📚 راهنمای ربات اندیکاتورها

🎯 Tren:
• روند اصلی را تشخیص می‌دهد
• از دو سوپر ترکیبی استفاده می‌کند
• سیگنال‌های قوی در تغییر روند

📈 Super:
• تأیید‌کننده سیگنال‌ها
• بر اساس ATR و میانگین‌ها
• فیلتر نویزهای بازار

⚡ No:
• تشخیص شکست‌های قیمتی
• ترکیب EMA با ATR
• سیگنال‌های ورود/خروج

🔗 منطق ترکیبی:
سیگنال قوی فقط زمانی صادر می‌شود که حداقل ۲ اندیکاتور هم‌جهت باشند.

⏰ تنظیم خودکار:
ربات به طور خودکار سرعت چک کردن را بر اساس کیفیت اتصال تنظیم می‌کند."""
        
        await query.edit_message_text(
            help_text,
            reply_markup=get_main_menu()
        )
    
    elif data == "back_to_main":
        await query.edit_message_text(
            "🤖 منوی اصلی\n\nلطفاً یک گزینه انتخاب کن:",
            reply_markup=get_main_menu()
        )
    
    elif data.startswith("crypto_"):
        symbol = data.replace("crypto_", "")
        current_symbol = symbol
        
        crypto_name = next((name for name, sym in CRYPTO_PAIRS.items() if sym == symbol), symbol)
        
        await query.edit_message_text(
            f"✅ ارز انتخاب شد: {crypto_name}\n\n"
            f"📊 نماد: {symbol}\n"
            f"📈 اندیکاتورها: Tren, Super, No\n"
            f"🕐 زمان: {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"حالا می‌تونی:\n"
            f"• 📊 وضعیت اندیکاتورها را ببینی\n"
            f"• ▶️ مانیتورینگ را شروع کنی",
            reply_markup=get_main_menu()
        )

# ==================== تابع اصلی ====================
def main():
    """شروع ربات"""
    print("=" * 60)
    print("🤖 ربات با اندیکاتورهای دقیق")
    print("📊 Tren + Super + Nov")
    print("🔗 قابلیت: تلاش مجدد و تنظیم خودکار")
    print(f"🔑 چت آیدی: {CHAT_ID}")
    print("=" * 60)
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ ربات آماده است!")
    print("📱 به تلگرام برو و /start را بفرست")
    print("=" * 60)
    
    app.run_polling()

if __name__ == '__main__':

    main()



