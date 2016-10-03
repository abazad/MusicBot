import json
import logging
import os
import socket
import threading
import time
import typing
import urllib
from datetime import datetime
from getpass import getpass
from json import JSONDecodeError
from os.path import isfile
from random import choice

import pylru
from gmusicapi.clients.mobileclient import Mobileclient
from gmusicapi.exceptions import CallFailure
from mutagen.mp3 import EasyMP3
from pydub import AudioSegment

import _version
from musicbot import config

_songs_path = config.get_songs_path()
_max_downloads = max(config.get_max_downloads(), 1)
_max_conversions = max(config.get_max_conversions(), 1)
_download_semaphore = threading.Semaphore(_max_downloads)
_conversion_semaphore = threading.Semaphore(_max_conversions)
_loading_ids = {}
_loading_ids_lock = threading.Lock()


class Song(object):
    _download_semaphore = None
    _conversion_semaphore = None

    def __init__(self, song_id: str, api, title=None, description=None, albumArtUrl=None, str_rep=None,
                 duration=None, user=None):
        """
        Constructor

        Keyword arguments:
        song_id -- the unique ID of the song
        api -- an instance of AbstractAPI capable of loading this song
        title -- the song title
        description -- a description of the title (can be the artist)
        albumArtUrl -- a URL to the album art
        str_rep -- a human readable string representation for this instance. Will be returned for __str__(). The song duration maybe will automatically appended.
        duration -- the song duration (as a string in the form [HH:]MM:SS)
        user -- a string describing which user queued this song (if applicable)
        """
        if not api:
            raise ValueError("api is None")
        if not isinstance(api, AbstractAPI):
            raise ValueError("api is not an instance of AbstractAPI")
        if not song_id:
            raise ValueError("song_id None")

        self.song_id = str(song_id)
        self.api = api
        self.description = description
        self.albumArtUrl = albumArtUrl
        self._api = api
        self.duration = duration
        self.user = str(user)
        self.loaded = False

        if str_rep:
            self._str_rep = str_rep
        elif title:
            self._str_rep = title
        else:
            self._str_rep = "Unknown"

        if title:
            self.title = title
        else:
            self.title = self._str_rep

    def load(self):
        try:
            if not os.path.isdir(_songs_path):
                os.makedirs(_songs_path)
        except OSError:
            raise ValueError("Invalid song path: " + _songs_path)

        songs_path = _songs_path  # TODO delete / refactor
        song_id = self.song_id
        fname = os.path.join(songs_path, ".".join([song_id, "mp3"]))

        loading_ids_lock = _loading_ids_lock  # TODO delete / refactor

        # Acquire a lock to access self._loading_ids
        loading_ids_lock.acquire()
        try:
            # If another thread is loading the same song, there is an event in _loading_ids to wait for
            event = _loading_ids[song_id]
            loading_ids_lock.release()
            # Wait for the loading thread to call event.set().
            # Since we released the loading_ids_lock before this, the event may already be set.
            # In that case, the wait() call will return immediately.
            event.wait()
            return fname
        except KeyError:
            # There is no other thread loading this song (yet), so we can create a new
            # event for this song to set at the end of the method.
            _loading_ids[song_id] = threading.Event()
            loading_ids_lock.release()

        if not isfile(fname):
            try:
                with _download_semaphore:
                    native_fname = self.api._download(self)
            except Exception as e:
                logging.getLogger("musicbot").exception("Exception during download of %s", song_id)
                raise e

            with _conversion_semaphore:
                if not _version.debug or isfile(native_fname):
                    song = AudioSegment.from_file(native_fname, native_fname.split(".")[-1])
                    # TODO normalization seems to cause a stutter of the playback
                    # song = effects.normalize(song)
                    fname_tmp = fname + ".tmp"
                    if isfile(fname_tmp):
                        os.remove(fname_tmp)
                    song.export(fname_tmp, "mp3",
                                tags={"title": self.title,
                                      "artist": self.description,
                                      "album": self.albumArtUrl,
                                      "composer": str(self)},
                                id3v2_version="3",
                                bitrate="320k")
                    os.remove(native_fname)
                    os.rename(fname_tmp, fname)

        loading_ids_lock.acquire()
        # Get the event other threads are possibly waiting for
        event = _loading_ids[song_id]
        del _loading_ids[song_id]
        # Set the event. We removed it from _loading_ids so it will soon be garbage collected.
        event.set()
        loading_ids_lock.release()

        self.loaded = True
        return fname

    def to_json(self) -> typing.Dict[str, str]:
        return {
            "song_id": self.song_id,
            "api_name": self.api.get_name(),
            "title": self.title,
            "description": self.description,
            "albumArtUrl": self.albumArtUrl,
            "str_rep": self._str_rep,
            "duration": self.duration,
            "user": self.user
        }

    @staticmethod
    def from_json(song_json: dict, apis: list):
        """
        Create a song from json.

        Keyword arguments:
        json -- the json representation of a song
        apis -- a dict from api names to apis
        """

        try:
            song_id = song_json['song_id']
        except KeyError:
            raise ValueError("invalid json (missing song_id")

        try:
            api_name = song_json['api_name']
            api = apis[api_name]
        except KeyError:
            raise ValueError("invalid json (missing or invalid api_name)")

        return Song(
            song_id=song_id,
            api=api,
            title=song_json.get("title", None),
            description=song_json.get("description", None),
            albumArtUrl=song_json.get("albumArtUrl", None),
            str_rep=song_json.get("str_rep", None),
            duration=song_json.get("duration", None),
            user=song_json.get("user", None)
        )

    def __repr__(self):
        return self.song_id

    def __str__(self):
        if self.duration:
            return "{} ({})".format(self._str_rep, self.duration)
        else:
            return self._str_rep

    def __hash__(self):
        return hash(self.song_id)

    def __eq__(self, other):
        return self.song_id == other.song_id

    def __lt__(self, other):
        return self.__str__() < other.__str__()


class AbstractAPI(object):
    def get_name(self) -> str:
        """
        Return the unique name of this API.
        The name can't contain any whitespace. Use lower_snake_case.
        """
        raise NotImplementedError()

    def get_pretty_name(self) -> str:
        """
        Return a pretty name of this API to show users.
        This name can be an arbitrary string.
        """
        raise NotImplementedError()

    def lookup_song(self, song_id: str) -> Song:
        """
        Look up the info about a song based on the song_id.
        Return a Song object.
        """
        raise NotImplementedError()

    def search_song(self, query: str, max_fetch: int = 1000) -> typing.Generator[Song, None, None]:
        """
        Search for songs.
        Return a generator yielding Song objects.
        The max_fetch argument may or may not determine how many songs are fetched at once.
        """
        raise NotImplementedError()

    def _download(self, song: Song) -> str:
        """
        Download a song and return its filename.
        The filename ALWAYS starts with a 'native_' prefix.
        :param song: the song to download
        :return: the songs filename
        """
        raise NotImplementedError()


class AbstractSongProvider(AbstractAPI):
    def __init__(self):
        super().__init__()

    def get_song(self) -> Song:
        """
        Return the next song and remove it from suggestions.
        """
        raise NotImplementedError()

    def add_played(self, song: Song):
        """
        Add a song to the list further suggestions are based on it.
        """
        raise NotImplementedError()

    def get_playlist(self) -> typing.List[Song]:
        """
        Return the list suggestions are based on.
        """
        raise NotImplementedError()

    def remove_from_playlist(self, song: Song):
        """
        Remove a song from the list suggestions are based on.
        """
        raise NotImplementedError()

    def get_suggestions(self, max_len: int) -> list:
        """
        Return a list of suggested songs with the given maximum length.
        """
        raise NotImplementedError()

    def remove_from_suggestions(self, song: Song):
        """
        Remove a song from the currently loaded suggestions.
        If the song is not in the suggestions, nothing happens.
        """
        raise NotImplementedError()

    def reload(self):
        """
        Reload suggestions. Do not drop the playlist.
        """
        raise NotImplementedError()

    def reset(self):
        """
        Reset any state and clear the playlist.
        """
        raise NotImplementedError()


class GMusicAPI(AbstractSongProvider):
    _api = None
    _songs = pylru.lrucache(256)
    _connect_lock = threading.Lock()

    def __init__(self):
        super().__init__()
        self._connect()
        self._quality = config.get_gmusic_quality()
        self._playlist_id = None
        self._playlist_token = None
        self._station_id = None
        self._last_played_ids = []
        self._suggestions = []
        self._playlist = set()
        self._load_ids()
        self._remote_playlist_load()

    def get_api(self) -> Mobileclient:
        return self._api

    def get_name(self):
        return "gmusic"

    def get_pretty_name(self):
        return "Google Play Music"

    def lookup_song(self, song_id):
        songs = self._songs
        if not song_id:
            raise ValueError("Song ID is None")
        elif song_id in songs:
            return songs[song_id]
        else:
            try:
                info = self._api.get_track_info(song_id)
            except CallFailure:
                return Song(song_id, self)
            return self._song_from_info(info)

    def search_song(self, query, max_fetch=100):
        if not query:
            raise ValueError("query is None")
        max_fetch = min(100, max_fetch)
        results = self._api.search(query, max_fetch)
        _song_from_info = self._song_from_info
        for track in results['song_hits']:
            info = track['track']
            yield _song_from_info(info)

    def set_quality(self, quality):
        if not quality:
            raise ValueError("quality is None")
        quality = quality.strip()
        if quality not in ["hi", "med", "low"]:
            raise ValueError("Quality must be hi, mid or low")
        self._quality = quality

    def _add_last_played_id(self, song_id):
        self._last_played_ids.append(song_id)
        self._last_played_ids = self._last_played_ids[-50:]

    def get_song(self):
        self._load_suggestions(1)
        song = self._suggestions.pop(0)
        song_id = song.song_id
        self._add_last_played_id(song_id)
        return song

    def add_played(self, song):
        if song not in self._playlist:
            self._playlist.add(song)
            self._remote_playlist_add(song)
        self._suggestions = list(filter(lambda song: song != song, self._suggestions))
        self._add_last_played_id(song.song_id)

    def get_playlist(self):
        return self._playlist

    def remove_from_playlist(self, song):
        if song in self._playlist:
            self._remote_playlist_remove(song)
            self._playlist.remove(song)

    def get_suggestions(self, max_len=15):
        if len(self._suggestions) < max_len:
            self._load_suggestions(max_len)

        if len(self._suggestions) > max_len:
            return self._suggestions[:max_len]
        else:
            return self._suggestions

    def remove_from_suggestions(self, song):
        try:
            self._suggestions.remove(song)
        except ValueError:
            pass

    def reload(self):
        self._suggestions.clear()
        self._remote_playlist_load()

    def reset(self):
        self._remote_playlist_delete()
        self._remote_station_delete()
        self._playlist.clear()

    def _load_suggestions(self, max_len):
        self._remote_station_create()
        api_songs = self._api.get_station_tracks(
            self._station_id, recently_played_ids=self._last_played_ids, num_tracks=max(50, max_len))
        if api_songs:
            self._suggestions.extend(map(self._song_from_info, api_songs))
        else:
            song_id = "Tj6fhurtstzgdpvfm4xv6i5cei4"
            fallback_song = Song(song_id, self,
                                 "Biste braun kriegste Fraun", "Mickie Krause",
                                 str_rep="Mickie Krause - Biste braun kriegste Fraun")
            self._suggestions.append(fallback_song)

    def _remote_playlist_load(self):
        self._remote_playlist_create()
        playlist_contents = self._api.get_all_user_playlist_contents()

        result = set()

        tracks = None
        for playlist in playlist_contents:
            if playlist['id'] == self._playlist_id:
                tracks = playlist['tracks']

        if not tracks:
            return result

        for track in tracks:
            result.add(self._song_from_info(track['track']))

        self._playlist = result

    def _remote_playlist_add(self, song):
        self._remote_playlist_create()
        self._api.add_songs_to_playlist(self._playlist_id, song.song_id)

    def _remote_playlist_remove(self, song):
        self._remote_playlist_create()
        if song in self._playlist:
            playlist_contents = self._api.get_all_user_playlist_contents()

            tracks = None
            for playlist in playlist_contents:
                if playlist['id'] == self._playlist_id:
                    tracks = playlist['tracks']
                    break

            if not tracks:
                return

            track = list(filter(lambda t: t['trackId'] == song.song_id, tracks))
            if not track:
                return

            track = dict(track[0])
            entry_id = track['id']

            self._api.remove_entries_from_playlist(entry_id)

    def _remote_playlist_create(self):
        if not self._playlist_id:
            playlist_name = self._format_playlist_name("BotPlaylist created on {} at {}")
            self._playlist_id = self._api.create_playlist(playlist_name)
            playlists = list(filter(lambda p: p['id'] == self._playlist_id, self._api.get_all_playlists()))
            if not playlists:
                logger = logging.getLogger("musicbot")
                logger.warning("Didn't find playlist that was created a moment ago. (Trying again)")
                time.sleep(0.5)
                playlists = list(filter(lambda p: p['id'] == self._playlist_id, self._api.get_all_playlists()))
                if not playlists:
                    logger.critical("Retry failed!")
                    raise IOError("Could not find created playlist")
            playlist = playlists[0]
            self._playlist_token = playlist['shareToken']
            self._write_ids()

    def _remote_playlist_delete(self):
        self._api.delete_playlist(self._playlist_id)
        self._playlist_id = None
        self._write_ids()

    def _remote_station_create(self):
        self._remote_playlist_create()
        if not self._station_id:
            station_name = self._format_playlist_name("BotStation created on {} at {}")
            self._station_id = self._api.create_station(station_name, playlist_token=self._playlist_token)
            self._write_ids()

    def _remote_station_delete(self):
        self._api.delete_stations([self._station_id])
        self._station_id = None
        self._write_ids()

    def _load_ids(self):
        secrets = config.get_secrets()
        self._playlist_token = secrets.get("playlist_token", None)
        if not self._playlist_token:
            return
        self._playlist_id = secrets.get("playlist_id", None)
        self._station_id = secrets.get("station_id", None)

    def _write_ids(self):
        secrets = config.get_secrets()
        secrets['playlist_token'] = self._playlist_token
        secrets['playlist_id'] = self._playlist_id
        secrets['station_id'] = self._station_id
        config.save_secrets()

    @staticmethod
    def _format_playlist_name(name):
        hostname = socket.gethostname()
        timestamp = time.strftime("%c")
        return name.format(hostname, timestamp)

    def _song_from_info(self, info):
        if "storeId" in info:
            song_id = info['storeId']
        else:
            song_id = info['id']
        songs = self._songs
        if song_id in songs:
            return songs[song_id]
        artist = info['artist']
        title = info['title']
        duration_millis = int(info['durationMillis'])
        duration = datetime.fromtimestamp(duration_millis / 1000).strftime("%M:%S")
        url = None
        if "albumArtRef" in info:
            ref = info["albumArtRef"]
            if ref:
                ref = ref[0]
                if "url" in ref:
                    url = ref["url"]

        song = Song(song_id, self, title, artist, url, " - ".join([artist, title]), duration)
        songs[song_id] = song
        return song

    def _download(self, song):
        if song.api != self:
            raise ValueError("Tried to download song %s with wrong API %s", song, self.get_name())
        song_id = song.song_id
        native_fname = os.path.join(_songs_path, ".".join(["native_" + song_id, "mp3"]))
        if isfile(native_fname):
            return native_fname
        native_fname_tmp = native_fname + ".tmp"
        if isfile(native_fname_tmp):
            os.remove(native_fname_tmp)

        try:
            attempts = 3
            url = None
            while attempts and not url:
                try:
                    url = self._api.get_stream_url(song_id, quality=self._quality)
                    if not url:
                        raise CallFailure("call returned None for song_id {}".format(song_id), "get_stream_url")
                except CallFailure as e:
                    # Sometimes, the call returns a 403
                    attempts -= 1
                    logger = logging.getLogger("musicbot")
                    logger.error("403, retrying... (%d attempts left)", attempts)
                    if not attempts:
                        logger.exception(e)
                        raise IOError("Can't download song from Google Play")

                request = urllib.request.Request(url)
                with urllib.request.urlopen(request) as page:
                    with open(native_fname_tmp, "wb") as file:
                        file.write(page.read())
        except Exception as e:
            logging.getLogger("musicbot").exception("Exception during download of %s", song_id)
            raise e
        os.rename(native_fname_tmp, native_fname)
        return native_fname

    @classmethod
    def _connect(cls):
        locked = cls._connect_lock.acquire(blocking=False)
        try:
            if locked:
                if not cls._api:
                    api = Mobileclient(debug_logging=False)

                    gmusic_locale = config.get_gmusic_locale()

                    secrets = config.get_secrets()

                    gmusic_user = config.request_secret("gmusic_username", "Enter your Google username: ", False)
                    if not gmusic_user:
                        raise ValueError("Empty Google username")

                    gmusic_password = config.request_secret("gmusic_password", "Enter your Google password: ")
                    if not gmusic_password:
                        raise ValueError("Empty Google password")

                    try:
                        gmusic_device_id = secrets['gmusic_device_id']
                    except KeyError as e:
                        choice = input(
                            "No GMusic device ID found. Do you want to use this devices ID (1) or select an existing device ID (2, recommended)? ").strip()
                        if choice == "1":
                            gmusic_device_id = Mobileclient.FROM_MAC_ADDRESS
                        elif choice == "2":
                            gmusic_device_id = getpass(
                                "Enter a device ID (leave empty to show all registered devices): ").strip()
                            if gmusic_device_id:
                                if gmusic_device_id.startswith("0x"):
                                    gmusic_device_id = gmusic_device_id[2:]
                                secrets['gmusic_device_id'] = gmusic_device_id
                                config.save_secrets()
                        else:
                            raise ValueError("No GMusic device ID chosen")

                    if not gmusic_device_id:
                        if not api.login(gmusic_user, gmusic_password, Mobileclient.FROM_MAC_ADDRESS, gmusic_locale):
                            raise ValueError("Could not log in to GMusic")

                        devices = api.get_registered_devices()
                        api.logout()
                        logger = logging.getLogger("musicbot")
                        logger.error("No device ID provided, printing registered devices:")
                        logger.error(json.dumps(devices, indent=4, sort_keys=True))
                        raise ValueError("Missing device ID in secrets")

                    if not api.login(gmusic_user, gmusic_password, gmusic_device_id, gmusic_locale):
                        raise ValueError("Could not log in to GMusic")
                    cls._api = api
        finally:
            if locked:
                cls._connect_lock.release()


class YouTubeAPI(AbstractAPI):
    _pafy = __import__("pafy")
    _songs = pylru.lrucache(256)
    _api_key = None

    def __init__(self):
        super().__init__()
        self._api_key = config.request_secret("youtube_api_key", "Enter YouTube API key: ")

        if not self._api_key:
            raise ValueError("Missing YouTube API key")

    def get_name(self):
        return "youtube"

    def get_pretty_name(self):
        return "YouTube"

    def lookup_song(self, song_id):
        songs = self._songs
        if not song_id:
            raise ValueError("Song ID is None")
        elif song_id in songs:
            return songs[song_id]
        else:
            url = "https://www.youtube.com/watch?v=" + song_id
            video = self._pafy.new(url, gdata=True)
            title = video.title
            description = video.description
            url = video.thumb
            duration = video.duration
            song = Song(song_id, self, title, description, albumArtUrl=url, duration=duration)
            songs[song_id] = song
            return song

    def search_song(self, query, max_fetch=50):
        if not query:
            raise ValueError("query is None")
        max_fetch = min(50, max_fetch)
        qs = {
            'q': query,
            'maxResults': max_fetch,
            'safeSearch': "none",
            'part': 'id,snippet',
            'type': 'video',
            'key': self._api_key
        }

        def _track_to_song(track):
            song_id = track['id']['videoId']
            snippet = track['snippet']
            title = snippet['title']
            description = snippet['description']

            # TODO, maybe find out duration

            url = None
            try:
                thumbnails = snippet['thumbnails']
                url = thumbnails['medium']['url']
            except KeyError:
                pass

            return Song(song_id, self, title, description, albumArtUrl=url)

        songs = self._pafy.call_gdata('search', qs)['items']
        for track in songs:
            yield _track_to_song(track)

    def _download(self, song):
        if song.api != self:
            raise ValueError("Tried to download song %s with wrong API %s", song, self.get_name())
        song_id = song.song_id
        url = "https://www.youtube.com/watch?v=" + song_id
        try:
            video = self._pafy.new(url)
        except TypeError as e:
            logging.getLogger("musicbot").exception("Error loading url: %s", url)
            raise e
        audio = video.getbestaudio()
        native_fname = os.path.join(_songs_path, ".".join(["native_" + song_id, audio.extension]))
        if isfile(native_fname):
            return native_fname
        native_fname_tmp = native_fname + ".tmp"
        if isfile(native_fname_tmp):
            os.remove(native_fname_tmp)
        audio.download(filepath=native_fname_tmp, quiet=True)
        os.rename(native_fname_tmp, native_fname)
        return native_fname


class SoundCloudAPI(AbstractAPI):
    _soundcloud = __import__("soundcloud")
    _songs = pylru.lrucache(256)
    _client = None
    _connect_lock = threading.Lock()

    def __init__(self):
        super().__init__()
        self._connect()

    def get_name(self):
        return "soundcloud"

    def get_pretty_name(self):
        return "SoundCloud"

    def lookup_song(self, song_id):
        songs = self._songs
        if not song_id:
            raise ValueError("Song ID is None")
        elif song_id in songs:
            return songs[song_id]
        else:
            info = self._client.get("/tracks/{}".format(song_id))
            return self._song_from_info(info)

    def search_song(self, query, max_fetch=200):
        if not query:
            raise ValueError("query is None")
        act_max_fetch = min(50, max_fetch)
        resource = self._client.get("tracks/", q=query, limit=act_max_fetch, linked_partitioning=1)
        _info_to_song = self._song_from_info
        count = 0
        while count < max_fetch:
            for info in resource.collection:
                song = _info_to_song(info)
                count += 1
                yield song

            try:
                next_href = resource.next_href
                if not next_href:
                    break
                resource = self._client.get(next_href)
            except AttributeError:
                break

    def _download(self, song):
        if song.api != self:
            raise ValueError("Tried to download song %s with wrong API %s", song, self.get_name())
        song_id = song.song_id
        native_fname = os.path.join(_songs_path, ".".join(["native_" + song_id, "mp3"]))
        if isfile(native_fname):
            return native_fname
        native_fname_tmp = native_fname + ".tmp"
        info = self._client.get("/tracks/{}".format(song_id))
        stream_url = info.stream_url
        url = self._client.get(stream_url, allow_redirects=False).location

        request = urllib.request.Request(url)
        with urllib.request.urlopen(request) as page:
            with open(native_fname_tmp, "wb") as file:
                file.write(page.read())

        os.rename(native_fname_tmp, native_fname)
        return native_fname

    def _song_from_info(self, info):
        song_id = str(info.id)
        songs = self._songs
        if song_id in songs:
            return songs[song_id]
        artist = info.user['username']
        title = info.title
        url = info.artwork_url
        duration_millis = info.duration
        duration = datetime.fromtimestamp(duration_millis / 1000).strftime("%M:%S")
        song = Song(song_id, self, title, artist, url, " - ".join([artist, title]), duration=duration)
        songs[song_id] = song
        return song

    @classmethod
    def _connect(cls):
        locked = cls._connect_lock.acquire(blocking=False)
        try:
            if locked:
                if not cls._client:
                    app_id = config.request_secret("soundcloud_id", "Enter SoundCloud App ID: ")
                    if not app_id:
                        raise ValueError("Missing SoundCloud App ID")
                    client = cls._soundcloud.Client(client_id=app_id)
                    cls._client = client
        finally:
            if locked:
                cls._connect_lock.release()


class OfflineAPI(AbstractSongProvider):
    def __init__(self):
        super().__init__()

        songs = []
        song_ids = {}

        if os.path.isdir(_songs_path):
            join = os.path.join
            for song_file_name in os.listdir(_songs_path):
                song_path = join(_songs_path, song_file_name)
                if not isfile(song_path) \
                        or not song_file_name.endswith(".mp3") \
                        or song_file_name.endswith(".tmp") \
                        or song_file_name.startswith("native_"):
                    continue
                song_id = ".".join(song_file_name.split(".")[:-1])
                song = self._try_load_song(song_id, song_path)
                if song:
                    song_ids[song.song_id] = song
                    songs.append(song)

        self._songs = songs
        self._song_ids = song_ids
        self._active_playlist = None
        self._playlists = self._load_playlists()
        self._next_songs = []
        self._last_played = []

    def _try_load_song(self, song_id, song_path):
        audio = EasyMP3(song_path)
        id3 = audio.tags
        try:
            title = id3['title'][0]
            artist = id3['artist'][0]
            str_rep = id3['composer'][0]
            album_art = id3['album'][0]
            duration = datetime.fromtimestamp(audio.info.length).strftime("%M:%S")
        except (KeyError, IndexError):
            return None
        song = Song(song_id, self, title, artist, album_art, str_rep, duration)
        song.loaded = True
        logging.getLogger("musicbot").debug("Loaded offline song: %s", song)
        return song

    def _load_playlists(self):
        playlists_path = os.path.join(_songs_path, "playlists.json")
        if not isfile(playlists_path):
            return set()

        try:
            with open(playlists_path, 'r') as playlists_file:
                playlists_json = json.loads(playlists_file.read())
                playlists = playlists_json['playlists']
        except (IOError, JSONDecodeError, KeyError):
            return set()

        if "active_id" in playlists_json:
            active_id = playlists_json['active_id']
        else:
            active_id = None

        result = set()
        for playlist_json in playlists:
            try:
                playlist = OfflineAPI._Playlist.from_json(self._song_ids, playlist_json)
                if playlist.playlist_id == active_id:
                    self._active_playlist = playlist
            except ValueError:
                logging.getLogger("musicbot").debug("Invalid playlist %s", json.dumps(playlist_json))
                continue
            result.add(playlist)
        return result

    def save_playlists(self):
        playlists_path = os.path.join(_songs_path, "playlists.json")
        playlists_json = {}
        if self._active_playlist:
            playlists_json['active_id'] = self._active_playlist.playlist_id
        playlists_json['playlists'] = list(map(OfflineAPI._Playlist.to_json, self._playlists))
        with open(playlists_path, 'w') as playlists_file:
            playlists_file.write(json.dumps(playlists_json))

    def get_name(self):
        return "offline_api"

    def get_pretty_name(self):
        return "Offline"

    def add_played(self, song: Song):
        self._last_played.append(song.song_id)
        self._last_played = self._last_played[-50:]

    def reload(self):
        pass

    def _download(self, song: Song):
        if song.api != self:
            raise ValueError("Tried to download song %s with wrong API %s", song, self.get_name())
        return song.song_id + ".mp3"

    def _load_next_songs(self, max_load=20):
        """
        Load the next songs up to max_load.
        :param max_load: the maximum number of songs to load
        """
        if len(self._next_songs) >= max_load:
            return

        playlist = self._active_playlist
        last_played = self._last_played
        if not playlist:
            self._next_songs.extend([choice(self._songs) for i in range(0, max_load)])
            return

        conflicts = 0
        extender = []
        while len(extender) < max_load and conflicts < 20:
            store_id = choice(playlist.song_ids)
            if store_id in last_played or store_id in extender:
                conflicts += 1
                continue
            extender.append(store_id)
        self._next_songs.extend(extender)

    def get_song(self):
        self._load_next_songs(1)
        return self._next_songs.pop(0)

    def get_suggestions(self, max_len=20):
        self._load_next_songs(max_len)
        return self._next_songs[:max_len]

    def remove_playlist(self, playlist_id):
        playlist = OfflineAPI._Playlist(playlist_id, "", set())
        if playlist in self._playlists:
            self._playlists.remove(playlist)

    def add_playlist(self, playlist_id, name, song_ids):
        self._playlists.add(OfflineAPI._Playlist(playlist_id, name, song_ids))

    def add_to_playlist(self, song):
        if self._active_playlist:
            self._active_playlist.add(song)

    def remove_from_playlist(self, song):
        if self._active_playlist:
            self._active_playlist.remove(song)

    def remove_from_suggestions(self, song: Song):
        try:
            self._next_songs.remove(song)
        except ValueError:
            pass

    def get_available_playlists(self):
        """
        Get a list of available playlists
        :return: a list of (playlist_id, playlist_name) tuples
        """
        return list(map(lambda playlist: (playlist.playlist_id, playlist.name), self._playlists))

    def get_active_playlist(self):
        """
        Get the active playlist
        :return: a (playlist_id, playlist_name) tuple or None
        """
        playlist = self._active_playlist
        if playlist:
            return playlist.playlist_id, playlist.name
        return None

    def set_active_playlist(self, playlist_id):
        for playlist in self._playlists:
            if playlist.playlist_id == playlist_id:
                self._active_playlist = playlist
                self._next_songs = []
                self._last_played = []
                return
        raise ValueError("Unknown playlist")

    def get_playlist(self):
        if self._active_playlist:
            return list(map(self.lookup_song, self._active_playlist.song_ids))
        else:
            return []

    def search_song(self, query, max_fetch=100):
        songs = self._songs
        query_parts = query.strip().lower().split(" ")

        def _match(song):
            title = song.title
            description = song.description
            song_str = title
            if title:
                song_str += " " + description
            else:
                song_str = description
            song_str = song_str.lower()
            for part in query_parts:
                if part in song_str:
                    return True

        return list(filter(_match, songs))

    def lookup_song(self, song_id):
        try:
            return self._song_ids[song_id]
        except KeyError:
            return None

    def reset(self):
        self._active_playlist = None
        self._last_played = []
        os.remove(os.path.join(_songs_path, "playlists.json"))

    class _Playlist(object):
        def __init__(self, playlist_id, name, song_ids):
            self.playlist_id = playlist_id
            self.name = name
            self.song_ids = set(song_ids)

        def add(self, song):
            self.song_ids.add(song)

        def remove(self, song):
            try:
                self.song_ids.remove(song)
            except KeyError:
                pass

        def to_json(self):
            return {
                "playlist_id": self.playlist_id,
                "name": self.name,
                "song_ids": list(self.song_ids)
            }

        @staticmethod
        def from_json(song_ids, playlist_json):
            try:
                playlist_id = playlist_json['playlist_id']
                name = playlist_json['name']
                song_ids = set(filter(lambda song_id: song_id in song_ids, playlist_json['song_ids']))
            except KeyError:
                raise ValueError()
            return OfflineAPI._Playlist(playlist_id, name, song_ids)

        def __eq__(self, other):
            return self.playlist_id == other.playlist_id

        def __hash__(self):
            return hash(self.playlist_id)
