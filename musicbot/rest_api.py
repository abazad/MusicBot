import asyncio
import logging
import os
import sqlite3
import threading
import time
import uuid

import falcon
import hug
import jwt
from passlib.hash import bcrypt_sha256
from pylru import lrudecorator

from musicbot import async_handler
from musicbot import config
from musicbot.music_apis import Song, AbstractSongProvider, AbstractAPI


class _API(object):
    '''
    Represents an API
    '''

    def __init__(self, api):
        if not isinstance(api, AbstractAPI):
            raise ValueError("Not an AbstractAPI implementation")

        self.api = api
        self.api_pretty_name = api.get_pretty_name()
        self.api_name = self.api.get_name()
        self.is_song_provider = isinstance(api, AbstractSongProvider)

    def to_json(self):
        return {"api_name": self.api_name,
                "is_song_provider": self.is_song_provider,
                "api_pretty_name": self.api_pretty_name}

    @staticmethod
    def from_json(api_json):
        try:
            api_name = api_json['api_name']
        except KeyError:
            raise ValueError("Invalid JSON. Missing key: 'api_name'")

        try:
            api = music_api_names[api_name]
        except KeyError:
            raise ValueError("Unknown API: " + api_name)

        return _API(api)

    def __eq__(self, other):
        if not isinstance(other, _API):
            return False
        return self.api_name == other.api_name

    def __hash__(self):
        return hash(self.api_name)


class _Permission(object):
    def __init__(self, name, description):
        self.name = name
        self.description = description

    def to_json(self):
        return {
            "name": self.name,
            "description": self.description
        }

    @staticmethod
    def from_json(perm_json):
        try:
            name = perm_json['name']
            description = perm_json['description']
        except KeyError:
            return ValueError("Missing key in json")
        return _Permission(name, description)


class _SecretClient(object):
    def __init__(self, name, pw_hash, permissions):
        self.name = name
        self.pw_hash = pw_hash
        self.permissions = permissions

    def __eq__(self, other):
        if not isinstance(other, _SecretClient):
            return False
        return str(self) == str(other)

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return "User {}: [permissions={}] [pw_hash={}]".format(self.name, self.permissions, self.pw_hash)

    def to_json(self):
        return {"name": self.name,
                "permissions": self.permissions,
                "pw_hash": self.pw_hash}

    @staticmethod
    def from_json(client_json):
        try:
            name = client_json['name']
            pw_hash = client_json['pw_hash']
            permissions = client_json['permissions']
            return _SecretClient(name, pw_hash, permissions)
        except KeyError as e:
            raise ValueError("Missing key: " + str(e))


def _create_token(secrets):
    '''
    Create a string token, write it to secrets['rest_token'] and return it.
    '''
    token = str(uuid.uuid4())
    secrets['rest_token'] = token
    return token


def _create_user_token(username, permissions):
    """
    Creates an encoded user token.
    :param username: the username
    :param permissions: a list of permissions (strings)
    :return: the encoded token
    """
    user_token = {
        "name": username,
        "permissions": permissions
    }
    return jwt.encode(user_token, token, algorithm="HS256")


def _read_secrets():
    secrets = config.get_secrets()
    if "rest_token" in secrets:
        return secrets['rest_token']
    else:
        result = _create_token(secrets)
        config.save_secrets()
        return result


def _get_db_conn():
    return sqlite3.connect("config/clients.db")


@lrudecorator(256)
def _get_client(username):
    db = _get_db_conn()
    try:
        cursor = db.cursor()
        cursor.execute("SELECT pw_hash, permissions FROM clients WHERE username=?", [username])
        client_row = cursor.fetchone()
        if not client_row:
            return None
        pw_hash = client_row[0]
        permissions = client_row[1].split(",")
        return _SecretClient(username, pw_hash, permissions)
    finally:
        db.close()


def _add_client(client):
    with _add_client_lock:
        if _get_client(client.name):
            raise ValueError("client already in clients")
        db = _get_db_conn()
        try:
            db.execute("INSERT INTO clients(username, pw_hash, permissions) VALUES(?, ?, ?)",
                       (client.name,
                        client.pw_hash,
                        ",".join(client.permissions)))
            db.commit()
        finally:
            db.close()


available_permissions = [
    _Permission("mod", "all admin permissions, except exit, reset and granting permissions"),
    _Permission("queue_remove", "remove a song from the queue"),
    _Permission("exit", "shut the bot down"),
    _Permission("reset", "reset all bot settings, delete the remote playlist and shut the program down")
]

_add_client_lock = threading.Lock()
player = None
queue = []
music_api_names = {}
apis_json = []
token = None

logger = logging.getLogger("musicbot")

db = _get_db_conn()
db.execute(
    "CREATE TABLE IF NOT EXISTS clients (userid INTEGER PRIMARY KEY ASC AUTOINCREMENT, username TEXT UNIQUE NOT NULL, pw_hash CHAR(75) NOT NULL, permissions TEXT)")
db.commit()
db.close()


def init(music_apis, queued_player):
    """
    Keyword arguments:
    music_apis -- a list of AbstractAPIs
    queued_player -- a Player instance
    """
    global music_api_names
    global apis_json
    global player
    global queue
    global token
    music_api_names = {api.get_name(): api for api in music_apis}
    apis_json = list(map(lambda music_api: _API(music_api).to_json(), music_apis))
    player = queued_player
    queue = player.get_queue()
    token = _read_secrets()


def verify(user_token):
    try:
        return jwt.decode(user_token, token, algorithm="HS256")
    except (KeyError, jwt.InvalidTokenError):
        return False


authentication = hug.authentication.token(verify)


@hug.post()
def register(username, password, response=None):
    if not username or not username.strip():
        logger.debug("Empty username")
        response.status = falcon.HTTP_BAD_REQUEST
        return "Empty username"
    username = username.strip().lower()
    if len(username) > 64:
        logger.debug("Username too long")
        response.status = falcon.HTTP_UNPROCESSABLE_ENTITY
        return "Username too long"
    if _get_client(username):
        logger.debug("Username %s already in use", username)
        response.status = falcon.HTTP_CONFLICT
        return "Name already in use"

    if len(password.strip()) < 6:
        logger.debug("Password too short")
        response.status = falcon.HTTP_BAD_REQUEST
        return "Invalid password. Must be of length >= 6"
    pw_hash = bcrypt_sha256.encrypt(password)
    client = _SecretClient(username, pw_hash, ["user"])
    try:
        _add_client(client)
    except ValueError:
        logger.debug("Username %s already in database", username)
        response.status = falcon.HTTP_CONFLICT
        return "Name already in use"
    logger.debug("Registered new user: %s", username)
    return _create_user_token(username, client.permissions)


@hug.put()
def login(username, password, response=None):
    """
    Logs user in. Returns status 400 response if user doesn't exist or password is wrong.
    :param username: a username
    :param password: a password
    :return: a token to authenticate with
    """
    if not username or not username.strip():
        logger.debug("Tried to log in with empty username")
        response.status = falcon.HTTP_400
        return "empty username"
    username = username.strip().lower()
    client = _get_client(username)
    if not client:
        logger.debug("Tried to log in with unknown username: %s", username)
        response.status = falcon.HTTP_400
        return "unknown"
    success = bcrypt_sha256.verify(password, client.pw_hash)
    if not success:
        logger.debug("Tried to log in with wrong password as user %s", username)
        response.status = falcon.HTTP_400
        return "wrong password"
    logger.debug("New user login: %s", username)
    return _create_user_token(username, client.permissions)


@asyncio.coroutine
@hug.put(requires=authentication)
def change_password(old_password, new_password, user: hug.directives.user, response=None):
    """
    Change the password of the user if the old password is correct and the new one satisfies the password requirements.
    :param old_password: the old password
    :param new_password: the new password
    """
    client = _get_client(user['name'])
    success = bcrypt_sha256.verify(old_password, client.pw_hash)
    if not success:
        logger.debug("%s tried to change his password with a wrong old password", user['name'])
        response.status = falcon.HTTP_FORBIDDEN
        return "Wrong password"

    new_password = new_password.strip()
    if len(new_password) < 6:
        logger.debug("Password too short")
        response.status = falcon.HTTP_BAD_REQUEST
        return "Invalid password. Must be of length >= 6"

    pw_hash = bcrypt_sha256.encrypt(new_password)

    db = _get_db_conn()
    try:
        db.execute("UPDATE clients SET pw_hash=? WHERE username=?", pw_hash, user['name'])
        db.commit()
        return "OK"
    finally:
        db.close()


@asyncio.coroutine
@hug.put(requires=authentication)
def delete_user(password, user: hug.directives.user, response=None):
    """
    Delete the users account.
    :param password: the user's password
    """
    client = _get_client(user['name'])
    success = bcrypt_sha256.verify(password, client.pw_hash)
    if not success:
        logger.debug("%s tried to delete his account with a wrong password", user['name'])
        response.status = falcon.HTTP_FORBIDDEN
        return "Wrong password"

    db = _get_db_conn()
    try:
        db.execute("DELETE FROM clients WHERE username=?", user['name'])
        db.commit()
        return "OK"
    finally:
        db.close()


@hug.get()
def music_apis():
    return apis_json


@asyncio.coroutine
@hug.put(requires=authentication)
def queue(body, remove: hug.types.boolean = False, user: hug.directives.user = None, response=None):
    try:
        song = Song.from_json(body, music_api_names)
        song.user = user['name']
    except ValueError as e:
        logger.debug("Received bad json %s", e)
        response.status = falcon.HTTP_400
        return str(e)

    if remove:
        if not has_permission(user, ["admin", "mod", "queue_remove"]):
            logger.debug("Unauthorized attempt to remove song from queue by %s", user['name'])
            response.status = falcon.HTTP_FORBIDDEN
            return "Not permitted"
        try:
            logger.debug("Song %s removed by %s", song, user['name'])
            queue.remove(song)
        except ValueError:
            logger.debug("%s tried to remove Song not in queue: %s", user['name'], song)
            response.status = falcon.HTTP_400
            return "song {} is not in queue".format(song)
    else:
        logger.debug("Song %s added by %s", song, user['name'])
        queue.append(song)
    return "OK"


@asyncio.coroutine
@hug.get()
def suggestions(api_name, max_fetch: hug.types.number = 10, response=None):
    max_fetch = min(10, max(1, max_fetch))

    try:
        api = music_api_names[api_name]
    except KeyError:
        response.status = falcon.HTTP_400
        return "Unknown API"

    if isinstance(api, AbstractSongProvider):
        return list(map(Song.to_json, api.get_suggestions(max_fetch)))
    else:
        logger.debug("Tried to get suggestions for API %s which isn't a SongProvider", api_name)
        response.status = falcon.HTTP_400
        return []


@asyncio.coroutine
@hug.get()
def search(api_name, query, max_fetch: hug.types.number = 50, response=None):
    max_fetch = min(50, max(1, max_fetch))
    try:
        api = music_api_names[api_name]
    except KeyError:
        logger.debug("Tried to search on unknown API %s", api_name)
        response.status = falcon.HTTP_400
        return "Unknown API"

    if not query:
        response.status = falcon.HTTP_400
        return "Invalid query"

    return list(map(Song.to_json, api.search_song(query, max_fetch=max_fetch)))


@hug.local()
@hug.get()
def player_state():
    current_song = player.get_current_song()
    if current_song:
        song_json = current_song.to_json()
    else:
        song_json = None

    return {"current_song": song_json,
            "last_played": list(map(Song.to_json, player.get_last_played())),
            "queue": list(map(Song.to_json, queue)),
            "paused": player.is_paused()}


@hug.put(requires=authentication)
def toggle_pause(user: hug.directives.user):
    if player._pause:
        logger.debug("Resumed by %s", user['name'])
        player.resume()
    else:
        logger.debug("Paused by %s", user['name'])
        player.pause()
    return player_state()


@asyncio.coroutine
@hug.put(requires=authentication)
def next_song(user: hug.directives.user):
    logger.debug("Skip to next song by %s", user['name'])
    player.next()
    return player_state()


@asyncio.coroutine
@hug.put(requires=authentication)
def move(moving_song_json, other_song_json, after_other: hug.types.boolean = False, response=None):
    try:
        moving_song = Song.from_json(moving_song_json, music_api_names)
        other_song = Song.from_json(other_song_json, music_api_names)
    except ValueError as e:
        logger.debug("Received invalid json (%s): %s , %s", str(e), moving_song_json, other_song_json)
        response.status = falcon.HTTP_400
        return str(e)

    try:
        queue.remove(moving_song)
    except ValueError:
        logger.debug("Tried to move song %s that wasn't in the queue", moving_song)
        response.status = falcon.HTTP_400
        return "song {} is not in queue".format(moving_song)

    try:
        index = queue.index(other_song)
        if after_other:
            index += 1
        queue.insert(index, moving_song)
        logger.debug("Moved song %s after/before(%s) %s", moving_song, after_other, other_song)
        return player_state()
    except ValueError:
        logger.debug("Couldn't move song %s, because other song %s was removed from queue", moving_song, other_song)
        response.status = falcon.HTTP_400
        return "song {} is not in queue".format(other_song)


@hug.local()
@asyncio.coroutine
@hug.get(requires=authentication)
def has_admin(user: hug.directives.user = None):
    """
    Check whether the server has an admin.
    If there is none and none is allowed, also returns True.
    :return: True or False
    """
    if not config.get_allow_rest_admin():
        return True
    if user and ("admin" in user['permissions']):
        return True
    db = _get_db_conn()
    try:
        cursor = db.cursor()
        cursor.execute("SELECT permissions FROM clients")
        rows = cursor.fetchall()
        for row in rows:
            if "admin" in row[0].split(","):
                return True
        return False
    finally:
        db.close()


@hug.local()
@hug.get(requires=authentication)
def is_admin(user: hug.directives.user):
    """
    Check whether the the calling user is admin
    :return: True or False
    """
    return "admin" in user['permissions']


@hug.local()
@asyncio.coroutine
@hug.get(requires=authentication)
def has_permission(user: hug.directives.user, needed_permissions=["admin"]):
    """
    Ensure that a user has at least one of the needed permissions.
    :param needed_permissions: an iterable of permission strings
    :return: True or False
    """
    return not set(user['permissions']).isdisjoint(set(needed_permissions))


@asyncio.coroutine
@hug.get(requires=authentication)
def get_permissions(user: hug.directives.user):
    """
    Return the permissions of the client.
    :return: a list of permissions
    """
    return user['permissions']


claim_admin_lock = threading.Lock()


@asyncio.coroutine
@hug.get(requires=authentication)
def claim_admin(user: hug.directives.user, response=None):
    """
    Request admin rights. If allow_rest_admin is set in config and no other admin exists, return admin token.
    :return: an admin token on success.
    """
    username = user['name']
    permissions = user['permissions']
    if "admin" in permissions:
        response.status = falcon.HTTP_400
        return None
    with claim_admin_lock:
        if has_admin():
            logger.debug("%s tried to claim admin rights, but there already is an admin.", user['name'])
            response.status = falcon.HTTP_CONFLICT
            return None
        permissions.append("admin")
        permissions = list(set(permissions))
        db = _get_db_conn()
        try:
            db.execute("UPDATE clients SET permissions=? WHERE username=?", (",".join(permissions), username))
            db.commit()
        finally:
            db.close()
    return _create_user_token(username, permissions)


@hug.local()
@asyncio.coroutine
@hug.get(requires=authentication)
def get_available_permissions(user: hug.directives.user = None, response=None):
    """
    Return a list of available permissions an admin can grant to users.
    Needs admin permission.
    :return: a list of permissions
    """
    if user and (not is_admin(user)):
        logger.debug("%s tried to get available permissions but is not admin.", user['name'])
        response.status = falcon.HTTP_FORBIDDEN
        return None
    return available_permissions


@hug.local()
@asyncio.coroutine
@hug.get(requires=authentication)
def get_users(user: hug.directives.user = None, response=None):
    """
    Return a list of all registered users with their permissions.
    Needs admin permission.
    :return: a list of users or None
    """
    if user and (not is_admin(user)):
        logger.debug("%s tried to get users but is not admin", user['name'])
        response.status = falcon.HTTP_FORBIDDEN
        return None
    db = _get_db_conn()
    try:
        cursor = db.cursor()
        cursor.execute("SELECT username, permissions FROM clients")
        result = []
        for row in cursor.fetchall():
            result.append({
                "username": row[0],
                "permissions": row[1].split(",")
            })
        return result
    finally:
        db.close()


@asyncio.coroutine
@hug.put(requires=authentication)
def grant_permission(target_username, permission: hug.types.json, user: hug.directives.user = None, response=None):
    """
    Grant a permission to a user
    Note that the new permissions only apply after the user logged out and in again.
    Needs admin permission.
    :param target_username: the username of the user the permission should be granted
    :param permission: the permission as returned by get_permissions
    :return: 'OK', error message or None
    """
    if not is_admin(user):
        logger.debug("%s tried to grant a permission %s to %s but is not admin.", user['name'], permission,
                     target_username)
        response.status = falcon.HTTP_FORBIDDEN
        return None
    target_username = target_username.strip().lower()
    client = _get_client(target_username)
    if not client:
        logger.debug("%s tried to grant permission to unknown user %s", user['name'], target_username)
        response.status = falcon.HTTP_400
        return "unknown target user"
    permissions = client.permissions
    permissions.append(permission)
    permissions = list(set(permissions))
    db = _get_db_conn()
    try:
        db.execute("UPDATE clients SET permissions=? WHERE username=?", [",".join(permissions), target_username])
    finally:
        db.close()
    return "OK"


@asyncio.coroutine
@hug.put(requires=authentication)
def revoke_permission(target_username, permission: hug.types.json, user: hug.directives.user = None, response=None):
    """
    Revokes a granted permission.
    Note that the new permissions only apply after the user logged out and in again.
    Needs admin permission.
    :param target_username: the username of the user whos permission should be revoked
    :param permission: the permission as returned by get_permissions
    :return: 'OK' or error_message or None
    """
    if not is_admin(user):
        logger.debug("%s tried to revoke a permission %s from %s but is not admin.", user['name'], permission,
                     target_username)
        response.status = falcon.HTTP_FORBIDDEN
        return None
    target_username = target_username.strip().lower()
    client = _get_client(target_username)
    if not client:
        logger.debug("%s tried to revoke permission from unknown user %s", user['name'], target_username)
        response.status = falcon.HTTP_400
        return "unknown target user"
    permissions = client.permissions
    try:
        permissions.remove(permission)
    except ValueError:
        pass
    db = _get_db_conn()
    try:
        db.execute("UPDATE clients SET permissions=? WHERE username=?", [",".join(permissions), target_username])
    finally:
        db.close()
    return "OK"


def _exit():
    time.sleep(2)
    async_handler.shutdown()


@hug.put(requires=authentication)
def exit_bot(user: hug.directives.user, response=None):
    if not has_permission(user, ["admin", "exit"]):
        logger.debug("%s called exit but is not admin", user['name'])
        response.status = falcon.HTTP_FORBIDDEN
        return None

    logger.debug("%s called exit", user['name'])
    async_handler.submit(_exit)
    return "OK"


@hug.put(requires=authentication)
def reset_bot(user: hug.directives.user, response=None):
    if not has_permission(user, ["admin", "reset"]):
        logger.debug("%s called reset but is not permitted", user['name'])
        response.status = falcon.HTTP_FORBIDDEN
        return None

    logger.debug("%s called reset", user['name'])

    for api_name in music_api_names:
        api = music_api_names[api_name]
        if isinstance(api, AbstractSongProvider):
            api.reset()

    del config.get_secrets()['rest_token']
    config.save_secrets()
    os.remove("config/clients.db")

    async_handler.submit(_exit)
    return "OK"
