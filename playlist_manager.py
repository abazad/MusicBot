import difflib
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from gmusicapi import CallFailure

from musicbot.music_apis import GMusicAPI, OfflineAPI


def download_songs(song_ids):
    songs = map(gmusic_api.lookup_song, song_ids)

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
    share_token = input("Please enter a share token: ").strip()
    try:
        if not share_token:
            print("Empty share token")
            return

        if share_token.endswith("%3D%3D"):
            share_token = share_token[:-6] + "=="

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
            track = song_json['track']
            if "storeId" in track:
                return track['storeId']
            else:
                return track['id']
        except KeyError:
            return None

    song_ids = filter(None, map(_get_song_id, playlist))

    # Download songs
    print("Downloading songs in playlist", name)
    download_songs(song_ids)

    print("Updating playlists.json")
    offline_api.remove_playlist(share_token)
    offline_api.add_playlist(share_token, name, song_ids)
    offline_api.save_playlists()
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
    offline_api.save_playlists()
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
