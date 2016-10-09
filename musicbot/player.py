import logging
import threading

import pyaudio
import pydub
from pydub.utils import make_chunks

from musicbot import async_handler
from musicbot.music_apis import AbstractSongProvider
from musicbot.telegram.notifier import Notifier, Cause


class SongQueue(list):
    def __init__(self, song_provider):
        super().__init__()
        self._stop_preparing = False
        self._prepare_event = threading.Event()
        self._song_provider = song_provider
        self._append_lock = threading.Lock()

        def close_prepare_thread():
            self._stop_preparing = True
            self._prepare_event.set()

        async_handler.execute(self._prepare_next, close_prepare_thread, name="prepare_thread")

    def _prepare_next(self):
        logger = logging.getLogger("musicbot")
        while not self._stop_preparing:
            next_song = self._song_provider.get_suggestions(1)[0]
            logger.debug("PREPARING: %s", str(next_song))
            next_song.load()
            logger.debug("FINISHED PREPARING: %s", str(next_song))
            self._prepare_event.wait()
            self._prepare_event.clear()

    def insert(self, index, song):
        list.insert(self, index, song)
        async_handler.submit(lambda: song.load())

    def pop(self, *args, **kwargs):
        try:
            result = list.pop(self, *args, **kwargs)
            if isinstance(result.api, AbstractSongProvider):
                result.api.add_played(result)
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
            async_handler.submit(_load_appended)
        self._append_lock.release()


class Player(object):
    def __init__(self, song_provider):
        self._pa = pyaudio.PyAudio()
        self._stop = False
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._skip = False
        self._last_played = []
        self._queue = SongQueue(song_provider)
        self._current_song = None
        self._current_segment = None
        self._lock = threading.Lock()
        self._next_chosen_event = threading.Event()

    def queue(self, song):
        self._queue.append(song)

    def get_queue(self):
        return self._queue

    def skip_song(self, song):
        self._queue.remove(song)
        Notifier.notify(Cause.queue_remove(song))

    def pause(self):
        self._resume_event.clear()

    def resume(self):
        self._resume_event.set()

    def next(self):
        '''
        Skip to the next song.
        Block until the next song is actually playing.
        '''
        self._on_song_end()
        self._skip = True
        self._resume_event.set()

    def get_current_song(self):
        return self._current_song

    def clear_queue(self):
        self._queue.clear()

    def _on_song_end(self):
        thread_name = str(threading.current_thread())
        logger = logging.getLogger("musicbot")
        # Get a reference to the current next_chosen_event.
        # The object attribute is replaced by a new event object after the player thread left this method.
        next_chosen_event = self._next_chosen_event
        with self._lock:
            if next_chosen_event.is_set():
                # If some other thread was faster, return immediately to prevent multiple song skips
                logger.debug("ENTERED _on_song_end after next_chosen (%s)", thread_name)
                return
            logger.debug("ENTERED _on_song_end (%s)", thread_name)
            song = self._queue.pop(0)
            logger.debug("POPPED song: %s", str(song))
            if not song or self._stop:
                logger.error("INVALID SONG POPPED OR STOP CALLED")
                return

            if not song.loaded:
                logger.debug("First song not loaded")
                try:
                    next_song = self._queue[0]
                    if next_song.loaded:
                        logger.debug("Delay %s' because %s is already loaded.", song, next_song)
                        self._queue.pop(0)
                        self._queue.insert(0, song)
                        song = next_song
                    else:
                        logger.debug("Second (%s) is not loaded")
                except IndexError:
                    logger.debug("No second song in queue")
            else:
                logger.debug("First song is loaded")

            fname = song.load()
            seg = pydub.AudioSegment.from_mp3(fname)
            self._current_song = song
            self._current_segment = seg
            self._next_chosen_event.set()

            Notifier.notify(Cause.current_song(song))
            self._add_played(song)

            logger.debug("LEAVING _on_song_end (%s)", thread_name)

    def run(self):
        _pa = self._pa
        _done_event = threading.Event()
        logger = logging.getLogger("musicbot")

        def _open_stream(seg):
            return _pa.open(format=_pa.get_format_from_width(seg.sample_width),
                            channels=seg.channels,
                            rate=seg.frame_rate,
                            output=True)

        def _run():
            while not self._stop:
                self._on_song_end()
                self._next_chosen_event = threading.Event()
                self._skip = False
                # Play song
                seg = self._current_segment
                stream = _open_stream(seg)
                for chunk in make_chunks(seg, 1000):
                    self._resume_event.wait()
                    if self._stop or self._skip:
                        break
                    stream.write(chunk.raw_data)
                stream.close()
            _done_event.set()

        def _stop():
            self._stop = True
            self._resume_event.set()
            _done_event.wait()
            _pa.terminate()

        async_handler.execute(_run, _stop, name="player_thread")

    def _add_played(self, song):
        self._last_played.append(song)
        self._last_played = self._last_played[-20:]

    def get_last_played(self):
        return self._last_played

    def is_paused(self):
        return not self._resume_event.is_set()
