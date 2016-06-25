import datetime
import os
import threading
import urllib

from gmusicapi import Mobileclient
import pyglet


def read_secrets():
    secrets = open("secrets.txt", "r")
    content = secrets.readlines()
    secrets.close()
    content = list(map(str.strip, content))
    return content[0], content[1], content[2], content[3]

user, password, device_id, token = read_secrets()

api = Mobileclient()
logged_in = api.login(user, password, device_id, "de_DE")
if not logged_in:
    print("login failed")
    exit(1)


def get_input(media, player):
    def wait_for_input():
        while(True):
            songName = input("What song?")
            if songName == "exit":
                pyglet.app.exit()
                break
            if songName == "next":
                player.next()
                continue
            search_results = api.search(songName, 10)

            songs = []
            for track in search_results["song_hits"]:
                song = track["track"]
                print(len(songs), song["artist"], song["title"])
                songs.append(song)

            choice = input("Which one?")
            choice = songs[int(choice)]
            url = api.get_stream_url(choice["storeId"])
            request = urllib.request.Request(url)
            page = urllib.request.urlopen(request)

            time = datetime.datetime.now()
            fname = "songs/" + "{}-{}-{}-{}{}{}".format(
                time.year, time.month, time.day, time.hour, time.minute, time.second) + ".mp3"
            file = open(fname, "wb")
            file.write(page.read())
            page.close()
            file.close()
            res = media.load(fname)
            player.queue(res)
            player.play()

    return wait_for_input

if not os.path.isdir("songs"):
    os.makedirs("songs")
player = pyglet.media.Player()
inputThread = threading.Thread(
    target=get_input(pyglet.media, player))
inputThread.start()
pyglet.app.run()
player.delete()
for file in os.listdir("songs"):
    try:
        os.remove("songs/" + file)
    except PermissionError:
        pass
