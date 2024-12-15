import os
import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext, Dispatcher
from fuzzywuzzy import process
from pymongo import MongoClient
import requests

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
JSON_URL = os.getenv("JSON_URL")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
CHANNELS = ["@cc_new_moviess"]
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Public URL for webhook

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

# Handle the /start command
async def start(update: Update, context: CallbackContext) -> None:
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

    /broadcast <movie1,movie2,...> <message> - Send a message to all users who requested one or more of the specified movies.

    /delete <movie1,movie2,...> - Delete one or more movies from the database.

    Example:
    /broadcast movie1,movie2 "New movie releases are available!"
    This will send the message to users who requested either movie1 or movie2.
    """

    await update.message.reply_text(help_message)

# Handle /broadcast command (admin only)
async def broadcast(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    if user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /broadcast <movie_names> <message>")
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

        await update.message.reply_text(f"✅ Broadcast message sent to users who requested {', '.join(movie_names)}.")
    else:
        await update.message.reply_text(f"❌ No requests found for the specified movies.")

# Handle /delete command (admin only)
async def delete_movies(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    if user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    args = context.args
    if len(args) == 0:
        await update.message.reply_text("Usage: /delete <movie_name1,movie_name2,...>")
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

    await update.message.reply_text(feedback_message)

# Flask app for webhook
app = Flask(__name__)

# Initialize Telegram bot and dispatcher
application = Application.builder().token(BOT_TOKEN).build()
dispatcher: Dispatcher = application.dispatcher

# Add handlers to dispatcher
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("help", help))
dispatcher.add_handler(CommandHandler("broadcast", broadcast))
dispatcher.add_handler(CommandHandler("requests", view_requests))
dispatcher.add_handler(CommandHandler("delete", delete_movies))
dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movie))
dispatcher.add_handler(CallbackQueryHandler(button_callback))

# Webhook route
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    """Process updates sent by Telegram."""
    update = Update.de_json(request.get_json(), application.bot)
    dispatcher.process_update(update)
    return "OK", 200

# Set webhook before the first request
@app.before_first_request
def set_webhook():
    application.bot.delete_webhook()
    application.bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")

# Run Flask app
if __name__ == "__main__":
    app.run(port=8443, host="0.0.0.0")
