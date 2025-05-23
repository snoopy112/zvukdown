import glob
import os
import sys
from pathlib import Path
from shutil import copyfile
from pprint import pprint

import requests
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import EasyMP3
from mutagen.id3 import ID3, APIC


class Zvukdown:
    def __init__(self):
        self.verify = True
        self.url = "https://zvuk.com/api/v1/graphql"
        self.headers = {
            "Content-Type": "application/json",
            "Host": "zvuk.com",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15"
        }

    def read_token(self):
        import os.path
        if os.path.exists("token.txt"):
            with open("token.txt", "r", encoding="utf8") as f:
                token = f.read()
                if len(token) != 32:
                    raise Exception("Некорректный токен")
                self.headers.update({"x-auth-token": token})
        else:
            raise Exception("Нет файла token.txt")

    def save_token(self, login, password):
        url = "https://zvuk.com/api/tiny/login/email"
        params = {
            "register": True
        }
        data = {
            "email": login,
            "password": password
        }
        resp = requests.post(url, params=params, data=data, verify=self.verify)
        resp.raise_for_status()
        resp = resp.json(strict=False)

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
    def __extract_metadata(track):
        return {
            "release_id": track["release"]["id"],
            "image": track["release"]["image"]["src"].replace(r"{size}", "orig"),
            "title": track["title"],
            "artist": track["credits"],
            "album": track["release"]["title"],
            "date": track["release"]["date"][:4],
            "genre": ", ".join(i["name"] for i in track["genres"]),
            "copyright": track["release"]["label"]["title"] if track["release"]["label"] else "",
            "tracknumber": str(track["position"]),
            "tracktotal": str(len(track["release"]["tracks"])),
            "format": "flac" if track["hasFlac"] else "mp3",
            "url": track["stream"]["flac"] if track["hasFlac"] else track["stream"]["high"]
        }

    def __get_tracks_info(self, track_ids):
        body = {
            "variables": {
                "ids": track_ids
            },
            "query": """query getFullTrack($ids: [ID!]!) {
                getTracks(ids: $ids) {
                    title
                    credits
                    position
                    genres { name }
                    release { id title date label { title } image { src } tracks { id } }
                    hasFlac
                    stream { flac high }
                }
            }"""
        }
        self.headers.update({"Content-Length": str(len(body["query"]))})

        resp = requests.post(self.url, headers=self.headers, json=body, verify=self.verify)
        resp.raise_for_status()

        return resp.json(strict=False)

    def __get_releases_info(self, release_ids):
        body = {
            "variables": {
                "ids": release_ids
            },
            "query": """query getReleases($ids: [ID!]!) {
                getReleases(ids: $ids) {
                    title
                    credits
                    date
                    tracks {
                        title
                        credits
                        position
                        genres { name }
                        release { id title date label { title } image { src } tracks { id } }
                        hasFlac
                        stream { flac high }
                    }
                }
            }"""
        }
        self.headers.update({"Content-Length": str(len(body["query"]))})

        resp = requests.post(self.url, headers=self.headers, json=body, verify=self.verify)
        resp.raise_for_status()

        return resp.json(strict=False)

    def __get_playlists_info(self, playlist_ids):
        body = {
            "variables": {
                "ids": playlist_ids
            },
            "query": """query getShortPlaylist($ids: [ID!]!) {
                getPlaylists(ids: $ids) {
                    title
                    tracks {
                        title
                        credits
                        position
                        genres { name }
                        release { id title date label { title } image { src } tracks { id } }
                        hasFlac
                        stream { flac high }
                    }
                }
            }"""
        }
        self.headers.update({"Content-Length": str(len(body["query"]))})

        resp = requests.post(self.url, headers=self.headers, json=body, verify=self.verify)
        resp.raise_for_status()

        return resp.json(strict=False)

    def __get_favorites_info(self):
        body = {
            "query": """query userCollection($collectionSubtype: CollectionSubtype = main) {
                collection(collectionSubtype: $collectionSubtype) {
                    tracks {
                        title
                        credits
                        position
                        genres { name }
                        release { id title date label { title } image { src } tracks { id } }
                        hasFlac
                        stream { flac high }
                    }
                }
            }"""
        }
        self.headers.update({"Content-Length": str(len(body["query"]))})

        resp = requests.post(self.url, headers=self.headers, json=body, verify=self.verify)
        resp.raise_for_status()

        return resp.json(strict=False)

    def __download_image(self, release_id, image_link):
        pic = Path(f"temp_{release_id}.jpg")
        if not pic.is_file():
            resp = requests.get(image_link, allow_redirects=True, verify=self.verify)
            resp.raise_for_status()
            with open(pic, "wb") as p:
                p.write(resp.content)
        return pic

    def __save_track(self, metadata, is_release, path):
        pic = self.__download_image(metadata["release_id"], metadata["image"])

        folder = self.__ntfs(path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)

        if is_release:
            if not os.path.isfile(os.path.join(folder, "cover.jpg")):
                copyfile(pic, os.path.join(folder, "cover.jpg"))
            filename = f'{int(metadata["tracknumber"]):02d} - {metadata["title"]}.{metadata["format"]}'
        else:
            filename = f'{metadata["artist"]} - {metadata["title"]}.{metadata["format"]}'

        filename = self.__ntfs(filename)
        filename = os.path.join(folder, filename)

        resp = requests.get(metadata["url"], allow_redirects=True, verify=self.verify)
        resp.raise_for_status()

        with open(filename, "wb") as f:
            f.write(resp.content)

        with open(pic, "rb") as p:
            cover = p.read()

        if metadata["format"] == "flac":
            audio = FLAC(filename)
            audio["ARTIST"] = metadata["artist"]
            audio["TITLE"] = metadata["title"]
            audio["ALBUM"] = metadata["album"]
            audio["GENRE"] = metadata["genre"]
            audio["DATE"] = metadata["date"]
            audio["TRACKNUMBER"] = metadata["tracknumber"]
            audio["TRACKTOTAL"] = metadata["tracktotal"]
            audio["COPYRIGHT"] = metadata["copyright"]

            coverart = Picture()
            coverart.data = cover
            coverart.type = 3
            coverart.mime = "image/jpeg"
            audio.add_picture(coverart)
            audio.save()
        else:
            audio = EasyMP3(filename)
            audio["artist"] = metadata["artist"]
            audio["title"] = metadata["title"]
            audio["album"] = metadata["album"]
            audio["genre"] = metadata["genre"]
            audio["date"] = metadata["date"]
            audio["tracknumber"] = f'{metadata["tracknumber"]}/{metadata["tracktotal"]}'
            audio["copyright"] = metadata["copyright"]
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

    def download_tracks(self, track_ids):
        tracks = self.__get_tracks_info(track_ids)
        tracks = tracks["data"]["getTracks"]

        print("\nИнформация о треках: \n")
        pprint(tracks)

        for i, track in enumerate(tracks, 1):
            print(f'\nСкачивание трека № {i}/{len(tracks)}')
            self.__save_track(self.__extract_metadata(track), is_release=False, path="")

    def download_releases(self, release_ids):
        releases = self.__get_releases_info(release_ids)
        releases = releases["data"]["getReleases"]

        print("\nИнформация о релизах: \n")
        pprint(releases)

        for album in releases:
            album_path = f'{album["credits"]} - {album["title"]} ({str(album["date"])[:4]})'

            print(f'\nСкачивание треков из релиза {album["credits"]} «‎{album["title"]}»‎')

            for i, track in enumerate(album["tracks"], 1):
                print(f'\nСкачивание трека № {i}/{len(album["tracks"])}')
                self.__save_track(self.__extract_metadata(track), is_release=True, path=album_path)

    def download_playlists(self, playlist_ids):
        playlists = self.__get_playlists_info(playlist_ids)
        playlists = playlists["data"]["getPlaylists"]

        print("\nИнформация о плейлистах: \n")
        pprint(playlists)

        for playlist in playlists:
            playlist_title = f'{playlist["title"]}'

            print(f"\nСкачивание треков из плейлиста «‎{playlist_title}»‎")

            for i, track in enumerate(playlist["tracks"], 1):
                print(f'\nСкачивание трека № {i}/{len(playlist["tracks"])}')
                self.__save_track(self.__extract_metadata(track), is_release=False, path=playlist_title)

    def download_favorites(self):
        favorites = self.__get_favorites_info()
        favorites = favorites["data"]["collection"]["tracks"]

        print("\nИнформация о коллекции: \n")
        pprint(favorites)

        playlist_title = "Моя коллекция"

        print(f"\nСкачивание треков из плейлиста «‎{playlist_title}»‎")

        for i, track in enumerate(favorites, 1):
            print(f'\nСкачивание трека № {i}/{len(favorites)}')
            self.__save_track(self.__extract_metadata(track), is_release=False, path=playlist_title)


if __name__ == "__main__":

    release_ids = []
    track_ids = []
    playlist_ids = []
    is_favorites = False
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
            elif "favorites" in i:
                is_favorites = True

        z.read_token()
        if release_ids:
            z.download_releases(release_ids)
        if track_ids:
            z.download_tracks(track_ids)
        if playlist_ids:
            z.download_playlists(playlist_ids)
        if is_favorites:
            z.download_favorites()
        list(map(os.remove, glob.glob("temp*.jpg")))
