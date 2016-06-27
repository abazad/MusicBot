#  -*- coding: utf-8 -*-
from _functools import reduce
import datetime
import json
import os
import signal
import sys
import threading
import urllib

from gmusicapi.clients.mobileclient import Mobileclient
from telegram import InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import InlineQueryHandler, ChosenInlineResultHandler
from telegram.ext.commandhandler import CommandHandler
from telegram.ext.updater import Updater


def pretty(some_map):
    return json.dumps(some_map, indent=4, sort_keys=True)


def read_secrets():
    secrets = open("secrets.txt", "r")
    content = secrets.readlines()
    secrets.close()
    content = list(map(str.strip, content))
    return content


song_queue = []

playing = False


def queue_next_song():
    global playing
    if playing:
        return
    if len(song_queue) > 0:
        queue_next_song = song_queue.pop(0)["res"]
        player.queue(queue_next_song)
        player.play()
        playing = True


def start_bot():
    global updater
    updater = Updater(token=token)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(
        CommandHandler('next', lambda b, u: player.next_source(), queue_next_song()))
    dispatcher.add_handler(CommandHandler('play', lambda b, u: player.play()))
    dispatcher.add_handler(
        CommandHandler('pause', lambda b, u: player.pause()))
    dispatcher.add_handler(CommandHandler('showqueue', show_queue))
    dispatcher.add_handler(InlineQueryHandler(get_inline_handler()))
    dispatcher.add_handler(ChosenInlineResultHandler(queue))

    updater.start_polling()

    print("Updater running")


def start(bot, update):
    bot.sendMessage(
        text="Type @gmusicqueuebot and search for a song", chat_id=update.message.chat_id)


def show_queue(bot, update):
    message = "*Current queue:*\n"
    if len(song_queue) > 0:
        message += reduce("{}\n{}".format, map(lambda x:
                                               lookup_song_name(x["store_id"]), song_queue))
    else:
        message += "_empty..._"
    bot.send_message(
        chat_id=update.message.chat_id, text=message, parse_mode="markdown")


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
        # action("SONG")
    return inline_handler


def load_song(store_id):
    url = api.get_stream_url(store_id)
    request = urllib.request.Request(url)
    page = urllib.request.urlopen(request)

    time = datetime.datetime.now()
    fname = "songs/" + "{}-{}-{}-{}-{}-{}".format(
        time.year, time.month, time.day, time.hour, time.minute, time.second) + ".mp3"
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
    fname = load_song(storeId)
    res = pyglet.media.load(fname)
    song_queue.append({"store_id": storeId, "res": res})
    queue_next_song()
    print("QUEUED by", user["first_name"], ":", song_name)

user, password, device_id, token = read_secrets()

api = Mobileclient(debug_logging=False)
if not api.login(user, password, device_id, "de_DE"):
    print("Failed to log in to gmusic")
    sys.exit(1)

pyglet = None
player = None
updater = None


def test():
    print("test")
    global playing
    playing = False
    queue_next_song()


def run_piglet():
    global pyglet, player
    import pyglet
    pyglet = pyglet
    player = pyglet.media.Player()
    player.set_handler("on_player_eos", test)
    pyglet.app.run()

pyglet_thread = threading.Thread(target=run_piglet, name="pyglet_thread")
bot_thread = threading.Thread(target=start_bot, name="bot_thread")
pyglet_thread.start()
bot_thread.start()

exiting = False


def exit_bot(signum=None, frame=None):
    global exiting
    if exiting:
        return
    exiting = True
    print("EXITING {} ...".format(signum))
    updater.stop()
    pyglet.app.exit()
    player.delete()
    api.logout()
    for file in os.listdir("songs"):
        try:
            os.remove("songs/" + file)
        except PermissionError:
            pass

    print("EXIT")
    sys.exit(0)


def listen_exit():
    signal.signal(signal.SIGTERM, exit_bot)
    signal.signal(signal.SIGINT, exit_bot)
    signal.signal(signal.SIGABRT, exit_bot)

listen_exit()
print("LISTENING")
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
