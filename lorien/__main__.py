import os
import random
import urllib.parse
import re
import json
from time import sleep

import discord
from discord.ext import commands
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup as bs

from youtube import YTDLSource
from youtubesearchpython import VideosSearch, PlaylistsSearch, Playlist

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
if "," in GUILD:
    GUILD = GUILD.split(",")
else:
    GUILD = [GUILD]

GUILD = [int(g) for g in GUILD]

song_queue = []
voice = None

class LorienContext(commands.Context):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store = {}

    async def react(self, emoji):
        await self.message.add_reaction(emoji)

class LorienBot(commands.Bot):
    async def get_context(self, message, *, cls=LorienContext):
        return await super().get_context(message, cls=cls)

bot = LorienBot(command_prefix='~')

@bot.check
async def globally_block_dms(ctx):
    return ctx.guild.id in GUILD

@bot.event
async def on_ready():
    for guild in bot.guilds:
        print(
            f'{bot.user} is connected to the following guilds:\n'
            f'{guild.name}(id: {guild.id})'
        )

def after_play():
    if len(song_queue) > 0:
        voice.play(song_queue[0], after=lambda e: after_play())
        del song_queue[0]

def search_yt(search):
    videosSearch = VideosSearch(search, limit = 1)
    result = videosSearch.result()['result'][0]
    print(result)
    return f'https://www.youtube.com/watch?v={result["id"]}'

def search_playlist(search):
    playlist_result = PlaylistsSearch(search, limit=1).result()['result'][0]['link']
    playlist = Playlist(playlist_result)

    videos = playlist.videos

    while playlist.hasMoreVideos:
        playlist.getNextVideos()
        videos += playlist.videos

    return list(sorted(list(set([v['title'].split('|')[0].strip() for v in videos]))))

def search_wiki(search):
    search = urllib.parse.quote(search)
    text = requests.get(f"https://eberron.fandom.com/wiki/Special:Search?query={search}&scope=internal&navigationSearch=true").text
    soup = bs(text, "html.parser")
    selector = '.unified-search__result__title'
    href = soup.select(selector)[0].get('href')
    return href

@bot.command(name='generate')
async def generate(ctx, *prefix):
    results = []
    while len(results) < 3:
        prefix = ' '.join(prefix).strip()
        novelai = {
            "input": f"This D&D character is {prefix}. I have come up with the character name \"",
            "model": "euterpe-v2",
            "parameters": {
                "use_string": True,
                "temperature": 0.5,
                "min_length": 5,
                "max_length": 20
            }
        }
        result = requests.post("https://api.novelai.net/ai/generate", data=json.dumps(novelai), headers={"Content-Type":"application/json","accept": "application/json"})
        print("output", json.loads(result.text)["output"])
        result = json.loads(result.text)["output"].split("\"")[0]
        result = re.sub("[^\w\'\s]", "", result)
        if result not in results:
            results.append(result)
            sleep(1)
    await ctx.send('\n'.join(results))

@bot.command(name='lastsession')
async def lastsession(ctx):
    text = requests.get('https://rentry.org/eberronicon/raw').text
    text = re.sub("\s+", " ", text)
    text = urllib.parse.quote(text)
    try:
        with open("lastsession.txt", "r") as lastsession_txt:
            prev_txt = lastsession_txt.read()
    except FileNotFoundError:
        prev_txt = ''
    if prev_txt != text:
        req_url = f"https://api.novelai.net/ai/generate-voice?text={text}&seed=42&voice=106&opus=false"
        content = requests.get(req_url).content
        with open("lastsession.mp3", "wb") as lastsession:
            lastsession.write(content)
        with open("lastsession.txt", "w") as lastsession_txt:
            lastsession_txt.write(text)
    await stop(ctx)
    await _play(ctx, "lastsession.mp3")

@bot.command(name='wiki')
async def wiki(ctx, *search):
    search = ' '.join(search).strip()
    href = search_wiki(search)
    await ctx.send(href)
    await ctx.react('📙')

@bot.command(name='ambience')
async def ambience(ctx, *search):
    global voice

    if 'suggest' in search[0]:
        PlaylistsSearch("RPG / D&D Ambienten Michael Ghelfi Studios", limit=1)
        msg_str = '**here are some random suggestions for the ambience command:**\n'
        videos = search_playlist("RPG / D&D Ambienten Michael Ghelfi Studios")
        videos = list(set(random.choices(videos, k=20)))
        msg_str += ' | '.join(videos)
        await ctx.send(msg_str[:2000])
        return

    if 'youtube.com' not in search[0]:
        url = ' '.join(search) + " dnd ambience"
    else:
        url = search[0]

    await stop(ctx)
    await _play(ctx, url, loop=True)

@bot.command(name='queue')
async def queue(ctx):
    await ctx.send("\n".join([f"{i} - {p.title}" for i, p in enumerate(song_queue)]))

async def _play(ctx, url, position=-1, loop=False):
    global voice

    if 'youtube.com' not in url and ".mp3" not in url:
        url = search_yt(url)

    if voice and voice.is_playing():
        if '.mp3' not in url:
            player = await YTDLSource.from_url(url, loop=loop)
        else:
            player = await YTDLSource.from_file(url)
        if position == -1:
            song_queue.append(player)
        else:
            song_queue.insert(position, player)
        await ctx.send(f"🔜 {player.title}")
        await ctx.react("🔜")
    else:
        author = ctx.message.author
        channel = author.voice.channel
        if not voice or not voice.is_connected():
            voice = await channel.connect()
        async with ctx.typing():
            if '.mp3' not in url:
                player = await YTDLSource.from_url(url, loop=False)
            else:
                player = await YTDLSource.from_file(url)
            voice.play(player, after=lambda e: after_play())
        await ctx.send(f'🎵 {player.title}')
        await ctx.react("🎵")

@bot.command(name='play')
async def play(ctx, *url):
    await _play(ctx, ' '.join(url).strip())

@bot.command(name='resume')
async def resume(ctx):
    if voice and voice.is_paused():
        voice.resume()
        await ctx.react("▶️")

@bot.command(name='pause')
async def pause(ctx):
    if voice and not voice.is_paused():
        voice.pause()
        await ctx.react("⏸️")

@bot.command(name='stop')
async def stop(ctx):
    global song_queue
    song_queue = []
    if voice and voice.is_playing():
        voice.stop()
        await ctx.react("🛑")

@bot.command(name='skip')
async def skip(ctx):
    if voice and voice.is_playing():
        voice.stop()
        await ctx.react("⏭️")

@bot.command(name='playnext')
async def playnext(ctx, url):
    await _play(ctx, url, 0)

@bot.command(name='loop')
async def loop(ctx, url):
    await _play(ctx, url, 0, True)
    if voice and voice.is_playing():
        voice.stop()
    await ctx.react("🔄")

bot.run(TOKEN)