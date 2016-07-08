import gc
import os
from random import choice
import threading
import time


class SongProvider(object):

    def __init__(self):
        self._last_played = []

    def get_song(self):
        result = None

        try:
            result = choice(self._last_played)
        except IndexError:
            # TODO: choose random song
            store_id = "Tuxryaz562qed3adlgm74ooxgue"
            result = store_id

        return result

    def add_played(self, song):
        self._last_played.append(song)


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


class Player(object):

    def __init__(self, load_song):
        import pyglet
        self._pyglet = pyglet
        pyglet.options['audio'] = ('directsound', 'pulse', 'openal')
        self._player = pyglet.media.Player()
        self._queue = SongQueue(SongProvider(), load_song)
        self._load_song = load_song
        self._player.set_handler("on_player_eos", self._on_eos)
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

    def _on_eos(self):
        from pyglet.media import MediaFormatException

        res = None
        while res is None:
            song = self._queue.pop(0)
            fname = self._load_song(song)
            try:
                res = self._pyglet.media.load(fname)
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
