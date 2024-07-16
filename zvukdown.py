import glob
import os
import sys
from pathlib import Path
from shutil import copyfile

import requests
from mutagen.flac import FLAC, Picture


class Zvukdown:
    def __init__(self):
        self.verify = True
        self.headers = {}

    def read_token(self):
        import os.path
        if os.path.exists("token.txt"):
            with open("token.txt", "r", encoding="utf8") as f:
                token = f.read()
                if len(token) != 32:
                    raise Exception("Некорректный токен")
                self.headers = {"x-auth-token": token}
        else:
            raise Exception("Нет файла token.txt")

    def save_token(self, login, password):
        url = "https://zvuk.com/api/tiny/login/email"
        params = {
            "register": True
        }
        data = {
            "email": login,
            "password": password,
        }
        r = requests.post(url, params=params, data=data, verify=self.verify)
        r.raise_for_status()
        resp = r.json(strict=False)
        token = resp.get("result", {}).get("token")
        if not token:
            token = resp.get("result", {}).get("profile", {}).get("token")
        if token and len(token) == 32:
            with open("token.txt", "w", encoding="utf8") as f:
                f.write(token)
            self.headers = {"x-auth-token": token}
        else:
            raise Exception("Токен не найден")

    @staticmethod
    def __ntfs(filename):
        for ch in ["<", ">", "@", "%", "!", "+", ":", '"', "/", "\\", "|", "?", "*"]:
            if ch in filename:
                filename = filename.replace(ch, "_")
        filename = " ".join(filename.split())
        filename = filename.replace(" .flac", ".flac")
        return filename

    @staticmethod
    def __to_str(l):
        global int
        if isinstance(l, int):
            return [l]
        elif not isinstance(l, str):
            l = [str(int) for int in l]
            l = ",".join(l)
            l = str(l.strip("[]"))
        return l

    def __get_copyright(self, label_ids):
        label_ids = self.__to_str(label_ids)
        url = "https://zvuk.com/api/tiny/labels"
        params = {
            "ids": label_ids
        }
        r = requests.get(url, params=params, headers=self.headers, verify=self.verify)
        r.raise_for_status()
        resp = r.json(strict=False)

        info = {}
        for i in resp["result"]["labels"].values():
            info[i["id"]] = i["title"]
        if not info:
            info = {
                int(label_ids): "Неизвестно"
            }
        return (info)

    def __get_tracks_metadata(self, track_ids):
        track_ids = self.__to_str(track_ids)
        params = {
            "ids": track_ids
        }
        url = "https://zvuk.com/api/tiny/tracks"
        r = requests.get(url, params=params, headers=self.headers, verify=self.verify)
        r.raise_for_status()
        resp = r.json(strict=False)
        info = {}
        for s in resp["result"]["tracks"].values():
            if s["has_flac"]:
                author = s["credits"]
                name = s["title"]
                album = s["release_title"]
                release_id = s["release_id"]
                track_id = s["id"]
                if s["genres"]:
                    genre = ", ".join(s["genres"])
                else:
                    genre = ""

                number = s["position"]
                image = s["image"]["src"].replace(r"&size={size}&ext=jpg", "")

                info[track_id] = {"author": author, "name": name, "album": album, "release_id": release_id,
                                  "track_id": track_id, "genre": genre, "number": number, "image": image}
            else:
                if s["highest_quality"] != "flac":
                    raise Exception("HQ качество не во flac-формате")
                raise Exception(f'Пропускаем трек: «{s["title"]}», т.к. он не во flac-формате')
        return info

    def __get_tracks_link(self, track_ids):
        links = {}
        print("\nПоиск треков:\n")
        index = 0
        for i in track_ids:
            url = "https://zvuk.com/api/tiny/track/stream"
            params = {
                "id": i,
                "quality": "flac"
            }
            r = requests.get(url, params=params, headers=self.headers, verify=self.verify)
            # r.raise_for_status()
            resp = r.json(strict=False)
            links[i] = resp["result"]["stream"]
            if links[i] != 0:
                index += 1
                print(f'{index}. id: {i}, url: {resp["result"]["stream"]}')
        return links

    def __get_releases_info(self, release_ids: object) -> object:
        release_ids = self.__to_str(release_ids)

        info = {}
        url = "https://zvuk.com/api/tiny/releases"
        params = {
            "ids": release_ids
        }
        r = requests.get(url, params=params, headers=self.headers, verify=self.verify)
        r.raise_for_status()
        resp = r.json(strict=False)

        labels = set()
        for i in resp["result"]["releases"].values():
            labels.add(i["label_id"])
        labels_info = self.__get_copyright(labels)

        for a in resp["result"]["releases"].values():
            info[a["id"]] = {"track_ids": a["track_ids"], "tracktotal": len(a["track_ids"]),
                             "copyright": labels_info[a["label_id"]], "date": a["date"],
                             "album": a["title"], "author": a["credits"]}
        # print(info)
        return info

    def __download_image(self, release_id, image_link):
        pic: Path = Path(f"temp_{release_id}.jpg")
        if not pic.is_file():
            r = requests.get(image_link, allow_redirects=True, verify=self.verify)
            with open(pic, "wb") as p:
                p.write(r.content)
        return pic

    def __save_track(self, url, metadata, releases, single):
        pic = self.__download_image(metadata["release_id"], metadata["image"])
        if not single and releases["tracktotal"] != 1:
            folder = f'{releases["author"]} - {releases["album"]} ({str(releases["date"])[:4]})'
            folder = self.__ntfs(folder)
            if not os.path.exists(folder):
                os.makedirs(folder)
                copyfile(pic, os.path.join(folder, "cover.jpg"))
            filename = f'{metadata["number"]:02d} - {metadata["name"]}.flac'
        else:
            folder = ""
            filename = f'{metadata["author"]} - {metadata["name"]}.flac'

        filename = self.__ntfs(filename)
        filename = os.path.join(folder, filename)

        r = requests.get(url, allow_redirects=True, verify=self.verify)
        with open(filename, "wb") as f:
            f.write(r.content)

        with open(pic, "rb")as p:
            cover = p.read()

        audio = FLAC(filename)
        audio["ARTIST"] = metadata["author"]
        audio["TITLE"] = metadata["name"]
        audio["ALBUM"] = metadata["album"]
        audio["TRACKNUMBER"] = str(metadata["number"])
        audio["TRACKTOTAL"] = str(releases["tracktotal"])

        audio["GENRE"] = metadata["genre"]
        audio["COPYRIGHT"] = releases["copyright"]
        audio["DATE"] = str(releases["date"])
        audio["YEAR"] = str(releases["date"])[:4]

        audio["RELEASE_ID"] = str(metadata["release_id"])
        audio["TRACK_ID"] = str(metadata["track_id"])

        coverart = Picture()
        coverart.data = cover
        coverart.type = 3  # as the front cover
        coverart.mime = "image/jpeg"
        audio.add_picture(coverart)

        # Printing the metadata
        print(audio.pprint())

        # Saving the changes
        audio.save()

    def download_tracks(self, track_ids, single=False, releases=""):
        metadata = self.__get_tracks_metadata(track_ids)
        link = self.__get_tracks_link(track_ids)

        if len(metadata) != len(link):
            raise Exception("metadata != link")

        if not releases:
            release_ids = set()
            for i in metadata.values():
                release_ids.add(i["release_id"])
            releases = self.__get_releases_info(release_ids)

        print("\nСкачивание треков:")
        index = 0
        for i in metadata.keys():
            index += 1
            print(f"\nСкачивание трека № {index}")
            self.__save_track(link[i], metadata[i], releases[metadata[i]["release_id"]], single)

    def download_albums(self, release_ids):
        track_ids = []
        releases = self.__get_releases_info(release_ids)

        print("\nИнформация о релизе: \n")
        from pprint import pprint
        pprint(releases)

        for i in releases.values():
            track_ids += i["track_ids"]
        self.download_tracks(track_ids, releases=releases)


if __name__ == "__main__":

    release_ids = []
    track_ids = []
    z = Zvukdown()

    if "login" in sys.argv:
        z.save_token(sys.argv[2], sys.argv[3])
        print("Токен успешно сохранён")
    else:
        if "debug" in sys.argv:
            z.verify = False
        for i in sys.argv:
            if "release" in i:
                release_ids.append(int(i.strip("https://zvuk.com/release/")))
            elif "track" in i:
                track_ids.append(int(i.strip("https://zvuk.com/track/")))

        z.read_token()
        if release_ids:
            z.download_albums(release_ids)
        if track_ids:
            z.download_tracks(track_ids, True)
        list(map(os.remove, glob.glob("temp*.jpg")))
