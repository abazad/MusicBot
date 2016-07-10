import gc
import json
import os
from random import choice
import threading
import time
import urllib
import pafy


def get_youtube_loader(video_id):
    def _youtube_loader():
        url = "https://www.youtube.com/watch?v=" + video_id

        video = pafy.new(url)
        audios = video.audiostreams
        audio = None
        for a in filter(lambda a: a.extension == "m4a", audios):
            if audio is None:
                audio = a
            elif a.bitrate > audio.bitrate:
                audio = a
        if audio is None:
            print("ERROR, NO m4a!")
            audio = video.getbestaudio()

        fname = "songs/" + video.videoid + "." + audio.extension

        if not os.path.isdir("songs"):
            os.mkdir("songs")

        if not os.path.isfile(fname):
            audio.download(filepath=fname, quiet=True)

        return fname
    return _youtube_loader


def get_gmusic_loader(api, store_id):
    def _gmusic_loader():
        fname = "songs/" + store_id + '.mp3'

        if not os.path.isfile(fname):
            url = api.get_stream_url(store_id)
            request = urllib.request.Request(url)
            page = urllib.request.urlopen(request)

            if not os.path.isdir("songs"):
                os.mkdir("songs")

            file = open(fname, "wb")
            file.write(page.read())
            file.close()
            page.close()

        return fname
    return _gmusic_loader


class SongProvider(object):

    def __init__(self, api):
        self._api = api
        self._playlist_id = None
        self._playlist_token = None
        self._station_id = None
        self._last_played = []
        self._try_restore_ids()

    def get_song(self):
        self._create_playlist()
        if not self._station_id:
            self._create_station()
        song = self._api.get_station_tracks(
            self._station_id, recently_played_ids=self._last_played)
        if song:
            song = choice(song)
            store_id = song['storeId']
            name = "{} - {}".format(song["artist"], song["title"])
            song = {'store_id': store_id,
                    'load_song': get_gmusic_loader(self._api, store_id),
                    'name': name}
            self._last_played.append(store_id)
            return song
        # Fallback song
        store_id = "Tj6fhurtstzgdpvfm4xv6i5cei4"
        return {'store_id': store_id,
                'load_song': get_gmusic_loader(self._api, store_id),
                'name': "Mickie Krause - Biste braun, kriegste Fraun"}

    def add_played(self, song):
        self._create_playlist()
        store_id = song['store_id']
        self._api.add_songs_to_playlist(self._playlist_id, store_id)
        self._last_played.append(store_id)
        if len(self._last_played) > 20:
            self._last_played = self._last_played[-20::]

    def _create_playlist(self):
        if not self._playlist_id:
            self._playlist_id = self._api.create_playlist("BotPlaylist")
            self._write_ids()
            playlist = list(filter(
                lambda p: p['id'] == self._playlist_id, self._api.get_all_playlists()))[0]
            self._playlist_token = playlist['shareToken']

    def _create_station(self):
        if not self._station_id:
            self._station_id = self._api.create_station(
                "BotStation", playlist_token=self._playlist_token)
            self._write_ids()

    def _write_ids(self):
        ids = {'playlist_token': self._playlist_token,
               'playlist_id': self._playlist_id, 'station_id': self._station_id}
        id_file = open("ids.json", "w")
        id_file.write(json.dumps(ids, indent=4, sort_keys=True))
        id_file.close()

    def _try_restore_ids(self):
        if os.path.isfile("ids.json"):
            id_file = open("ids.json", "r")
            ids = json.loads(id_file.read())
            id_file.close()
            self._playlist_id = ids['playlist_id']
            self._playlist_token = ids['playlist_token']
            self._station_id = ids['station_id']

    def reset(self):
        os.remove("ids.json")
        api = self._api
        api.delete_stations([self._station_id])
        api.delete_playlist(self._playlist_id)


class SongQueue(list):

    def __init__(self, song_provider):
        self._song_provider = song_provider

    def pop(self, *args, **kwargs):
        result = None

        try:
            result = list.pop(self, *args, **kwargs)
            # All gmusic store ids start with T and are 27 chars long
            if result['store_id'].startswith("T") and len(result['store_id']) == 27:
                self._song_provider.add_played(result)
        except IndexError:
            result = self._song_provider.get_song()
        return result

    def append(self, *args, **kwargs):
        song = args[0]
        fname = song['load_song']()
        song['load_song'] = lambda: fname
        list.append(self, *args, **kwargs)

    def reset(self):
        self._song_provider.reset()


class Player(object):

    def __init__(self, api):
        import pyglet
        self._pyglet = pyglet
        pyglet.options['audio'] = ('directsound', 'pulse', 'openal')
        self._player = pyglet.media.Player()
        self._api = api
        self._queue = SongQueue(SongProvider(api))
        self._player.set_handler("on_player_eos", self._on_eos)
        self._current_song = None
        self._on_eos()

    def queue(self, song):
        self._queue.append(song)

    def get_queue(self):
        return self._queue

    def skip_song(self, **kwargs):
        '''
        Needs argument store_id or queue_position
        '''
        if "store_id" in kwargs:
            store_id = kwargs["store_id"]
            self._queue = list(
                filter(lambda song: song['store_id'] != store_id))
        elif "queue_position" in kwargs:
            pos = kwargs["queue_position"]
            self._queue.pop(pos)

    def pause(self):
        self._player.pause()

    def resume(self):
        self._player.play()

    def next(self):
        self._player.next_source()

    def reset(self):
        self._queue.reset()
        self._player.delete()

    def get_current_song(self):
        return self._current_song

    def clear_queue(self):
        self._queue.clear()

    def _on_eos(self):
        from pyglet.media import MediaFormatException

        res = None
        while res is None:
            song = self._queue.pop(0)
            fname = song['load_song']()
            try:
                res = self._pyglet.media.load(fname)
                self._current_song = song
            except MediaFormatException:
                gc.collect()

                # There is no way to let pyglet close the file so yeah... this
                # is the "solution" for now
                # Who doesn't love "temporary" hacks?
                def _try_delete():
                    attempts = 20
                    while attempts > 0:
                        try:
                            os.remove(fname)
                            break
                        except:
                            time.sleep(15)
                            attempts -= 1
                threading.Thread(
                    name="delete_thread_" + fname, target=_try_delete).start()

        self._player.queue(res)
        self._player.play()

    def run(self):
        self._pyglet.app.run()

    def close(self):
        self._player.delete()
        self._pyglet.app.exit()
