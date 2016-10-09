import difflib
import os
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from gmusicapi import CallFailure
from mutagen.id3 import ID3
from mutagen.mp3 import MP3, HeaderNotFoundError

from musicbot.music_apis import GMusicAPI, OfflineAPI, Song


def download_songs(song_ids, include_uploaded):
    own_songs = {}
    if include_uploaded:
        # This is a generator object loading 1000 songs at once
        all_songs = api.get_all_songs(True)

    all_songs_lock = threading.Lock()

    def _lookup_song(song_id):
        if not include_uploaded or song_id.startswith("T"):
            return gmusic_api.lookup_song(song_id)
        if song_id in own_songs:
            return own_songs[song_id]
        with all_songs_lock:
            if song_id in own_songs:
                return own_songs[song_id]
            result = None
            for thousand_songs in all_songs:
                for song_json in thousand_songs:
                    if "id" in song_json:
                        song = gmusic_api._song_from_info(song_json)
                        own_songs[song.song_id] = song
                        if song.song_id == song_id:
                            result = song
                if result:
                    break
            return result

    songs = filter(None, map(_lookup_song, song_ids))

    def _load(song):
        print("Loading song", song)
        song.load()

    with ThreadPoolExecutor(os.cpu_count() * 2) as thread_pool:
        loading = thread_pool.map(_load, songs)
        for _ in loading:
            pass


def ask_for_action():
    message = "\n(1) Add a playlist\n(2) Remove a playlist\n(3) Show playlists\n(4) Exit\nWhat do you want to do? "
    return input(message)


def handle_add_playlist():
    choice = input("(1) a Google Play Music playlist\n(2) a local directory\nWherefrom? ")
    if choice == "1":
        handle_add_gmusic_playlist()
    elif choice == "2":
        handle_add_local_playlist()
    else:
        print("Invalid choice")
        return


def add_directory(playlist_id, directory_path, recursive, db):
    isdir = os.path.isdir
    isfile = os.path.isfile
    join = os.path.join
    for file_path in os.listdir(directory_path):
        joined_path = join(directory_path, file_path)
        if isdir(joined_path):
            if recursive:
                add_directory(playlist_id, joined_path, recursive, db)
            else:
                continue

        if isfile(joined_path) and joined_path.endswith(".mp3"):
            print("Loading song", joined_path)
            try:
                audio = MP3(joined_path, ID3=ID3)
            except HeaderNotFoundError:
                print("No ID3 header found for", joined_path)
                continue
            id3 = audio.tags
            try:
                title = id3['TIT2'][0]
                if "TPE1" in id3:
                    artist = id3['TPE1']
                else:
                    artist = id3.get("TPE2", None) or id3["TPE3"]
                artist = artist[0]

                if "APIC:" in id3:
                    apic = id3['APIC:']
                    db.execute("INSERT OR IGNORE INTO albumArts(songId, albumArt) VALUES(?, ?)",
                               [joined_path, apic.data])
                duration = datetime.fromtimestamp(audio.info.length).strftime("%M:%S")
                song = Song(joined_path, offline_api, title, artist, duration=duration)
            except (KeyError, IndexError) as e:
                print("Could not load", joined_path, e)
                continue

            song_tuple = (joined_path, song.title, song.description, str(song), joined_path)
            db.execute(
                "INSERT OR IGNORE INTO songs(songId, title, description, stringRep, path) VALUES(?, ?, ?, ?, ?)",
                song_tuple)
            db.execute("INSERT OR IGNORE INTO playlistSongs(songId, playlistId) VALUES(?, ?)",
                       (joined_path, playlist_id))


def handle_add_local_playlist():
    directory_path = input("Enter a directory path: ")
    if not os.path.isdir(os.path.expanduser(directory_path)):
        print("Invalid directory")
        return
    rec_choice = input("Include subdirectories (Y/N)? ").lower()
    recursive = rec_choice == "y"

    name = input("How do you want to call the playlist? ")

    real_path = os.path.realpath(directory_path)
    db = sqlite3.connect(offline_api._db_path)
    try:
        with db:
            db.execute("INSERT INTO playlists(playlistId, name) VALUES(?, ?)", [real_path, name])
            add_directory(real_path, real_path, recursive, db)
    finally:
        db.close()


def handle_add_gmusic_playlist():
    share_token = input("Please enter a share token: ").strip()
    if not share_token:
        print("Empty share token")
        return

    incluce_uploaded = input(
        "Do you want to include your own (uploaded) songs (Y/N)? May take significantly longer. ").strip().lower()
    incluce_uploaded = incluce_uploaded == "y"
    try:
        if share_token.endswith("%3D%3D"):
            share_token = share_token[:-6] + "=="

        if incluce_uploaded:
            playlists = list(filter(lambda p: p['shareToken'] == share_token, api.get_all_user_playlist_contents()))
            if playlists:
                playlist = playlists[0]['tracks']
            else:
                print("Invalid share token")
                return
        else:
            playlist = api.get_shared_playlist_contents(share_token)
    except CallFailure as e:
        print("Invalid share token", e)
        return

    if not playlist:
        print("Empty or invalid playlist")
        return

    name = None
    while not name:
        name = input("How do you want to call the playlist (no spaces, hopefully unique)? ").strip()
        if " " in name:
            name = None

    def _get_song_id(song_json):
        try:
            return song_json['trackId']
        except KeyError:
            return None

    song_ids = list(filter(None, map(_get_song_id, playlist)))

    # Download songs
    print("Downloading songs in playlist", name)
    download_songs(song_ids, incluce_uploaded)

    print("Updating playlists database")
    offline_api.add_playlist(share_token, name, song_ids)
    print("Done.")


def handle_remove_playlist():
    playlists = offline_api.get_available_playlists()
    if not playlists:
        print("There are no playlists")
        return
    message = "(1) enter a share token\n(2) search by name\n(3) pick from list\nHow do you want to specify the playlist? "
    method = input(message)
    share_token = None
    if method == "1":
        share_token = input("Enter a share token: ").strip()
    elif method == "2":
        name = input("Enter a playlist name (no spaces): ").strip()
        possibilities = list(map(lambda playlist_tuple: playlist_tuple[1], playlists))
        matches = difflib.get_close_matches(name, possibilities, 10)
        if not matches:
            print("No matches")
            return
        if len(matches) > 1:
            for match in enumerate(matches):
                print("(" + str(match[0]) + ")", match[1])
            choice = input("Which one do you mean? ")
            try:
                choice = int(choice)
                name = matches[choice]
            except (ValueError, IndexError):
                print("Invalid choice")
                return
        else:
            name = matches[0]
        for playlist_tuple in playlists:
            if playlist_tuple[1] == name:
                share_token = playlist_tuple[0]
        if not share_token:
            print("Unknown playlist")
            return
    elif method == "3":
        for playlist in enumerate(playlists):
            print(playlist[0], "|", playlist[1][1])
        choice = input("Which one do you want to remove? ")
        try:
            choice = int(choice)
            share_token = playlists[choice][0]
        except (ValueError, IndexError):
            print("Invalid choice")
            return
    else:
        print("Invalid input")
        return

    print("Removing playlist")
    offline_api.remove_playlist(share_token)
    print("Done.")


def show_playlists():
    print("Available playlists:")
    playlists = offline_api.get_available_playlists()
    if not playlists:
        print("None")
    for playlist_tuple in playlists:
        print(playlist_tuple[1])


if __name__ == "__main__":
    offline_api = OfflineAPI()

    try:
        gmusic_api = GMusicAPI()
        api = gmusic_api.get_api()
    except ValueError:
        print("Couldn't connect to GMusic")
        sys.exit(1)
    try:
        while True:
            action = ask_for_action()
            if action == "1":
                handle_add_playlist()
            elif action == "2":
                handle_remove_playlist()
            elif action == "3":
                show_playlists()
            elif action == "4":
                break
            else:
                print("Invalid input")
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(0)
