import json
from os import path
from signal import SIGTERM
import socket
import sys
import threading
from time import sleep

from gmusicapi.clients.mobileclient import Mobileclient
import pafy
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
    secrets_path = path.join(secrets_location, "secrets.json")
    secrets = open(secrets_path, "r")
    content = secrets.read()
    secrets.close()
    content = json.loads(content)
    user = content["username"].strip()
    password = content["password"].strip()
    device_id = content["device_id"].strip()
    token = content["token"].strip()
    youtube_token = content["youtube_bot_token"]
    api_key = content["youtube_api_key"]
    return user, password, device_id, token, youtube_token, api_key


def start_bot():
    global updater
    updater = Updater(token=token)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(MessageHandler([Filters.text], handle_message))

    # public commands
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('showqueue', show_queue))
    dispatcher.add_handler(CommandHandler('currentsong', show_current_song))
    dispatcher.add_handler(CommandHandler('cancel', cancel_keyboard))
    dispatcher.add_handler(CommandHandler('login', login))

    # password protected commands
    dispatcher.add_handler(CommandHandler('next', next_song))
    dispatcher.add_handler(CommandHandler('play', play))
    dispatcher.add_handler(CommandHandler('pause', pause))
    dispatcher.add_handler(CommandHandler('skip', skip))
    dispatcher.add_handler(CommandHandler('movesong', move_song))

    # admin commands
    dispatcher.add_handler(CommandHandler('admin', set_admin))
    dispatcher.add_handler(CommandHandler('clearqueue', clear_queue))
    dispatcher.add_handler(CommandHandler('reset', reset_bot))
    dispatcher.add_handler(CommandHandler('exit', exit_bot_command))
    dispatcher.add_handler(CommandHandler('ip', send_ip))
    dispatcher.add_handler(CommandHandler('togglepassword', toggle_password))
    dispatcher.add_handler(CommandHandler('setpassword', set_password))
    dispatcher.add_handler(CommandHandler('banuser', ban_user))
    dispatcher.add_handler(CommandHandler('setquality', set_quality))

    dispatcher.add_handler(InlineQueryHandler(get_inline_handler()))
    dispatcher.add_handler(ChosenInlineResultHandler(queue))

    updater.start_polling()


def start_youtube_bot():
    global youtube_updater
    youtube_updater = Updater(token=youtube_token)
    dispatcher = youtube_updater.dispatcher

    dispatcher.add_handler(InlineQueryHandler(get_youtube_inline_handler()))
    dispatcher.add_handler(ChosenInlineResultHandler(youtube_queue))
    youtube_updater.start_polling()


def handle_message(bot, update):
    chat_id = update.message.chat_id
    if chat_id in keyboard_sent:
        text = update.message.text
        if ")" not in text:
            return
        c = text.split(")")[0]
        if str.isdecimal(c):
            i = int(c) - 1
            action = keyboard_sent[chat_id]
            action(i)
        else:
            print("INVALID CHOICE:", c)


def hide_keyboard(bot, chat_id, message):
    markup = replykeyboardhide.ReplyKeyboardHide()
    bot.send_message(
        chat_id=chat_id, text=message, reply_markup=markup, parse_mode="markdown")


def cancel_keyboard(bot, update):
    chat_id = update.message.chat_id
    if chat_id in keyboard_sent:
        del keyboard_sent[chat_id]
    hide_keyboard(bot, chat_id, "kk...")


def start(bot, update):
    if not is_logged_in(update.message.from_user):
        bot.send_message(
            chat_id=update.message.chat_id, text="Please log in with /login [password]")
        return
    bot.send_message(
        text="Type @gmusicqueuebot and search for a song", chat_id=update.message.chat_id)


def login(bot, update):
    chat_id = update.message.chat_id
    user = update.message.from_user
    if not session_password:
        bot.send_message(chat_id=chat_id, text="There is no password")
        return

    user_map = user_tuple_from_user(user)

    if user_map in session_clients:
        bot.send_message(chat_id=chat_id, text="You are already logged in")
        return

    if session_password == " ":
        bot.send_message(
            chat_id=chat_id, text="Admin hasn't decided which password to use yet")
        return

    split = update.message.text.split(" ")
    if len(split) < 2:
        bot.send_message(
            chat_id=chat_id, text="Usage: /login [password]")
        return

    password = split[1].strip()
    if not password:
        bot.send_message(chat_id=chat_id, text="Password can't be empty")
        return

    if password == session_password:
        session_clients.add(user_map)
        bot.send_message(chat_id=chat_id, text="Successfully logged in")
    else:
        bot.send_message(chat_id=chat_id, text="Wrong password")


def _admin(func):
    def _admin_func(bot, update):
        if admin_chat_id == update.message.chat_id:
            func(bot, update)
        else:
            bot.send_message(
                chat_id=update.message.chat_id, text="This command is for admins only")
    return _admin_func


def user_tuple_from_user(user):
    return (user.id,  user.first_name)


def is_logged_in(user):
    return not session_password or user_tuple_from_user(user) in session_clients


def _password_protected(func):
    def _password_protected_func(bot, update):
        chat_id = update.message.chat_id
        if session_password == " ":
            bot.send_message(
                chat_id=chat_id, text="Admin hasn't decided which password to use yet")
            return

        user = update.message.from_user
        if is_logged_in(user):
            func(bot, update)
        else:
            bot.send_message(
                chat_id=chat_id, text="Please log in with /login [password]")

    return _password_protected_func


def get_queue_message():
    queue = queued_player.get_queue()
    message = "\n"
    header_str = "*Current queue:*"
    if len(queue) > 0:
        message = header_str + "\n" + \
            message.join(map(lambda song: song['name'], queue))
    else:
        message = message.join([header_str, "_empty..._"])
    return message


def show_queue(bot, update):
    message = get_queue_message()
    bot.send_message(
        chat_id=update.message.chat_id, text=message, parse_mode="markdown")

keyboard_sent = {}


def send_queue_keyboard(bot, chat_id, message_id, text):
    queue = queued_player.get_queue()
    keyboard = []
    for i in range(0, len(queue)):
        keyboard.append(
            ["{}) {}".format(i + 1, queue[i]['name'])])

    markup = replykeyboardmarkup.ReplyKeyboardMarkup(
        keyboard, one_time_keyboard=True, resize_keyboard=True)

    bot.send_message(chat_id=chat_id, text=text,
                     reply_markup=markup, reply_to_message_id=message_id)


@_password_protected
def skip(bot, update):
    queue = queued_player.get_queue()
    if len(queue) == 0:
        bot.send_message(chat_id=update.message.chat_id,
                         text="No songs in queue", reply_to_message_id=update.message.message_id)
        return

    chat_id = update.message.chat_id
    if chat_id in keyboard_sent:
        return

    send_queue_keyboard(bot, chat_id, update.message.message_id, "What song?")

    def skip_action(queue_position):
        queued_player.skip_song(queue_position=queue_position)
        hide_keyboard(bot, chat_id, get_queue_message())
        del keyboard_sent[chat_id]

    keyboard_sent[chat_id] = skip_action


@_password_protected
def move_song(bot, update):
    message = update.message
    chat_id = message.chat_id
    queue = queued_player.get_queue()

    if len(queue) <= 1:
        bot.send_message(chat_id=chat_id,
                         text="Not >1 songs in queue", reply_to_message_id=message.message_id)
        return

    if chat_id in keyboard_sent:
        return

    send_queue_keyboard(
        bot, chat_id, update.message.message_id, "What song do you want to move?")

    def move_song_first_action(source_position):
        source = queue[source_position]
        queue.pop(source_position)
        send_queue_keyboard(
            bot, chat_id, message.message_id, "Before what song should it be?")

        def move_song_second_action(target_position):
            queue.insert(target_position, source)
            hide_keyboard(bot, chat_id, get_queue_message())
            del keyboard_sent[chat_id]

        keyboard_sent[chat_id] = move_song_second_action

    keyboard_sent[chat_id] = move_song_first_action


@_password_protected
def play(bot, update):
    queued_player.resume()


@_password_protected
def pause(bot, update):
    queued_player.pause()


@_password_protected
def next_song(bot, update):
    def _next_job():
        queued_player.next()
        show_current_song(bot, update)
    threading.Thread(target=_next_job, name="next_thread").start()


def show_current_song(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text="Now playing: {}".format(
        queued_player.get_current_song()['name']))


def search_song(query):
    max_results = 20
    results = api.search(query, max_results)
    songs = []
    for track in results["song_hits"]:
        song = track["track"]
        songs.append(song)
    return songs


def get_inline_handler():
    def get_inline_result(song):
        song_id = song["storeId"]
        song_title = song["title"]
        artist = song["artist"]
        song_str = "{} - {}".format(artist, song_title)
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
        if not is_logged_in(update.inline_query.from_user):
            return

        query = update.inline_query.query
        if not query:
            return

        search_results = search_song(query)

        results = list(map(get_inline_result, search_results))
        bot.answerInlineQuery(update.inline_query.id, results)
    return inline_handler


def search_youtube_song(query):
    qs = {
        'q': query,
        'maxResults': 20,
        'safeSearch': "none",
        'part': 'id,snippet',
        'type': 'video',
        'key': youtube_api_key
    }

    wdata = pafy.call_gdata('search', qs)
    return wdata['items']


def get_youtube_inline_handler():
    def get_inline_result(song):
        song_id = song['id']['videoId']
        snippet = song['snippet']
        title = snippet['title']
        song_names[song_id] = title
        description = snippet["description"]
        result = InlineQueryResultArticle(
            id=song_id,
            title=title,
            description=description,
            input_message_content=InputTextMessageContent(title)
        )

        if "thumbnails" in snippet:
            thumbnails = snippet['thumbnails']
            url = thumbnails['medium']['url']
            result.thumb_url = url

        return result

    def inline_handler(bot, update):
        if not is_logged_in(update.inline_query.from_user):
            return

        query = update.inline_query.query
        if not query:
            return

        search_results = search_youtube_song(query)
        results = list(map(get_inline_result, search_results))
        bot.answerInlineQuery(update.inline_query.id, results)
    return inline_handler

song_names = {}


def lookup_song_name(store_id):
    if not store_id:
        return "Nothing"
    elif store_id in song_names:
        return song_names[store_id]
    else:
        info = api.get_track_info(store_id)
        title = "{} - {}".format(info["artist"], info["title"])
        song_names[store_id] = title
        return title


def lookup_youtube_song_name(video_id):
    if not video_id:
        return "Nothing"
    elif video_id in song_names:
        return song_names[video_id]
    else:
        url = "https://www.youtube.com/watch?v=" + video_id
        video = pafy.new(url)
        title = video.title
        song_names[video_id] = title
        return title


@_admin
def clear_queue(bot, update):
    queued_player.clear_queue()


def queue(bot, update):
    storeId = update.chosen_inline_result["result_id"]
    user = update.chosen_inline_result["from_user"]
    song_name = lookup_song_name(storeId)
    queued_player.queue(
        {'store_id': storeId, 'load_song': player.get_gmusic_loader(api, storeId), 'name': song_name})
    print("QUEUED by", user["first_name"], ":", song_name)


def youtube_queue(bot, update):
    video_id = update.chosen_inline_result["result_id"]
    user = update.chosen_inline_result["from_user"]
    song_name = lookup_youtube_song_name(video_id)
    queued_player.queue({'store_id': video_id, 'load_song': player.get_youtube_loader(
        video_id), 'name': song_name})
    print("YT_QUEUED by", user["first_name"], ":", song_name)


def save_config(file="config.json", *args):
    config_file = open(file, 'r')
    config = json.loads(config_file.read())
    config_file.close()
    for key, value in args:
        config[key] = value
    config_file = open(file, 'w')
    config_file.write(json.dumps(config, indent=4, sort_keys=True))


def set_admin(bot, update):
    global admin_chat_id
    chat_id = update.message.chat_id
    if not admin_chat_id:
        admin_chat_id = chat_id
        save_config("ids.json", ('admin_chat_id', admin_chat_id))
        bot.send_message(text="You're admin now!", chat_id=chat_id)
    elif chat_id == admin_chat_id:
        bot.send_message(text="You already are admin!", chat_id=chat_id)
    else:
        bot.send_message(text="There can be only one!", chat_id=chat_id)


@_admin
def reset_bot(bot, update):
    save_config("ids.json", ('admin_chat_id', 0))
    queued_player.reset()
    exit_bot()


def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    return s.getsockname()[0]


@_admin
def send_ip(bot, update):
    text = "IP-Address: {}".format(get_ip_address())
    bot.send_message(text=text, chat_id=admin_chat_id)


@_admin
def toggle_password(bot, update):
    global session_password
    chat_id = update.message.chat_id
    if session_password:
        session_password = None
        session_clients.clear()
        bot.send_message(chat_id=chat_id, text="Password deactivated")
        return

    session_password = " "
    bot.send_message(
        chat_id=chat_id, text="Password is now enabled. Set a password with /setpassword [password]")


@_admin
def set_password(bot, update):
    global session_password
    chat_id = update.message.chat_id
    if not session_password:
        bot.send_message(
            chat_id=chat_id, text="Please enable password protection with /togglepassword first")
        return

    split = update.message.text.split(" ")
    if len(split) < 2:
        bot.send_message(
            chat_id=chat_id, text="Usage: /setpassword [password]")
        return

    password = split[1].strip()
    if not password:
        bot.send_message(chat_id=chat_id, text="Password can't be empty")
        return

    session_password = password
    session_clients.add(user_tuple_from_user(update.message.from_user))
    bot.send_message(chat_id=chat_id, text="Successfully changed password")


@_admin
def ban_user(bot, update):
    chat_id = update.message.chat_id
    global session_clients
    if chat_id in keyboard_sent:
        bot.send_message(
            chat_id=chat_id, text="Finish what you were doing first")
        return

    if not session_password:
        bot.send_message(chat_id=chat_id, text="Password is disabled")
        return

    if not session_clients:
        bot.send_message(chat_id=chat_id, text="No clients logged in")
        return

    keyboard = []

    for client_id, first_name in session_clients:
        keyboard.append(["{}) {}".format(client_id, first_name)])

    markup = replykeyboardmarkup.ReplyKeyboardMarkup(
        keyboard, one_time_keyboard=True, resize_keyboard=True)

    def _ban_action(ban_id):
        global session_clients
        global session_password
        ban_id = ban_id + 1
        session_clients = set(
            filter(lambda client: client[0] != ban_id, session_clients))
        del keyboard_sent[chat_id]
        session_password = " "
        hide_keyboard(bot, chat_id, "Banned user. Please set a new password.")

    keyboard_sent[chat_id] = _ban_action

    bot.send_message(chat_id=chat_id, text="Who should be banned?",
                     reply_markup=markup, reply_to_message_id=update.message.message_id)


@_admin
def set_quality(bot, update):
    chat_id = update.message.chat_id
    split = update.message.text.split(" ")
    if len(split) < 2:
        bot.send_message(
            chat_id=chat_id, text="Usage: /setquality [hi/med/low]")
        return

    quality = split[1]
    if quality in ["hi", "med", "low"]:
        player.quality = quality
        save_config(("quality", quality))
        bot.send_message(chat_id=chat_id, text="Successfully changes quality")
    else:
        bot.send_message(chat_id=chat_id, text="Invalid quality")
        return


exiting = False
exit_lock = threading.Lock()


@_admin
def exit_bot_command(bot, update):
    exit_bot()


def exit_bot(updater_stopped=False):
    with exit_lock:
        global exiting
        if exiting:
            print("ALREADY EXITING")
            return
        exiting = True

    def exit_job():
        print("EXITING ...")
        if not updater_stopped:
            updater.signal_handler(signum=SIGTERM, frame=None)
        print("Updater stopped")
        youtube_updater.stop()
        print("Youtube updater stopped")
        queued_player.close()
        print("Player closed")
        api.logout()
        print("EXIT")
        sys.exit(0)
    # There is a bug in python-telegram-bot that causes a deadlock if
    # updater.stop() is called from a handler...
    threading.Thread(target=exit_job, name="EXIT_THREAD").start()


with open("config.json", "r") as config_file:
    config = json.loads(config_file.read())
    secrets_location = config.get('secrets_location', "")
    del config

with open("ids.json", "r") as ids_file:
    ids = json.loads(ids_file.read())
    admin_chat_id = ids.get('admin_chat_id', 0)
    del ids

user, password, device_id, token, youtube_token, youtube_api_key = read_secrets()

session_clients = set()
session_password = None
if admin_chat_id:
    session_password = " "


api = Mobileclient(debug_logging=False)
if not api.login(user, password, device_id, "de_DE"):
    print("Failed to log in to gmusic")
    sys.exit(1)

queued_player = None
updater = None
youtube_updater = None


def run_player():
    global queued_player
    queued_player = player.Player(api)
    queued_player.run()

player_thread = threading.Thread(target=run_player, name="player_thread")
start_bot()
start_youtube_bot()
player_thread.start()


while(updater is None or youtube_updater is None):
    sleep(1)
try:
    updater.idle()
except InterruptedError:
    pass
exit_bot(True)
