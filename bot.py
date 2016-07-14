import json
from signal import SIGTERM
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
    secrets = open("secrets.json", "r")
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

    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('next', next_song))
    dispatcher.add_handler(
        CommandHandler('play', lambda b, u: queued_player.resume()))
    dispatcher.add_handler(
        CommandHandler('pause', lambda b, u: queued_player.pause()))
    dispatcher.add_handler(CommandHandler('skip', skip))
    dispatcher.add_handler(CommandHandler('showqueue', show_queue))
    dispatcher.add_handler(
        CommandHandler('currentsong', lambda b, u: show_current_song(b, u.message.chat_id)))
    dispatcher.add_handler(
        CommandHandler('clearqueue', lambda b, u: queued_player.clear_queue()))
    dispatcher.add_handler(CommandHandler('movesong', move_song))
    dispatcher.add_handler(CommandHandler('admin', set_admin))
    dispatcher.add_handler(CommandHandler('reset', reset_bot))
    dispatcher.add_handler(CommandHandler('exit', lambda b, u: exit_bot()))

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


def start(bot, update):
    bot.sendMessage(
        text="Type @gmusicqueuebot and search for a song", chat_id=update.message.chat_id)


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


def next_song(bot, update):
    def _next_job():
        queued_player.next()
        message = update.message
        show_current_song(bot, message.chat_id)
    threading.Thread(target=_next_job, name="next_thread").start()


def show_current_song(bot, chat_id):
    bot.send_message(chat_id=chat_id, text="Now playing: {}".format(
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


def save_config(*args):
    config_file = open('config.json', 'r')
    config = json.loads(config_file.read())
    config_file.close()
    for key, value in args:
        config[key] = value
    config_file = open('config.json', 'w')
    config_file.write(json.dumps(config, indent=4, sort_keys=True))


def set_admin(bot, update):
    global admin_chat_id
    chat_id = update.message.chat_id
    if not admin_chat_id:
        admin_chat_id = chat_id
        save_config(('admin_chat_id', admin_chat_id))
        bot.send_message(text="You're admin now!", chat_id=chat_id)
    elif chat_id == admin_chat_id:
        bot.send_message(text="You already are admin!", chat_id=chat_id)
    else:
        bot.send_message(text="There can be only one!", chat_id=chat_id)


def reset_bot(bot, update):
    if update.message.chat_id == admin_chat_id:
        save_config(('admin_chat_id', 0))
        queued_player.reset()
        exit_bot()

user, password, device_id, token, youtube_token, youtube_api_key = read_secrets()

config_file = open("config.json", "r")
config = json.loads(config_file.read())
admin_chat_id = config.get('admin_chat_id', 0)
config_file.close()

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

exiting = False


exit_lock = threading.Lock()


def exit_bot():
    with exit_lock:
        global exiting
        if exiting:
            return
        exiting = True

    def exit_job():
        print("EXITING ...")
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

while(updater is None or youtube_updater is None):
    sleep(1)
updater.idle()
exit_bot()
