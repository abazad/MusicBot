import os
import sys
from zipfile import ZipFile

import main


whitelist = ["config", "musicbot", "LICENSE", "main.py", "requirements.txt", "updater.py"]


def _add_file(package, cur_dir, file):
    path = os.path.join(cur_dir, file)
    if os.path.isdir(path):
        for file in os.listdir(path):
            _add_file(package, path, file)
        return
    package.write(path)


def _create_package(source_path=".", target_dir=".", branch="unknown", snapshot=True):
    if snapshot:
        snapshot = "-SNAPSHOT"
    else:
        snapshot = ""

    package_fname = "TelegramMusicBot-{version}-{branch}{snapshot}.zip".format(
        version=main.__version__, branch=branch, snapshot=snapshot)

    files = os.listdir(source_path)
    try:
        with ZipFile(package_fname, 'w') as package:
            for file in files:
                if file in whitelist:
                    _add_file(package, source_path, file)
    except Exception as e:
        print(e)

if __name__ == '__main__':
    branch = True
    snapshot = True
    if len(sys.argv) >= 2:
        for arg in sys.argv[1:]:
            if arg == "--tag" or arg == "-t":
                branch = os.environ['CIRCLE_TAG']
                snapshot = False
            if arg == "--branch" or arg == "-b":
                branch = os.environ['CIRCLE_BRANCH']
    else:
        print("defaulting to branch build")
        try:
            branch = os.environ['CIRCLE_BRANCH']
        except KeyError:
            print("not a branch build")
            sys.exit(1)

    _create_package(target_dir=os.environ['CIRCLE_ARTIFACTS'], branch=branch, snapshot=snapshot)
