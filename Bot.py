#  -*- coding: utf-8 -*-
import datetime
import json
import os
import sys
import threading
import urllib

from gmusicapi.clients.mobileclient import Mobileclient
import pyglet
from telegram import InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import InlineQueryHandler, ChosenInlineResultHandler
from telegram.ext.commandhandler import CommandHandler
from telegram.ext.messagehandler import MessageHandler, Filters
from telegram.ext.updater import Updater


def pretty(some_map):
    return json.dumps(some_map, indent=4, sort_keys=True)


def read_secrets():
    secrets = open("secrets.txt", "r")
    content = secrets.readlines()
    secrets.close()
    content = list(map(str.strip, content))
    return content


def start_bot():
    updater = Updater(token=token)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('next', lambda b, u: player.next()))
    dispatcher.add_handler(CommandHandler('play', lambda b, u: player.play()))
    dispatcher.add_handler(
        CommandHandler('pause', lambda b, u: player.pause()))
    dispatcher.add_handler(InlineQueryHandler(get_inline_handler()))
    dispatcher.add_handler(ChosenInlineResultHandler(queue))

    updater.start_polling()

    print("Updater running")


def start(bot, update):
    bot.sendMessage(
        text="Type @gmusicqueuebot and search for a song", chat_id=update.message.chat_id)


def search_song(query, max_results=10):
    results = api.search(query, max_results)
    songs = []
    for track in results["song_hits"]:
        song = track["track"]
        songs.append(song)
    return songs


def get_inline_handler():
    def get_inline_result(song):
        result = InlineQueryResultArticle(
            id=song["storeId"],
            title=song["title"],
            description="by {}".format(song["artist"]),
            input_message_content=InputTextMessageContent(
                "{} - {}".format(song["artist"], song["title"]))
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
    fname = "songs/" + "{}-{}-{}-{}{}{}".format(
        time.year, time.month, time.day, time.hour, time.minute, time.second) + ".mp3"
    file = open(fname, "wb")
    file.write(page.read())
    file.close()
    page.close()
    return fname


def queue(bot, update):
    storeId = update.chosen_inline_result["result_id"]
    fname = load_song(storeId)
    res = pyglet.media.load(fname)
    player.queue(res)
    player.play()
    print("QUEUED")

user, password, device_id, token = read_secrets()

api = Mobileclient(debug_logging=False)
if not api.login(user, password, device_id, "de_DE"):
    print("Failed to log in to gmusic")
    exit(1)

player = pyglet.media.Player()
player.play()

updater = None
threading.Thread(target=start_bot, name="bot_thread").start()

pyglet.app.run()
updater.stop()
player.delete()
api.logout()
for file in os.listdir("songs"):
    try:
        os.remove("songs/" + file)
    except PermissionError:
        pass

print("EXIT")
