import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext
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

# Handle the /start command
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("🎬 Welcome to the Movie Bot!\nSend me a movie name to search for its link.")

# Handle movie search
async def search_movie(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    movie_name = update.message.text.strip()
    
    # Fetch data from JSON
    movie_data = fetch_movie_data()
    movie_names = list(movie_data.keys())
    
    # Find similar matches
    matches = process.extract(movie_name, movie_names, limit=5)
    buttons = []

    # Create buttons for matches
    for match in matches:
        matched_movie = match[0]
        match_url = movie_data[matched_movie]
        buttons.append(InlineKeyboardButton(text=matched_movie, url=match_url))
    
    # Prepare response
    if buttons:
        keyboard = InlineKeyboardMarkup([[button] for button in buttons])
        message = (
            f"🎥 Here are the closest matches for '{movie_name}':\n\n"
            "👇 Click on a button to access the movie."
        )
        await update.message.reply_text(message, reply_markup=keyboard)
    else:
        await update.message.reply_text("❌ No matching movies found. You can request the movie.")
        return

    # Ask user if the response was helpful
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

    if action == "response_yes":
        await query.edit_message_text("🎉 Hope it helped! Enjoy your movie. 🍿")
    elif action == "response_no":
        # Increment request count in MongoDB
        existing_request = requests_collection.find_one({"movie_name": movie_name})
        if existing_request:
            requests_collection.update_one(
                {"movie_name": movie_name}, {"$inc": {"request_count": 1}}
            )
        else:
            requests_collection.insert_one({"movie_name": movie_name, "request_count": 1})
        
        await query.edit_message_text("📋 Your request has been noted. We'll try to add it soon. 😊")

# Handle /requests command (admin only)
async def view_requests(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    if user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Fetch all requests from MongoDB
    movie_requests = requests_collection.find()
    if movie_requests.count() == 0:
        await update.message.reply_text("📋 No movie requests yet.")
        return

    message = "📋 *Movie Requests:*\n\n"
    for request in movie_requests:
        message += f"🎥 {request['movie_name']} - {request['request_count']} requests\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")

# Main function to set up the bot
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("requests", view_requests))
    
    # Message handler for movie search
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movie))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
