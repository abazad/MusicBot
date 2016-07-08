import json
import os
from os.path import isfile, isdir
import signal
import sys
import threading
import urllib

from gmusicapi.clients.mobileclient import Mobileclient
from telegram import InlineQueryResultArticle, InputTextMessageContent
from telegram import replykeyboardhide
from telegram import replykeyboardmarkup
from telegram.ext import InlineQueryHandler, ChosenInlineResultHandler
from telegram.ext.commandhandler import CommandHandler
from telegram.ext.messagehandler import MessageHandler, Filters
from telegram.ext.updater import Updater

import player


def pretty(some_map):
    return json.dumps(some_map, indent=4, sort_keys=True)


def read_secrets():
    secrets = open("secrets.json", "r")
    content = secrets.read()
    secrets.close()
    content = json.loads(content)
    user = content["username"].strip()
    password = content["password"].strip()
    device_id = content["device_id"].strip()
    token = content["token"].strip()
    return user, password, device_id, token


def start_bot():
    global updater
    updater = Updater(token=token)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(MessageHandler([Filters.text], handle_message))

    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(
        CommandHandler('next', lambda b, u: queued_player.next()))
    dispatcher.add_handler(
        CommandHandler('play', lambda b, u: queued_player.resume()))
    dispatcher.add_handler(
        CommandHandler('pause', lambda b, u: queued_player.pause()))
    dispatcher.add_handler(CommandHandler('skip', skip))
    dispatcher.add_handler(CommandHandler('showqueue', show_queue))

    dispatcher.add_handler(InlineQueryHandler(get_inline_handler()))
    dispatcher.add_handler(ChosenInlineResultHandler(queue))

    updater.start_polling()


def handle_message(bot, update):
    chat_id = update.message.chat_id
    if chat_id in skip_keyboard_sent:
        text = update.message.text
        if ")" not in text:
            return
        c = text.split(")")[0]
        if str.isdecimal(c):
            i = int(c) - 1
            queued_player.skip_song(queue_position=i)
            hide_keyboard(bot, chat_id, get_queue_message())
            skip_keyboard_sent.remove(chat_id)
        else:
            print("INVALID CHOICE:", c)


def hide_keyboard(bot, chat_id, message):
    markup = replykeyboardhide.ReplyKeyboardHide()
    bot.send_message(
        chat_id=chat_id, text=message, reply_markup=markup, parse_mode="markdown")


def start(bot, update):
    bot.sendMessage(
        text="Type @gmusicqueuebot and search for a song", chat_id=update.message.chat_id)


def get_queue_message():
    queue = queued_player.get_queue()
    message = "\n"
    header_str = "*Current queue:*"
    if len(queue) > 0:
        message = header_str + "\n" + \
            message.join(map(lookup_song_name, queue))
    else:
        message = message.join([header_str, "_empty..._"])
    return message


def show_queue(bot, update):
    message = get_queue_message()
    bot.send_message(
        chat_id=update.message.chat_id, text=message, parse_mode="markdown")

skip_keyboard_sent = set()


def skip(bot, update):
    queue = queued_player.get_queue()

    if len(queue) == 0:
        bot.send_message(chat_id=update.message.chat_id,
                         text="No songs in queue", reply_to_message_id=update.message.message_id)
        return

    chat_id = update.message.chat_id
    if chat_id in skip_keyboard_sent:
        return

    keyboard = []
    for i in range(0, len(queue)):
        keyboard.append(["{}) {}".format(i + 1, lookup_song_name(queue[i]))])

    markup = replykeyboardmarkup.ReplyKeyboardMarkup(
        keyboard, one_time_keyboard=True)

    bot.send_message(chat_id=chat_id, text="What song?",
                     reply_markup=markup, reply_to_message_id=update.message.message_id)

    skip_keyboard_sent.add(chat_id)


def search_song(query, max_results=10):
    results = api.search(query, max_results)
    songs = []
    for track in results["song_hits"]:
        song = track["track"]
        songs.append(song)
    return songs

song_names = {}


def get_inline_handler():
    def get_inline_result(song):
        song_id = song["storeId"]
        song_title = song["title"]
        artist = song["artist"]
        song_str = "{} - {}".format(artist, song_title)
        song_names[song_id] = song_str
        result = InlineQueryResultArticle(
            id=song_id,
            title=song_title,
            description="by {}".format(artist),
            input_message_content=InputTextMessageContent(song_str)
        )

        if "albumArtRef" in song:
            ref = song["albumArtRef"]
            if len(ref) > 0:
                ref = ref[0]
                if "url" in ref:
                    url = ref["url"]
                    result.thumb_url = url

        return result

    def inline_handler(bot, update):
        query = update.inline_query.query
        if not query:
            return

        search_results = search_song(query)

        results = list(map(get_inline_result, search_results))
        bot.answerInlineQuery(update.inline_query.id, results)
    return inline_handler


def load_song(store_id):
    fname = "songs/" + store_id + ".mp3"

    if not isfile(fname):
        url = api.get_stream_url(store_id)
        request = urllib.request.Request(url)
        page = urllib.request.urlopen(request)

        if not isdir("songs"):
            os.mkdir("songs")

        file = open(fname, "wb")
        file.write(page.read())
        file.close()
        page.close()

    return fname


def lookup_song_name(store_id):
    if store_id in song_names:
        return song_names[store_id]
    else:
        info = api.get_track_info(store_id)
        return "{} - {}".format(info["artist"], info["title"])


def queue(bot, update):
    storeId = update.chosen_inline_result["result_id"]
    user = update.chosen_inline_result["from_user"]
    song_name = lookup_song_name(storeId)
    queued_player.queue(storeId)
    print("QUEUED by", user["first_name"], ":", song_name)

user, password, device_id, token = read_secrets()

api = Mobileclient(debug_logging=False)
if not api.login(user, password, device_id, "de_DE"):
    print("Failed to log in to gmusic")
    sys.exit(1)

queued_player = None
updater = None


def run_player():
    global queued_player
    queued_player = player.Player(load_song)
    queued_player.run()

player_thread = threading.Thread(target=run_player, name="player_thread")
bot_thread = threading.Thread(target=start_bot, name="bot_thread")
player_thread.start()
bot_thread.start()

exiting = False


def exit_bot(signum=None, frame=None):
    global exiting
    if exiting:
        return
    exiting = True
    print("EXITING {} ...".format(signum))
    updater.stop()
    queued_player.close()
    api.logout()

    print("EXIT")
    sys.exit(0)


def listen_exit():
    signal.signal(signal.SIGTERM, exit_bot)
    signal.signal(signal.SIGINT, exit_bot)
    signal.signal(signal.SIGABRT, exit_bot)

listen_exit()
print("RUNNING")
while 1:
    try:
        input_str = input("")
        if input_str.lower() == "exit":
            exit_bot()
    except SystemExit:
        break
    except EOFError:
        if exiting:
            break
        else:
            print("Try again?")
