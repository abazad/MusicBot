import threading
import time


class SongQueue(list):

    def __init__(self, song_provider, notificator):
        super().__init__()
        self._stop_preparing = False
        self._prepare_event = threading.Event()
        self._song_provider = song_provider
        self._append_lock = threading.Lock()
        self._notificator = notificator
        threading.Thread(name="prepareThread", target=self._prepare_next).start()

    def _prepare_next(self):
        while not self._stop_preparing:
            print("PREPARING")
            next_song = self._song_provider.get_suggestions(1)[0]
            next_song.load()
            print("FINISHED PREPARING")
            self._prepare_event.wait()
            self._prepare_event.clear()

    def pop(self, *args, **kwargs):
        result = None

        try:
            result = list.pop(self, *args, **kwargs)
            # All gmusic store ids start with T and are 27 chars long
            song_id = result.song_id
            if song_id.startswith("T") and len(song_id) == 27:
                self._song_provider.add_played(result)
        except IndexError:
            result = self._song_provider.get_song()
            self._prepare_event.set()
        return result

    def append(self, song):
        def _append():
            print("LOADING APPENDED SONG")
            song.load()
            self._append_lock.acquire()
            if song not in self:
                list.append(self, song)
            self._append_lock.release()
            print("FINISHED LOADING APPENDED SONG")
            NotificationCause = self._notificator.NotificationCause
            self._notificator.notify(NotificationCause.queue_add(song))

        threading.Thread(target=_append, name="append_thread").start()


class Player(object):

    def __init__(self, api, notificator):
        import simpleaudio
        self._sa = simpleaudio
        self._player = None
        self._stop = False
        self._pause = False
        self._api = api
        self._queue = SongQueue(api, notificator)
        self._current_song = None
        self._lock = threading.Lock()
        self._barrier = threading.Barrier(2)
        self._notificator = notificator

    def queue(self, song):
        self._queue.append(song)

    def get_queue(self):
        return self._queue

    def skip_song(self, queue_position):
        song = self._queue.pop(queue_position)
        NotificationCause = self._notificator.NotificationCause
        self._notificator.notify(NotificationCause.queue_remove(song))

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
        if not self._lock.acquire(blocking=False):
            if threading.current_thread().name == "player_thread":
                self._barrier.wait()
            return
        song = self._queue.pop(0)
        if not song or self._stop:
            return
        fname = song.load()

        wave_obj = self._sa.WaveObject.from_wave_file(fname)
        if self._player:
            self._player.stop()
        self._player = wave_obj.play()
        self._current_song = song

        NotificationCause = self._notificator.NotificationCause
        self._notificator.notify(NotificationCause.next_song())

        if threading.current_thread().name != "player_thread":
            self._barrier.wait()
        self._lock.release()

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