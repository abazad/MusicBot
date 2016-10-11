import os
import sys
from zipfile import ZipFile

import _version

whitelist = ["config", "musicbot", "LICENSE", "main.py", "requirements.txt", "updater.py", "playlist_manager.py",
             "invalidate_secret.py"]


def _add_file(package, cur_dir, file):
    path = os.path.join(cur_dir, file)
    if os.path.isdir(path):
        for file in os.listdir(path):
            _add_file(package, path, file)
        return
    package.write(path)


def _create_package():
    try:
        branch = os.environ['CIRCLE_TAG']
        tag = True
    except KeyError:
        try:
            branch = os.environ['CIRCLE_BRANCH']
            tag = False
        except KeyError:
            print("Neither tag nor branch build")
            sys.exit(1)

    repo_name = os.environ['CIRCLE_PROJECT_REPONAME']
    target_dir = os.environ['CIRCLE_ARTIFACTS']
    if tag:
        sha1 = ""
    else:
        sha1 = "-" + os.environ['CIRCLE_SHA1']

    package_fname = os.path.join(
        target_dir, "{repo_name}-{branch}-{version}{sha1}.zip".format(repo_name=repo_name,
                                                                      branch=branch,
                                                                      version=_version.__version__,
                                                                      sha1=sha1))

    files = os.listdir(".")

    with ZipFile(package_fname, 'w') as package:
        for file in files:
            if file in whitelist:
                _add_file(package, ".", file)


if __name__ == '__main__':
    _create_package()
