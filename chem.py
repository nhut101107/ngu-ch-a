# -*- coding: utf-8 -*-

# === Import Thư viện ===
import telebot
import json
import logging
import os
import random
import time
import threading # Cần cho /thongbao và xóa tin nhắn delay
import subprocess # <<< CẦN THIẾT CHO LỆNH SPAM >>>
import sqlite3
import requests # Cần cho các API (/thoitiet, /phim, /rutgon)
import qrcode   # Cần cho lệnh /qr
from io import BytesIO # Cần cho lệnh /qr
from datetime import datetime, timedelta, date # Cần cho /time, /plan, /diemdanh
from pathlib import Path
from threading import Lock
import html # Dùng để escape HTML entities

# === Cấu hình ===
# --- Bắt buộc thay đổi ---
BOT_TOKEN = "7352828711:AAEM-kWD-A8PXrjpYKLbHAn-MRVXKMzzmK0"             # !!! THAY TOKEN BOT CỦA BẠN !!!
ADMIN_ID = 5992662564                          # !!! THAY ID TELEGRAM ADMIN CỦA BẠN !!!
ADMIN_USERNAME = "mnhutdznecon"          # !!! THAY USERNAME ADMIN (không có @) !!!
WEATHER_API_KEY = "a40c3955762a3e2ccbd83c25ece1cf5c" # !!! THAY API KEY THỜI TIẾT !!!
TMDB_API_KEY = "2a551c919f8c5fe445096179fc184ac3"            # !!! THAY API KEY CỦA TMDb !!!

# --- Đường dẫn file ---
BASE_DIR = Path(__file__).parent
DATA_FILE_PATH = BASE_DIR / "taixiu_data_telebot.json" # File dữ liệu game (JSON)
DB_FILE_PATH = BASE_DIR / "user_vip_data.db"          # File database VIP (SQLite)
QR_CODE_IMAGE_PATH = BASE_DIR / "vietqr_payment.png"  # File ảnh QR cho /muavip (Cần tạo sẵn)

# --- Thông tin VIP & Ngân hàng ---
VIP_PRICE = "50K"
VIP_DURATION_DAYS = 30
BANK_NAME = "MB Bank"
ACCOUNT_NUMBER = "17363999999999" # Thay STK thật nếu cần
ACCOUNT_NAME = "BUI MINH NHUT"    # Thay tên TK thật nếu cần
MAX_VIP_DURATION_DAYS = 18250 # ~50 năm

# --- Cấu hình Game ---
HOUSE_EDGE_PERCENT = 5 # Tỷ lệ lợi thế nhà cái (%) cho Tài Xỉu
JACKPOT_AMOUNT = 100000000
JACKPOT_CHANCE_ONE_IN = 5000 # Tỷ lệ 1/5000 trúng Jackpot mỗi lần chơi Tài Xỉu
DELETE_DELAY = 15 # Giây
CHECKIN_REWARD = 1000000
PLAY_COOLDOWN = 2 # Giây chờ giữa các lần chơi Tài Xỉu
BAUCUA_COOLDOWN = 2 # Giây chờ giữa các lần chơi Bầu Cua
TOP_N = 10 # Số lượng người hiển thị trong /top
BAUCUA_ITEMS = ["bầu", "cua", "tôm", "cá", "gà", "nai"]
BAUCUA_ICONS = {"bầu": "🍐", "cua": "🦀", "tôm": "🦐", "cá": "🐟", "gà": "🐓", "nai": "🦌"}

# --- Cấu hình Spam SMS (Nếu dùng - Cần script ngoài) ---
SPAM_SCRIPT_NAME = "smsv1.py" # Tên file script spam nếu có
SPAM_FREE_COOLDOWN = 50 # Giây chờ giữa các lần spam FREE (Cho lệnh /spam)
SPAM_FREE_MAX_COUNT = 5 # Số lần spam tối đa mỗi lệnh cho FREE (/spam)
SPAM_VIP_MAX_COUNT = 30 # Số lần spam tối đa mỗi lệnh cho VIP (/spamvip)
BLACKLISTED_NUMBERS = {"112", "113", "114", "115", "119", "911"} # Các số bị cấm spam
SPAM_TIMEOUT = 60 # Giây chờ tối đa cho script spam chạy

# === Logging ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# === Quản lý dữ liệu & Trạng thái ===
data_lock = Lock()
start_time = datetime.now() # <<< Ghi lại thời điểm bot bắt đầu chạy cho lệnh /time
last_command_time = {} # Lưu thời gian dùng lệnh cuối cùng của user {user_id: {command_name: timestamp}}
allowed_vip_users = set() # Set chứa user_id của VIP đang hoạt động
maintenance_mode = False
MAINTENANCE_MESSAGE = "🛠️ Bot đang bảo trì để nâng cấp. Vui lòng thử lại sau ít phút!"

# === Các hàm tiện ích ===
# ... (giữ nguyên các hàm tiện ích: format_xu, get_user_info_from_message, get_user_profile_info) ...
def format_xu(amount: int | float) -> str:
    """Định dạng số tiền thành chuỗi có dấu chấm."""
    try:
        if isinstance(amount, float) and amount.is_integer(): amount = int(amount)
        if isinstance(amount, float): amount = round(amount)
        return f"{amount:,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return str(amount)

def get_user_info_from_message(message: telebot.types.Message) -> tuple[int, str]:
    """Lấy user_id và tên hiển thị an toàn từ message."""
    user = message.from_user
    user_id = user.id
    user_name = user.username or f"{user.first_name} {user.last_name or ''}".strip() or f"User_{user_id}"
    safe_user_name = html.escape(user_name)
    return user_id, safe_user_name

# --- Hàm helper lấy thông tin user (cho /info) ---
def get_user_profile_info(user_id: int) -> str:
    """Lấy và định dạng thông tin người dùng từ user_id."""
    try:
        chat = bot.get_chat(user_id)
        uid = chat.id
        fname = html.escape(chat.first_name or "")
        lname = html.escape(chat.last_name or "")
        full_name = f"{fname} {lname}".strip()
        uname = chat.username
        safe_bio = "Không thể lấy hoặc không có."
        try:
             maybe_bio = getattr(chat, 'bio', None)
             if maybe_bio:
                 safe_bio = html.escape(maybe_bio)
        except Exception: pass

        mention_link = f"<a href='tg://user?id={uid}'>{full_name or 'Không tên'}</a>"
        info_lines = [
            "👤 <b>Thông tin người dùng</b> 👤",
            "--------------------------",
            f"🆔 ID: <code>{uid}</code>",
            f"📝 Tên: {mention_link}",
            f"🔗 Username: @{uname}" if uname else "🔗 Username: Không có",
            f"📜 Bio: {safe_bio}"
        ]
        return "\n".join(info_lines)
    except telebot.apihelper.ApiTelegramException as e:
        error_msg = str(e).lower()
        logger.warning(f"Lỗi API khi lấy thông tin user {user_id}: {e}")
        if "chat not found" in error_msg or "user not found" in error_msg:
            return f"❌ Không tìm thấy người dùng với ID <code>{user_id}</code>."
        elif "bot can't initiate conversation" in error_msg:
             return f"❌ Tôi không thể bắt đầu trò chuyện với người dùng ID <code>{user_id}</code>."
        else:
            return f"❌ Lỗi API Telegram: {html.escape(str(e))}"
    except Exception as e:
        logger.error(f"Lỗi không xác định khi lấy thông tin user {user_id}: {e}", exc_info=True)
        return f"❌ Lỗi không mong muốn khi lấy thông tin ID <code>{user_id}</code>."


# === Database Setup (SQLite cho VIP Users) ===
# ... (giữ nguyên các hàm DB: initialize_vip_database, load_vip_users_from_db, save_vip_user_to_db, delete_vip_user_from_db, get_vip_expiration_time_from_db) ...
def initialize_vip_database():
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS vip_users (
                            user_id INTEGER PRIMARY KEY,
                            expiration_time TEXT NOT NULL
                          )''')
        conn.commit(); conn.close()
        logger.info(f"Đã khởi tạo/kết nối database VIP: {DB_FILE_PATH}")
    except Exception as e: logger.error(f"Lỗi khởi tạo database VIP: {e}", exc_info=True)

def load_vip_users_from_db():
    global allowed_vip_users
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False); conn.row_factory = sqlite3.Row
        cursor = conn.cursor(); cursor.execute('SELECT user_id, expiration_time FROM vip_users'); rows = cursor.fetchall(); conn.close()
        current_time = datetime.now(); valid_vips = set(); expired_vips_to_delete = []
        for row in rows:
            user_id = row['user_id']; exp_time_str = row['expiration_time']
            try:
                exp_time = datetime.fromisoformat(exp_time_str)
                if exp_time > current_time: valid_vips.add(user_id)
                else: expired_vips_to_delete.append(user_id)
            except (ValueError, TypeError): logger.warning(f"DB VIP: Format time lỗi user {user_id}: {exp_time_str}")
        allowed_vip_users = valid_vips; logger.info(f"Đã load {len(allowed_vip_users)} VIP users hợp lệ.")
        if expired_vips_to_delete:
            logger.info(f"Đang xóa {len(expired_vips_to_delete)} VIP users hết hạn...")
            conn_del = sqlite3.connect(DB_FILE_PATH, check_same_thread=False); cursor_del = conn_del.cursor()
            cursor_del.executemany("DELETE FROM vip_users WHERE user_id = ?", [(uid,) for uid in expired_vips_to_delete])
            conn_del.commit(); conn_del.close(); logger.info(f"Đã xóa {len(expired_vips_to_delete)} VIP users hết hạn.")
    except Exception as e: logger.error(f"Lỗi load VIP users: {e}", exc_info=True); allowed_vip_users = set()

def save_vip_user_to_db(user_id: int, duration_days: int) -> tuple[bool, datetime | str]:
    if not (0 < duration_days <= MAX_VIP_DURATION_DAYS): return False, f"Số ngày VIP phải từ 1 đến {MAX_VIP_DURATION_DAYS}."
    try:
        current_expiration = get_vip_expiration_time_from_db(user_id); start_date = datetime.now()
        if current_expiration and current_expiration > start_date: start_date = current_expiration
        expiration_time = start_date + timedelta(days=duration_days)
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False); cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO vip_users (user_id, expiration_time) VALUES (?, ?)', (user_id, expiration_time.isoformat()))
        conn.commit(); conn.close(); logger.info(f"Lưu/Update VIP user {user_id}, hết hạn {expiration_time.isoformat()}")
        load_vip_users_from_db(); return True, expiration_time
    except OverflowError: logger.error(f"Lỗi tràn số khi tính ngày hết hạn VIP cho user {user_id}, {duration_days} ngày."); return False, "Lỗi tràn số (thời gian quá xa)."
    except Exception as e: logger.error(f"Lỗi lưu VIP user {user_id}: {e}", exc_info=True); return False, f"Lỗi DB: {e}"

def delete_vip_user_from_db(target_user_id: int) -> bool:
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False); cursor = conn.cursor()
        cursor.execute("DELETE FROM vip_users WHERE user_id = ?", (target_user_id,)); conn.commit()
        deleted_rows = cursor.rowcount; conn.close()
        if deleted_rows > 0: logger.info(f"Đã xóa VIP user {target_user_id}."); allowed_vip_users.discard(target_user_id); return True
        return False
    except Exception as e: logger.error(f"Lỗi xóa VIP user {target_user_id}: {e}", exc_info=True); return False

def get_vip_expiration_time_from_db(user_id: int) -> datetime | None:
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False); cursor = conn.cursor()
        cursor.execute("SELECT expiration_time FROM vip_users WHERE user_id = ?", (user_id,)); result = cursor.fetchone(); conn.close()
        if result:
            try: return datetime.fromisoformat(result[0])
            except (ValueError, TypeError): logger.warning(f"DB VIP: Format time lỗi khi đọc user {user_id}: {result[0]}"); return None
        return None
    except Exception as e: logger.error(f"Lỗi query hạn VIP user {user_id}: {e}", exc_info=True); return None

# === Các hàm load/save/get data game (JSON) ===
# ... (giữ nguyên: load_game_data_sync, save_game_data_sync, get_player_data) ...
def load_game_data_sync() -> dict:
    with data_lock:
        try:
            if DATA_FILE_PATH.exists() and DATA_FILE_PATH.stat().st_size > 0:
                with open(DATA_FILE_PATH, "r", encoding="utf-8") as f: return json.load(f)
            logger.warning(f"File data game {DATA_FILE_PATH} trống hoặc không tồn tại. Tạo mới."); return {}
        except json.JSONDecodeError: logger.error(f"Lỗi giải mã JSON trong file {DATA_FILE_PATH}. Trả về dữ liệu trống.", exc_info=True); return {}
        except Exception as e: logger.error(f"Lỗi đọc file {DATA_FILE_PATH}: {e}. Trả về dữ liệu trống.", exc_info=True); return {}

def save_game_data_sync(data: dict):
    with data_lock:
        temp_file_path = DATA_FILE_PATH.with_suffix(".json.tmp")
        try:
            with open(temp_file_path, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(temp_file_path, DATA_FILE_PATH)
        except Exception as e:
            logger.error(f"Lỗi nghiêm trọng khi lưu game data vào {DATA_FILE_PATH}: {e}", exc_info=True)
            if temp_file_path.exists():
                try: temp_file_path.unlink() # Cố gắng xóa file tạm nếu có lỗi
                except OSError as rm_err: logger.error(f"Không thể xóa file tạm {temp_file_path} sau lỗi lưu: {rm_err}")

def get_player_data(user_id: int, user_name: str, data: dict) -> dict:
    """Lấy hoặc tạo dữ liệu người chơi trong dictionary data."""
    uid = str(user_id) # JSON keys phải là string
    safe_user_name = user_name # Tên đã được escape từ get_user_info_from_message
    player_info = data.get(uid)

    if player_info is None:
        # Tạo mới nếu chưa có
        player_info = {
            "name": safe_user_name,
            "xu": 100000, # Số xu khởi đầu
            "plays": 0,
            "last_checkin_date": None
        }
        data[uid] = player_info
        logger.info(f"Tạo người chơi mới: ID={uid}, Tên='{safe_user_name}', Xu={player_info['xu']}")
    else:
        # Cập nhật tên nếu thay đổi và đảm bảo các key cần thiết tồn tại
        if player_info.get("name") != safe_user_name:
            logger.info(f"Cập nhật tên người chơi {uid}: '{player_info.get('name')}' -> '{safe_user_name}'")
            player_info["name"] = safe_user_name
        player_info.setdefault("xu", 0) # Đảm bảo có key 'xu', giá trị mặc định 0 nếu thiếu
        player_info.setdefault("plays", 0) # Đảm bảo có key 'plays'
        player_info.setdefault("last_checkin_date", None) # Đảm bảo có key 'last_checkin_date'

    return player_info

# === Logic Game ===
# ... (giữ nguyên: roll_dice_sync, roll_baucua_sync) ...
def roll_dice_sync() -> tuple[list[int], int, str]:
    """Tung 3 xúc xắc cho Tài Xỉu."""
    dice = [random.randint(1, 6) for _ in range(3)]; total = sum(dice)
    result = "tài" if 11 <= total <= 18 else "xỉu"; return dice, total, result

def roll_baucua_sync() -> list[str]:
    """Tung 3 'xúc xắc' Bầu Cua."""
    return random.choices(BAUCUA_ITEMS, k=3)

# === Khởi tạo Bot ===
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')
logger.info("TeleBot instance đã được tạo.")

# === Hàm xóa tin nhắn sau delay ===
# ... (giữ nguyên: delete_message_after_delay) ...
def delete_message_after_delay(chat_id: int, message_id: int, delay: int):
    """Xóa tin nhắn trong một thread riêng sau một khoảng thời gian delay."""
    def delete_task():
        try:
            time.sleep(delay)
            bot.delete_message(chat_id=chat_id, message_id=message_id)
        except telebot.apihelper.ApiTelegramException as e:
            # Bỏ qua lỗi nếu tin nhắn không tìm thấy (đã bị xóa thủ công hoặc lỗi khác)
            if "message to delete not found" in str(e).lower() or "message identifier is not specified" in str(e).lower():
                pass # Lỗi thường gặp, không cần log nhiều
            else:
                logger.warning(f"Lỗi API khi xóa tin nhắn {message_id} trong chat {chat_id}: {e}")
        except Exception as e:
            logger.warning(f"Lỗi không xác định khi xóa tin nhắn {message_id} trong chat {chat_id}: {e}")

    if delay > 0:
        thread = threading.Thread(target=delete_task, daemon=True)
        thread.start()

# === Middleware kiểm tra bảo trì ===
# ... (giữ nguyên: handle_maintenance) ...
@bot.message_handler(func=lambda message: maintenance_mode and message.from_user.id != ADMIN_ID)
def handle_maintenance(message: telebot.types.Message):
    """Chặn người dùng thường khi đang bảo trì."""
    try:
        if message.text: # Chỉ trả lời tin nhắn văn bản để tránh spam lỗi
            bot.reply_to(message, MAINTENANCE_MESSAGE)
    except Exception as e:
        logger.error(f"Lỗi gửi tin nhắn bảo trì cho user {message.from_user.id}: {e}")

# === Các lệnh ADMIN ===
# ... (giữ nguyên các lệnh admin: /add, /xoavip, /socam, /thongbao, /baotri, /hoantat, /cong) ...
@bot.message_handler(commands=['add'])
def add_vip_command(message: telebot.types.Message):
    user_id, _ = get_user_info_from_message(message)
    if user_id != ADMIN_ID: return bot.reply_to(message, "⛔ Bạn không có quyền sử dụng lệnh này!")

    args = message.text.split()
    # /add user_id [số_ngày]
    if len(args) < 2 or not args[1].isdigit():
        return bot.reply_to(message, f"❌ Sai cú pháp! Dùng: <code>/add &lt;user_id&gt; [số_ngày]</code>\n(Mặc định là {VIP_DURATION_DAYS} ngày nếu không nhập số ngày)")

    try:
        target_user_id = int(args[1])
        duration_days = VIP_DURATION_DAYS # Mặc định
        if len(args) >= 3:
            try:
                duration_days = int(args[2])
                if not (0 < duration_days <= MAX_VIP_DURATION_DAYS):
                    return bot.reply_to(message, f"⚠️ Số ngày VIP phải là một số dương và không quá {MAX_VIP_DURATION_DAYS} ngày.")
            except ValueError:
                return bot.reply_to(message, "⚠️ Số ngày VIP phải là một số nguyên hợp lệ.")

        success, result_data = save_vip_user_to_db(target_user_id, duration_days)

        if success and isinstance(result_data, datetime):
            exp_str = result_data.strftime('%Y-%m-%d %H:%M:%S')
            reply_msg = f"✅ Đã cấp/gia hạn VIP thành công <b>{duration_days}</b> ngày cho người dùng ID <code>{target_user_id}</code>.\n⏳ Ngày hết hạn mới: <b>{exp_str}</b>."
            bot.reply_to(message, reply_msg)
            # Thông báo cho người dùng được cấp VIP
            try:
                bot.send_message(target_user_id, f"🎉 Chúc mừng! Bạn đã được quản trị viên cấp/gia hạn <b>{duration_days}</b> ngày VIP.\n🗓️ VIP của bạn sẽ hết hạn vào lúc: {exp_str}")
                logger.info(f"Admin {user_id} đã cấp {duration_days} ngày VIP cho user {target_user_id}")
            except Exception as e:
                logger.warning(f"Không thể gửi tin nhắn thông báo cấp VIP cho user {target_user_id}: {e}")
                bot.reply_to(message, f"ℹ️ Đã cấp VIP thành công nhưng không thể gửi tin nhắn thông báo cho người dùng ID <code>{target_user_id}</code> (có thể do họ đã chặn bot).")
        else:
            bot.reply_to(message, f"❌ Lỗi khi thêm VIP cho ID <code>{target_user_id}</code>: {result_data}")
            logger.error(f"Admin {user_id} gặp lỗi khi thêm VIP cho {target_user_id}: {result_data}")

    except ValueError:
        bot.reply_to(message, "❌ User ID không hợp lệ. Vui lòng nhập ID dạng số.")
    except Exception as e:
        logger.error(f"Lỗi không mong muốn trong lệnh /add: {e}", exc_info=True)
        bot.reply_to(message, "❌ Đã xảy ra lỗi không mong muốn trong quá trình xử lý.")

@bot.message_handler(commands=['xoavip'])
def xoavip_command(message: telebot.types.Message):
    user_id, _ = get_user_info_from_message(message)
    if user_id != ADMIN_ID: return bot.reply_to(message, "⛔ Bạn không có quyền sử dụng lệnh này!")

    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return bot.reply_to(message, "❌ Sai cú pháp! Dùng: <code>/xoavip &lt;user_id&gt;</code>")

    try:
        target_user_id = int(args[1])
        deleted = delete_vip_user_from_db(target_user_id)

        if deleted:
            bot.reply_to(message, f"✅ Đã xóa thành công trạng thái VIP của người dùng ID <code>{target_user_id}</code>.")
            logger.info(f"Admin {user_id} đã xóa VIP của user {target_user_id}")
            # Thông báo cho người dùng bị xóa VIP
            try:
                bot.send_message(target_user_id, "ℹ️ Trạng thái VIP của bạn đã bị quản trị viên thu hồi.")
            except Exception as e:
                logger.warning(f"Không thể gửi tin nhắn thông báo thu hồi VIP cho user {target_user_id}: {e}")
        else:
            bot.reply_to(message, f"ℹ️ Không tìm thấy người dùng VIP với ID <code>{target_user_id}</code> hoặc đã có lỗi xảy ra khi xóa.")
            logger.warning(f"Admin {user_id} xóa VIP user {target_user_id} thất bại (không tìm thấy hoặc lỗi DB).")

    except ValueError:
        bot.reply_to(message, "❌ User ID không hợp lệ. Vui lòng nhập ID dạng số.")
    except Exception as e:
        logger.error(f"Lỗi không mong muốn trong lệnh /xoavip: {e}", exc_info=True)
        bot.reply_to(message, "❌ Đã xảy ra lỗi không mong muốn trong quá trình xử lý.")

@bot.message_handler(commands=['socam'])
def socam_command(message: telebot.types.Message):
    # Lưu ý: Danh sách này chỉ tồn tại trong bộ nhớ, sẽ mất khi bot khởi động lại.
    # Cần giải pháp lưu trữ lâu dài (file/DB) nếu muốn cấm vĩnh viễn.
    user_id, _ = get_user_info_from_message(message)
    if user_id != ADMIN_ID: return bot.reply_to(message, "⛔ Bạn không có quyền!")
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "❌ Syntax: <code>/socam [SĐT]</code>")
    phone_number = args[1].replace('+', '').replace(' ', '').strip()
    if not phone_number.isdigit(): return bot.reply_to(message, "❌ Số điện thoại không hợp lệ.")
    if phone_number in BLACKLISTED_NUMBERS: return bot.reply_to(message, f"ℹ️ Số <code>{phone_number}</code> đã có trong danh sách cấm tạm thời.")
    BLACKLISTED_NUMBERS.add(phone_number); logger.info(f"Admin {ADMIN_ID} thêm số {phone_number} vào blacklist tạm thời.")
    bot.reply_to(message, f"✅ Đã thêm số <code>{phone_number}</code> vào danh sách cấm tạm thời (sẽ mất khi bot restart).")

@bot.message_handler(commands=['thongbao'])
def thongbao_command(message: telebot.types.Message):
    user_id, _ = get_user_info_from_message(message)
    if user_id != ADMIN_ID: return bot.reply_to(message, "⛔ Bạn không có quyền!")

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return bot.reply_to(message, "❌ Vui lòng nhập nội dung thông báo: <code>/thongbao [Nội dung cần gửi]</code>")

    broadcast_message = args[1].strip()
    game_data = load_game_data_sync()
    user_ids_str = list(game_data.keys())

    if not user_ids_str:
        return bot.reply_to(message, "ℹ️ Không có người dùng nào trong dữ liệu để gửi thông báo.")

    total_users = len(user_ids_str)
    sent_count = 0
    failed_count = 0
    blocked_count = 0

    logger.info(f"Admin {ADMIN_ID} bắt đầu gửi thông báo đến {total_users} người dùng...")
    try:
        confirm_msg = bot.reply_to(message, f"⏳ Đang chuẩn bị gửi thông báo đến <b>{total_users}</b> người dùng...")
    except Exception as e:
        logger.error(f"Lỗi gửi tin nhắn xác nhận /thongbao: {e}")
        return # Không thể gửi xác nhận thì dừng

    def broadcast_thread_func():
        nonlocal sent_count, failed_count, blocked_count
        for user_id_str in user_ids_str:
            try:
                user_id_int = int(user_id_str)
                bot.send_message(user_id_int, broadcast_message)
                sent_count += 1
                time.sleep(0.1) # Thêm delay nhỏ để tránh rate limit API
            except ValueError:
                logger.warning(f"Bỏ qua ID không hợp lệ trong dữ liệu: {user_id_str}")
                failed_count += 1
            except telebot.apihelper.ApiTelegramException as e:
                error_str = str(e).lower()
                if "forbidden: bot was blocked by the user" in error_str:
                    blocked_count += 1
                    logger.info(f"Người dùng {user_id_str} đã chặn bot.")
                elif "chat not found" in error_str:
                    blocked_count += 1
                    logger.warning(f"Không tìm thấy chat của người dùng {user_id_str} (có thể đã xóa tài khoản).")
                # Có thể thêm các điều kiện lỗi khác ở đây
                else:
                    logger.warning(f"Lỗi API Telegram khi gửi thông báo đến {user_id_str}: {e}")
                    failed_count += 1
                time.sleep(0.5) # Delay lớn hơn nếu gặp lỗi API
            except Exception as e:
                logger.error(f"Lỗi không xác định khi gửi thông báo đến {user_id_str}: {e}", exc_info=True)
                failed_count += 1
                time.sleep(0.5)

        # Kết thúc vòng lặp, gửi kết quả
        result_text = (
            f"✅ <b>Thông báo hoàn tất!</b>\n"
            f"--------------------------\n"
            f"✔️ Gửi thành công: <b>{sent_count}</b>\n"
            f"❌ Gửi thất bại: <b>{failed_count}</b>\n"
            f"🚫 Bị chặn/Không tìm thấy: <b>{blocked_count}</b>"
        )
        try:
            # Sửa tin nhắn xác nhận ban đầu
            bot.edit_message_text(result_text, chat_id=confirm_msg.chat.id, message_id=confirm_msg.message_id)
        except Exception as edit_e:
            logger.error(f"Lỗi không thể sửa tin nhắn kết quả thông báo: {edit_e}")
            # Gửi tin nhắn mới nếu không sửa được
            bot.send_message(ADMIN_ID, result_text)

    # Chạy hàm gửi trong một thread riêng để không block bot chính
    broadcast_thread = threading.Thread(target=broadcast_thread_func, daemon=True)
    broadcast_thread.start()

@bot.message_handler(commands=['baotri'])
def baotri_command(message: telebot.types.Message):
    global maintenance_mode
    user_id, _ = get_user_info_from_message(message)
    if user_id != ADMIN_ID: return bot.reply_to(message, "⛔ Bạn không có quyền!")
    maintenance_mode = True
    logger.info(f"Admin {ADMIN_ID} đã BẬT chế độ bảo trì.")
    bot.reply_to(message, "✅ Đã bật chế độ bảo trì. Chỉ Admin mới có thể dùng lệnh.")

@bot.message_handler(commands=['hoantat'])
def hoantat_command(message: telebot.types.Message):
    global maintenance_mode
    user_id, _ = get_user_info_from_message(message)
    if user_id != ADMIN_ID: return bot.reply_to(message, "⛔ Bạn không có quyền!")
    maintenance_mode = False
    logger.info(f"Admin {ADMIN_ID} đã TẮT chế độ bảo trì.")
    bot.reply_to(message, "✅ Đã tắt chế độ bảo trì. Bot hoạt động bình thường.")

@bot.message_handler(commands=['cong'])
def cong_command(message: telebot.types.Message):
    user_id, _ = get_user_info_from_message(message)
    if user_id != ADMIN_ID: return bot.reply_to(message, "⛔ Bạn không có quyền!")

    args = message.text.split()
    target_user_id = None
    amount = None

    # /cong user_id amount
    if len(args) == 3:
        try:
            target_user_id = int(args[1])
            amount_str = args[2].replace('.', '').replace(',', '') # Xóa dấu chấm, phẩy
            amount = int(amount_str)
            if amount <= 0:
                return bot.reply_to(message, "❌ Số xu cộng phải là số dương.")
        except ValueError:
            return bot.reply_to(message, "❌ Sai cú pháp hoặc số không hợp lệ.\nDùng: <code>/cong [user_id] [số_xu]</code>")
    else:
        return bot.reply_to(message, "❌ Sai cú pháp! Dùng: <code>/cong [user_id] [số_xu]</code>")

    game_data = load_game_data_sync()
    # Lấy tên để hiển thị, nếu chưa có thì dùng tên mặc định
    target_name_temp = game_data.get(str(target_user_id), {}).get("name", f"User_{target_user_id}")
    target_player = get_player_data(target_user_id, target_name_temp, game_data) # Hàm này cũng tạo user nếu chưa có

    target_player["xu"] += amount
    save_game_data_sync(game_data) # Lưu lại dữ liệu sau khi thay đổi

    logger.info(f"Admin {user_id} đã cộng {format_xu(amount)} xu cho {target_player['name']}(ID:{target_user_id}). Số dư mới: {format_xu(target_player['xu'])}")
    bot.reply_to(message, f"✅ Đã cộng thành công <b>{format_xu(amount)}</b> xu cho người dùng {target_player['name']} (ID: <code>{target_user_id}</code>).\n💰 Số dư mới của họ: <b>{format_xu(target_player['xu'])}</b> xu.")


# === Các lệnh Người dùng ===

# --- Cập nhật lệnh /start, /help ---
@bot.message_handler(commands=['start', 'help'])
def start_help_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    # Đảm bảo người dùng có trong dữ liệu khi họ /start
    game_data = load_game_data_sync()
    player_data = get_player_data(user_id, user_name, game_data)
    save_game_data_sync(game_data) # Lưu nếu user mới được tạo

    is_admin = user_id == ADMIN_ID
    is_vip = user_id in allowed_vip_users

    help_text = f"""
👋 Chào {user_name}! Số dư của bạn: 💰 <b>{format_xu(player_data['xu'])}</b> xu.
"""
    if is_vip:
        exp_time = get_vip_expiration_time_from_db(user_id)
        if exp_time:
            help_text += f"💎 Bạn là thành viên <b>VIP</b> (Hết hạn: {exp_time.strftime('%d/%m/%Y %H:%M')})\n"
    help_text += "\n📖 <b>Lệnh Người Dùng Thường:</b>"
    help_text += """
├─ /help - Xem lệnh
├─ /muavip - 💎 Hướng dẫn mua/gia hạn VIP 
├─ /plan - 📅 Kiểm tra thời hạn VIP của bạn
├─ /diemdanh - 🎁 Nhận xu miễn phí mỗi ngày
├─ /check - 💰 Xem số dư xu hiện tại
├─ /play <code>[tài|xỉu] [số_xu|all]</code> - 🎲 Chơi game Tài Xỉu
├─ /baucua <code>[vật] [số_xu|all|10k|1m]</code> - 🦀 Chơi game Bầu Cua 
├─ /top - 🏆 Xem bảng xếp hạng người chơi giàu nhất
├─ /time - ⏱️ Xem thời gian bot đã hoạt động
├─ /info <code>[reply tin nhắn / ID người dùng]</code> - 👤 Xem thông tin cơ bản của người dùng Telegram
├─ /qr <code>[Nội dung cần tạo QR]</code> - 🧐 Tạo mã QR từ văn bản
├─ /rutgon <code>[Link URL cần rút gọn]</code> - 🔗 Rút gọn link URL dài
├─ /thoitiet <code>[Tên thành phố/địa điểm]</code> - 🌦️ Xem thông tin thời tiết
├─ /phim <code>[Tên phim cần tìm]</code> - 🎬 Tìm thông tin chi tiết về phim
├─ /spam <code>[SĐT] [Số lượng]</code> - 📱 Gửi SMS free nên max 5 lần với mỗi lần gửi lệnh là 50s
├─ /admin - 🧑‍💼 Liên hệ với quản trị viên 
"""
    # Thêm lệnh VIP nếu người dùng là VIP
    if is_vip:
        vip_commands_text = f"""
💎 <b>Lệnh Dành Riêng Cho VIP:</b>
└─ /spamvip <code>[SĐT] [Số lượng]</code> - 📱 Gửi SMS 
"""
        help_text += vip_commands_text

    # Thêm lệnh Admin nếu người dùng là Admin
    if is_admin:
        admin_commands_text = f"""
🔒 <b>Lệnh Dành Riêng Cho Admin:</b>
├─ /add <code>[id] [ngày]</code> - Thêm hoặc gia hạn VIP cho người dùng
├─ /xoavip <code>[id]</code> - Xóa trạng thái VIP của người dùng
├─ /cong <code>[id] [xu]</code> - Cộng xu vào tài khoản người dùng
├─ /thongbao <code>[nội dung]</code> - Gửi thông báo đến tất cả người dùng
├─ /socam <code>[SĐT]</code> - Thêm SĐT vào danh sách đen tạm thời (cho lệnh spam)
├─ /baotri - 🛠️ Bật chế độ bảo trì (chỉ admin dùng được bot)
└─ /hoantat - ✅ Tắt chế độ bảo trì
"""
        help_text += admin_commands_text

    help_text += f"\nChúc bạn sử dụng bot vui vẻ!"
    bot.reply_to(message, help_text, disable_web_page_preview=True)

# ... (giữ nguyên các lệnh người dùng khác: /top, /info, /muavip, /plan, /check, /diemdanh, /time, /play, /baucua, /qr, /rutgon, /thoitiet, /phim, /admin) ...
@bot.message_handler(commands=['top'])
def top_command(message: telebot.types.Message):
    """Hiển thị bảng xếp hạng người chơi theo số xu."""
    user_id, user_name = get_user_info_from_message(message)
    logger.info(f"User {user_id} ({user_name}) yêu cầu xem /top.")

    game_data = load_game_data_sync()
    if not game_data:
        return bot.reply_to(message, "ℹ️ Hiện tại chưa có dữ liệu người chơi nào để xếp hạng.")

    player_list = []
    for uid_str, p_data in game_data.items():
        # Chỉ thêm vào danh sách nếu có đủ thông tin 'xu' và 'name'
        if isinstance(p_data, dict) and "xu" in p_data and "name" in p_data:
             player_list.append({
                 "id": uid_str, # Giữ ID dạng string như trong dict gốc
                 "name": p_data["name"], # Tên đã được escape sẵn
                 "xu": p_data.get("xu", 0) # Lấy xu, mặc định là 0 nếu thiếu
             })
        else:
            logger.warning(f"Dữ liệu người chơi không hợp lệ trong /top cho ID {uid_str}: {p_data}")


    if not player_list:
        return bot.reply_to(message, "ℹ️ Không tìm thấy người chơi hợp lệ nào trong dữ liệu.")

    # Sắp xếp người chơi theo số xu giảm dần
    # Dùng lambda function để chỉ định sắp xếp theo key 'xu'
    sorted_players = sorted(player_list, key=lambda p: p["xu"], reverse=True)

    # Lấy top N người chơi đầu tiên
    top_players = sorted_players[:TOP_N]

    # Tạo tin nhắn hiển thị bảng xếp hạng
    reply_lines = [f"🏆 <b>BẢNG XẾP HẠNG TOP {len(top_players)} ĐẠI GIA</b> 🏆", "--------------------------"]
    ranks_emojis = ["🥇", "🥈", "🥉"] # Emoji cho top 3

    for rank, player in enumerate(top_players, 1): # Bắt đầu rank từ 1
        rank_icon = ranks_emojis[rank-1] if rank <= len(ranks_emojis) else "🏅" # Icon top 3 hoặc icon thường
        safe_name = player["name"] # Tên đã được escape khi lưu
        formatted_xu = format_xu(player["xu"])
        reply_lines.append(f"{rank_icon} {rank}. {safe_name} - 💰 <b>{formatted_xu}</b> xu")

    reply_text = "\n".join(reply_lines)
    bot.reply_to(message, reply_text)

@bot.message_handler(commands=['info'])
def info_command(message: telebot.types.Message):
    user_id_to_check = None
    args = message.text.split()
    requesting_user_id = message.from_user.id

    # Trường hợp 1: Reply tin nhắn của người khác
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        user_id_to_check = target_user.id
        logger.info(f"User {requesting_user_id} yêu cầu /info của user {target_user.id} (thông qua reply).")
    # Trường hợp 2: Cung cấp ID người dùng
    elif len(args) > 1:
        try:
            user_id_to_check = int(args[1])
            logger.info(f"User {requesting_user_id} yêu cầu /info cho ID: {user_id_to_check}.")
        except ValueError:
            return bot.reply_to(message, "❌ ID người dùng không hợp lệ. Vui lòng nhập ID dạng số hoặc reply tin nhắn.")
    # Trường hợp 3: Không có reply, không có ID -> lấy thông tin bản thân
    else:
        user_id_to_check = message.from_user.id
        logger.info(f"User {requesting_user_id} yêu cầu /info của chính mình.")

    if user_id_to_check:
        info_text = get_user_profile_info(user_id_to_check)
        bot.reply_to(message, info_text, disable_web_page_preview=True)
    else:
        # Trường hợp này không nên xảy ra nếu logic trên đúng
        bot.reply_to(message, "❌ Không thể xác định người dùng cần xem thông tin.")

@bot.message_handler(commands=['muavip'])
def muavip_telebot_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    # Tạo nội dung chuyển khoản duy nhất cho người dùng
    transfer_content = f"NAP VIP {user_id}"

    caption_text = f"""
💎 <b>Đăng Ký / Gia Hạn VIP</b> 💎
--------------------------
👤 Người dùng: <b>{user_name}</b> (ID: <code>{user_id}</code>)
✨ Quyền lợi VIP: (Ví dụ: Chơi game không giới hạn cooldown, truy cập lệnh đặc biệt,...)
💰 Phí dịch vụ: <b>{VIP_PRICE} / {VIP_DURATION_DAYS} ngày</b>
--------------------------
💳 <b>Thông Tin Thanh Toán:</b>
🏦 Ngân hàng: <b>{BANK_NAME}</b>
🔢 Số tài khoản: <code>{ACCOUNT_NUMBER}</code>
✍️ Tên chủ tài khoản: <b>{ACCOUNT_NAME}</b>
💬 Nội dung chuyển khoản: <code>{transfer_content}</code> (<b>QUAN TRỌNG - GHI ĐÚNG NỘI DUNG NÀY</b>)
--------------------------
⚠️ <b>Lưu ý quan trọng:</b>
1️⃣ Chuyển khoản chính xác số tiền và nội dung yêu cầu.
2️⃣ Sau khi chuyển khoản thành công, chụp lại biên lai giao dịch.
3️⃣ Nhấn nút 'Liên Hệ Admin' bên dưới và gửi biên lai kèm theo ID <code>{user_id}</code> của bạn để Admin xác nhận và kích hoạt VIP.
❓ Nếu có bất kỳ thắc mắc nào, vui lòng nhấn nút 'Liên Hệ Admin'.
"""
    # Tạo nút bấm Inline
    markup = telebot.types.InlineKeyboardMarkup()
    btn_contact = telebot.types.InlineKeyboardButton(text="👉 Liên Hệ Admin Xác Nhận", url=f"https://t.me/{ADMIN_USERNAME}")
    markup.add(btn_contact)

    try:
        # Kiểm tra xem file QR có tồn tại không
        if not QR_CODE_IMAGE_PATH.exists():
            logger.error(f"Lỗi lệnh /muavip: Không tìm thấy file ảnh QR tại {QR_CODE_IMAGE_PATH}")
            return bot.reply_to(message, f"❌ Lỗi hệ thống: Không tìm thấy mã QR thanh toán. Vui lòng liên hệ Admin (@{ADMIN_USERNAME}) để được hỗ trợ.")

        # Gửi ảnh QR kèm caption và nút bấm
        with open(QR_CODE_IMAGE_PATH, 'rb') as qr_photo:
            bot.send_photo(
                message.chat.id,
                photo=qr_photo,
                caption=caption_text,
                reply_markup=markup,
                reply_to_message_id=message.message_id # Trả lời tin nhắn gốc của người dùng
            )
        logger.info(f"User {user_id} ({user_name}) đã yêu cầu xem thông tin /muavip.")
    except FileNotFoundError:
         logger.error(f"Lỗi FileNotFoundError khi gửi /muavip: Không tìm thấy file {QR_CODE_IMAGE_PATH}")
         bot.reply_to(message, f"❌ Lỗi hệ thống: Không tìm thấy file QR. Vui lòng liên hệ Admin.")
    except Exception as e:
        logger.error(f"Lỗi không mong muốn trong lệnh /muavip: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Đã xảy ra lỗi khi gửi thông tin mua VIP. Vui lòng thử lại hoặc liên hệ Admin (@{ADMIN_USERNAME}).")

@bot.message_handler(commands=['plan'])
def plan_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    expiration_time = get_vip_expiration_time_from_db(user_id)
    now = datetime.now()

    if expiration_time and expiration_time > now:
        # VIP còn hạn
        remaining_time = expiration_time - now
        days = remaining_time.days
        seconds = remaining_time.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        parts = []
        if days > 0: parts.append(f"{days} ngày")
        if hours > 0: parts.append(f"{hours} giờ")
        if minutes > 0: parts.append(f"{minutes} phút")
        # Nếu còn dưới 1 phút thì hiển thị giây
        if not parts and seconds > 0 : parts.append(f"{seconds} giây")
        # Nếu hết hạn trong tích tắc (rất hiếm)
        if not parts: time_str = "sắp hết hạn"
        else: time_str = ", ".join(parts)

        exp_str_formatted = expiration_time.strftime('%H:%M:%S ngày %d/%m/%Y')
        reply_text = (
            f"👑 {user_name}, bạn đang là thành viên <b>VIP</b>.\n"
            f"🗓️ Thời gian còn lại: <b>~{time_str}</b>\n"
            f"⏳ Hết hạn vào lúc: {exp_str_formatted}"
        )
        bot.reply_to(message, reply_text)
        logger.info(f"User {user_id} ({user_name}) kiểm tra /plan: Còn hạn VIP đến {exp_str_formatted}")

    elif expiration_time and expiration_time <= now:
        # VIP đã hết hạn
        exp_str_formatted = expiration_time.strftime('%d/%m/%Y')
        reply_text = f"😥 {user_name}, gói VIP của bạn đã hết hạn vào ngày {exp_str_formatted}. Hãy dùng lệnh /muavip để gia hạn nhé!"
        bot.reply_to(message, reply_text)
        logger.info(f"User {user_id} ({user_name}) kiểm tra /plan: VIP đã hết hạn vào {exp_str_formatted}.")
    else:
        # Chưa từng là VIP hoặc đã bị xóa
        reply_text = f"ℹ️ {user_name}, bạn hiện chưa phải là thành viên VIP. Sử dụng lệnh /muavip để xem hướng dẫn đăng ký."
        bot.reply_to(message, reply_text)
        logger.info(f"User {user_id} ({user_name}) kiểm tra /plan: Chưa phải là VIP.")

@bot.message_handler(commands=['check'])
def check_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    game_data = load_game_data_sync()
    player_data = get_player_data(user_id, user_name, game_data)
    # Không cần save lại vì get_player_data chỉ đọc hoặc tạo nếu chưa có
    bot.reply_to(message, f"💰 {user_name}, số dư hiện tại của bạn là: <b>{format_xu(player_data['xu'])}</b> xu.")

@bot.message_handler(commands=['diemdanh'])
def diemdanh_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    today_str = date.today().isoformat() # Lấy ngày hiện tại dưới dạng 'YYYY-MM-DD'
    game_data = load_game_data_sync()
    player_data = get_player_data(user_id, user_name, game_data)

    # Kiểm tra xem đã điểm danh hôm nay chưa
    if player_data.get("last_checkin_date") == today_str:
        return bot.reply_to(message, f"🗓️ {user_name}, bạn đã điểm danh ngày hôm nay rồi. Hãy quay lại vào ngày mai nhé!")

    # Chưa điểm danh -> Cộng thưởng và cập nhật ngày
    player_data["xu"] += CHECKIN_REWARD
    player_data["last_checkin_date"] = today_str
    save_game_data_sync(game_data) # Lưu lại dữ liệu

    logger.info(f"User {user_id} ({user_name}) thực hiện /diemdanh (+{CHECKIN_REWARD}). Ngày: {today_str}")
    bot.reply_to(message, f"✅ Điểm danh ngày {date.today().strftime('%d/%m/%Y')} thành công!\n🎁 Bạn nhận được <b>{format_xu(CHECKIN_REWARD)}</b> xu.\n💰 Số dư mới: <b>{format_xu(player_data['xu'])}</b> xu.")

@bot.message_handler(commands=['time'])
def time_command(message: telebot.types.Message):
    now = datetime.now()
    uptime_delta = now - start_time # start_time được ghi lại khi bot khởi động
    total_seconds = int(uptime_delta.total_seconds())

    days = total_seconds // (24 * 3600)
    seconds_remaining = total_seconds % (24 * 3600)
    hours = seconds_remaining // 3600
    seconds_remaining %= 3600
    minutes = seconds_remaining // 60
    seconds = seconds_remaining % 60

    uptime_parts = []
    if days > 0: uptime_parts.append(f"{days} ngày")
    if hours > 0: uptime_parts.append(f"{hours} giờ")
    if minutes > 0: uptime_parts.append(f"{minutes} phút")
    if seconds > 0 or not uptime_parts: uptime_parts.append(f"{seconds} giây") # Hiển thị giây nếu uptime < 1 phút

    uptime_str = ", ".join(uptime_parts)
    bot.reply_to(message, f"⏱️ Bot đã hoạt động được: <b>{uptime_str}</b>.");
    logger.info(f"User {message.from_user.id} ({get_user_info_from_message(message)[1]}) yêu cầu /time.")

@bot.message_handler(commands=['play'])
def play_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    args = message.text.split()[1:] # Lấy các đối số sau /play

    # --- Kiểm tra cú pháp ---
    if len(args) != 2:
        return bot.reply_to(message, "❌ Sai cú pháp! Ví dụ:\n<code>/play tài 10000</code>\n<code>/play xỉu all</code>")

    choice = args[0].lower() # tài hoặc xỉu
    bet_input = args[1].lower() # số tiền hoặc 'all'

    if choice not in ["tài", "xỉu"]:
        return bot.reply_to(message, "❌ Lựa chọn không hợp lệ. Vui lòng chọn <b>tài</b> hoặc <b>xỉu</b>.")

    # --- Kiểm tra Cooldown ---
    command_name = 'play'
    current_time = time.time()
    user_last_cmd_times = last_command_time.setdefault(user_id, {}) # Lấy dict thời gian của user, tạo mới nếu chưa có
    last_play_time = user_last_cmd_times.get(command_name, 0) # Lấy thời gian chơi lần cuối, mặc định 0

    if current_time - last_play_time < PLAY_COOLDOWN:
        wait_time = round(PLAY_COOLDOWN - (current_time - last_play_time), 1)
        msg_wait = bot.reply_to(message, f"⏳ Chơi quá nhanh! Vui lòng chờ <b>{wait_time} giây</b> nữa.")
        # Tự động xóa tin nhắn chờ và tin nhắn gốc sau khi hết cooldown + 1s
        delete_message_after_delay(message.chat.id, msg_wait.message_id, wait_time + 1)
        delete_message_after_delay(message.chat.id, message.message_id, wait_time + 1)
        return

    # --- Xử lý tiền cược ---
    game_data = load_game_data_sync()
    player_data = get_player_data(user_id, user_name, game_data)
    current_xu = player_data.get("xu", 0)
    bet_amount = 0

    if bet_input == "all":
        if current_xu <= 0:
            return bot.reply_to(message, f"😥 Bạn đã hết xu. Hãy /diemdanh để nhận thêm nhé!")
        bet_amount = current_xu
    else:
        try:
            bet_amount_str = bet_input.replace('.', '').replace(',', '') # Xóa dấu ngăn cách
            bet_amount = int(bet_amount_str)
            if bet_amount <= 0:
                 return bot.reply_to(message, "⚠️ Số tiền cược phải lớn hơn 0.")
        except ValueError:
            return bot.reply_to(message, "⚠️ Số tiền cược không hợp lệ. Vui lòng nhập số hoặc 'all'.")

    # --- Kiểm tra số dư ---
    if bet_amount > current_xu:
        return bot.reply_to(message, f"😥 Bạn không đủ <b>{format_xu(bet_amount)}</b> xu để cược. Số dư hiện tại: <b>{format_xu(current_xu)}</b> xu.")

    # --- Thực hiện game ---
    logger.info(f"User {user_id} ({user_name}) /play: Cược {format_xu(bet_amount)} xu vào '{choice}'.")

    # Trừ tiền cược trước khi tung xúc xắc
    player_data["xu"] -= bet_amount
    player_data["plays"] = player_data.get("plays", 0) + 1
    user_last_cmd_times[command_name] = current_time # Cập nhật thời gian chơi cuối

    # Tung xúc xắc
    dice, total, result = roll_dice_sync()
    dice_str = ' + '.join(map(str, dice))
    is_win = (choice == result)
    win_amount = 0 # Tổng tiền nhận lại (bao gồm cả tiền cược gốc)
    net_gain = 0   # Tiền lãi/lỗ ròng
    jackpot_hit = False
    jackpot_win_amount = 0

    if is_win:
        # Thắng: Tính tiền thắng dựa trên lợi thế nhà cái
        net_gain = round(bet_amount * (1 - (HOUSE_EDGE_PERCENT / 100.0))) # Tiền lãi = tiền cược * (1 - tỉ lệ nhà cái)
        win_amount = bet_amount + net_gain # Tổng nhận lại = cược + lãi
        player_data["xu"] += win_amount # Cộng tiền thắng vào tài khoản

        # Kiểm tra Jackpot
        if random.randint(1, JACKPOT_CHANCE_ONE_IN) == 1:
             jackpot_hit = True
             jackpot_win_amount = JACKPOT_AMOUNT
             player_data["xu"] += jackpot_win_amount # Cộng tiền Jackpot
             logger.info(f"💥 JACKPOT! User {user_id} ({user_name}) trúng {format_xu(jackpot_win_amount)} xu!")
    else:
        # Thua: Mất tiền cược
        net_gain = -bet_amount
        # Không cần trừ vì đã trừ ở trước đó

    save_game_data_sync(game_data) # Lưu lại dữ liệu người chơi

    # --- Gửi kết quả ---
    result_icon = "🎯" if is_win else "💥"
    result_text = f"<b>Thắng</b>" if is_win else f"<b>Thua</b>"

    msg = (
        f"🎲 <b>Kết Quả Tài Xỉu</b> 🎲\n"
        f"--------------------------\n"
        f"👤 Người chơi: {user_name}\n"
        f"👇 Bạn chọn: <b>{choice.capitalize()}</b>\n"
        f"🎲 Kết quả: <b>{dice_str} = {total} ({result.capitalize()})</b>\n"
        f"--------------------------\n"
        f"{result_icon} Bạn đã {result_text}!\n"
    )
    if is_win:
        msg += f"🎉 Thắng: <b>+{format_xu(net_gain)}</b> xu\n"
    if jackpot_hit:
        # Dùng cách khác thay <blink>
        msg += f"<b>💎💎💎 NỔ HŨ JACKPOT!!! +{format_xu(jackpot_win_amount)} xu 💎💎💎</b>\n"
    if not is_win:
        msg += f"💸 Mất: <b>{format_xu(abs(net_gain))}</b> xu\n" # Hiển thị số tiền mất (dương)

    msg += f"💰 Số dư mới: <b>{format_xu(player_data['xu'])}</b> xu."

    bot.reply_to(message, msg)
    logger.info(f"/play Result: User:{user_id}, Dice:{dice}, Total:{total}, Result:{result}, Choice:{choice}, Bet:{bet_amount}, Win:{is_win}, Net:{net_gain}, Jackpot:{jackpot_hit}")


@bot.message_handler(commands=['baucua'])
def baucua_telebot_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    args = message.text.split()[1:]

    # --- Kiểm tra cú pháp ---
    if len(args) != 2:
        valid_items_str = ", ".join([f"{BAUCUA_ICONS.get(item, '')}<code>{item}</code>" for item in BAUCUA_ITEMS])
        return bot.reply_to(message, f"❌ Sai cú pháp! Ví dụ:\n<code>/baucua cua 10000</code>\n<code>/baucua bầu all</code>\n<code>/baucua tôm 10k</code>\n<code>/baucua cá 1m</code>\nCác vật phẩm hợp lệ: {valid_items_str}")

    choice = args[0].lower() # Vật phẩm cược
    bet_input = args[1].lower() # Số tiền hoặc 'all', '10k', '1m'

    if choice not in BAUCUA_ITEMS:
        valid_items_str = ", ".join([f"<code>{item}</code>" for item in BAUCUA_ITEMS])
        return bot.reply_to(message, f"❌ Vật phẩm '<code>{html.escape(choice)}</code>' không hợp lệ!\nChọn một trong các vật phẩm sau: {valid_items_str}")

    # --- Kiểm tra Cooldown ---
    command_name = 'baucua'
    current_time = time.time()
    user_last_cmd_times = last_command_time.setdefault(user_id, {})
    last_baucua_time = user_last_cmd_times.get(command_name, 0)

    if current_time - last_baucua_time < BAUCUA_COOLDOWN:
        wait_time = round(BAUCUA_COOLDOWN - (current_time - last_baucua_time), 1)
        msg_wait = bot.reply_to(message, f"⏳ Chơi quá nhanh! Vui lòng chờ <b>{wait_time} giây</b> nữa.")
        delete_message_after_delay(message.chat.id, msg_wait.message_id, wait_time + 1)
        delete_message_after_delay(message.chat.id, message.message_id, wait_time + 1)
        return

    # --- Xử lý tiền cược (bao gồm k, m) ---
    game_data = load_game_data_sync()
    player_data = get_player_data(user_id, user_name, game_data)
    current_xu = player_data.get("xu", 0)
    bet_amount = 0
    multiplier = 1 # Hệ số nhân (cho k, m)

    if bet_input != 'all':
        if bet_input.endswith('k'):
            multiplier = 1000
            bet_input = bet_input[:-1] # Bỏ chữ 'k'
        elif bet_input.endswith('m'):
            multiplier = 1000000
            bet_input = bet_input[:-1] # Bỏ chữ 'm'

    if bet_input == "all":
        if current_xu <= 0:
            return bot.reply_to(message, f"😥 Bạn đã hết xu. Hãy /diemdanh để nhận thêm nhé!")
        bet_amount = current_xu
    else:
        try:
            bet_amount_str = bet_input.replace('.', '').replace(',', '')
            # Nhân với hệ số k hoặc m (nếu có)
            bet_amount = int(bet_amount_str) * multiplier
            if bet_amount <= 0:
                 return bot.reply_to(message, "⚠️ Số tiền cược phải lớn hơn 0.")
        except ValueError:
            return bot.reply_to(message, "⚠️ Số tiền cược không hợp lệ. Vui lòng nhập số, 'all', hoặc dạng 10k, 1m.")

    # --- Kiểm tra số dư ---
    if bet_amount > current_xu:
        return bot.reply_to(message, f"😥 Bạn không đủ <b>{format_xu(bet_amount)}</b> xu để cược. Số dư hiện tại: <b>{format_xu(current_xu)}</b> xu.")

    # --- Thực hiện game ---
    logger.info(f"User {user_id} ({user_name}) /baucua: Cược {format_xu(bet_amount)} xu vào '{choice}'.")

    player_data["xu"] -= bet_amount # Trừ tiền cược
    user_last_cmd_times[command_name] = current_time # Cập nhật thời gian chơi

    # Tung xúc xắc Bầu Cua
    results = roll_baucua_sync() # ['cua', 'bầu', 'cua']
    results_icons = [BAUCUA_ICONS.get(item, item) for item in results] # ['🦀', '🍐', '🦀']
    results_str_icons = " ".join(results_icons) # "🦀 🍐 🦀"
    results_str_text = ', '.join(results) # "cua, bầu, cua"

    # Đếm số lần vật phẩm cược xuất hiện
    match_count = results.count(choice)
    net_gain = 0 # Lãi/lỗ ròng

    if match_count > 0:
        # Thắng: Thắng gấp `match_count` lần tiền cược
        win_multiplier = match_count
        net_gain = bet_amount * win_multiplier # Tiền lãi
        player_data["xu"] += bet_amount + net_gain # Cộng lại tiền cược gốc + tiền lãi
    else:
        # Thua: Mất tiền cược
        net_gain = -bet_amount
        # Không cần làm gì vì đã trừ tiền trước đó

    save_game_data_sync(game_data) # Lưu lại dữ liệu

    # --- Gửi kết quả ---
    result_icon = "🎯" if match_count > 0 else "💥"
    result_text = f"<b>Thắng</b>" if match_count > 0 else f"<b>Thua</b>"
    choice_icon = BAUCUA_ICONS.get(choice, choice)

    msg = (
        f"🦀 <b>Kết Quả Bầu Cua</b> 🦐\n"
        f"--------------------------\n"
        f"👤 Người chơi: {user_name}\n"
        f"👇 Bạn chọn: {choice_icon} (<code>{choice}</code>)\n"
        f"🎲 Kết quả: {results_str_icons} ({results_str_text})\n"
        f"--------------------------\n"
        f"{result_icon} Bạn đã {result_text}!\n"
    )
    if match_count > 0:
        msg += f"🎉 Thắng: <b>+{format_xu(net_gain)}</b> xu (xuất hiện {match_count} lần)\n"
    else:
        msg += f"💸 Mất: <b>{format_xu(abs(bet_amount))}</b> xu\n" # Hiển thị số tiền mất (dương)

    msg += f"💰 Số dư mới: <b>{format_xu(player_data['xu'])}</b> xu."

    bot.reply_to(message, msg)
    logger.info(f"/baucua Result: User:{user_id}, Results:{results}, Choice:{choice}, Bet:{bet_amount}, Matches:{match_count}, Net:{net_gain}")

@bot.message_handler(commands=['qr'])
def qr_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    text_to_encode = message.text.split(maxsplit=1)

    if len(text_to_encode) < 2 or not text_to_encode[1].strip():
        return bot.reply_to(message, "❌ Vui lòng nhập nội dung bạn muốn tạo mã QR.\nVí dụ: <code>/qr Nội dung cần mã hóa</code>")

    content = text_to_encode[1].strip()
    logger.info(f"User {user_id} ({user_name}) yêu cầu tạo QR cho nội dung: '{content[:50]}...'")

    try:
        # Tạo đối tượng QRCode
        qr = qrcode.QRCode(
            version=1, # Độ phức tạp của QR, 1 là đơn giản nhất
            error_correction=qrcode.constants.ERROR_CORRECT_L, # Mức độ sửa lỗi (L=Low, M, Q, H)
            box_size=10, # Kích thước mỗi ô vuông trong QR
            border=4,    # Độ dày viền trắng xung quanh
        )
        qr.add_data(content) # Thêm dữ liệu cần mã hóa
        qr.make(fit=True)    # Tạo mã QR, tự động điều chỉnh version nếu cần

        # Tạo ảnh từ mã QR
        img = qr.make_image(fill_color="black", back_color="white")

        # Lưu ảnh vào bộ nhớ đệm (BytesIO) để gửi đi
        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0) # Đưa con trỏ về đầu stream

        # Escape nội dung để hiển thị an toàn trong caption
        safe_caption_content = html.escape(content)
        # Giới hạn độ dài caption nếu nội dung quá dài
        max_caption_len = 200
        if len(safe_caption_content) > max_caption_len:
            safe_caption_content = safe_caption_content[:max_caption_len] + "..."

        bot.send_photo(
            message.chat.id,
            photo=img_byte_arr,
            caption=f"✨ Đây là mã QR của bạn cho nội dung:\n<code>{safe_caption_content}</code>",
            reply_to_message_id=message.message_id
        )
        logger.info(f"Đã tạo và gửi QR thành công cho user {user_id}.")

    except Exception as e:
        logger.error(f"Lỗi khi tạo hoặc gửi mã QR cho user {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Đã xảy ra lỗi khi tạo mã QR: {html.escape(str(e))}")

@bot.message_handler(commands=['rutgon'])
def rutgon_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    args = message.text.split(maxsplit=1)

    if len(args) < 2 or not args[1].strip():
        return bot.reply_to(message, "❌ Vui lòng cung cấp link URL bạn muốn rút gọn.\nVí dụ: <code>/rutgon https://example.com/very/long/link</code>")

    url_to_shorten = args[1].strip()

    # Kiểm tra sơ bộ xem có giống URL không
    if not url_to_shorten.lower().startswith(('http://', 'https://')):
        return bot.reply_to(message, "❌ Link không hợp lệ. Link phải bắt đầu bằng <code>http://</code> hoặc <code>https://</code>.")

    logger.info(f"User {user_id} ({user_name}) yêu cầu rút gọn link: {url_to_shorten}")
    api_url = "https://cleanuri.com/api/v1/shorten" # Sử dụng API của cleanuri.com
    payload = {'url': url_to_shorten}

    try:
        # Gửi yêu cầu POST đến API với timeout 10 giây
        response = requests.post(api_url, data=payload, timeout=10)
        response.raise_for_status() # Ném lỗi nếu status code là 4xx hoặc 5xx
        result = response.json() # Parse kết quả JSON

        # Kiểm tra lỗi từ API cleanuri
        if "error" in result:
            error_msg = result["error"]
            logger.error(f"Lỗi từ API cleanuri khi rút gọn '{url_to_shorten}': {error_msg}")
            return bot.reply_to(message, f"❌ Lỗi từ dịch vụ rút gọn: {html.escape(error_msg)}")

        # Lấy link đã rút gọn
        short_url = result.get("result_url")
        if short_url:
            reply_text = (
                f"🔗 Link gốc: {html.escape(url_to_shorten)}\n"
                f"✨ Link rút gọn: {short_url}"
            )
            # disable_web_page_preview=True để Telegram không hiển thị preview của link gốc
            bot.reply_to(message, reply_text, disable_web_page_preview=True)
            logger.info(f"Đã rút gọn link '{url_to_shorten}' thành công thành '{short_url}' cho user {user_id}")
        else:
            logger.error(f"API cleanuri không trả về 'result_url' cho link '{url_to_shorten}'. Phản hồi: {result}")
            bot.reply_to(message, "❌ Lỗi không xác định từ dịch vụ rút gọn (không tìm thấy link kết quả).")

    except requests.exceptions.Timeout:
        logger.error(f"Timeout khi gọi API cleanuri cho link: {url_to_shorten}")
        bot.reply_to(message, "⏳ Yêu cầu đến dịch vụ rút gọn link bị quá thời gian. Vui lòng thử lại sau.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Lỗi kết nối đến API cleanuri: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Lỗi kết nối đến dịch vụ rút gọn link. Chi tiết: {html.escape(str(e))}")
    except json.JSONDecodeError:
        logger.error(f"Lỗi giải mã JSON từ API cleanuri khi rút gọn link: {url_to_shorten}")
        bot.reply_to(message, "❌ Lỗi xử lý phản hồi từ dịch vụ rút gọn link.")
    except Exception as e:
        logger.error(f"Lỗi không mong muốn trong lệnh /rutgon: {e}", exc_info=True)
        bot.reply_to(message, "❌ Đã xảy ra lỗi không mong muốn.")

@bot.message_handler(commands=['thoitiet'])
def weather_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    args = message.text.split(maxsplit=1)

    # Kiểm tra API Key
    if not WEATHER_API_KEY or WEATHER_API_KEY == "YOUR_OPENWEATHERMAP_API_KEY":
        logger.warning(f"User {user_id} dùng /thoitiet nhưng API key chưa cấu hình.")
        return bot.reply_to(message, "⚠️ Tính năng thời tiết chưa được cấu hình. Vui lòng liên hệ Admin.")

    if len(args) < 2 or not args[1].strip():
        return bot.reply_to(message, "❌ Vui lòng nhập tên thành phố hoặc địa điểm bạn muốn xem thời tiết.\nVí dụ: <code>/thoitiet Hà Nội</code>")

    location = args[1].strip()
    logger.info(f"User {user_id} ({user_name}) yêu cầu xem thời tiết tại: '{location}'")

    # Gọi API OpenWeatherMap
    base_url = "http://api.openweathermap.org/data/2.5/weather?"
    complete_url = base_url + "appid=" + WEATHER_API_KEY + "&q=" + location + "&units=metric&lang=vi"

    try:
        response = requests.get(complete_url, timeout=10)
        response.raise_for_status() # Check lỗi HTTP 4xx/5xx
        weather_data = response.json()

        # Kiểm tra mã phản hồi từ API (có thể 200 nhưng vẫn báo lỗi bên trong)
        if weather_data.get("cod") != 200:
             error_message = weather_data.get("message", "Lỗi không xác định từ API")
             logger.error(f"Lỗi từ API OpenWeatherMap (mã {weather_data.get('cod')}) cho '{location}': {error_message}")
             if "city not found" in error_message.lower():
                 return bot.reply_to(message, f"❌ Không tìm thấy địa điểm '<code>{html.escape(location)}</code>'. Vui lòng kiểm tra lại tên.")
             else:
                 return bot.reply_to(message, f"❌ Lỗi từ dịch vụ thời tiết: {html.escape(error_message)}")

        # Trích xuất thông tin thời tiết
        main = weather_data.get("main", {})
        weather_desc_list = weather_data.get("weather", [{}]) # Lấy list weather, mặc định là list trống
        weather_desc = weather_desc_list[0] if weather_desc_list else {} # Lấy phần tử đầu tiên nếu list không rỗng
        wind = weather_data.get("wind", {})
        sys_info = weather_data.get("sys", {})

        city_name = weather_data.get("name", location) # Tên thành phố chuẩn hóa từ API
        country = sys_info.get("country", "") # Mã quốc gia
        temp = main.get("temp", "N/A")
        feels_like = main.get("feels_like", "N/A")
        humidity = main.get("humidity", "N/A")
        description = weather_desc.get("description", "Không có mô tả").capitalize() # Mô tả thời tiết, viết hoa chữ đầu
        icon_code = weather_desc.get("icon") # Mã icon thời tiết
        wind_speed = wind.get("speed", "N/A") # Tốc độ gió (m/s vì units=metric)

        # Mapping mã icon sang emoji (có thể mở rộng thêm)
        weather_icons = {
            "01d": "☀️", "01n": "🌙", "02d": "🌤️", "02n": "☁️",
            "03d": "☁️", "03n": "☁️", "04d": "☁️", "04n": "☁️",
            "09d": "🌧️", "09n": "🌧️", "10d": "🌦️", "10n": "🌧️",
            "11d": "⛈️", "11n": "⛈️", "13d": "❄️", "13n": "❄️",
            "50d": "🌫️", "50n": "🌫️"
        }
        icon_emoji = weather_icons.get(icon_code, "❓") # Emoji mặc định nếu không có icon

        # Tạo tin nhắn kết quả
        reply_text = (
            f"<b>Thời tiết tại {html.escape(city_name)}, {country}</b> {icon_emoji}\n"
            f"--------------------------\n"
            f"🌡️ Nhiệt độ: <b>{temp}°C</b> (Cảm giác như: {feels_like}°C)\n"
            f"💧 Độ ẩm: <b>{humidity}%</b>\n"
            f"🌬️ Tốc độ gió: <b>{wind_speed} m/s</b>\n"
            f"📝 Mô tả: <b>{html.escape(description)}</b>"
        )

        bot.reply_to(message, reply_text)
        logger.info(f"Đã gửi thông tin thời tiết cho '{location}' tới user {user_id}")

    except requests.exceptions.Timeout:
        logger.error(f"Timeout khi gọi API OpenWeatherMap cho: {location}")
        bot.reply_to(message, "⏳ Yêu cầu đến dịch vụ thời tiết bị quá thời gian. Vui lòng thử lại sau.")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Lỗi kết nối đến API OpenWeatherMap: {req_err}", exc_info=True)
        bot.reply_to(message, "❌ Lỗi kết nối đến dịch vụ thời tiết.")
    except json.JSONDecodeError:
        logger.error(f"Lỗi giải mã JSON từ API OpenWeatherMap cho: '{location}'")
        bot.reply_to(message, "❌ Lỗi xử lý dữ liệu thời tiết.")
    except IndexError:
         logger.error(f"IndexError khi xử lý dữ liệu thời tiết cho '{location}' (có thể do API trả về list weather rỗng).")
         bot.reply_to(message, "❌ Lỗi dữ liệu thời tiết không đầy đủ.")
    except Exception as e:
        logger.error(f"Lỗi không mong muốn trong lệnh /thoitiet '{location}': {e}", exc_info=True)
        bot.reply_to(message, "❌ Đã xảy ra lỗi không mong muốn khi lấy thông tin thời tiết.")

@bot.message_handler(commands=['phim'])
def movie_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    args = message.text.split(maxsplit=1)

    # Kiểm tra API Key
    if not TMDB_API_KEY or TMDB_API_KEY == "YOUR_TMDB_API_KEY":
        logger.warning(f"User {user_id} dùng /phim nhưng API key TMDb chưa cấu hình.")
        return bot.reply_to(message, "⚠️ Tính năng tìm phim chưa được cấu hình. Vui lòng liên hệ Admin.")

    if len(args) < 2 or not args[1].strip():
        return bot.reply_to(message, "❌ Vui lòng nhập tên phim bạn muốn tìm.\nVí dụ: <code>/phim Inception</code>")

    query = args[1].strip()
    logger.info(f"User {user_id} ({user_name}) tìm kiếm phim: '{query}'")

    search_url = f"https://api.themoviedb.org/3/search/movie"
    params = {
        "api_key": TMDB_API_KEY,
        "query": query,
        "language": "vi-VN", # Ưu tiên tiếng Việt
        "include_adult": False
    }

    try:
        # Bước 1: Tìm kiếm phim để lấy ID
        response_search = requests.get(search_url, params=params, timeout=10)
        response_search.raise_for_status()
        search_results = response_search.json()

        # Nếu không có kết quả tiếng Việt, thử tìm tiếng Anh
        if not search_results.get("results"):
            logger.info(f"Không tìm thấy phim '{query}' bằng tiếng Việt, thử tìm bằng tiếng Anh.")
            params["language"] = "en-US"
            response_search = requests.get(search_url, params=params, timeout=10)
            response_search.raise_for_status()
            search_results = response_search.json()
            # Nếu vẫn không có kết quả thì báo lỗi
            if not search_results.get("results"):
                return bot.reply_to(message, f"❌ Không tìm thấy phim nào khớp với '<code>{html.escape(query)}</code>'.")

        # Lấy thông tin phim đầu tiên trong kết quả tìm kiếm
        movie = search_results["results"][0]
        movie_id = movie.get("id")

        if not movie_id:
            logger.error(f"Kết quả tìm phim '{query}' không chứa ID. Kết quả đầu tiên: {movie}")
            return bot.reply_to(message, f"❌ Lỗi dữ liệu khi tìm phim '<code>{html.escape(query)}</code>'.")

        # Bước 2: Lấy chi tiết phim bằng ID (ưu tiên tiếng Việt)
        details_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
        details_params = {
            "api_key": TMDB_API_KEY,
            "language": "vi-VN",
            "append_to_response": "credits" # Lấy thông tin credits (đạo diễn, diễn viên)
        }
        details_response_vn = requests.get(details_url, params=details_params, timeout=10)
        details = None
        # Nếu lấy chi tiết TV thành công và có title thì dùng
        if details_response_vn.status_code == 200:
            details_vn = details_response_vn.json()
            if details_vn.get("title"): # Đôi khi API trả về 200 nhưng nội dung rỗng
                details = details_vn
                logger.info(f"Đã lấy chi tiết phim '{query}' (ID: {movie_id}) bằng tiếng Việt.")

        # Nếu không lấy được chi tiết tiếng Việt, thử lấy tiếng Anh
        if not details:
            logger.info(f"Không lấy được chi tiết tiếng Việt cho phim ID {movie_id}, thử lấy tiếng Anh.")
            details_params["language"] = "en-US"
            details_response_en = requests.get(details_url, params=details_params, timeout=10)
            details_response_en.raise_for_status() # Nếu tiếng Anh cũng lỗi thì báo lỗi luôn
            details = details_response_en.json()
            logger.info(f"Đã lấy chi tiết phim '{query}' (ID: {movie_id}) bằng tiếng Anh.")

        # Trích xuất thông tin chi tiết
        title = details.get("title", "N/A")
        original_title = details.get("original_title", "")
        tagline = details.get("tagline", "")
        overview = details.get("overview", "Không có mô tả.")
        release_date_str = details.get("release_date", "N/A") # dạng 'YYYY-MM-DD'
        runtime = details.get("runtime") # Số phút (integer) or None
        genres_list = details.get("genres", [])
        genres = ", ".join([g["name"] for g in genres_list]) if genres_list else "N/A"
        rating = details.get("vote_average", 0) # float
        vote_count = details.get("vote_count", 0) # integer
        poster_path = details.get("poster_path") # string or None (vd: /path/to/poster.jpg)
        homepage = details.get("homepage") # string or None

        # Lấy thông tin đạo diễn và diễn viên từ 'credits'
        director = "N/A"
        actors_list = []
        crew = details.get("credits", {}).get("crew", [])
        cast = details.get("credits", {}).get("cast", [])
        for member in crew:
            if member.get("job") == "Director":
                director = member.get("name", "N/A")
                break # Lấy đạo diễn đầu tiên tìm thấy
        if cast:
            actors_list = [a.get("name", "") for a in cast[:5] if a.get("name")] # Lấy tên 5 diễn viên đầu
        actors = ", ".join(actors_list) if actors_list else "N/A"

        # Định dạng thời lượng phim
        runtime_str = "N/A"
        if isinstance(runtime, int) and runtime > 0:
            hours = runtime // 60
            minutes = runtime % 60
            if hours > 0:
                runtime_str = f"{hours} giờ {minutes} phút"
            else:
                runtime_str = f"{minutes} phút"

        # Định dạng đánh giá
        rating_str = "Chưa đánh giá"
        if vote_count > 0 and isinstance(rating, (float, int)) and rating > 0:
             rating_str = f"{rating:.1f}/10 ({vote_count:,} lượt)" # Định dạng số vote có dấu phẩy

        # Định dạng ngày phát hành
        release_date_formatted = release_date_str
        try:
            if release_date_str != "N/A":
                 release_dt = datetime.strptime(release_date_str, '%Y-%m-%d')
                 release_date_formatted = release_dt.strftime('%d/%m/%Y') # Đổi sang DD/MM/YYYY
        except ValueError:
             pass # Giữ nguyên chuỗi gốc nếu không parse được

        # Escape HTML các trường văn bản
        safe_title = html.escape(title)
        safe_original_title = html.escape(original_title) if original_title else ""
        safe_tagline = html.escape(tagline) if tagline else ""
        safe_genres = html.escape(genres)
        safe_director = html.escape(director)
        safe_actors = html.escape(actors)
        safe_overview = html.escape(overview or 'Chưa có mô tả.')

        # Tạo caption
        caption_lines = []
        caption_lines.append(f"🎬 <b>{safe_title}</b>")
        if safe_original_title and safe_original_title != safe_title:
            caption_lines.append(f"   <i>(Tên gốc: {safe_original_title})</i>")
        if safe_tagline:
            caption_lines.append(f"   <i>“{safe_tagline}”</i>")
        caption_lines.append("--------------------------")
        caption_lines.append(f"⭐️ Đánh giá: <b>{rating_str}</b>")
        caption_lines.append(f"🗓️ Phát hành: {release_date_formatted}")
        caption_lines.append(f"⏱️ Thời lượng: {runtime_str}")
        caption_lines.append(f"🎭 Thể loại: {safe_genres}")
        caption_lines.append(f"🎬 Đạo diễn: {safe_director}")
        caption_lines.append(f"👥 Diễn viên: {safe_actors}")
        caption_lines.append("--------------------------")

        # Giới hạn độ dài tóm tắt
        max_overview_length = 350 # Giới hạn để caption không quá dài
        if len(safe_overview) > max_overview_length:
            safe_overview = safe_overview[:max_overview_length] + "..."

        caption_lines.append(f"📝 <b>Nội dung:</b>\n{safe_overview}")
        if homepage:
            caption_lines.append(f"\n🔗 Trang chủ: {homepage}")

        caption = "\n".join(caption_lines)

        # Gửi kết quả (có ảnh nếu tìm thấy poster)
        if poster_path:
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" # w500 là kích thước ảnh
            try:
                # Telegram giới hạn caption ảnh là 1024 ký tự
                max_caption_length = 1024
                if len(caption) > max_caption_length:
                    caption = caption[:max_caption_length-25] + "...\n(Nội dung bị cắt bớt)"

                bot.send_photo(
                    message.chat.id,
                    photo=poster_url,
                    caption=caption,
                    reply_to_message_id=message.message_id
                )
                logger.info(f"Đã gửi thông tin phim '{title}' kèm poster cho user {user_id}")
            except Exception as img_err:
                logger.warning(f"Lỗi khi gửi ảnh poster phim '{title}': {img_err}. Sẽ gửi dạng văn bản.")
                # Gửi dạng văn bản nếu gửi ảnh lỗi
                bot.reply_to(message, caption, disable_web_page_preview=True)
        else:
            # Gửi dạng văn bản nếu không có poster
            bot.reply_to(message, caption, disable_web_page_preview=True)
            logger.info(f"Đã gửi thông tin phim '{title}' (không có poster) cho user {user_id}")

    except requests.exceptions.Timeout:
        logger.error(f"Timeout khi gọi API TMDb cho phim: {query}")
        bot.reply_to(message, "⏳ Yêu cầu đến dịch vụ tìm phim bị quá thời gian. Vui lòng thử lại sau.")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Lỗi kết nối đến API TMDb: {req_err}", exc_info=True)
        bot.reply_to(message, "❌ Lỗi kết nối đến dịch vụ tìm phim.")
    except json.JSONDecodeError:
        logger.error(f"Lỗi giải mã JSON từ API TMDb khi tìm phim: '{query}'")
        bot.reply_to(message, "❌ Lỗi xử lý dữ liệu phim.")
    except IndexError:
         logger.warning(f"IndexError khi xử lý kết quả tìm phim '{query}' (có thể do kết quả rỗng sau khi lọc).")
         bot.reply_to(message, f"❌ Không tìm thấy chi tiết cho phim '<code>{html.escape(query)}</code>' hoặc dữ liệu trả về không hợp lệ.")
    except Exception as e:
        logger.error(f"Lỗi không mong muốn trong lệnh /phim '{query}': {e}", exc_info=True)
        bot.reply_to(message, "❌ Đã xảy ra lỗi không mong muốn khi tìm thông tin phim.")

@bot.message_handler(commands=['admin'])
def admin_contact_command(message: telebot.types.Message):
     user_id, user_name = get_user_info_from_message(message)
     bot.reply_to(message, f"🧑‍💼 Nếu bạn cần hỗ trợ hoặc có thắc mắc, vui lòng liên hệ quản trị viên: @{ADMIN_USERNAME}")
     logger.info(f"User {user_id} ({user_name}) yêu cầu thông tin liên hệ admin.")

# === CÁC LỆNH SPAM MỚI ===

def run_spam_script(phone_number: str, count: int, message: telebot.types.Message) -> bool:
    """Hàm helper để chạy script spam và xử lý kết quả."""
    script_path = BASE_DIR / SPAM_SCRIPT_NAME
    if not script_path.exists():
        logger.error(f"Lỗi: Script spam '{SPAM_SCRIPT_NAME}' không tìm thấy tại '{script_path}'.")
        bot.reply_to(message, f"❌ Lỗi hệ thống: Không tìm thấy công cụ spam. Vui lòng liên hệ Admin (@{ADMIN_USERNAME}).")
        return False

    command = ['python', str(script_path), phone_number, str(count)]
    try:
        logger.info(f"Đang chạy script spam: {' '.join(command)}")
        # Gửi tin nhắn chờ
        waiting_msg = bot.reply_to(message, f"⏳ Đang bắt đầu gửi <b>{count}</b> tin nhắn đến <code>{html.escape(phone_number)}</code>... Vui lòng chờ.")

        # Chạy script trong nền với timeout
        result = subprocess.run(command, capture_output=True, text=True, timeout=SPAM_TIMEOUT, check=False) # check=False để không ném lỗi nếu script thất bại

        # Xóa tin nhắn chờ
        try:
            bot.delete_message(chat_id=waiting_msg.chat.id, message_id=waiting_msg.message_id)
        except Exception:
            pass # Bỏ qua nếu không xóa được

        # Xử lý kết quả
        if result.returncode == 0:
            logger.info(f"Script spam cho SĐT {phone_number} hoàn thành thành công. Output:\n{result.stdout}")
            bot.reply_to(message, f"✅ Đã gửi thành công <b>{count}</b> tin nhắn đến <code>{html.escape(phone_number)}</code>.")
            return True
        else:
            logger.error(f"Script spam cho SĐT {phone_number} thất bại (return code {result.returncode}).\nStderr: {result.stderr}\nStdout: {result.stdout}")
            error_details = f"Chi tiết lỗi (nếu có): {html.escape(result.stderr.strip() or result.stdout.strip() or 'Không có output cụ thể')}"
            bot.reply_to(message, f"❌ Gửi tin nhắn đến <code>{html.escape(phone_number)}</code> thất bại.\n{error_details[:1000]}") # Giới hạn độ dài lỗi
            return False

    except FileNotFoundError:
        logger.error(f"Lỗi: Lệnh 'python' không tìm thấy hoặc script '{SPAM_SCRIPT_NAME}' không tồn tại.")
        bot.reply_to(message, f"❌ Lỗi hệ thống: Không thể thực thi công cụ spam. Vui lòng liên hệ Admin (@{ADMIN_USERNAME}).")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"Script spam cho SĐT {phone_number} bị timeout sau {SPAM_TIMEOUT} giây.")
        bot.reply_to(message, f"⏳ Quá trình gửi tin nhắn đến <code>{html.escape(phone_number)}</code> mất quá nhiều thời gian và đã bị dừng.")
        return False
    except Exception as e:
        logger.error(f"Lỗi không mong muốn khi chạy script spam cho SĐT {phone_number}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Đã xảy ra lỗi không mong muốn khi thực hiện lệnh spam: {html.escape(str(e))}")
        return False

@bot.message_handler(commands=['spam'])
def spam_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)
    args = message.text.split()

    # --- Kiểm tra cú pháp ---
    if len(args) != 3:
        return bot.reply_to(message, f"❌ Sai cú pháp! Ví dụ: <code>/spam 09xxxxxxxx 5</code>\n(Tối đa {SPAM_FREE_MAX_COUNT} tin, cooldown {SPAM_FREE_COOLDOWN}s)")

    phone_number = args[1].replace('+', '').replace(' ', '').strip()
    count_str = args[2]

    # --- Validate Input ---
    if not phone_number.isdigit():
        return bot.reply_to(message, "❌ Số điện thoại không hợp lệ (chỉ chứa số).")

    if phone_number in BLACKLISTED_NUMBERS:
        return bot.reply_to(message, f"🚫 Số điện thoại <code>{html.escape(phone_number)}</code> nằm trong danh sách cấm.")

    try:
        count = int(count_str)
        if not (0 < count <= SPAM_FREE_MAX_COUNT):
            return bot.reply_to(message, f"⚠️ Số lượng tin nhắn phải từ 1 đến {SPAM_FREE_MAX_COUNT}.")
    except ValueError:
        return bot.reply_to(message, "⚠️ Số lượng tin nhắn không hợp lệ (phải là số).")

    # --- Kiểm tra Cooldown ---
    command_name = 'spam_free' # Dùng tên riêng cho cooldown free
    current_time = time.time()
    user_last_cmd_times = last_command_time.setdefault(user_id, {})
    last_spam_time = user_last_cmd_times.get(command_name, 0)

    if current_time - last_spam_time < SPAM_FREE_COOLDOWN:
        wait_time = round(SPAM_FREE_COOLDOWN - (current_time - last_spam_time), 1)
        msg_wait = bot.reply_to(message, f"⏳ Bạn vừa sử dụng lệnh này! Vui lòng chờ <b>{wait_time} giây</b> nữa.")
        delete_message_after_delay(message.chat.id, msg_wait.message_id, wait_time + 1)
        delete_message_after_delay(message.chat.id, message.message_id, wait_time + 1)
        return

    # --- Thực hiện Spam ---
    logger.info(f"User {user_id} ({user_name}) yêu cầu /spam: SĐT={phone_number}, Count={count}")
    success = run_spam_script(phone_number, count, message)

    if success:
        # Cập nhật thời gian cooldown chỉ khi thực hiện thành công (hoặc ít nhất là đã chạy script)
        user_last_cmd_times[command_name] = current_time

@bot.message_handler(commands=['spamvip'])
def spamvip_command(message: telebot.types.Message):
    user_id, user_name = get_user_info_from_message(message)

    # --- Kiểm tra VIP ---
    if user_id not in allowed_vip_users:
        # Có thể kiểm tra cả expiration_time ở đây nếu muốn chắc chắn hơn
        # expiration_time = get_vip_expiration_time_from_db(user_id)
        # if not expiration_time or expiration_time <= datetime.now():
        return bot.reply_to(message, "⛔ Lệnh này chỉ dành cho thành viên VIP! Sử dụng /muavip để đăng ký.")

    args = message.text.split()

    # --- Kiểm tra cú pháp ---
    if len(args) != 3:
        return bot.reply_to(message, f"❌ Sai cú pháp! Ví dụ: <code>/spamvip 09xxxxxxxx 20</code>\n(Tối đa {SPAM_VIP_MAX_COUNT} tin)")

    phone_number = args[1].replace('+', '').replace(' ', '').strip()
    count_str = args[2]

    # --- Validate Input ---
    if not phone_number.isdigit():
        return bot.reply_to(message, "❌ Số điện thoại không hợp lệ (chỉ chứa số).")

    if phone_number in BLACKLISTED_NUMBERS:
        return bot.reply_to(message, f"🚫 Số điện thoại <code>{html.escape(phone_number)}</code> nằm trong danh sách cấm.")

    try:
        count = int(count_str)
        if not (0 < count <= SPAM_VIP_MAX_COUNT):
            return bot.reply_to(message, f"⚠️ Số lượng tin nhắn phải từ 1 đến {SPAM_VIP_MAX_COUNT}.")
    except ValueError:
        return bot.reply_to(message, "⚠️ Số lượng tin nhắn không hợp lệ (phải là số).")

    # --- Thực hiện Spam (Không Cooldown cho VIP) ---
    logger.info(f"VIP User {user_id} ({user_name}) yêu cầu /spamvip: SĐT={phone_number}, Count={count}")
    run_spam_script(phone_number, count, message)
    # Không cần cập nhật last_command_time cho VIP spam

# === Khởi chạy Bot ===
def main():
    logger.info("--- Bot đang khởi tạo ---")
    # Khởi tạo database và load dữ liệu ban đầu
    initialize_vip_database()
    load_vip_users_from_db()
    _ = load_game_data_sync() # Load thử để đảm bảo file không lỗi, không cần lưu kết quả ở đây

    logger.info(f"Bot Token: ...{BOT_TOKEN[-6:]}")
    logger.info(f"Admin ID: {ADMIN_ID} | Admin Username: @{ADMIN_USERNAME}")
    logger.info(f"Game Data File: {DATA_FILE_PATH}")
    logger.info(f"VIP DB File: {DB_FILE_PATH}")
    logger.info(f"VIP QR Code Image: {QR_CODE_IMAGE_PATH}")
    logger.info(f"Spam Script: {SPAM_SCRIPT_NAME}")
    logger.info(f"Bot bắt đầu chạy lúc: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("--- Bot đã sẵn sàng nhận lệnh ---")

    try:
        # Bắt đầu lắng nghe tin nhắn từ Telegram
        # logger_level=logging.INFO để thấy log của thư viện telebot
        # skip_pending=True để bỏ qua các tin nhắn cũ khi bot offline
        bot.infinity_polling(logger_level=logging.WARNING, skip_pending=True) # Giảm log của telebot xuống WARNING
    except Exception as e:
        # Log lỗi nghiêm trọng khiến bot dừng
        logger.critical(f"!!! LỖI NGHIÊM TRỌNG KHIẾN BOT DỪNG HOẠT ĐỘNG: {e}", exc_info=True)
    finally:
        # Thông báo khi bot dừng (dù do lỗi hay dừng thủ công)
        logger.info("--- Bot đang dừng... ---")
        # Có thể thêm các hành động dọn dẹp ở đây nếu cần
        logger.info("--- Bot đã dừng hoàn toàn ---")

if __name__ == '__main__':
    main()
