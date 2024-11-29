from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext
from telegram.constants import ChatMemberStatus
import logging
import requests
import os
from fuzzywuzzy import process
from pymongo import MongoClient

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID'))
JSON_URL = os.getenv('JSON_URL')
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME')

# MongoDB setup
MONGO_URL = os.getenv('MONGO_URI')
client = MongoClient(MONGO_URL)
db = client['movie_bot']
user_collection = db['users']

# Helper: Fetch movie data
def fetch_movie_data():
    try:
        response = requests.get(JSON_URL)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching JSON data: {e}")
        return {}

# Helper: Check user subscription
async def is_user_subscribed(user_id, context):
    try:
        member_status = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member_status.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.warning(f"Failed to check subscription status for user {user_id}: {e}")
        return False

# Helper: Store user in MongoDB
def store_user(user_id, username=None, first_name=None):
    if not user_collection.find_one({"_id": user_id}):
        user_collection.insert_one({
            "_id": user_id,
            "username": username,
            "first_name": first_name
        })

# Helper: Generate search response
async def generate_search_response(movie_name):
    movie_data = fetch_movie_data()
    movie_names = list(movie_data.keys())
    matches = process.extract(movie_name, movie_names, limit=4)
    
    if matches:
        buttons = [InlineKeyboardButton(text=match[0], url=movie_data[match[0]]) for match in matches]
        return InlineKeyboardMarkup([[button] for button in buttons])
    return "No matching movies found. Try again or request here: @anonyms_middle_man_bot!"

# Function: Delete message
async def delete_message(context):
    job_data = context.job.data
    try:
        await context.bot.delete_message(chat_id=job_data['chat_id'], message_id=job_data['message_id'])
    except Exception as e:
        logger.error(f"Failed to delete message {job_data['message_id']}: {e}")

# Command: /start
async def start_command(update, context):
    user = update.message.from_user
    store_user(user.id, user.username, user.first_name)
    buttons = [
        [InlineKeyboardButton("About 🧑‍💻", callback_data='about')],
        [InlineKeyboardButton("Request Movie 😇", url='https://t.me/anonyms_middle_man_bot')]
    ]
    welcome_message = (
        "🎬 Welcome to the Movie Search Bot! 🍿\n"
        "Search for your favorite movies easily:\n"
        "`/search <movie_name>` or type the movie name directly.\n"
        "Enjoy your content! 😎"
    )
    await update.message.reply_text(welcome_message, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

# Command: /search
async def search_command(update, context):
    user = update.message.from_user
    if not await is_user_subscribed(user.id, context):
        return await prompt_subscription(update)
    
    if not context.args:
        return await update.message.reply_text("Usage: /search <movie_name>")
    
    movie_name = " ".join(context.args)
    await send_search_results(update, context, movie_name)

# Function: Handle movie search
async def send_search_results(update, context, movie_name):
    loading_message = await update.message.reply_text("🔍 Searching... 🍿")
    result = await generate_search_response(movie_name)
    if isinstance(result, InlineKeyboardMarkup):
        message = await loading_message.edit_text(f"Results for '{movie_name}':", reply_markup=result)
        context.job_queue.run_once(delete_message, 60, data={'message_id': message.message_id, 'chat_id': update.message.chat_id})
    else:
        await loading_message.edit_text(result)

# Prompt subscription
async def prompt_subscription(update):
    message = (
        "🔔 To access the movie search, please subscribe to our channel:\n"
        "⚝ After subscribing, send the movie name directly. ⌕"
    )
    keyboard = [[InlineKeyboardButton("Join Now", url="https://t.me/addlist/4LAlWDoYvHk2ZDdl")]]
    await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

# Callback: Button actions
async def button_callback(update, context):
    query = update.callback_query
    await query.answer()
    
    if query.data == "about":
        about_message = (
            "🤖 *About the Bot*:\n"
            "Search for movies by name.\n"
            "*Developer*: [Harsh](https://t.me/Harsh_Raj1)"
        )
        back_button = InlineKeyboardButton("🔙 Back", callback_data='back_to_start')
        await query.edit_message_text(about_message, reply_markup=InlineKeyboardMarkup([[back_button]]), parse_mode="Markdown")
    elif query.data == "back_to_start":
        await start_command(update, context)

# Command: /broadcast
async def broadcast_message(update, context):
    if update.message.from_user.id != ADMIN_USER_ID:
        return await update.message.reply_text("Unauthorized.")
    if not context.args:
        return await update.message.reply_text("Usage: /broadcast <message>")
    
    broadcast_text = " ".join(context.args)
    users = user_collection.find({}, {"_id": 1})
    for user in users:
        try:
            await context.bot.send_message(chat_id=user["_id"], text=broadcast_text)
        except Exception as e:
            logger.warning(f"Failed to send message to user {user['_id']}: {e}")

# Command: /userlist
async def user_list_command(update, context):
    if update.message.from_user.id != ADMIN_USER_ID:
        return await update.message.reply_text("Unauthorized.")
    user_count = user_collection.count_documents({})
    await update.message.reply_text(f"Total users: {user_count}")

# Main
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("broadcast", broadcast_message))
    application.add_handler(CommandHandler("userlist", user_list_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.run_polling()

if __name__ == "__main__":
    main()

