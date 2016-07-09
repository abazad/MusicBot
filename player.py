import gc
import json
import os
from random import choice
import threading
import time


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
            store_id = choice(song)['storeId']
            self._last_played.append(store_id)
            return store_id
        # Fallback song
        return "Tj6fhurtstzgdpvfm4xv6i5cei4"

    def add_played(self, song):
        self._create_playlist()
        self._api.add_songs_to_playlist(self._playlist_id, song)
        self._last_played.append(song)
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

    def __init__(self, song_provider, load_song):
        self._song_provider = song_provider
        self._load_song = load_song

    def pop(self, *args, **kwargs):
        result = None

        try:
            result = list.pop(self, *args, **kwargs)
            self._song_provider.add_played(result)
        except IndexError:
            result = self._song_provider.get_song()

        return result

    def append(self, *args, **kwargs):
        result = list.append(self, *args, **kwargs)

        def _load_song():
            return self._load_song(args[0])
        threading.Thread(target=_load_song, name="song_loader").start()
        return result

    def reset(self):
        self._song_provider.reset()


class Player(object):

    def __init__(self, load_song, api):
        import pyglet
        self._pyglet = pyglet
        pyglet.options['audio'] = ('directsound', 'pulse', 'openal')
        self._player = pyglet.media.Player()
        self._queue = SongQueue(SongProvider(api), load_song)
        self._load_song = load_song
        self._player.set_handler("on_player_eos", self._on_eos)
        self._current_song = None
        self._on_eos()

    def queue(self, store_id):
        self._queue.append(store_id)

    def get_queue(self):
        return self._queue

    def skip_song(self, **kwargs):
        '''
        Needs argument store_id or queue_position
        '''
        if "store_id" in kwargs:
            store_id = kwargs["store_id"]
            self._queue = list(filter(lambda song: song != store_id))
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
            fname = self._load_song(song)
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
