import glob
import os
import sys
from pathlib import Path
from shutil import copyfile

import requests
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import EasyMP3
from mutagen.id3 import ID3, APIC


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
        else:
            raise Exception("Токен не найден")

    @staticmethod
    def __ntfs(filename):
        for ch in ["<", ">", "@", "%", "!", "+", ":", '"', "/", "\\", "|", "?", "*"]:
            if ch in filename:
                filename = filename.replace(ch, "_")
        filename = " ".join(filename.split())
        filename = filename.replace(" .flac", ".flac")
        filename = filename.replace(" .mp3", ".mp3")
        return filename

    @staticmethod
    def __to_str(ids):
        if isinstance(ids, (list, set)):
            ids = ",".join([str(i) for i in ids])
        else:
            ids = str(ids)
        return ids

    def __get_copyright(self, label_ids):
        url = "https://zvuk.com/api/tiny/labels"
        params = {
            "ids": self.__to_str(label_ids)
        }
        r = requests.get(url, params=params, headers=self.headers, verify=self.verify)
        r.raise_for_status()
        resp = r.json(strict=False)

        info = {}
        for i in resp["result"]["labels"].values():
            info[i["id"]] = i["title"]
        return info

    def __get_tracks_metadata(self, track_ids):
        url = "https://zvuk.com/api/tiny/tracks"
        params = {
            "ids": self.__to_str(track_ids)
        }
        r = requests.get(url, params=params, headers=self.headers, verify=self.verify)
        r.raise_for_status()
        resp = r.json(strict=False)

        info = {}
        for s in resp["result"]["tracks"].values():
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
            file_format = "flac" if s["has_flac"] else "mp3"

            info[track_id] = {"track_id": track_id, "release_id": release_id, "author": author, "name": name,
                              "album": album, "genre": genre, "number": number, "image": image, "format": file_format}
        return info

    def __get_tracks_link(self, track_ids):
        links = {}
        index = 0

        print("\nПоиск треков:\n")

        for track_id in track_ids:
            url = "https://zvuk.com/api/tiny/track/stream"
            params = {
                "id": track_id,
                "quality": "flac"
            }
            r = requests.get(url, params=params, headers=self.headers, verify=self.verify)
            r.raise_for_status()
            resp = r.json(strict=False)

            links[track_id] = resp["result"]["stream"]
            if links[track_id] != 0:
                index += 1
                print(f'{index}. id: {track_id}, url: {resp["result"]["stream"]}')

        return links

    def __get_releases_info(self, release_ids):
        url = "https://zvuk.com/api/tiny/releases"
        params = {
            "ids": self.__to_str(release_ids)
        }
        r = requests.get(url, params=params, headers=self.headers, verify=self.verify)
        r.raise_for_status()
        resp = r.json(strict=False)

        labels = set()
        for i in resp["result"]["releases"].values():
            labels.add(i["label_id"])
        labels_info = self.__get_copyright(labels)

        info = {}
        for a in resp["result"]["releases"].values():
            info[a["id"]] = {"track_ids": a["track_ids"], "tracktotal": len(a["track_ids"]),
                             "copyright": labels_info.get(a["label_id"], ""), "date": a["date"],
                             "album": a["title"], "author": a["credits"]}
        # print(info)
        return info

    def __get_playlists_info(self, playlist_ids):
        url = "https://zvuk.com/api/tiny/playlists"
        params = {
            "ids": self.__to_str(playlist_ids)
        }
        r = requests.get(url, params=params, headers=self.headers, verify=self.verify)
        r.raise_for_status()
        resp = r.json(strict=False)

        return resp

    def __download_image(self, release_id, image_link):
        pic = Path(f"temp_{release_id}.jpg")
        if not pic.is_file():
            r = requests.get(image_link, allow_redirects=True, verify=self.verify)
            r.raise_for_status()
            with open(pic, "wb") as p:
                p.write(r.content)
        return pic

    def __save_track(self, url, metadata, releases, is_single, is_playlist, path):
        pic = self.__download_image(metadata["release_id"], metadata["image"])

        folder = self.__ntfs(path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)

        if not is_single and not is_playlist:
            if not os.path.isfile(os.path.join(folder, "cover.jpg")):
                copyfile(pic, os.path.join(folder, "cover.jpg"))
            filename = f'{metadata["number"]:02d} - {metadata["name"]}.{metadata["format"]}'
        else:
            filename = f'{metadata["author"]} - {metadata["name"]}.{metadata["format"]}'

        filename = self.__ntfs(filename)
        filename = os.path.join(folder, filename)

        r = requests.get(url, allow_redirects=True, verify=self.verify)
        r.raise_for_status()

        with open(filename, "wb") as f:
            f.write(r.content)

        with open(pic, "rb") as p:
            cover = p.read()

        if metadata["format"] == "flac":
            audio = FLAC(filename)
            audio["ARTIST"] = metadata["author"]
            audio["TITLE"] = metadata["name"]
            audio["ALBUM"] = metadata["album"]
            audio["GENRE"] = metadata["genre"]
            audio["DATE"] = str(releases["date"])[:4]
            audio["TRACKNUMBER"] = str(metadata["number"])
            audio["TRACKTOTAL"] = str(releases["tracktotal"])
            audio["COPYRIGHT"] = releases["copyright"]

            audio["RELEASE_ID"] = str(metadata["release_id"])
            audio["TRACK_ID"] = str(metadata["track_id"])

            coverart = Picture()
            coverart.data = cover
            coverart.type = 3
            coverart.mime = "image/jpeg"
            audio.add_picture(coverart)
            audio.save()
        else:
            audio = EasyMP3(filename)
            audio["artist"] = metadata["author"]
            audio["title"] = metadata["name"]
            audio["album"] = metadata["album"]
            audio["genre"] = metadata["genre"]
            audio["date"] = str(releases["date"])[:4]
            audio["tracknumber"] = str(metadata["number"])
            audio["copyright"] = releases["copyright"]
            audio.save()

            id3_tag = ID3(filename)
            #id3_tag.delall("APIC")
            if not id3_tag.get("APIC:"):
                coverart = APIC()
                coverart.data = cover
                coverart.type = 3
                coverart.mime = "image/jpeg"
                id3_tag["APIC"] = coverart
            id3_tag.save()

        # Printing the metadata
        print(audio.pprint())

    def download_tracks(self, track_ids, is_single=False, is_playlist=False, releases=None, path=""):
        metadata = self.__get_tracks_metadata(track_ids)
        link = self.__get_tracks_link(track_ids)

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
            self.__save_track(link[i], metadata[i], releases[metadata[i]["release_id"]], is_single, is_playlist, path)

    def download_albums(self, release_ids):
        releases = self.__get_releases_info(release_ids)

        print("\nИнформация о релизе: \n")
        from pprint import pprint
        pprint(releases)

        for i in releases.values():
            track_ids = i["track_ids"]
            album_path = f'{i["author"]} - {i["album"]} ({str(i["date"])[:4]})'
            self.download_tracks(track_ids, is_single=False, is_playlist=False, releases=releases, path=album_path)

    def download_playlists(self, playlist_ids):
        playlists = self.__get_playlists_info(playlist_ids)

        print("\nИнформация о плейлисте: \n")
        from pprint import pprint
        pprint(playlists)

        for i in playlists["result"]["playlists"].values():
            track_ids = i["track_ids"]
            playlist_path = i["title"]
            self.download_tracks(track_ids, is_single=False, is_playlist=True, path=playlist_path)


if __name__ == "__main__":

    release_ids = []
    track_ids = []
    playlist_ids = []
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
            elif "playlist" in i:
                playlist_ids.append(int(i.strip("https://zvuk.com/playlist/")))

        z.read_token()
        if release_ids:
            z.download_albums(release_ids)
        if track_ids:
            z.download_tracks(track_ids, is_single=True, is_playlist=False)
        if playlist_ids:
            z.download_playlists(playlist_ids)
        list(map(os.remove, glob.glob("temp*.jpg")))
