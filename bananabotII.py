print("bananabot starting")
import discord
from discord.ext import commands
from discord.ext.commands import Bot
from discord.voice_client import VoiceClient
import random
import asyncio
from mutagen.mp3 import MP3
import os
from wakeonlan import send_magic_packet

import pyqrcode
from pyqrcode import QRCode

from os import listdir
from os.path import isfile, join

# shit from audiojack.py
import imghdr
import os
import re
import socket
import subprocess
import sys
import urllib.request, urllib.error, urllib.parse
from urllib.parse import urlparse
import musicbrainzngs
import youtube_dl
from mutagen.id3 import ID3, TPE1, TIT2, TALB, APIC
from pathlib import Path

musicbrainzngs.set_useragent(socket.gethostname(), '1.1.1')
print("initalizing audiojack.py...")


class AudioJack(object):
    def __init__(self, bitrate=256, small_cover_art=False, quiet=False):
        self.opts = {
            'format': 'bestaudio',
            'outtmpl': '%(id)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': str(bitrate)
            }]
        }
        if quiet:
            self.opts['quiet'] = 1
            self.opts['no_warnings'] = 1
        self.ydl = youtube_dl.YoutubeDL(self.opts)
        self.small_cover_art = small_cover_art
        self._cover_art_cache = {}

    def get_results(self, url):
        info = self.ydl.extract_info(url, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        return self._get_metadata(self._parse(info))

    def select(self, entry, path=None):
        if 'url' not in entry:
            raise ValueError('Media URL must be specified.')
        info = self.ydl.extract_info(entry['url'])
        file = '%s.mp3' % info['id']
        tags = ID3()
        filename = entry['title'] if 'title' in entry and entry['title'] else 'download'
        filename = re.sub(r'\W*[^a-zA-Z\d\s]\W*', '_', filename)
        if 'title' in entry:
            tags.add(TIT2(encoding=3, text=entry['title']))
        if 'artist' in entry:
            tags.add(TPE1(encoding=3, text=entry['artist']))
        if 'album' in entry:
            tags.add(TALB(encoding=3, text=entry['album']))
        if 'img' in entry and entry['img'] != '':
            scheme = urlparse(entry['img']).scheme
            img_path = entry['img']
            if scheme == '':
                # Local path to absolute path
                img_path = os.path.abspath(img_path)
            if scheme[:4] != 'http':
                # Absolute path to file URI
                img_path = 'file:///%s' % img_path
            img_request = urllib.request.urlopen(img_path)
            img = img_request.read()
            img_request.close()
            valid_exts = ['jpeg', 'png', 'gif', 'bmp']
            ext = imghdr.what(None, img)
            if ext not in valid_exts:
                a = 0
            # raise ValueError('%s is an unsupported file extension.' % ext)
            else:
                mime = 'image/%s' % ext
                tags.add(APIC(encoding=3, mime=mime, type=3, data=img))
        tags.save(file, v2_version=3)
        if path:
            filename = '%s/%s' % (path, filename)
            if not os.path.exists(path):
                os.makedirs(path)
        target_file = '%s.mp3' % filename
        i = 1
        while os.path.exists(target_file):
            target_file = '%s (%d).mp3' % (filename, i)
            i += 1
        os.rename(file, target_file)
        return os.path.realpath(target_file)

    def cut_file(self, file, start_time=0, end_time=None):
        output = '%s_cut.mp3' % file
        # Export cover art temporarily
        ca = '%s_ca.jpg' % file
        subprocess.Popen(['ffmpeg', '-i', file, ca]).communicate()
        # Cut file
        if end_time:
            subprocess.Popen(
                ['ffmpeg', '-i', file, '-ss', str(start_time), '-to', str(end_time), '-c:a', 'copy', '-id3v2_version',
                 '3', output]).communicate()
        else:
            subprocess.Popen(
                ['ffmpeg', '-i', file, '-ss', str(start_time), '-c:a', 'copy', '-id3v2_version', '3',
                 output]).communicate()
        # Add cover art back
        subprocess.Popen(
            ['ffmpeg', '-y', '-i', output, '-i', ca, '-map', '0:0', '-map', '1:0', '-c', 'copy', '-id3v2_version', '3',
             file]).communicate()
        os.remove(output)
        os.remove(ca)
        return file

    def _parse(self, info):
        parsed = {
            'url': info['webpage_url']
        }

        banned_words = ['lyrics', 'hd', 'hq', 'free download', 'download', '1080p', 'official music video', 'm/v']
        feats = ['featuring', 'feat.', 'ft.', 'feat', 'ft']
        artist_delimiters = [',', 'x', '&', 'and']

        video_title = info['title']
        video_title = re.sub(r'\([^)]*|\)|\[[^]]*|\]', '', video_title).strip()  # Remove parentheses and brackets
        video_title = re.sub(self._gen_regex(banned_words), ' ', video_title).strip()  # Remove banned words
        parsed_title = re.split(r'\W*[\-:] \W*', video_title)  # 'Artist - Title' => ['Artist', 'Title']

        title = self._split(parsed_title[-1], feats)  # 'Song feat. Some Guy' => ['Song', 'Some Guy']
        parsed['title'] = title[0]
        secondary_artist_list = title[1:]

        if info['uploader'][-8:] == ' - Topic' and info['uploader'][:-8] != 'Various Artists':
            parsed['artists'] = [info['uploader'][:-8]]

        elif len(parsed_title) > 1:
            artists = self._split(parsed_title[-2], feats)  # 'A1 and A2 feat. B1' => ['A1 and A2', 'B1']
            parsed['artists'] = self._split(artists[0], artist_delimiters)  # 'A1 and A2' => ['A1', 'A2']
            secondary_artist_list.extend(artists[1:])

        if len(secondary_artist_list) > 0:
            # Each string in the secondary_artist_list is split according to the artist delimiters.
            # Each of the newly created lists are then flattened into a single list (see self._flatten).
            parsed['secondary_artists'] = self._multi_split(secondary_artist_list, artist_delimiters)
        return parsed

    def _get_metadata(self, parsed):
        results = []
        temp = []
        artists = parsed['artists'] if 'artists' in parsed else None
        artist = artists[0] if artists else ''
        artistname = artists[1] if artists and len(artists) > 1 else ''
        mb_results = musicbrainzngs.search_recordings(query=parsed['title'], artist=artist, artistname=artistname,
                                                      limit=20)
        for recording in mb_results['recording-list']:
            if 'release-list' in recording:
                title = recording['title']
                if ('artists' not in parsed or re.sub(r'\W', '', title.lower()) == re.sub(r'\W', '', parsed[
                    'title'].lower())) and self._valid_title(title):
                    artists = [a['artist']['name'] for a in recording['artist-credit'] if
                               isinstance(a, dict) and 'artist' in a]
                    artist = artists[0]  # Only use the first artist (may change in the future)
                    for release in recording['release-list']:
                        album = release['title']
                        album_id = release['id']
                        entry = {
                            'url': parsed['url'],
                            'title': title,
                            'artist': artist,
                            'album': album
                        }
                        if entry not in temp and self._valid(release):
                            temp.append(entry.copy())
                            entry['id'] = album_id
                            entry['img'] = self._cover_art_cache[
                                album_id] if album_id in self._cover_art_cache else self._get_cover_art(album_id)
                            results.append(entry)
        return results

    def _flatten(self, lst):
        return [item for sublist in lst for item in sublist]

    def _gen_regex(self, word_list):
        return r'(?:^|\W)*?(?i)(?:%s)\W*' % '|'.join(word_list)

    def _split(self, string, delimiters):
        return re.split(self._gen_regex(delimiters), string)

    def _multi_split(self, lst, delimiters):
        return self._flatten([self._split(item, delimiters) for item in lst])

    def _valid(self, release):
        banned_words = ['instrumental', 'best of', 'diss', 'remix', 'what i call', 'ministry of sound']
        approved_secondary_types = ['soundtrack', 'remix', 'mixtape/street']
        for word in banned_words:
            if word in release['title'].lower():
                return False
        if 'secondary-type-list' in release['release-group']:
            st = release['release-group']['secondary-type-list'][0].lower()
            if st not in approved_secondary_types:
                return False
        if not self._get_cover_art(release['id']):
            return False
        return True

    def _valid_title(self, title):
        banned_words = ['remix', 'instrumental', 'a cappella', 'remake']
        for word in banned_words:
            if word in title.lower():
                return False
        return True

    def _get_cover_art(self, album_id):
        try:
            if album_id in self._cover_art_cache:
                return self._cover_art_cache[album_id]
            else:
                if self.small_cover_art:
                    self._cover_art_cache[album_id] = \
                        musicbrainzngs.get_image_list(album_id)['images'][0]['thumbnails'][
                            'small']
                else:
                    self._cover_art_cache[album_id] = musicbrainzngs.get_image_list(album_id)['images'][0]['image']
                return self._cover_art_cache[album_id]
        except musicbrainzngs.musicbrainz.ResponseError:
            return None


aj = AudioJack(quiet=True)

# audiojack stuff
print("initalizing discord.py...")
quack = open('badwords.txt')
hold = quack.read()
quack.close()
nonoword = hold.split('\n')

# discord stuff
def refreshSL():
    global soundlist
    soundlist = [f for f in listdir("./") if isfile(join("./", f))]
    for x in range(0,len(soundlist)):
        y = soundlist[x]
        y = y[0:len(y) - 4]
        soundlist[x] = y
refreshSL()


intentz = discord.Intents.default()
intentz.members = True
intentz.message_content = True
client = commands.Bot(command_prefix='pp', intents=intentz)
hold = ""
with open('help.txt', 'r') as fyylee:
    helptext = fyylee.read()


@client.event
async def on_ready():
    print('bananabot ready')


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.author.bot:
        return
    if(False):
        if ((str(message.author.id)=='185562474546724864' or '141688393947021312' or '141678385024729088') and str(message.channel.id=='409190314725736448')):	#if grayson sends a message in #sbot?
            print("harrassing grayson with bananabot per mendelson's request")
            await message.channel.send(file=discord.File("graywojak.png"))
    if message.content.startswith('pp '):
        cmd = message.content[3:]
        print("FULL MESSAGE TEXT: " + message.content)
        print("FROM: " + message.author.name + " @: " + str(message.created_at))
        if ((str(message.author.id)) == '141688393947021312'):
            await stumpf(message)
        elif ((str(message.author.id)) == '538954067272007731') & (cmd == "1190099622"):
            await startrob()
        if (cmd == 'ass')or(cmd == 'test'):
            await message.channel.send("bananabot OK")
        elif (cmd == 'help'):
            await message.channel.send(helptext)
        elif ("QR" in cmd):
            await sqr(message)
        elif ("emojify" in cmd):
            await emojify(message)
        elif ("1337" in cmd):
            await leet(message)
        elif ("annoy" in cmd):
            await annoy(message)
        elif (cmd == "bully"):
            await bully(message)
        elif ("list sounds" in cmd):
            await sounds(message)
        elif ("play" in cmd):
            await psound(message)
        elif ("stop" in cmd):
            await ssound(message)
        elif (cmd == "flip"):
            await coinflip(message)
        elif ("roll" in cmd):
            await dice(message)
    print("\n")







async def sqr(message):
    msg = message.content[3:]
    msg = msg[3:]
    print("creating QR code: " + msg)
    qr = pyqrcode.create(msg)
    qr.png("qr.png", scale=4)
    await message.channel.send(file=discord.File("qr.png"))
    os.remove("qr.png")


async def emojify(message):
    msg = message.content[3:]
    msg = msg.lower()
    print("emojify :" + msg + " ; " + str(message.author))
    if ("emojifyc" in msg):
        msg = msg[9:]
        hold = 1
    else:
        msg = msg[8:]
        hold = 0
    out = " "
    for c in msg:
        if ((hold == 1) and (not (c == ' '))):
            out = out + '\\'
        else:
            out = out + ' '
        if (c == 'a'):
            out = out + "🇦 "
        elif (c == 'b'):
            out = out + "🇧 "
        elif (c == 'c'):
            out = out + "🇨 "
        elif (c == 'd'):
            out = out + "🇩 "
        elif (c == 'e'):
            out = out + "🇪 "
        elif (c == 'f'):
            out = out + "🇫 "
        elif (c == 'g'):
            out = out + "🇬 "
        elif (c == 'h'):
            out = out + "🇭 "
        elif (c == 'i'):
            out = out + "🇮 "
        elif (c == 'j'):
            out = out + "🇯 "
        elif (c == 'k'):
            out = out + "🇰 "
        elif (c == 'l'):
            out = out + "🇱 "
        elif (c == 'm'):
            out = out + "🇲 "
        elif (c == 'n'):
            out = out + "🇳 "
        elif (c == 'o'):
            out = out + "🇴 "
        elif (c == 'p'):
            out = out + "🇵 "
        elif (c == 'q'):
            out = out + "🇶 "
        elif (c == 'r'):
            out = out + "🇷 "
        elif (c == 's'):
            out = out + "🇸 "
        elif (c == 't'):
            out = out + "🇹 "
        elif (c == 'u'):
            out = out + "🇺 "
        elif (c == 'v'):
            out = out + "🇻 "
        elif (c == 'w'):
            out = out + "🇼 "
        elif (c == 'x'):
            out = out + "🇽 "
        elif (c == 'y'):
            out = out + "🇾 "
        elif (c == 'z'):
            out = out + "🇿 "
        elif (c == ' '):
            out = out + "    "
        elif (c == '1'):
            out = out + "1️⃣ "
        elif (c == '2'):
            out = out + "2️⃣ "
        elif (c == '3'):
            out = out + "3️⃣ "
        elif (c == '4'):
            out = out + "4️⃣ "
        elif (c == '5'):
            out = out + "5️⃣ "
        elif (c == '6'):
            out = out + "6️⃣ "
        elif (c == '7'):
            out = out + "7️⃣ "
        elif (c == '8'):
            out = out + "8️⃣ "
        elif (c == '9'):
            out = out + "9️⃣ "
        elif (c == '0'):
            out = out + "0️⃣ "
        elif (c == '-'):
            out = out + "➖ "
    await message.channel.send(out)


async def coinflip(message):
    a = random.random()
    if(a>0.5):
        await message.channel.send("heads")
    else:
        await message.channel.send("tails")


async def dice(message):
    out=" "
    msg = message.content[3:]
    msg = msg[5:]
    idx = msg.find(' ')
    dii = int(msg[:idx])
    die = int(msg[idx+1:])
    tot = 0
    for d in (range(0,dii)):
        if(d>0):
            out = out + ','
        num = random.randint(1, die)
        tot = tot + num
        out = out+ str(num)
    average = tot/dii
    out = out + ". Average: " + str(average) + ". Total: " + str(tot)
    await message.channel.send(out)


async def leet(message):
    msg = message.content[3:]
    msg = msg.lower()
    print("leetify: " + msg + " ; " + str(message.author))
    msg = msg[5:]
    out = " "
    for c in msg:
        if (c == 'a'):
            out = out + "4"
        elif (c == 'e'):
            out = out + "3"
        elif (c == 'o'):
            out = out + "0"
        elif (c == 't'):
            out = out + "7"
        elif (c == 'i'):
            out = out + "1"
        elif (c == 's'):
            out = out + "5"
        elif (c == 'i'):
            out = out + "1"
        else:
            out = out + c
    await message.channel.send(out)


async def annoy(message):
    msg = message.content[3:]
    msg = msg[6:]
    print("annoy: " + msg + " ; " + str(message.author) )
    out = " "
    for c in msg:
        out = out + "|| "
        out = out + c
        out = out + " ||"
    await message.channel.send(out)


async def bully(message):#bully command
    print("bully")
    x = 0
    out = "*ahem*: you are a"
    hold = 7
    while x <= hold:
        y = random.randrange(1, 1382)
        out += " "
        out += nonoword[y]
        x += 1
    await message.channel.send(out)


async def sounds(message):#lists sounds
    print("list sounds")
    refreshSL()
    await message.channel.send(soundlist)


async def psound(message):
    msg = message.content[3:]
    refreshSL()
    clist = client.voice_clients
    for x in clist:
        if (x.guild == message.guild):
            await x.disconnect()
    msg = msg[5:]
    voice_channel = message.author.voice
    if (voice_channel != None):
        hold = ""
        if (msg in soundlist):
            hold = msg
            hold += ".mp3"
        else:
            await message.channel.send("that isn't a file in the list dummy")
            return
        vclient = await message.author.voice.channel.connect()
        source = discord.FFmpegPCMAudio(hold)
        audio = MP3(hold)
        alen = .02 + audio.info.length
        vclient.play(source)
        print("playing audio file: " + hold + " IN: " + message.author.voice.channel.name)
        await asyncio.sleep(alen)
        await vclient.disconnect()
        discord.FFmpegPCMAudio.cleanup

    else:
        await message.channel.send('you are not in a voice channel')


async def ssound(message):
    clist = client.voice_clients
    for x in clist:
        if (x.guild == message.guild):
            await x.disconnect()


async def stumpf(message):
    msg = message.content[3:]
    print("you dummy")
    if ("flood" in msg):
        out = ""
        out += "'"
        for x in range(500):
            out += "\n"
        out += "'"
        await message.channel.send(out)
    elif ("scream" in msg):
        out = ""
        for x in range(1750):
            out += "A"
        out += "H"
        await message.channel.send(out)
    elif ("audiojack" in msg):
        url = msg[10:]
        await message.channel.send("K...")
        results = aj.get_results(url)
        # print("link to download: "+ str(url))
        if len(results) > 0:
            download = aj.select(results[0])
        else:
            download = aj.select({'url': url})
        print('Downloaded %s' % download)
        await message.channel.send('Downloaded %s' % download)
        dli = download.index('bananabo') + len('bananabo') + 1
        sp1 = download[:dli]
        sp2 = download[dli:]
        Path(download).rename(sp1 + "music\\" + sp2)
        print(sp1 + "music\\" + sp2)
    elif ("youtube" in msg):
        url = msg[8:]
        await message.channel.send("workin' on it...")

        video_info = youtube_dl.YoutubeDL().extract_info(url=url, download=False)
        alen = video_info['duration']
        titl = "ytplayback"
        filename = f"{titl}.mp3"
        print(filename)
        options = {'format': 'bestaudio/best', 'keepvideo': False, 'outtmpl': filename, }
        with youtube_dl.YoutubeDL(options) as ydl:
            ydl.download([video_info['webpage_url']])
        print("Download complete")

        await message.channel.send("starting playback...")
        print(filename)

        clist = client.voice_clients#gets list of all voice channels in servers bbot is in
        for x in clist:#disconnects from any channels in the server the message is from
            if (x.guild == message.guild):
                await x.disconnect()
            voice_channel = message.author.voice
        if (voice_channel != None):
            vclient = await message.author.voice.channel.connect()
            # audio = MP3(filename)
            source = discord.FFmpegPCMAudio(filename)
            alen = .02 + alen  # audio.info.length
            vclient.play(source)
            print("playing audio file: " + filename + " IN: " + message.author.voice.channel.name)
            await asyncio.sleep(alen)
            await vclient.disconnect()
            discord.FFmpegPCMAudio.cleanup
        else:
                await message.channel.send('get you ass in a voice chat')
        await asyncio.sleep(5)
        os.remove(filename)
    elif (msg == "die"):
        await message.channel.send("k")
        exit()
    elif (msg == "1190099622"):	
        print("waking rob_bole")
        await send_magic_packet("B4:2E:99:EC:50:30")



with open('client.token', 'r') as fyylee:
    clientid = fyylee.read()
client.run(clientid)
