from gmusicapi.exceptions import CallFailure
import json
import os
import pafy
from pydub import AudioSegment, effects
import re
import threading
import time
import urllib


config_file = open("config.json", "r")
config = json.loads(config_file.read())

max_downloads = config['max_downloads']
max_conversions = config['max_conversions']
quality = config['quality']
song_path = config['song_path']

if not re.compile(r'[ \S]+(\\|\/)$').match(song_path):
    song_path += "/"

if not os.path.isdir(song_path):
    try:
        os.makedirs(song_path)
    except OSError:
        print("'%s' is not a valid directory path. Exiting." % song_path)
        exit()

download_semaphore = threading.Semaphore(max_downloads)
convert_semaphore = threading.Semaphore(max_conversions)

config_file.close()


def get_youtube_loader(video_id):
    def _youtube_loader():
        url = "https://www.youtube.com/watch?v=" + video_id

        video = pafy.new(url)
        audio = video.getbestaudio()

        video_fname = song_path + video.videoid + "." + audio.extension
        fname = song_path + video.videoid + ".wav"

        if not os.path.isfile(fname):
            if not os.path.isfile(video_fname):
                download_semaphore.acquire()
                video_fname_tmp = video_fname + ".tmp"
                if os.path.isfile(video_fname_tmp):
                    os.remove(video_fname_tmp)
                audio.download(filepath=video_fname_tmp, quiet=True)
                os.rename(video_fname_tmp, video_fname)
                download_semaphore.release()

            convert_semaphore.acquire()
            song = AudioSegment.from_file(video_fname, audio.extension)
            song = effects.normalize(song)
            fname_tmp = fname + ".tmp"
            if os.path.isfile(fname_tmp):
                os.remove(fname_tmp)
            song.export(fname_tmp, "wav")
            os.remove(video_fname)
            os.rename(fname_tmp, fname)
            convert_semaphore.release()

        return fname
    return _youtube_loader


def get_gmusic_loader(api, store_id):
    def _gmusic_loader():
        mp3_fname = song_path + store_id + '.mp3'
        fname = song_path + store_id + ".wav"

        if not os.path.isfile(fname):
            if not os.path.isfile(mp3_fname):
                download_semaphore.acquire()
                attempts = 3
                url = None
                while attempts and not url:
                    try:
                        url = api.get_stream_url(store_id, quality=quality)
                    except CallFailure as e:
                        # Sometimes, the call returns a 403
                        attempts -= 1
                        print(
                            "403, retrying... ({} attempts left)".format(attempts))
                        if not attempts:
                            print(e)

                if not attempts:
                    return None  # TODO do something else here

                request = urllib.request.Request(url)
                page = urllib.request.urlopen(request)

                mp3_fname_tmp = mp3_fname + ".tmp"
                if os.path.isfile(mp3_fname_tmp):
                    os.remove(mp3_fname_tmp)

                file = open(mp3_fname_tmp, "wb")
                file.write(page.read())
                file.close()
                page.close()
                os.rename(mp3_fname_tmp, mp3_fname)
                download_semaphore.release()

            convert_semaphore.acquire()
            song = AudioSegment.from_mp3(mp3_fname)
            song = effects.normalize(song)
            fname_tmp = fname + ".tmp"
            if os.path.isfile(fname_tmp):
                os.remove(fname_tmp)
            song.export(fname_tmp, "wav")
            os.remove(mp3_fname)
            os.rename(fname_tmp, fname)
            convert_semaphore.release()

        return fname
    return _gmusic_loader


def get_soundcloud_loader(client, track):
    def _soundcloud_loader():
        url = client.get(track.stream_url, allow_redirects=False).location
        track_id = str(track.id)
        mp3_fname = song_path + track_id + ".mp3"
        fname = song_path + track_id + ".wav"

        if not os.path.isfile(fname):
            if not os.path.isfile(mp3_fname):
                download_semaphore.acquire()
                mp3_fname_tmp = mp3_fname + ".tmp"
                if os.path.isfile(mp3_fname_tmp):
                    os.remove(mp3_fname_tmp)

                request = urllib.request.Request(url)
                page = urllib.request.urlopen(request)

                file = open(mp3_fname_tmp, "wb")
                file.write(page.read())
                file.close()
                page.close()

                os.rename(mp3_fname_tmp, mp3_fname)
                download_semaphore.release()

            convert_semaphore.acquire()
            song = AudioSegment.from_mp3(mp3_fname)
            song = effects.normalize(song)
            fname_tmp = fname + ".tmp"
            if os.path.isfile(fname_tmp):
                os.remove(fname_tmp)
            song.export(fname_tmp, "wav")
            os.remove(mp3_fname)
            os.rename(fname_tmp, fname)
            convert_semaphore.release()

        return fname
    return _soundcloud_loader


class SongProvider(object):

    def __init__(self, api):
        self._api = api
        self._playlist_id = None
        self._playlist_token = None
        self._station_id = None
        self._last_played = []
        self._next_songs = []
        self._try_restore_ids()
        self._playlist_entries = self._get_playlist_entries()

    def get_song(self):
        self._create_playlist()
        if not self._station_id:
            self._create_station()
        song = self.get_suggestions(1)[0]
        self._next_songs.pop(0)
        store_id = song['store_id']
        self._last_played.append(store_id)
        return song

    def add_played(self, song):
        self._create_playlist()
        store_id = song['store_id']

        if store_id not in self._playlist_entries:
            self._api.add_songs_to_playlist(self._playlist_id, store_id)
            self._playlist_entries.add(store_id)

        self._last_played.append(store_id)
        self._next_songs.remove(store_id)
        if len(self._last_played) > 50:
            self._last_played = self._last_played[-50::]

    def get_playlist_content(self):
        return self._playlist_entries

    def remove_from_playlist(self, store_id):
        if store_id in self._playlist_entries:
            playlist_contents = self._api.get_all_user_playlist_contents()

            tracks = None
            for playlist in playlist_contents:
                if playlist['id'] == self._playlist_id:
                    tracks = playlist['tracks']
                    break

            if not tracks:
                return

            track = list(filter(lambda t: t['trackId'] == store_id, tracks))
            if not track:
                return

            track = dict(track[0])
            entry_id = track['id']

            self._api.remove_entries_from_playlist(entry_id)
            self._playlist_entries.remove(store_id)

    def get_suggestions(self, count):
        def _song_from_api_song(song):
            if "storeId" in song:
                store_id = song['storeId']
            elif "id" in song:
                store_id = song['id']
            else:
                return None

            name = "{} - {}".format(song["artist"], song["title"])
            song['store_id'] = store_id
            song['load_song'] = get_gmusic_loader(self._api, store_id)
            song['name'] = name

            return song

        next_len = len(self._next_songs)
        if next_len < count:
            api_songs = self._api.get_station_tracks(
                self._station_id, recently_played_ids=self._last_played, num_tracks=max(25, count - next_len))
            if api_songs:
                self._next_songs.extend(
                    filter(lambda s: s, map(_song_from_api_song, api_songs)))
            elif not self._next_songs:
                # Fallback song
                store_id = "Tj6fhurtstzgdpvfm4xv6i5cei4"
                return [{'store_id': store_id,
                         'load_song': get_gmusic_loader(self._api, store_id),
                         'name': "Mickie Krause - Biste braun, kriegste Fraun"}] * count
            else:
                return self._next_songs
        return self._next_songs[:count]

    def _create_playlist(self):
        if not self._playlist_id:
            self._playlist_id = self._api.create_playlist("BotPlaylist")
            self._write_ids()
            playlist = list(filter(
                lambda p: p['id'] == self._playlist_id, self._api.get_all_playlists()))[0]
            self._playlist_token = playlist['shareToken']

    def _get_playlist_entries(self):
        self._create_playlist()
        playlist_contents = self._api.get_all_user_playlist_contents()

        result = set()

        tracks = None
        for playlist in playlist_contents:
            if playlist['id'] == self._playlist_id:
                tracks = playlist['tracks']

        if not tracks:
            return result

        for track in tracks:
            result.add(track['track']['storeId'])
        return result

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

    def __init__(self, song_provider, notificator):
        super().__init__()
        self.song_provider = song_provider
        self._next_random = None
        self._prepare_next()
        self._lock = threading.Lock()
        self._notificator = notificator

    def _prepare_next(self):
        print("PREPARING")
        next_song = self.song_provider.get_song()
        fname = next_song['load_song']()
        next_song['load_song'] = lambda: fname
        self._next_random = next_song
        print("FINISHED PREPARING")

    def pop(self, *args, **kwargs):
        result = None

        try:
            result = list.pop(self, *args, **kwargs)
            # All gmusic store ids start with T and are 27 chars long
            store_id = result['store_id']
            if store_id.startswith("T") and len(store_id) == 27:
                self.song_provider.add_played(result)
        except IndexError:
            if self._lock.acquire(blocking=False):
                while self._next_random is None:
                    time.sleep(0.2)
                result = self._next_random
                self._next_random = None
                threading.Thread(
                    target=self._prepare_next, name="prepare_thread").start()
                self._lock.release()

        return result

    def append(self, *args, **kwargs):
        song = args[0]

        def _append():
            print("LOADING APPENDED SONG")
            fname = song['load_song']()
            song['load_song'] = lambda: fname
            list.append(self, *args, **kwargs)
            print("FINISHED LOADING APPENDED SONG")
            NotificationCause = self._notificator.NotificationCause
            self._notificator.notify(NotificationCause.queue_add(song['name']))

        threading.Thread(target=_append, name="append_thread").start()

    def reset(self):
        self.song_provider.reset()


class Player(object):

    def __init__(self, api, notificator, song_provider=None):
        import simpleaudio
        self._sa = simpleaudio
        self._player = None
        self._stop = False
        self._pause = False
        self._api = api
        if not song_provider:
            song_provider = SongProvider(api)
        self._queue = SongQueue(song_provider, notificator)
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
        self._notificator.notify(NotificationCause.queue_remove(song['name']))

    def pause(self):
        self._pause = True
        if self._player:
            self._player.stop()

    def resume(self):
        self._pause = False

    def next(self):
        self._on_song_end()

    def reset(self):
        self._queue.reset()
        self._player.stop()

    def get_current_song(self):
        return self._current_song

    def clear_queue(self):
        self._queue.clear()

    def get_remote_playlist(self):
        return self._queue.song_provider.get_playlist_content()

    def remove_from_remote_playlist(self, store_id):
        self._queue.song_provider.remove_from_playlist(store_id)

    def get_song_suggestions(self, count=20):
        return self._queue.song_provider.get_suggestions(count)

    def _on_song_end(self):
        if not self._lock.acquire(blocking=False):
            if threading.current_thread().name == "player_thread":
                self._barrier.wait()
            return
        song = self._queue.pop(0)
        if not song or self._stop:
            return
        fname = song['load_song']()

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
