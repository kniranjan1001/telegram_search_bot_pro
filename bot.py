import os
import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext
from pymongo import MongoClient
from fuzzywuzzy import process
import requests

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Now you can access the environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
JSON_URL = os.getenv("JSON_URL")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
CHANNELS = ["@cc_new_moviess"]  # Assuming CHANNELS are comma-separated
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Log environment variables loading
logger.info("Loaded environment variables")

# MongoDB setup
try:
    client = MongoClient(MONGO_URI)
    db = client["movie_bot"]
    requests_collection = db["movie_requests"]
    logger.info("MongoDB connection established successfully")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {e}")

# Fetch movie data from JSON URL
def fetch_movie_data():
    try:
        response = requests.get(JSON_URL)
        response.raise_for_status()
        logger.info("Fetched movie data from JSON URL successfully")
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

# Handle the /start command
async def start(update: Update, context: CallbackContext) -> None:
    logger.info(f"/start command received from user {update.message.from_user.id}")
    user = update.message.from_user
    subscribed = await is_subscribed(user.id, context)
    
    if not subscribed:
        buttons = [[InlineKeyboardButton("Subscribe Here", url=f"https://t.me/addlist/4LAlWDoYvHk2ZDdl")] for channel in CHANNELS]
        await update.message.reply_text(
            "🔔 You need to subscribe to the following channels to use this bot:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    await update.message.reply_text("🎬 Welcome to the Movie Bot! Send me a movie name to search for its link.")

# Handle movie search
async def search_movie(update: Update, context: CallbackContext) -> None:
    logger.info(f"Movie search request from user {update.message.from_user.id}: {update.message.text}")
    user = update.message.from_user
    subscribed = await is_subscribed(user.id, context)

    if not subscribed:
        buttons = [[InlineKeyboardButton("Subscribe Here", url=f"https://t.me/addlist/4LAlWDoYvHk2ZDdl")] for channel in CHANNELS]
        await update.message.reply_text(
            "🔔 You need to subscribe to the following channels to use this bot:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    movie_name = update.message.text.strip()
    movie_data = fetch_movie_data()
    movie_names = list(movie_data.keys())

    if not movie_names:
        logger.warning(f"No movies found for search term: {movie_name}")
    
    matches = process.extract(movie_name, movie_names, limit=5)
    buttons = []

    for match in matches:
        matched_movie = match[0]
        match_url = movie_data[matched_movie]
        buttons.append(InlineKeyboardButton(text=matched_movie, url=match_url))

    if buttons:
        keyboard = InlineKeyboardMarkup([[button] for button in buttons])
        message = await update.message.reply_text(
            f"🎥 Here are the closest matches for '{movie_name}':\n\n👇 Click on a button to access the movie.",
            reply_markup=keyboard,
        )
    else:
        message = await update.message.reply_text("❌ No matching movies found. You can request the movie.")
        return

    # Immediately send the Yes/No options for confirmation
    options_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes", callback_data=f"response_yes|{movie_name}"),
                InlineKeyboardButton("❌ No", callback_data=f"response_no|{movie_name}"),
            ]
        ]
    )
    await update.message.reply_text("📽️ Did this contain your movie?", reply_markup=options_keyboard)

# Handle user response to suggestions
async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    action = data[0]
    movie_name = data[1]
    user = query.from_user

    if action == "response_yes":
        await query.edit_message_text("🎉 Hope it helped! Enjoy your movie🍿. ⌲ For upload updates join - https://t.me/+agty3W0_CAFkZmI1 ♡")
    elif action == "response_no":
        existing_request = requests_collection.find_one({"movie_name": movie_name})
        if existing_request:
            if user.id not in existing_request["user_requested"]:
                requests_collection.update_one(
                    {"movie_name": movie_name},
                    {"$inc": {"times": 1}, "$addToSet": {"user_requested": user.id}} ,
                )
        else:
            requests_collection.insert_one(
                {"movie_name": movie_name, "times": 1, "user_requested": [user.id]}
            )
        await query.edit_message_text("📋 Your request has been noted. We'll try to add it soon. 😊 For upload updates join - https://t.me/+agty3W0_CAFkZmI1 ♡")

# Handle /requests command (admin only)
async def view_requests(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    if user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    movie_requests = requests_collection.find()
    if requests_collection.count_documents({}) == 0:
        await update.message.reply_text("📋 No movie requests yet.")
        return

    message = "📋 *Movie Requests:*\n\n"
    for request in movie_requests:
        message += (
            f"🎥 {request['movie_name']} - {request['times']} requests\n"
            f"👥 Requested by: {', '.join(map(str, request['user_requested']))}\n\n"
        )

    await update.message.reply_text(message, parse_mode="Markdown")

# Handle /help command (admin only)
async def help(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    if user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    help_message = """
    *Help for Admin:* 

    /start - Start the bot and check for channel subscription.

    /requests - View all movie requests and the number of times each movie has been requested.
    """

    await update.message.reply_text(help_message)

# Remove /broadcast method and related handler

# Set up webhook and handlers
def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("requests", view_requests))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movie))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Set up webhook
    application.bot.set_webhook(WEBHOOK_URL)

    # Flask app to handle webhook requests
    app = Flask(__name__)

    @app.route(f"/{BOT_TOKEN}", methods=["POST"])
    def webhook():
        json_str = request.get_data().decode("UTF-8")
        update = Update.de_json(json_str, application.bot)
        application.process_update(update)
        return "OK"

    # Start the Flask web server
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    main()
