import logging
import threading
import time

from musicbot.music_apis import AbstractSongProvider
from musicbot.telegram.notifier import Notifier, Cause


class SongQueue(list):

    def __init__(self, song_provider):
        super().__init__()
        self._stop_preparing = False
        self._prepare_event = threading.Event()
        self._song_provider = song_provider
        self._append_lock = threading.Lock()
        threading.Thread(name="prepare_thread", target=self._prepare_next).start()

    def _prepare_next(self):
        logger = logging.getLogger("musicbot")
        while not self._stop_preparing:
            next_song = self._song_provider.get_suggestions(1)[0]
            logger.debug("PREPARING: %s", str(next_song))
            next_song.load()
            logger.debug("FINISHED PREPARING: %s", str(next_song))
            self._prepare_event.wait()
            self._prepare_event.clear()

    def pop(self, *args, **kwargs):
        result = None

        try:
            result = list.pop(self, *args, **kwargs)
            if isinstance(result._api, AbstractSongProvider):
                result._api.add_played(result)
        except IndexError:
            result = self._song_provider.get_song()
            self._prepare_event.set()
        return result

    def append(self, song):
        def _load_appended():
            logger = logging.getLogger("musicbot")
            self._song_provider.remove_from_suggestions(song)
            logger.debug("LOADING APPENDED SONG: %s", str(song))
            song.load()
            logger.debug("FINISHED LOADING APPENDED SONG: %s", str(song))
            Notifier.notify(Cause.queue_add(song))

        self._append_lock.acquire()
        if song not in self:
            list.append(self, song)
            threading.Thread(target=_load_appended, name="load_appended_thread").start()
        self._append_lock.release()

    def close(self):
        self._stop_preparing = True
        self._prepare_event.set()


class Player(object):

    def __init__(self, song_provider):
        import simpleaudio
        self._sa = simpleaudio
        self._player = None
        self._stop = False
        self._pause = False
        self._queue = SongQueue(song_provider)
        self._current_song = None
        self._lock = threading.Lock()

    def queue(self, song):
        self._queue.append(song)

    def get_queue(self):
        return self._queue

    def skip_song(self, song):
        self._queue.remove(song)
        Notifier.notify(Cause.queue_remove(song))

    def pause(self):
        self._pause = True
        if self._player:
            self._player.stop()

    def resume(self):
        self._pause = False

    def next(self):
        self._on_song_end()

    def get_current_song(self):
        return self._current_song

    def clear_queue(self):
        self._queue.clear()

    def _on_song_end(self):
        thread_name = threading.current_thread().name
        logger = logging.getLogger("musicbot")
        if self._lock.acquire(blocking=False):
            logger.debug("ENTERED _on_song_end (%s)", thread_name)
            song = self._queue.pop(0)
            logger.debug("POPPED song: %s", str(song))
            if not song or self._stop:
                logger.error("INVALID SONG POPPED OR STOP CALLED")
                self._lock.release()
                return

            if not song.loaded:
                try:
                    next_song = self._queue[0]
                    if next_song.loaded:
                        logger.debug("Delay %s' because %s is already loaded.", song, next_song)
                        self._queue.pop(0)
                        self._queue.insert(0, song)
                        song = next_song
                except IndexError:
                    pass

            fname = song.load()

            wave_obj = self._sa.WaveObject.from_wave_file(fname)
            if self._player:
                self._player.stop()
            self._player = wave_obj.play()
            self._current_song = song

            Notifier.notify(Cause.current_song(song))

            time.sleep(1)
            logger.debug("LEAVING _on_song_end (%s)", thread_name)
            self._lock.release()
        else:
            logger.debug("Failed to acquire _on_song_end lock (%s)", thread_name)

    def run(self):
        def _run():
            while not self._stop:
                if self._pause:
                    time.sleep(1)
                else:
                    self._on_song_end()
                    self._player.wait_done()
        threading.Thread(name="player_thread", target=_run).start()

    def close(self):
        self._stop = True
        if self._player:
            self._player.stop()
        self._queue.close()
