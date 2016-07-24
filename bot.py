from concurrent.futures.thread import ThreadPoolExecutor
from gmusicapi.clients.mobileclient import Mobileclient
import json
import multiprocessing
from os import path
import pylru
from signal import SIGTERM
import socket
import sys
from telegram import InlineQueryResultArticle, InputTextMessageContent
from telegram.ext.commandhandler import CommandHandler
from telegram.ext.messagehandler import MessageHandler, Filters
from telegram.replykeyboardmarkup import ReplyKeyboardMarkup
import threading
from time import sleep

from telegram.ext import InlineQueryHandler, ChosenInlineResultHandler
from telegram.ext.updater import Updater
from telegram.replykeyboardhide import ReplyKeyboardHide

import player


# Utility methods
def save_config(file="config.json", *args):
    config_file = open(file, 'r')
    config = json.loads(config_file.read())
    config_file.close()
    for key, value in args:
        config[key] = value
    config_file = open(file, 'w')
    config_file.write(json.dumps(config, indent=4, sort_keys=True))


keyboard_sent = {}


def send_keyboard(bot, chat_id, text, items, action=None):
    keyboard = []
    for item in items:
        keyboard.append([item])

    markup = ReplyKeyboardMarkup(
        keyboard, one_time_keyboard=True, resize_keyboard=True)

    bot.send_message(chat_id=chat_id, text=text,
                     reply_markup=markup)

    if action:
        keyboard_sent[chat_id] = action


def hide_keyboard(bot, chat_id, message):
    markup = ReplyKeyboardHide()
    bot.send_message(
        chat_id=chat_id, text=message, reply_markup=markup, parse_mode="markdown")


def cancel_keyboard(bot, update):
    chat_id = update.message.chat_id
    if chat_id in keyboard_sent:
        del keyboard_sent[chat_id]
    hide_keyboard(bot, chat_id, "kk...")


def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    return s.getsockname()[0]


def handle_message(bot, update):
    chat_id = update.message.chat_id
    if chat_id in keyboard_sent:
        action = keyboard_sent[chat_id]
        action(bot, update)


def user_tuple_from_user(gmusic_user):
    return (gmusic_user.id,  gmusic_user.first_name)


def is_logged_in(user):
    return not session_password or user_tuple_from_user(user) in session_clients


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


def get_queue_keyboard_items():
    keyboard_items = []
    queue = queued_player.get_queue()
    for i in range(0, len(queue)):
        keyboard_items.append("{}) {}".format(i + 1, queue[i]['name']))
    return keyboard_items


song_names = pylru.lrucache(512)


def lookup_gmusic_song_name(store_id):
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


def lookup_soundcloud_track(song_id):
    if not song_id:
        return "Nothing"
    elif song_id in song_names:
        return song_names[song_id]
    else:
        track = soundcloud_client.get("/tracks/{}".format(song_id))
        return track


# Decorators

def admin_command(func):
    def _admin_func(bot, update):
        if admin_chat_id == update.message.chat_id:
            func(bot, update)
        else:
            bot.send_message(
                chat_id=update.message.chat_id, text="This command is for admins only")
    return _admin_func


def password_protected_command(func):
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


def keyboard_answer_handler(func):
    def _handler(bot, update):
        text = update.message.text
        if ")" not in text:
            return
        c = text.split(")")[0]
        if str.isdecimal(c):
            func(int(c))
        else:
            print("INVALID CHOICE:", c)
    return _handler


thread_pool = ThreadPoolExecutor(max(4, multiprocessing.cpu_count() * 2))


def multithreaded_command(func):
    def _multithreaded_func(bot, update):
        thread_pool.submit(func, bot, update)
    return _multithreaded_func


# Publicly available commands

def start(bot, update):
    if not is_logged_in(update.message.from_user):
        bot.send_message(
            chat_id=update.message.chat_id, text="Please log in with /login [password]")
        return
    bot.send_message(
        text="Type @gmusicqueuebot and search for a song", chat_id=update.message.chat_id)


session_clients = set()


def login(bot, update):
    chat_id = update.message.chat_id
    user = update.message.from_user
    if not session_password:
        bot.send_message(chat_id=chat_id, text="There is no password")
        return

    user_tuple = user_tuple_from_user(user)

    if user_tuple in session_clients:
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
        session_clients.add(user_tuple)
        bot.send_message(chat_id=chat_id, text="Successfully logged in")
    else:
        bot.send_message(chat_id=chat_id, text="Wrong password")


def answer_queue(bot, update):
    message = get_queue_message()
    bot.send_message(
        chat_id=update.message.chat_id, text=message, parse_mode="markdown")


def answer_current_song(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text="Now playing: {}".format(
        queued_player.get_current_song()['name']))


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


# Password protected commands

@multithreaded_command
@password_protected_command
def skip(bot, update):
    chat_id = update.message.chat_id
    queue = queued_player.get_queue()
    if len(queue) == 0:
        bot.send_message(chat_id=chat_id,
                         text="No songs in queue", reply_to_message_id=update.message.message_id)
        return

    if chat_id in keyboard_sent:
        return

    @keyboard_answer_handler
    def _skip_action(queue_position):
        queue_position -= 1
        queued_player.skip_song(queue_position=queue_position)
        hide_keyboard(bot, chat_id, get_queue_message())
        del keyboard_sent[chat_id]

    keyboard_items = get_queue_keyboard_items()
    send_keyboard(bot, chat_id, "What song?", keyboard_items, _skip_action)


@multithreaded_command
@password_protected_command
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

    @keyboard_answer_handler
    def _first_action(source_position):
        source_position -= 1
        source = queue[source_position]
        queue.pop(source_position)
        keyboard_items = get_queue_keyboard_items()

        @keyboard_answer_handler
        def _second_action(target_position):
            target_position -= 1
            queue.insert(target_position, source)
            hide_keyboard(bot, chat_id, get_queue_message())
            del keyboard_sent[chat_id]

        send_keyboard(
            bot, chat_id,  "Before what song should it be?", keyboard_items, _second_action)

    keyboard_items = get_queue_keyboard_items()
    send_keyboard(
        bot, chat_id, "What song do you want to move?", keyboard_items, _first_action)


@password_protected_command
def play(bot, update):
    queued_player.resume()


@password_protected_command
def pause(bot, update):
    queued_player.pause()


@password_protected_command
def next_song(bot, update):
    # This is not using the threadpool because the thread name is important.
    #
    #
    #
    # Sorry.
    def _next_job():
        queued_player.next()
        answer_current_song(bot, update)
    threading.Thread(target=_next_job, name="next_thread").start()


def get_gmusic_inline_handler():
    def _search_song(query):
        max_results = 20
        results = api.search(query, max_results)
        songs = []
        for track in results["song_hits"]:
            song = track["track"]
            songs.append(song)
        return songs

    def _get_inline_result_article(song):
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

    @multithreaded_command
    def _inline_handler(bot, update):
        if not is_logged_in(update.inline_query.from_user):
            return

        query = update.inline_query.query
        if not query:
            return

        search_results = _search_song(query)
        results = list(map(_get_inline_result_article, search_results))
        bot.answerInlineQuery(update.inline_query.id, results)

    return _inline_handler


def get_youtube_inline_handler():
    def _search_song(query):
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

    def _get_inline_result_article(song):
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

    @multithreaded_command
    def _inline_handler(bot, update):
        if not is_logged_in(update.inline_query.from_user):
            return

        query = update.inline_query.query
        if not query:
            return

        search_results = _search_song(query)
        results = list(map(_get_inline_result_article, search_results))
        bot.answerInlineQuery(update.inline_query.id, results)

    return _inline_handler


def get_soundcloud_inline_handler():
    def _search_song(query):
        return soundcloud_client.get("tracks/", q=query)

    def _get_inline_result_article(track):
        song_id = track.id
        title = track.title
        song_names[song_id] = track
        description = track.user['username']
        result = InlineQueryResultArticle(
            id=song_id,
            title=title,
            description=description,
            input_message_content=InputTextMessageContent(title),
            thumb_url=track.artwork_url
        )
        return result

    @multithreaded_command
    def _inline_handler(bot, update):
        if not is_logged_in(update.inline_query.from_user):
            return

        query = update.inline_query.query
        if not query:
            return

        search_results = _search_song(query)
        results = list(map(_get_inline_result_article, search_results))
        bot.answerInlineQuery(update.inline_query.id, results)

    return _inline_handler


# Since inline query results can be cached, the queue methods have to
# check for client authentication too

@multithreaded_command
def gmusic_queue(bot, update):
    storeId = update.chosen_inline_result["result_id"]
    user = update.chosen_inline_result["from_user"]

    if not is_logged_in(user):
        return

    song_name = lookup_gmusic_song_name(storeId)
    queued_player.queue(
        {'store_id': storeId, 'load_song': player.get_gmusic_loader(api, storeId), 'name': song_name})
    print("GM_QUEUED by", user["first_name"], ":", song_name)


@multithreaded_command
def youtube_queue(bot, update):
    video_id = update.chosen_inline_result["result_id"]
    user = update.chosen_inline_result["from_user"]

    if not is_logged_in(user):
        return

    song_name = lookup_youtube_song_name(video_id)
    queued_player.queue({'store_id': video_id, 'load_song': player.get_youtube_loader(
        video_id), 'name': song_name})
    print("YT_QUEUED by", user["first_name"], ":", song_name)


@multithreaded_command
def soundcloud_queue(bot, update):
    song_id = update.chosen_inline_result["result_id"]
    user = update.chosen_inline_result["from_user"]

    if not is_logged_in(user):
        return

    track = lookup_soundcloud_track(song_id)
    queued_player.queue({'store_id': song_id, 'load_song': player.get_soundcloud_loader(
        soundcloud_client, track), 'name': track.title})
    print("SC_QUEUED by", user["first_name"], ":", track.title)


# Admin commands

@admin_command
def clear_queue(bot, update):
    queued_player.clear_queue()


@admin_command
def reset_bot(bot, update):
    save_config("ids.json", ('admin_chat_id', 0))
    queued_player.reset()
    exit_bot()


@multithreaded_command
@admin_command
def send_ip(bot, update):
    text = "IP-Address: {}".format(get_ip_address())
    bot.send_message(text=text, chat_id=admin_chat_id)


@admin_command
def toggle_password(bot, update):
    global session_password
    chat_id = update.message.chat_id
    if session_password:
        session_password = None
        session_clients.clear()
        bot.send_message(chat_id=chat_id, text="Password disabled")
    else:
        session_password = " "
        bot.send_message(
            chat_id=chat_id, text="Password is now enabled. Set a password with /setpassword [password]")


@admin_command
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

    gmusic_password = split[1].strip()
    if not gmusic_password:
        bot.send_message(chat_id=chat_id, text="Password can't be empty")
        return

    session_password = gmusic_password
    session_clients.add(user_tuple_from_user(update.message.from_user))
    bot.send_message(
        chat_id=chat_id, text="Successfully changed password")


@multithreaded_command
@admin_command
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

    text = "Who should be banned?"
    keyboard_items = list(
        map(lambda client_tuple: "{}) {}".format(client_tuple[0], client_tuple[1]), session_clients))

    def _ban_action(ban_id):
        global session_clients
        global session_password
        ban_id = ban_id + 1
        session_clients = set(
            filter(lambda client: client[0] != ban_id, session_clients))
        del keyboard_sent[chat_id]
        session_password = " "
        hide_keyboard(
            bot, chat_id, "Banned user. Please set a new password.")

    send_keyboard(bot, chat_id, text, keyboard_items, _ban_action)


@admin_command
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


@admin_command
def exit_bot_command(bot, update):
    exit_bot()


# Onetime bot startup methods

def run_player():
    global queued_player
    queued_player = player.Player(api)
    queued_player.run()


def start_gmusic_bot():
    global gmusic_updater
    gmusic_updater = Updater(token=gmusic_token)
    dispatcher = gmusic_updater.dispatcher

    dispatcher.add_handler(MessageHandler([Filters.text], handle_message))

    # public commands
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('showqueue', answer_queue))
    dispatcher.add_handler(CommandHandler('currentsong', answer_current_song))
    dispatcher.add_handler(CommandHandler('cancel', cancel_keyboard))
    dispatcher.add_handler(CommandHandler('login', login))

    # gmusic_password protected commands
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

    dispatcher.add_handler(InlineQueryHandler(get_gmusic_inline_handler()))
    dispatcher.add_handler(ChosenInlineResultHandler(gmusic_queue))

    gmusic_updater.start_polling()


def start_youtube_bot():
    global youtube_updater
    youtube_updater = Updater(token=youtube_token)
    dispatcher = youtube_updater.dispatcher

    dispatcher.add_handler(InlineQueryHandler(get_youtube_inline_handler()))
    dispatcher.add_handler(ChosenInlineResultHandler(youtube_queue))
    youtube_updater.start_polling()


def start_soundcloud_bot():
    global soundcloud_updater
    soundcloud_updater = Updater(token=soundcloud_token)
    dispatcher = soundcloud_updater.dispatcher

    dispatcher.add_handler(InlineQueryHandler(get_soundcloud_inline_handler()))
    dispatcher.add_handler(ChosenInlineResultHandler(soundcloud_queue))
    soundcloud_updater.start_polling()


exiting = False
exit_lock = threading.Lock()


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
            gmusic_updater.signal_handler(signum=SIGTERM, frame=None)
        print("GMusic Updater stopped")
        youtube_updater.stop()
        print("YouTube updater stopped")
        soundcloud_updater.stop()
        print("SoundCloud updater stopped")
        queued_player.close()
        print("Player closed")
        api.logout()
        print("EXIT")
        sys.exit(0)
    # There is a bug in python-telegram-bot that causes a deadlock if
    # gmusic_updater.stop() is called from a handler...
    threading.Thread(target=exit_job, name="EXIT_THREAD").start()


# Load config and secrets
with open("config.json", "r") as config_file:
    config = json.loads(config_file.read())
    secrets_location = config.get('secrets_location', "")
    secrets_path = path.join(secrets_location, "secrets.json")
    del config

with open(secrets_path, "r") as secrets_file:
    content = secrets_file.read()
    content = json.loads(content)
    content = {k: str.strip(v) for k, v in content.items()}
    try:
        gmusic_user = content["gmusic_username"]
        gmusic_password = content["gmusic_password"]
        gmusic_device_id = content["gmusic_device_id"]
        gmusic_token = content["gmusic_bot_token"]
    except KeyError:
        print("Missing GMusic secrets")
        exit(2)

    youtube_token = content.get("youtube_bot_token", None)
    youtube_api_key = content.get("youtube_api_key", None)
    soundcloud_token = content.get("soundcloud_bot_token", None)
    soundcloud_id = content.get("soundcloud_id", None)
    del content


if path.isfile("ids.json"):
    with open("ids.json", "r") as ids_file:
        ids = json.loads(ids_file.read())
        admin_chat_id = ids.get('admin_chat_id', 0)
        del ids
else:
    admin_chat_id = 0


session_password = None
if admin_chat_id:
    session_password = " "


api = Mobileclient(debug_logging=False)
if not api.login(gmusic_user, gmusic_password, gmusic_device_id, "de_DE"):
    print("Failed to log in to gmusic")
    sys.exit(1)

if soundcloud_id and soundcloud_token:
    import soundcloud
    soundcloud_client = soundcloud.Client(client_id=soundcloud_id)

queued_player = None
gmusic_updater = None
youtube_updater = None
soundcloud_updater = None


start_gmusic_bot()

if youtube_token and youtube_api_key:
    import pafy
    start_youtube_bot()
else:
    youtube_updater = True

if soundcloud_token and soundcloud_id:
    start_soundcloud_bot()
else:
    soundcloud_updater = True


player_thread = threading.Thread(target=run_player, name="player_thread")
player_thread.start()


# Wait until all updaters are initialized
while(not (gmusic_updater and youtube_updater and soundcloud_updater)):
    sleep(1)
try:
    gmusic_updater.idle()
except InterruptedError:
    pass
exit_bot(True)
