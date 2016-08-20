import configparser
import hashlib
import json
import os
import sys

import requests


def _go_through_files(cur_dir, data, repo_name, bw_list, is_whitelist, file=sys.stdout):
    updated = False
    for content in data:
        path = os.path.join(cur_dir, content['name'])
        print(path, file=file)

        # check if file is in the black/whitelist
        if (content["name"] in bw_list) != is_whitelist:
            print("file found in blacklist/not found in whitelist", file=file)
            continue

        # if there is a directory go through it per recursive call
        if(content["type"] == "dir"):
            os.makedirs(path)
            resp = requests.get(url=content['url'])
            if _go_through_files(path, json.loads(resp.text), repo_name, bw_list, is_whitelist, file):
                updated = True
            continue

        try:  # check if the file is there
            # hash the current file
            with open(path, "r", encoding="utf-8") as f:
                sha1 = hashlib.sha1()
                sha1.update(f.read().encode("utf-8"))
                hashoff = format(sha1.hexdigest())
        except IOError:  # if no file is offline always download
            hashoff = None

        # download the most recent file
        resp = requests.get(url=content["download_url"])

        if hashoff:
            # hash the most recent file
            sha1 = hashlib.sha1()
            sha1.update(resp.text.encode('utf-8'))
            hashon = format(sha1.hexdigest())

        # compare hash of the offline and online file and overwrite if they are
        # different
        if not hashoff or (hashon != hashoff):
            updated = True
            print("difference found, updating", file=file)
            with open(path, "w", encoding="utf-8") as f:
                f.write(resp.text)
        else:
            print("no difference found", file=file)
    return updated


def update(output=sys.stdout):
    config = configparser.ConfigParser()
    config.read_file(open('config/updater.settings'))
    repo_name = config.get("Section1", "repo")
    is_whitelist = config.getboolean("Section1", "whitelist")
    bw_list = str(config.get("Section1", "list")).split("\n")
    # get a list of files in the repo
    resp = requests.get(url="https://api.github.com/repos/" + repo_name + "/contents")
    data = json.loads(resp.text)
    # check these files
    return _go_through_files("", data, repo_name, bw_list, is_whitelist, output)


def main():
    update()


if __name__ == '__main__':
    main()
