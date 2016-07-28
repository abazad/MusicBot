import configparser
import hashlib
import json
import requests
import sys

# get config
config = configparser.ConfigParser()
config.read_file(open('updater.settings'))
repoName = config.get("Section1", "repo")
whitelist = config.getboolean("Section1", "whitelist")
BoWList = config.get("Section1", "list").split("\n")


def _go_through_files(data, file=sys.stdout):
    updated = False
    for content in data:
        print(content["name"], file=file)

        # check if file is in the black/whitelist
        if (content["name"] in BoWList) != whitelist:
            print("file found in blacklist/not found in whitelist", file=file)
            continue

        # if there is a directory go through it per recursive call
        if(content["type"] == "dir"):
            resp = requests.get(
                url="https://api.github.com/repos/" + repoName + "/contents/" + content["name"])
            if _go_through_files(json.loads(resp.text), file):
                updated = True

        try:  # check if the file is there
            # hash the current file
            with open(content["name"], "r", encoding="utf-8") as f:
                sha1 = hashlib.sha1()
                sha1.update(f.read().encode("utf-8"))
                hashoff = format(sha1.hexdigest())
        except IOError:  # if no file is offline always download
            hashoff = None

        # downlaod the most recent file
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
            with open(content["name"], "w", encoding="utf-8") as f:
                f.write(resp.text)
        else:
            print("no difference found", file=file)
    return updated


def update(output=sys.stdout):
    # get a list of files in the repo
    resp = requests.get(
        url="https://api.github.com/repos/" + repoName + "/contents")
    data = json.loads(resp.text)
    # check these files
    return _go_through_files(data, output)


def main():
    update()


if __name__ == '__main__':
    main()
