from concurrent.futures.thread import ThreadPoolExecutor
from enum import Enum
import json
import multiprocessing
import os
import signal
import socket
import sys
import threading
import time

import colorama
from telegram import InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import InlineQueryHandler, ChosenInlineResultHandler
from telegram.ext.commandhandler import CommandHandler
from telegram.ext.messagehandler import MessageHandler, Filters
from telegram.ext.updater import Updater
from telegram.replykeyboardhide import ReplyKeyboardHide
from telegram.replykeyboardmarkup import ReplyKeyboardMarkup

from telegrammusicbot import player, music_apis
from telegrammusicbot.plugin_handler import PluginLoader

try:
    os.chdir("..")
except:
    print("Could not change dir")
    sys.exit(100)

config_dir = "config"
config_path = os.path.join(config_dir, "config.json")
ids_path = os.path.join(config_dir, "ids.json")

# Initialize colorama for colored output
colorama.init()


# Utility methods

def save_config(file, **kwargs):
    with open(file, 'r') as config_file:
        config = json.loads(config_file.read())

    for key in kwargs:
        config[key] = kwargs[key]

    with open(file, 'w') as config_file:
        config_file.write(json.dumps(config, indent=4, sort_keys=True))


keyboard_sent = {}


def send_keyboard(bot, chat_id, text, items, action=None):
    keyboard = []
    for item in items:
        keyboard.append([item])

    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)

    if action:
        keyboard_sent[chat_id] = action


def hide_keyboard(bot, chat_id, message):
    markup = ReplyKeyboardHide()
    bot.send_message(chat_id=chat_id, text=message, reply_markup=markup, parse_mode="markdown")


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
        if action(bot, update):
            del keyboard_sent[chat_id]


def user_tuple_from_user(user):
    return (user.id, user.first_name)


def is_logged_in(user):
    return (not enable_session_password) or (user_tuple_from_user(user) in session_clients)


def get_current_song_message():
    return "Now playing: {}".format(queued_player.get_current_song())


def get_queue_message():
    queue = queued_player.get_queue()
    message = "\n"
    header_str = "*Current queue:*"
    if len(queue) > 0:
        message = header_str + "\n" + message.join(map(str, queue))
    else:
        message = message.join([header_str, "_empty..._"])
    return message


def get_queue_keyboard_items():
    keyboard_items = []
    queue = queued_player.get_queue()
    for i in range(0, len(queue)):
        keyboard_items.append("{}) {}".format(i + 1, queue[i]))
    return keyboard_items


class Notificator(object):

    class NotificationCause(Enum):
        next_song = get_current_song_message
        queue_add = lambda song: "Added to queue: " + str(song)
        queue_remove = lambda song: "Removed from queue: " + str(song)

    class _Subscriber(object):

        def __init__(self, chat_id, silent):
            self.chat_id = chat_id
            self.silent = silent

        def __hash__(self):
            return hash(self.chat_id)

        def __eq__(self, other):
            return self.chat_id == other.chat_id

    _subscribers = set()
    _bot = None

    @staticmethod
    def subscribe(bot, update):
        if not Notificator._bot:
            Notificator._bot = bot
        chat_id = update.message.chat_id

        def _action(bot, update):
            text = update.message.text.lower()
            if "y" in text:
                silent = False
            else:
                silent = True

            subscriber = Notificator._Subscriber(chat_id, silent)
            Notificator._subscribers.add(subscriber)
            hide_keyboard(bot, chat_id, "Subscribed.")
            return True

        keyboard_items = ["Yes", "No"]
        send_keyboard(bot, chat_id, "Do you want to receive notifications?", keyboard_items, _action)

    @staticmethod
    def unsubscribe(bot, update):
        chat_id = update.message.chat_id
        subscriber = Notificator._Subscriber(chat_id, True)
        Notificator._subscribers.remove(subscriber)
        bot.send_message(chat_id=chat_id, text="Unsubscribed.")

    @staticmethod
    def notify(cause):
        if Notificator._bot:
            for subscriber in Notificator._subscribers:
                chat_id = subscriber.chat_id
                silent = subscriber.silent
                Notificator._bot.send_message(chat_id=chat_id, text=cause, disable_notification=silent)

    @staticmethod
    def is_subscriber(chat_id):
        return Notificator._Subscriber(chat_id, True) in Notificator._subscribers


# Decorators

def admin_command(func):
    def _admin_func(bot, update):
        if admin_chat_id == update.message.chat_id:
            return func(bot, update)
        else:
            bot.send_message(chat_id=update.message.chat_id, text="This command is for admins only")
            return None
    return _admin_func


def password_protected_command(func):
    def _password_protected_func(bot, update):
        chat_id = update.message.chat_id
        if enable_session_password and not session_password:
            bot.send_message(chat_id=chat_id, text="Admin hasn't decided which password to use yet")
            return None

        user = update.message.from_user
        if is_logged_in(user):
            return func(bot, update)
        else:
            bot.send_message(chat_id=chat_id, text="Please log in with /login [password]")
            return None

    return _password_protected_func


def keyboard_answer_handler(func):
    def _handler(bot, update):
        text = update.message.text
        if ")" not in text:
            return False
        c = text.split(")")[0]
        if str.isdecimal(c):
            return func(int(c))
        else:
            print("INVALID CHOICE:", c)
            return False
    return _handler


thread_pool = ThreadPoolExecutor(max(4, multiprocessing.cpu_count() * 2))


def multithreaded_command(func):
    def _multithreaded_func(bot, update):
        thread_pool.submit(func, bot, update)
    return _multithreaded_func


# Publicly available commands

def start(bot, update):
    if not is_logged_in(update.message.from_user):
        bot.send_message(chat_id=update.message.chat_id, text="Please log in with /login [password]")
        return
    bot.send_message(text="Type @gmusicqueuebot and search for a song", chat_id=update.message.chat_id)


session_clients = set()


def login(bot, update):
    chat_id = update.message.chat_id
    user = update.message.from_user
    if not enable_session_password:
        bot.send_message(chat_id=chat_id, text="There is no password")
        return

    user_tuple = user_tuple_from_user(user)

    if user_tuple in session_clients:
        bot.send_message(chat_id=chat_id, text="You are already logged in")
        return

    if not session_password:
        bot.send_message(chat_id=chat_id, text="Admin hasn't decided which password to use yet")
        return

    split = update.message.text.split(" ")
    if len(split) < 2:
        bot.send_message(chat_id=chat_id, text="Usage: /login [password]")
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
    bot.send_message(chat_id=update.message.chat_id, text=message, parse_mode="markdown")


def answer_current_song(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=get_current_song_message())


def set_admin(bot, update):
    global admin_chat_id
    chat_id = update.message.chat_id
    if not admin_chat_id:
        admin_chat_id = chat_id
        save_config(ids_path, admin_chat_id=admin_chat_id)
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
    if not queue:
        bot.send_message(chat_id=chat_id, text="No songs in queue")
        return

    @keyboard_answer_handler
    def _skip_action(queue_position):
        queue_position -= 1
        queued_player.skip_song(queue_position)
        hide_keyboard(bot, chat_id, get_queue_message())
        return True

    keyboard_items = get_queue_keyboard_items()
    send_keyboard(bot, chat_id, "What song?", keyboard_items, _skip_action)


@multithreaded_command
@password_protected_command
def move_song(bot, update):
    message = update.message
    chat_id = message.chat_id
    queue = queued_player.get_queue()

    if len(queue) <= 1:
        bot.send_message(chat_id=chat_id, text="Not >1 songs in queue")
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
            return True

        send_keyboard(bot, chat_id, "Before what song should it be?", keyboard_items, _second_action)
        return False

    keyboard_items = get_queue_keyboard_items()
    send_keyboard(bot, chat_id, "What song do you want to move?", keyboard_items, _first_action)


@password_protected_command
def play(bot, update):
    queued_player.resume()


@password_protected_command
def pause(bot, update):
    queued_player.pause()


@multithreaded_command
@password_protected_command
def next_song(bot, update):
    queued_player.next()
    if not Notificator.is_subscriber(update.message.chat_id):
        answer_current_song(bot, update)


def get_inline_handler(api, suggest=False):
    def _get_inline_result_article(song):
        try:
            artist = song.artist
            title = song.title
            str_rep = str(song)
            if artist and title:
                description = "by {}".format(artist)
            else:
                title = str_rep
                description = ""

            result = InlineQueryResultArticle(
                id=song.song_id,
                title=title,
                description=description,
                input_message_content=InputTextMessageContent(str_rep)
            )

            url = song.albumArtUrl
            if url:
                result.thumb_url = url
            return result
        except Exception as e:
            print(e)
            return None

    @multithreaded_command
    def _inline_handler(bot, update):
        if not is_logged_in(update.inline_query.from_user):
            return

        query = update.inline_query.query
        if query:
            song_list = api.search_song(query)
            # set server-side caching time to default (300 seconds)
            cache_time = 300
        elif suggest:
            song_list = queued_player.get_song_suggestions(20)
            cache_time = 20
        else:
            return

        # Filter duplicate songs
        seen = set()
        seen_add = seen.add

        def _seen_add(song):
            if song in seen:
                return False
            else:
                seen_add(song)
                return True

        song_list = filter(_seen_add, song_list)

        results = list(map(_get_inline_result_article, song_list))
        bot.answerInlineQuery(update.inline_query.id, results, cache_time=cache_time)

    return _inline_handler


def queue(api):
    @multithreaded_command
    def _queue(bot, update):
        song_id = update.chosen_inline_result["result_id"]
        user = update.chosen_inline_result["from_user"]

        if not is_logged_in(user):
            return

        song = api.lookup_song(song_id)
        print("QUEUED by", user["first_name"], ":", song)
        queued_player.queue(song)

    return _queue


# Admin commands

@admin_command
def clear_queue(bot, update):
    queued_player.clear_queue()


@admin_command
def reset_bot(bot, update):
    save_config(ids_path, admin_chat_id=0)
    queued_player.close()
    gmusic_api.reset()
    exit_bot()


@multithreaded_command
@admin_command
def send_ip(bot, update):
    text = "IP-Address: {}".format(get_ip_address())
    bot.send_message(text=text, chat_id=admin_chat_id)


@admin_command
def toggle_password(bot, update):
    global enable_session_password
    chat_id = update.message.chat_id
    if enable_session_password:
        enable_session_password = False
        session_clients.clear()
        bot.send_message(chat_id=chat_id, text="Password disabled")
    else:
        enable_session_password = True
        bot.send_message(chat_id=chat_id, text="Password is now enabled. Set a password with /setpassword [password]")
    save_config(config_path, enable_session_password=enable_session_password)


@admin_command
def set_password(bot, update):
    global session_password
    chat_id = update.message.chat_id
    if not enable_session_password:
        bot.send_message(chat_id=chat_id, text="Please enable password protection with /togglepassword first")
        return

    split = update.message.text.split(" ")
    if len(split) < 2:
        bot.send_message(chat_id=chat_id, text="Usage: /setpassword [password]")
        return

    password = split[1].strip()
    if not password:
        bot.send_message(chat_id=chat_id, text="Password can't be empty")
        return

    session_password = password
    session_clients.add(user_tuple_from_user(update.message.from_user))
    bot.send_message(chat_id=chat_id, text="Successfully changed password")


@multithreaded_command
@admin_command
def ban_user(bot, update):
    chat_id = update.message.chat_id
    global session_clients

    if not enable_session_password:
        bot.send_message(chat_id=chat_id, text="Password is disabled")
        return

    if not session_clients:
        bot.send_message(chat_id=chat_id, text="No clients logged in")
        return

    text = "Who should be banned?"
    keyboard_items = list(map(lambda client_tuple: "{}) {}".format(client_tuple[0], client_tuple[1]), session_clients))

    def _ban_action(ban_id):
        global session_clients
        global session_password
        ban_id = ban_id + 1
        session_clients = set(filter(lambda client: client[0] != ban_id, session_clients))
        session_password = None
        hide_keyboard(bot, chat_id, "Banned user. Please set a new password.")
        return True

    send_keyboard(bot, chat_id, text, keyboard_items, _ban_action)


@admin_command
def set_quality(bot, update):
    chat_id = update.message.chat_id
    split = update.message.text.split(" ")
    if len(split) < 2:
        bot.send_message(chat_id=chat_id, text="Usage: /setquality [hi/med/low]")
        return

    quality = split[1]
    try:
        gmusic_api.set_quality(quality)
        save_config(config_path, quality=quality)
        bot.send_message(chat_id=chat_id, text="Successfully changed quality")
    except ValueError:
        bot.send_message(chat_id=chat_id, text="Invalid quality")
        return


@admin_command
def exit_bot_command(bot, update):
    exit_bot()


@multithreaded_command
@admin_command
def remove_from_playlist(bot, update):
    chat_id = update.message.chat_id
    playlist = gmusic_api.get_playlist()

    if not playlist:
        bot.send_message(chat_id=chat_id, text="The playlist is empty.")
        return

    def _action(bot, update):
        text = update.message.text
        if "|" not in text:
            return False

        song_id = text.split("|")[1].strip()
        song = gmusic_api.lookup_song(song_id)

        if song not in playlist:
            bot.send_message(chat_id=chat_id, text="That song is not in the BotPlaylist")

        gmusic_api.remove_from_playlist(song)

        hide_keyboard(bot, chat_id, "Removed from playlist: " + str(song))
        return True

    keyboard_items = list(map(lambda song: "{} | {}".format(song, song.song_id), sorted(playlist)))

    send_keyboard(bot, chat_id, "What song should be removed?", keyboard_items, _action)


@admin_command
def reload_station_songs(bot, update):
    # Drop the pre-fetched next_songs list. The list will be refilled when needed.
    gmusic_api.reload()
    bot.send_message(chat_id=update.message.chat_id, text="Reloaded station songs.")


# Onetime bot startup methods

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

    dispatcher.add_handler(CommandHandler('subscribe', Notificator.subscribe))
    dispatcher.add_handler(CommandHandler('unsubscribe', Notificator.unsubscribe))

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
    dispatcher.add_handler(CommandHandler('stationremove', remove_from_playlist))
    dispatcher.add_handler(CommandHandler('stationreload', reload_station_songs))

    # Load additional Commands
    for plugin in plugin_loader.get_plugins():
        dispatcher.add_handler(CommandHandler(plugin.get_label(), plugin.run_command))

    dispatcher.add_handler(InlineQueryHandler(get_inline_handler(gmusic_api, enable_suggestions)))
    dispatcher.add_handler(ChosenInlineResultHandler(queue(gmusic_api)))

    gmusic_updater.start_polling()


def start_youtube_bot():
    global youtube_updater
    youtube_updater = Updater(token=youtube_token)
    dispatcher = youtube_updater.dispatcher

    dispatcher.add_handler(InlineQueryHandler(get_inline_handler(youtube_api)))
    dispatcher.add_handler(ChosenInlineResultHandler(queue(youtube_api)))
    youtube_updater.start_polling()


def start_soundcloud_bot():
    global soundcloud_updater
    soundcloud_updater = Updater(token=soundcloud_token)
    dispatcher = soundcloud_updater.dispatcher

    dispatcher.add_handler(InlineQueryHandler(get_inline_handler(soundcloud_api)))
    dispatcher.add_handler(ChosenInlineResultHandler(queue(soundcloud_api)))
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
            gmusic_updater.signal_handler(signum=signal.SIGTERM, frame=None)
        print("GMusic Updater stopped")
        youtube_updater.stop()
        print("YouTube updater stopped")
        soundcloud_updater.stop()
        print("SoundCloud updater stopped")
        queued_player.close()
        print("Player closed")
        print("EXIT")
        sys.exit(0)
    # There is a bug in python-telegram-bot that causes a deadlock if
    # gmusic_updater.stop() is called from a handler...
    threading.Thread(target=exit_job, name="EXIT_THREAD").start()


# Load config and secrets
try:
    with open(config_path, "r") as config_file:
        config = json.loads(config_file.read())
        secrets_location = config.get('secrets_location', "config")
        secrets_path = os.path.join(secrets_location, "secrets.json")
        enable_updates = config.get("auto_updates", 0)
        enable_suggestions = config.get("suggest_songs", 0)
        enable_session_password = config.get("enable_session_password", 1)
        load_plugins = config.get("load_plugins", 1)
except IOError as e:
    print("Could not open config.json:", e)
    exit(3)

try:
    with open(secrets_path, "r") as secrets_file:
        secrets = json.loads(secrets_file.read())
        secrets = {k: str.strip(v) for k, v in secrets.items()}
        try:
            gmusic_token = secrets["gmusic_bot_token"]
        except KeyError:
            print("Missing GMusic token")
            sys.exit(1)

        youtube_token = secrets.get("youtube_bot_token", None)
        soundcloud_token = secrets.get("soundcloud_bot_token", None)
except IOError:
    print("Could not open secrets.json")

if os.path.isfile(ids_path):
    with open(ids_path, "r") as ids_file:
        ids = json.loads(ids_file.read())
        admin_chat_id = ids.get('admin_chat_id', 0)
        del ids
else:
    admin_chat_id = 0


session_password = None


plugin_loader = PluginLoader()
if load_plugins:
    plugin_loader.load_plugins()

try:
    gmusic_api = music_apis.GMusicAPI(config_dir, config, secrets)
    if soundcloud_token:
        soundcloud_api = music_apis.SoundCloudAPI(config_dir, config, secrets)
    if youtube_token:
        youtube_api = music_apis.YouTubeAPI(config_dir, config, secrets)
except KeyError as e:
    print(e)
    sys.exit(2)

queued_player = player.Player(gmusic_api, Notificator)
gmusic_updater = None
youtube_updater = None
soundcloud_updater = None


def main():
    if enable_updates:
        print("Checking for updates...")
        from telegrammusicbot import updater
        with open(os.devnull, 'w') as devnull:
            if updater.update(output=devnull):
                print("Restarting after update...")
                os.execl(sys.executable, sys.executable, *sys.argv)
                sys.exit(0)
            else:
                print("No updates found.")

    global youtube_updater
    global soundcloud_updater

    start_gmusic_bot()

    if youtube_token:
        start_youtube_bot()
    else:
        youtube_updater = True

    if soundcloud_token:
        start_soundcloud_bot()
    else:
        soundcloud_updater = True

    queued_player.run()

    # Wait until all updaters are initialized
    while(not (gmusic_updater and youtube_updater and soundcloud_updater)):
        time.sleep(1)

    try:
        gmusic_updater.idle()
    except InterruptedError:
        pass
    exit_bot(True)

if __name__ == "__main__":
    main()
