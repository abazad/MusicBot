import json, requests
import hashlib
import configparser
import codecs

#get config
config = configparser.ConfigParser()
config.readfp(open('updater.settings'))
repoName = config.get("Section1", "repo")
whitelist = config.getboolean("Section1", "whitelist")
BoWList = config.get("Section1", "list").split("\n")


def go_through_files(data):
    for content in data:
        print(content["name"])

        #check if file is in the black/whitelist
        if (content["name"] in BoWList)!=whitelist:
            print("file found in blacklist/not found in whitelist")
            continue

        #if there is a directory go through it per recursive call
        if(content["type"]=="dir"):
            resp = requests.get(url="https://api.github.com/repos/"+ repoName +"/contents/"+content["name"])
            goThroughFiles(json.loads(resp.text))

        try: #check if the file is there
            #hash the current file
            f=codecs.open(content["name"], "rb+", "utf-8")
            sha1 = hashlib.sha1()
            sha1.update(f.read().encode('utf-8'))
            hashoff=format(sha1.hexdigest())

        except IOError: #if no file is offline always download
            f=codecs.open(content["name"], "w", "utf-8")
            hashoff="null"

        #downlaod the most recent file
        resp=requests.get(url=content["download_url"])

        #hash the most recent file
        sha1 = hashlib.sha1()
        sha1.update(resp.text.encode('utf-8'))
        hashon=format(sha1.hexdigest())

        #compare hash of the offline and online file and overwrite if they are different
        if hashon!=hashoff:
            print("difference found, updating")
            f.write(resp.text)
        else:
            print("no difference found")



#main
#get a list of files in the repo
resp = requests.get(url="https://api.github.com/repos/"+ repoName +"/contents")
data = json.loads(resp.text)
#check these files
go_through_files(data)
