import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext
from telegram.error import BadRequest, TimedOut, NetworkError
from fuzzywuzzy import process
from pymongo import MongoClient
import requests
import time

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
JSON_URL = os.getenv("JSON_URL")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
CHANNELS = ["@cc_new_moviess"]

# MongoDB setup
client = MongoClient(MONGO_URI)
db = client["movie_bot"]
requests_collection = db["movie_requests"]

# Fetch movie data from JSON URL
def fetch_movie_data():
    try:
        response = requests.get(JSON_URL)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching data from JSON URL: {e}")
        return {}

# Check user subscription status
async def is_subscribed(user_id: int, context: CallbackContext) -> bool:
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception as e:
            logger.error(f"Error checking subscription for user {user_id} in {channel}: {e}")
            return False
    return True

# Safe message sending function
async def safe_send_message(update: Update, text: str, reply_markup=None, parse_mode=None):
    """Safely send a message with error handling"""
    try:
        return await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        logger.error(f"BadRequest when sending message: {e}")
        try:
            # Try sending without reply_to_message_id
            return await update.message.chat.send_message(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e2:
            logger.error(f"Failed to send message even without reply: {e2}")
            return None
    except Exception as e:
        logger.error(f"Unexpected error when sending message: {e}")
        return None

# Safe callback query edit function
async def safe_edit_message(query, text: str, reply_markup=None, parse_mode=None):
    """Safely edit a callback query message with error handling"""
    try:
        return await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        logger.error(f"BadRequest when editing message: {e}")
        try:
            # Try sending a new message instead
            return await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e2:
            logger.error(f"Failed to send new message: {e2}")
            return None
    except Exception as e:
        logger.error(f"Unexpected error when editing message: {e}")
        return None

# Handle the /start command
async def start(update: Update, context: CallbackContext) -> None:
    try:
        user = update.message.from_user
        subscribed = await is_subscribed(user.id, context)
        
        if not subscribed:
            buttons = [[InlineKeyboardButton("Subscribe Here", url=f"https://t.me/addlist/ijkMdb6cwtRkYjA1")] for channel in CHANNELS]
            await safe_send_message(
                update,
                "🔔 You need to subscribe to the following channels to use this bot:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return

        await safe_send_message(update, "🎬 Welcome to the Movie Request Bot!\n👉 Send me original movie name \n👉 We will try to find match \n👉 Click No if no match found \n Ur request will be noted 😎.")
    except Exception as e:
        logger.error(f"Error in start command: {e}")

# Handle movie search
async def search_movie(update: Update, context: CallbackContext) -> None:
    try:
        user = update.message.from_user
        subscribed = await is_subscribed(user.id, context)

        if not subscribed:
            buttons = [[InlineKeyboardButton("Subscribe Here", url=f"https://t.me/addlist/ijkMdb6cwtRkYjA1")] for channel in CHANNELS]
            await safe_send_message(
                update,
                "🔔 You need to subscribe to the following channels to use this bot:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return

        movie_name = update.message.text.strip()
        movie_data = fetch_movie_data()
        movie_names = list(movie_data.keys())

        matches = process.extract(movie_name, movie_names, limit=5)
        buttons = []

        for match in matches:
            matched_movie = match[0]
            match_url = movie_data[matched_movie]
            buttons.append(InlineKeyboardButton(text=matched_movie, url=match_url))

        if buttons:
            keyboard = InlineKeyboardMarkup([[button] for button in buttons])
            message = await safe_send_message(
                update,
                f"🎥 Here are the closest matches for '{movie_name}':\n\n👇 Click on a button to access the movie.",
                reply_markup=keyboard
            )
            
            # Add a small delay to prevent race conditions
            await asyncio.sleep(0.5)
            
            # Send the Yes/No options for confirmation
            options_keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ Yes", callback_data=f"response_yes|{movie_name}"),
                        InlineKeyboardButton("❌ No", callback_data=f"response_no|{movie_name}"),
                    ]
                ]
            )
            await safe_send_message(update, "📽️ Did this contain your movie?", reply_markup=options_keyboard)
        else:
            await safe_send_message(update, "❌ No matching movies found. You can request the movie.")
            
    except Exception as e:
        logger.error(f"Error in search_movie: {e}")
        try:
            await safe_send_message(update, "❌ An error occurred while searching for movies. Please try again.")
        except:
            pass

# Handle user response to suggestions
async def button_callback(update: Update, context: CallbackContext) -> None:
    try:
        query = update.callback_query
        await query.answer()

        data = query.data.split("|")
        action = data[0]
        movie_name = data[1]
        user = query.from_user

        if action == "response_yes":
            await safe_edit_message(query, "🎉 Hope it helped! Enjoy your movie🍿. ⌲ For upload updates join - https://t.me/+agty3W0_CAFkZmI1 ♡")
        elif action == "response_no":
            existing_request = requests_collection.find_one({"movie_name": movie_name})
            if existing_request:
                # Check if the user has already requested this movie
                if user.id not in existing_request["user_requested"]:
                    requests_collection.update_one(
                        {"movie_name": movie_name},
                        {"$inc": {"times": 1}, "$addToSet": {"user_requested": user.id}},
                    )
            else:
                requests_collection.insert_one(
                    {"movie_name": movie_name, "times": 1, "user_requested": [user.id]}
                )
            await safe_edit_message(query, "📋 Your request has been noted. We'll try to add it soon. 😊 For upload updates join - https://t.me/+agty3W0_CAFkZmI1 ♡")
            
    except Exception as e:
        logger.error(f"Error in button_callback: {e}")

# Handle /requests command (admin only)
async def view_requests(update: Update, context: CallbackContext) -> None:
    try:
        user = update.message.from_user
        if user.id != ADMIN_USER_ID:
            await safe_send_message(update, "❌ You are not authorized to use this command.")
            return

        movie_requests = requests_collection.find()
        if requests_collection.count_documents({}) == 0:
            await safe_send_message(update, "📋 No movie requests yet.")
            return

        message = "📋 *Movie Requests:*\n\n"
        for request in movie_requests:
            message += (
                f"🎥 {request['movie_name']} - {request['times']} requests\n"
                f"👥 Requested by: {', '.join(map(str, request['user_requested']))}\n\n"
            )

        await safe_send_message(update, message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in view_requests: {e}")

# Handle /help command (admin only)
async def help(update: Update, context: CallbackContext) -> None:
    try:
        user = update.message.from_user
        if user.id != ADMIN_USER_ID:
            await safe_send_message(update, "❌ You are not authorized to use this command.")
            return

        help_message = """
        *Help for Admin:* 

        /start - Start the bot and check for channel subscription.

        /requests - View all movie requests and the number of times each movie has been requested.

        /broadcast <movie1,movie2,...> <message> - Send a message to all users who requested one or more of the specified movies.

        /delete <movie1,movie2,...> - Delete one or more movies from the database.

        Example:
        /broadcast movie1,movie2 "New movie releases are available!"
        This will send the message to users who requested either movie1 or movie2.
        """

        await safe_send_message(update, help_message)
    except Exception as e:
        logger.error(f"Error in help command: {e}")

# Handle /broadcast command (admin only)
async def broadcast(update: Update, context: CallbackContext) -> None:
    try:
        user = update.message.from_user
        if user.id != ADMIN_USER_ID:
            await safe_send_message(update, "❌ You are not authorized to use this command.")
            return

        args = context.args
        if len(args) < 2:
            await safe_send_message(update, "Usage: /broadcast <movie_names> <message>")
            return

        movie_names = args[0].split(",")
        message = " ".join(args[1:])
        user_ids = set()

        for movie_name in movie_names:
            movie_request = requests_collection.find_one({"movie_name": movie_name.strip()})

            if not movie_request:
                continue

            user_ids.update(movie_request["user_requested"])

        if user_ids:
            for user_id in user_ids:
                try:
                    await context.bot.send_message(chat_id=user_id, text=message)
                except Exception as e:
                    logger.error(f"Failed to send message to user {user_id}: {e}")

            await safe_send_message(update, f"✅ Broadcast message sent to users who requested {', '.join(movie_names)}.")
        else:
            await safe_send_message(update, f"❌ No requests found for the specified movies.")
    except Exception as e:
        logger.error(f"Error in broadcast command: {e}")

# Handle /delete command (admin only)
async def delete_movies(update: Update, context: CallbackContext) -> None:
    try:
        user = update.message.from_user
        if user.id != ADMIN_USER_ID:
            await safe_send_message(update, "❌ You are not authorized to use this command.")
            return

        args = context.args
        if len(args) == 0:
            await safe_send_message(update, "Usage: /delete <movie_name1,movie_name2,...>")
            return

        movie_names = args[0].split(",")
        feedback_message = "📋 Deleting the following movies:\n\n"

        for movie_name in movie_names:
            movie_name = movie_name.strip()  # Remove extra spaces
            result = requests_collection.delete_one({"movie_name": movie_name})

            if result.deleted_count > 0:
                feedback_message += f"✅ {movie_name}\n"
            else:
                feedback_message += f"❌ {movie_name} not found in the database.\n"

        await safe_send_message(update, feedback_message)
    except Exception as e:
        logger.error(f"Error in delete_movies command: {e}")

# Error handler
async def error_handler(update: Update, context: CallbackContext) -> None:
    """Log errors and handle them gracefully"""
    logger.error(f"Exception while handling an update: {context.error}")
    
    # Try to send error message to user if possible
    if update and update.message:
        try:
            await safe_send_message(update, "❌ An error occurred. Please try again later.")
        except:
            pass

# Main function to set up the handlers with retry logic
def main() -> None:
    max_retries = 5
    retry_delay = 10  # seconds
    
    for attempt in range(max_retries):
        try:
            application = Application.builder().token(BOT_TOKEN).build()
            
            # Add error handler
            application.add_error_handler(error_handler)
            
            # Add command handlers
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("help", help))
            application.add_handler(CommandHandler("broadcast", broadcast))
            application.add_handler(CommandHandler("requests", view_requests))
            application.add_handler(CommandHandler("delete", delete_movies))
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movie))
            application.add_handler(CallbackQueryHandler(button_callback))

            # Check if running on Render (webhook) or locally (polling)
            if os.environ.get("RENDER"):
                webhook_url = f"https://telegram-search-bot-pro.onrender.com/{BOT_TOKEN}"
                logger.info("Starting webhook mode...")
                application.run_webhook(
                    listen='0.0.0.0', 
                    port=int(os.environ.get("PORT", 5000)), 
                    webhook_url=webhook_url, 
                    url_path=BOT_TOKEN
                )
            else:
                logger.info("Starting polling mode...")
                application.run_polling(
                    drop_pending_updates=True,
                    allowed_updates=Update.ALL_TYPES
                )
            
            break  # If we reach here, the bot started successfully
            
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.error("Max retries reached. Exiting.")
                raise

if __name__ == "__main__":
    # Keep the bot running forever with restart capability
    while True:
        try:
            logger.info("Starting bot...")
            main()
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Bot crashed with error: {e}")
            logger.info("Restarting bot in 30 seconds...")
            time.sleep(30)
