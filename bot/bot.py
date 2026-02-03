import logging
import os
import re
import paramiko
import psycopg2
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)


load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
RM_HOST = os.getenv("RM_HOST")
RM_PORT = int(os.getenv("RM_PORT", 22))
RM_USER = os.getenv("RM_USER")
RM_PASSWORD = os.getenv("RM_PASSWORD")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_DATABASE = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASS")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


FIND_EMAIL, EMAIL_SAVE_DECISION = range(2)
FIND_PHONE, PHONE_SAVE_DECISION = range(2, 4)
CHECK_PASSWORD = 4

def ssh_command(command):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=RM_HOST, port=RM_PORT, username=RM_USER, password=RM_PASSWORD, timeout=10) 
        stdin, stdout, stderr = client.exec_command(command)
        result = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        client.close()
        
        if result: return result
        if error: return f"Error output: {error}"
        return "Command executed, empty output."
    except Exception as e:
        logger.error(f"SSH Error: {e}")
        return f"SSH Error: {e}"

def db_query(query, params=None, fetch=False):
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_DATABASE,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cur = conn.cursor()
        cur.execute(query, params)
        
        if fetch:
            result = cur.fetchall()
        else:
            conn.commit()
            result = True
            
        cur.close()
        return result
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return None
    finally:
        if conn: conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot started! Commands:\n"
        "/find_email - Find & Save Email\n"
        "/find_phone_number - Find & Save Phone\n"
        "/verify_password - Check password complexity\n"
        "--- System Info (SSH) ---\n"
        "/get_uptime - Server Uptime\n"
        "/get_release - OS Release\n"
        "/get_free - RAM/Disk Usage\n"
        "/get_apt_list - Installed Packages (Top 20)\n"
        "/get_repl_logs - DB Replication Status\n"
        "--- Database ---\n"
        "/get_emails - List saved emails\n"
        "/get_phone_numbers - List saved phones"
    )

async def find_email_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send text to find Email:")
    return FIND_EMAIL

async def find_email_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    
    if not emails:
        await update.message.reply_text("Emails not found.")
        return ConversationHandler.END

    unique_emails = list(set(emails))
    context.user_data['found_emails'] = unique_emails
    
    reply_keyboard = [['Yes', 'No']]
    await update.message.reply_text(
        f"Found: {', '.join(unique_emails)}\nSave to DB?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return EMAIL_SAVE_DECISION

async def email_save_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.lower()
    emails = context.user_data.get('found_emails', [])
    user_id = update.effective_user.id
    
    if choice == 'yes':
        for email in emails:
            db_query("INSERT INTO messages (user_id, text) VALUES (%s, %s)", (user_id, f"Email: {email}"))
        await update.message.reply_text("Saved.", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    
    context.user_data.clear()
    return ConversationHandler.END

async def find_phone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send text to find Phone:")
    return FIND_PHONE

async def find_phone_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    phones = re.findall(r'(?:\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}', text)
    
    if not phones:
        await update.message.reply_text("Phones not found.")
        return ConversationHandler.END

    unique_phones = list(set(phones))
    context.user_data['found_phones'] = unique_phones
    
    reply_keyboard = [['Yes', 'No']]
    await update.message.reply_text(
        f"Found: {', '.join(unique_phones)}\nSave to DB?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return PHONE_SAVE_DECISION

async def phone_save_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.lower()
    phones = context.user_data.get('found_phones', [])
    user_id = update.effective_user.id
    
    if choice == 'yes':
        for phone in phones:
            db_query("INSERT INTO messages (user_id, text) VALUES (%s, %s)", (user_id, f"Phone: {phone}"))
        await update.message.reply_text("Saved.", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
        
    context.user_data.clear()
    return ConversationHandler.END

async def verify_password_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send password to verify complexity:")
    return CHECK_PASSWORD

async def verify_password_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    
    if (len(password) >= 8 and
        re.search(r"\d", password) and
        re.search(r"[a-z]", password) and
        re.search(r"[A-Z]", password)):
        await update.message.reply_text("Password is STRONG.")
    else:
        await update.message.reply_text(
            "Password is WEAK.\n"
            "Requirements:\n"
            "- At least 8 characters\n"
            "- At least 1 digit\n"
            "- Uppercase and Lowercase letters"
        )
    return ConversationHandler.END

async def get_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    output = ssh_command("uptime")
    await update.message.reply_text(f"System Uptime:\n{output}")

async def get_release(update: Update, context: ContextTypes.DEFAULT_TYPE):
    output = ssh_command("cat /etc/*release | grep PRETTY_NAME")
    await update.message.reply_text(f"OS Release:\n{output}")

async def get_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    output = ssh_command("free -h")
    await update.message.reply_text(f"Memory Usage:\n{output}")

async def get_apt_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching package list (Top 20)...")

    output = ssh_command("apt list --installed | head -n 20")
    await update.message.reply_text(f"Installed Packages:\n```\n{output}\n```", parse_mode='Markdown')

async def get_repl_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Requesting DB logs...")
    cmd = "ps -ef | grep 'postgres' | grep -v grep"
    output = ssh_command(cmd)
    
    await update.message.reply_text(f"Replication Process Status:\n```\n{output}\n```", parse_mode='Markdown')

async def get_emails_from_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_query("SELECT text FROM messages WHERE text LIKE 'Email:%' ORDER BY id DESC LIMIT 10", fetch=True)
    if rows:
        text = "\n".join([r[0] for r in rows])
        await update.message.reply_text(f"Last Emails:\n{text}")
    else:
        await update.message.reply_text("No emails in DB.")

async def get_phones_from_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_query("SELECT text FROM messages WHERE text LIKE 'Phone:%' ORDER BY id DESC LIMIT 10", fetch=True)
    if rows:
        text = "\n".join([r[0] for r in rows])
        await update.message.reply_text(f"Last Phones:\n{text}")
    else:
        await update.message.reply_text("No phones in DB.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

def main():
    if not TOKEN:
        print("Bot token not found!")
        return

    application = Application.builder().token(TOKEN).build()

    conv_email = ConversationHandler(
        entry_points=[CommandHandler('find_email', find_email_start)],
        states={
            FIND_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, find_email_process)],
            EMAIL_SAVE_DECISION: [MessageHandler(filters.Regex('^(Yes|No|yes|no)$'), email_save_decision)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    conv_phone = ConversationHandler(
        entry_points=[CommandHandler('find_phone_number', find_phone_start)],
        states={
            FIND_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, find_phone_process)],
            PHONE_SAVE_DECISION: [MessageHandler(filters.Regex('^(Yes|No|yes|no)$'), phone_save_decision)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    conv_password = ConversationHandler(
        entry_points=[CommandHandler('verify_password', verify_password_start)],
        states={
            CHECK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_password_process)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )


    application.add_handler(conv_email)
    application.add_handler(conv_phone)
    application.add_handler(conv_password)
    
    application.add_handler(CommandHandler("start", start))
    

    application.add_handler(CommandHandler("get_emails", get_emails_from_db))
    application.add_handler(CommandHandler("get_phone_numbers", get_phones_from_db))
    
    application.add_handler(CommandHandler("get_repl_logs", get_repl_logs))
    application.add_handler(CommandHandler("get_uptime", get_uptime))
    application.add_handler(CommandHandler("get_release", get_release))
    application.add_handler(CommandHandler("get_free", get_free))
    application.add_handler(CommandHandler("get_apt_list", get_apt_list))

    application.run_polling()

if __name__ == '__main__':
    main()
