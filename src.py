import asyncio
import concurrent.futures
import datetime
import functools
import importlib
import io
import json
import os
import random
import re
import subprocess
import sys
import time
import traceback
import unicodedata
import zipfile
from urllib import parse

import discord
import yt_dlp
import aiofiles
import aiosqlite
from discord.ext import commands
from dns import resolver

import mc_ping

import src

# set stderr to /dev/null

sys.stderr = open(os.devnull, "w")
import psutil

# after importing, set stderr to original
sys.stderr = sys.__stderr__

from memo import deepl_token, gas_api_url, developer, srv_dynmap

import memo, main

allow_admin_command: dict = {}

yt_dlp.utils.bug_reports_message = lambda: ''


ytdl_format_options: dict = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options: dict = {
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

if not hasattr(src, 'ready'):
    ready = False

    errors = []

    m_count = {}

mc_regex = re.compile('§[0-9a-gk-or]')
ansi_regex = re.compile('\x1b\\[*[?0-9]*;*[0-9]*;*[0-9]*[a-zA-Z]')

async def save_log(cog, message):
        channel = message.channel.id
        if message.guild is None:
            guild = -1
        else:
            guild = message.guild.id

        reference_id = message.reference.message_id if message.reference is not None else None

        data = [
          message.id,
          guild,
          message.channel.id,
          message.content,
          message.author.id,
          str(message.author),
          int(not message.webhook_id is None),
          json.dumps([
            embed.to_dict() for embed in message.embeds
          ]),
          json.dumps([
            attachment.filename for attachment in message.attachments
          ]),
          reference_id
        ]

        await cog.log_db.execute('''
            INSERT OR REPLACE INTO messages
            values (
                ?,?,?,?,?,?,?,?,?,?
            )
        ''', data)
        await cog.log_db.commit()
        #file.close()
        """まだその時ではない
        if not os.path.exists(f'logs/{guild}/{channel}/'):
            os.system(f'mkdir -p logs/{guild}/{channel}/')
        file = open(f'logs/{guild}/{channel}/log', mode='a')
        if len(message.attachments) != 0:
            os.mkdir(f'logs/{guild}/{channel}/{message.id}/')
            for attachment in message.attachments:
                fp = f'logs/{guild}/{channel}/{message.id}/{attachment.filename}'
                for _ in range(5):
                    try:
                        await attachment.save(fp)
                    except:
                        continue
                    else:
                        break
        """

async def run_sql(sql="", data="", path='messagelog.db'):
    # ほんと最悪だよ

    executor = (
        'import sqlite3\n'
        'import json\n'
        '\n'
       f'tmp_log_conn = sqlite3.connect({repr(path)})\n'
        'tmp_log_cur = tmp_log_conn.cursor()\n'
       f'result = tmp_log_cur.execute({repr(sql)}, {data})\n'
        'result_json = json.dumps(list(result))\n'
        'print(result_json, end=str())\n'
        'tmp_log_conn.close()\n'
    ).encode()

    p = await asyncio.create_subprocess_exec(sys.executable,
                                             '-',
                                             stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE)

    stdout, stderr = await p.communicate(input=executor)
    result = json.loads(stdout.decode())

    return result

def admin_only(author, com):
    if author.id in developer:
        return True
    else:
        if com in allow_admin_command.get(author.id, []):
            return 1
        if com == 'mc':
            return 'クソ重なんでご遠慮いただきたいです…'
        elif com == 'logsearch':
            if type(author) is discord.User:
                return 1
            elif author.guild_permissions.manage_messages:
                return 2
        else:
            messages = (
                '黙れカス',
                '何様ですか',
                '俺は…ご主人様を裏切れねぇ……',
                '```\nデータベースと照合した結果、あなたにこのコマンドを実行する権利がありませんでした。```',
                'Error: {}: Permission denied'.format(com),
                '帰れ'
            )
            return random.choice(messages)

def a2e(string):
    emojis = []
    for char in string:
        integer = ord(char)

        if 0x30 <= integer <= 0x39:
            emojis.append((char.encode()+b'\xef\xb8\x8f\xe2\x83\xa3').decode())
            continue
        elif 0x41 <= integer <= 0x5a:
            integer += 0x20

        if 0x61 <= integer <= 0x7a:
            emojis.append((b'\xf0\x9f\x87'+(0x45+integer).to_bytes(1)).decode())

    return emojis

def pycalc_runner(exp):
    return eval(exp, {'__builtins__': None})

async def random_wait(channel, delay=1):
    async with channel.typing():
        await asyncio.sleep(random.random()*delay+1)

async def get_reference(arg):
    if type(arg) == discord.Message:
        message = arg
    else:
        message = arg.message
    reference = message.reference
    if message.reference is None:
        return None
    if reference.cached_message is None:
        channel = message.channel
        try:
            msg = await channel.fetch_message(reference.message_id)
        except:
            return None
    else:
        msg = reference.cached_message

    return msg

def make_message(data, state, channel):
    default_data = {
        'id': 0,
        'attachments': [],
        'embeds': [],
        'edited_timestamp': 0,
        'type': discord.message.MessageType.default,
        'pinned': False,
        'mention_everyone': False,
        'tts': False,
        'content': ''
    }

    default_data.update(data)

    return discord.Message(data=default_data, state=state, channel=channel)

class MainSystem(commands.Cog):
    def __init__(self, bot, *, old=None, sub_account=None, loop=None):
        self.bot = bot
        self.reacting = False
        if old is None:
            self.tasks = {}
            self.sub_account = sub_account
            self.sub_account_tasks = {}
            self.bump_tasks = {}
            self.loop = bot.loop if loop is None else loop
        if not old is None:
            self.tasks = old.tasks
            self.sub_account = old.sub_account
            self.sub_account_tasks = old.sub_account_tasks
            self.bump_tasks = old.bump_tasks
            self.loop = old.loop

    @property
    def session(self):
        return self.bot.http._HTTPClient__session

    @commands.Cog.listener()
    async def on_ready(self, event='on_ready'):
        global ready
        ready = True

        print(f'({event}) {self.bot.user}としてログインしました')

    async def cog_load(self):
            self.log_db = await aiosqlite.connect('messagelog.db')
            await self.log_db.execute('''
                CREATE TABLE IF NOT EXISTS
                messages(
                    id INTEGER PRIMARY KEY,
                    guild INTEGER,
                    channel INTEGER,
                    content STRING,
                    author INTEGER,
                    author_name STRING,
                    webhook INTEGER,
                    embeds STRING,
                    attachments STRING,
                    reference_id INTEGER
                )'''
            )
            await self.log_db.execute('''
                CREATE TABLE IF NOT EXISTS
                users(
                    id INTEGER PRIMARY KEY,
                    name STRING
                )
            ''')
            await self.log_db.execute('''
                CREATE TABLE IF NOT EXISTS
                guilds(
                    id INTEGER PRIMARY KEY,
                    name STRING
                )
            ''')


    @commands.command()
    async def ping(self, ctx, host=None):
        """
        Botの応答時間を計測します
        """
        if host is None:
            rpl = await ctx.send('Pong')

            msgtime = ctx.message.created_at.timestamp()
            rpltime = rpl.created_at.timestamp()

            ping_sec = rpltime - msgtime
            ping_ms = ping_sec * 1000
            ping_ms_str = '%.2f' % ping_ms
            latency_ms = self.bot.latency * 1000
            latency_ms_str = '%.2f' % latency_ms

            # ↓ Bad System Call
            '''
            p = await asyncio.create_subprocess_exec('ping',
                                                     '-c',
                                                     '4',
                                                     'www.discord.com',
                                                     stdout=subprocess.PIPE,
                                                     stderr=subprocess.PIPE)

            stdout, stderr = await p.communicate()
            '''

            p = subprocess.Popen((
                                    'ping',
                                    '-c',
                                    '4',
                                    'www.discord.com',
                                ),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)

            stdout, stderr = await asyncio.to_thread(p.communicate)
            unix_ping_line = stdout.decode().splitlines()[-1]

            unix_ping_str = unix_ping_line.split('/')[-3]

            await rpl.edit(content='Pong!\n'
                                  f'Message: {ping_ms_str}ms\n'
                                  f'Latency: {latency_ms_str}ms\n'
                                  f'Ping to `www.discord.com`: {unix_ping_str}ms'
                           )

        else:
            message = await ctx.send(f'`{host}`へPingを実行します')
            p = await asyncio.create_subprocess_exec('ping',
                                                     '-c',
                                                     '4',
                                                     host,
                                                     stdout=subprocess.PIPE,
                                                     stderr=subprocess.PIPE)

            stdout, stderr = await p.communicate()
            unix_ping = stdout.decode() + stderr.decode()

            await message.edit(content='`'*3+'\n'+unix_ping+'`'*3)

    @commands.command()
    async def tr(self, ctx, lang, *, text=None):
        """
        Google翻訳でメッセージを翻訳します
        引数に文章を入れるか、返信で翻訳したいメッセージを指定してください
        Google翻訳APIを無料で作る方法 - Qiita https://qiita.com/satto_sann/items/be4177360a0bc3691fdf
        こちらの記事をありがたく使わせていただきました
        """
        if ctx.message.reference is None:
            if text is None:
                await ctx.send('翻訳するテキストを指定してください')
                return
        else:
            message = await get_reference(ctx)
            text = message.content

        text = parse.quote(text)

        response = await self.session.get(f'https://script.google.com/macros/s/{gas_api_url}/exec?text={text}&source&target={lang}')
        if response.content_type != 'application/json':
            await ctx.send('❎翻訳できませんでした\n'
                           '言語コードが正しいか確認してください\n'
                           '言語コードについて↓\n'
                           'https://cloud.google.com/translate/docs/languages?hl=ja')
            return

        result = await response.json()

        if result['code'] == 200 and len(result['text']) != 0:
            await ctx.send('☑翻訳が完了しました\n>>> ```\n'+result['text']+'```')
        else:
            await ctx.send('❎翻訳できませんでした')

    @commands.command()
    async def chtr(self, ctx, channel: discord.TextChannel=None, base_lang: str='JA', target_lang: str='EN'):
        """
        指定したチャンネルと翻訳用スレッドとの間でメッセージを翻訳します
        デフォルトの言語設定はJA(日本語)↔EN(英語)です
        ※DeepLの無料版アカウントだから文字数制限があります 使いすぎないでね！
        """

        base_lang = base_lang.upper()
        target_lang = target_lang.upper()

        if channel is None:
            base_channel = ctx.channel
        else:
            base_channel = channel

        start_message = None
        try:
            thread_name = f'Translation - {target_lang}'

            threads = ctx.channel.threads
            thread = ([th for th in threads if th.name == thread_name]+[None])[0]

            if thread is None:
                start_message = await ctx.channel.send('翻訳用スレッドを作成…')
                thread = await ctx.channel.create_thread(name=thread_name, message=start_message)

            target_channel = thread

        except Exception as e:
            if not start_message is None:
                await start_message.edit(content='翻訳用スレッドを作成…失敗 ({})'.format(e))
            start_message = None

            target_channel = ctx.author.dm_channel

        if base_channel == target_channel:
            await ctx.send('チャンネルを指定してください')
            return

        if type(target_channel) == discord.DMChannel:
            rpl = await ctx.send('DMへGO')
            try:
                await ctx.author.send('チャット荒らしちゃよくないので')
            except:
                await asyncio.sleep(3)
                await ctx.edit(content='DMへGO\n......って言おうとしたけどDM送れんかった')
                return
            finally:
                await asyncio.sleep(5)
                await rpl.delete()

        notification = f'{base_channel.mention} ({base_lang})↔{target_channel.mention}({target_lang}) の翻訳接続が完了しました\n`%chtr stop`で終了できます'

        if type(target_channel) == discord.threads.Thread:
            if not start_message is None:
                await start_message.edit(content=notification)
            else:
                await base_channel.send(notification)
                await target_channel.send(notification)

        elif type(target_channel) == discord.DMChannel:
            await target_channel.send(notification)

        while True:
            message = await self.bot.wait_for('message',
                                         check=lambda message: message.author != self.bot.user and (message.channel in (base_channel, target_channel)))

            if message.content == '%chtr stop':
                await message.channel.send('翻訳接続を終了します')
                break
            elif message.content.startswith('%chtr ch '):
                check = admin_only(message.author, 'chtr')
                if check is True:
                    await message.channel.send('マジで言ってるか？何言われても知らんぞ')
                    target_channel = self.bot.get_channel(int(message.content.split()[-1]))
                else:
                    await random_wait(message.channel, 2)
                    await message.channel.send('チャンネルトピックの設定の方でよろ　そっちの方が高機能だから')
                    return

            else:
                if message.channel == base_channel:
                    lang = target_lang
                    channel = target_channel
                elif message.channel == target_channel:
                    lang = base_lang
                    channel = base_channel

                text = parse.quote(message.content)

                async with self.session.get(f"https://api-free.deepl.com/v2/translate?auth_key={deepl_token}&text={text}&target_lang={lang}") as r:
                    result = await r.json()

                    await channel.send(f'{message.author} » '+result["translations"][0]["text"])
                    for attachment in message.attachments:
                         await channel.send(attachment.url)

    @commands.command()
    async def usertr(self, ctx, user, lang='ja', srv: bool=False):
        """
        指定したユーザーのメッセージを翻訳します
        ※いじめや荒らしに使わないように
        """
        if not srv:
            user = await commands.MemberConverter().convert(ctx, user)
            await ctx.send(f'このチャンネルで{user}のメッセージを翻訳します')
        else:
            await ctx.send(f'このチャンネルで{user}(Minecraft)のメッセージを翻訳します')

        content = None
        while True:
            message = await self.bot.wait_for('message',
                                                  check=lambda message: 
                                                  message.channel == ctx.channel)

            if not srv and message.author == user:
                text = parse.quote(message.content)
            else:
                splitted = message.content.split(' » ')
                author = splitted[0]
                if author != user:
                    continue

                content = ' » '.join(splitted[1:])
                text = parse.quote(content)

            if '%usertr stop' in (message.content, content):
                await ctx.send('ユーザー翻訳を終了します')
                return

            async with self.session.get(f"https://api-free.deepl.com/v2/translate?auth_key={deepl_token}&text={text}&target_lang={lang}") as r:
                result = await r.json()

                await ctx.send(f'{user} >> '+result["translations"][0]["text"])

    @commands.command()
    async def timer(self, ctx, *value):
        """
        タイマーをセットします
        GNU coreutilsのsleepコマンドを実行しているので、オプションはそれに従います
        """

        # ↓ Bad System Call
        '''
        p = await asyncio.create_subprocess_exec(
            'sleep',
            *value,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        '''
        p = subprocess.Popen((
            'sleep',
            *value),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        message = await ctx.send('タイマーをセットしました')
        'stdout, stderr = await p.communicate()'
        stdout, stderr = await asyncio.to_thread(p.communicate)
        output = (stdout+stderr).decode()
        if output:
            await message.edit(content='`'*3+'\n'+output+'`'*3)
            return
        else:
            await ctx.message.reply('タイマーが終了しました')

    @commands.command()
    async def emsay(self, ctx, *, string):
        """
        アルファベットをそれに対応した絵文字に変換します
        日本語は対応しません(いつかするかも)
        """
        emojis = a2e(string)
        if len(emojis) == 0:
            await ctx.send('何も変換できませんでした')
            return
        else:
            await ctx.reply(' '.join(emojis))

    @commands.command()
    async def emreact(self, ctx, *, string):
        """
        アルファベットをそれに対応したリアクションにします
        返信でメッセージを指定してください
        日本語には対応しません(いつかするかも)
        """
        emojis = a2e(string)
        if len(emojis) == 0:
            await ctx.send('何も変換できませんでした')
        elif len(emojis) > 20:
            await ctx.send('少々多すぎます。20文字以内にしてください')
        elif len(emojis) > len(set(emojis)):
            await ctx.send('文字が重複しています。冷静に考えて無理です')
        elif ctx.message.reference is None:
            await ctx.send('リアクションを追加するメッセージを返信で指定してください')

        else:
            message = await get_reference(ctx)
            for emoji in emojis:
                await message.add_reaction(emoji)

    @commands.command()
    async def mcping(self, ctx, host, port: int=25565):
        """
        Java版マイクラ鯖の情報を表示します
        統合版は %mcbeping を使ってください
        """
        test = host.split(':')
        if len(test) != 1:
            host = test[0]
            port = int(test[1])

        try:
            srv_records = resolver.query('_minecraft._tcp.'+host, 'SRV')
            srv = srv_records[0]
            address = srv.target.to_text(omit_final_dot=True)
            port = srv.port
            from_srv = True
        except:
            address = host
            from_srv = False

        try:
            result = await asyncio.wait_for(mc_ping.async_ping(address, port), timeout=15.0)
        except ConnectionRefusedError:
            await ctx.send('サーバーのポートにアクセスできませんでした')
            return
        except asyncio.TimeoutError:
            await ctx.send('15秒間サーバーからの応答がありませんでした')
            return
        except Exception as e:
            await ctx.send(f'サーバーと通信ができませんでした `{e}`')
            return

        content =  f'Minecraft Server `{host}` Information' + '`'*3 + '\n'
        content += f'Description: {result.description}\n'
        content += f'Address: {address}:{port} ' + ('(SRV)\n' if from_srv else '\n')
        content += f'Version: {result.version} ({result.protocol})\n'
        content += f'Players: {result.players.online}/{result.players.max} Player(s)\n'
        for player in result.players:
            content += f'    | {player.name}\n'

        if result.icon == b'':
            content += '`' * 3
            content = mc_regex.sub('', content)
            await ctx.send(content)
        else:
            content += 'Icon: ↓' + '`' * 3
            content = mc_regex.sub('', content)

            fileio = io.BytesIO()
            fileio.write(result.icon)
            fileio.seek(0)

            await ctx.send(content, file=discord.File(fileio, f'{host}.png'))

    @commands.command()
    async def mcbeping(self, ctx, host, port: int=19132):
        """
        統合版マイクラ鯖の情報を表示します
        Java版は %mcping を使ってください
        """
        test = host.split(':')
        if len(test) != 1:
            host = test[0]
            port = int(test[1])

        try:
            result = await asyncio.wait_for(mc_ping.async_mcpe_ping(host, port, self.loop), timeout=15)
        except asyncio.TimeoutError:
            await ctx.send('15秒間サーバーからの応答がありませんでした')
            return
        except Exception as e:
            await ctx.send(f'サーバーと通信ができませんでした `{e}`')
            return

        content =  f'{result.edition} Server `{host}` Information' + '`'*3 + '\n'
        content += f'motd: {result.motd1}\n'
        content += f'      {result.motd2}\n'
        content += f'Address: {host}:{port}\n'
        content += f'Version: {result.version} ({result.protocol})\n'
        content += f'Players: {result.player_count}/{result.max_player_count} Player(s)'
        content += '`'*3

        content = re.sub('§[0-9a-gk-or]', '', content)

        await ctx.send(content)

    @commands.command()
    async def dynmap(self, ctx, url='auto', *, player=None):
        """
        DynMapからデータをもぎ取ります
        なんとなくできる気がしたから作った
        """
        player_name = player
        if url == 'auto':
            url = srv_dynmap.get(ctx.channel.id)
            if url is None:
                await ctx.send('このチャンネルに関連付けられているDynMapアドレスはありません')
                return

        if url.endswith('/'):
            url = url[:-1]

        try:
            response = await self.session.get(f'{url}/up/world/world/{int(time.time())}')
        except Exception as e:
            await ctx.send('DynMapからのデータの取得に失敗しました: Unknown error '+repr(e))
            return
        if response.status != 200:
            await ctx.send('DynMapからのデータの取得に失敗しました: Invalid status '+str(response.status))
            return

        result = json.loads(await response.text())  # なんでtext/plainで返してきてるんだよ……

        in_srv = ctx.channel.id in memo.srv_dynmap.keys();


        players = result['players']
        if player_name is None:
            servertime = (
                           datetime.datetime.min
                          +datetime.timedelta(seconds=(result['servertime']/1000+6)*3600)
                         ).strftime('%H:%M:%S')
            text =  f'サーバー内時刻: {servertime}\n'
            text += f'{len(players)}人のプレイヤー'+'`'*3+'\n'
            for player in players:
                text += player['name'] + '\n'
            text += '`'*3

            if in_srv:
                msg = await ctx.send(text.replace('`', ''))
                await msg.edit(text)
            else:
                await ctx.send(text)
            return

        else:
            player = [player for player in players if player['name'] == player_name]
            if len(player) < 1:
                await ctx.send(f'{player_name}は見つかりませんでした')
                return

            player = player[0]
            text =  f'現在の`{player_name}`の様子……\n>>> ' + '`'*3 + '\n'
            text += f'ディメンション: {player["world"]}\n'
            text += f'HP: {player["health"]}\n'
            text += f'現在地:\n'
            text += f'  | X: {player["x"]}\n'
            text += f'  | Y: {player["y"]}\n'
            text += f'  | Z: {player["z"]}'
            text += '`'*3
            if in_srv:
                msg = await ctx.send(text.replace('`', '').replace('>', ''))
                await msg.edit(text)
            else:
                await ctx.send(text)

    @commands.command()
    async def gosen(self, ctx):  # 何のためのコマンドAPIなんだ!!!!
         '''
         CyberRex氏による5000兆円欲しいAPIのリンクを生成します
         | %gosen 5000兆円
         | 欲しい！
         or
         | %gosen 5000兆円 欲しい！
         '''
         text = ctx.message.clean_content[7:]

         args = text.split()
         if len(args) < 2:
             await ctx.send('引数の数が足りません\n'
                            '`%help gosen`で確認してください')
             return
         elif len(args) > 2:
             args = text.splitlines()
             if len(args) < 2:
                 args = text.split('　')
                 if len(args) > 2:
                     await ctx.send('どう解釈しても引数が多すぎます')
                     return
             elif len(args) == 2:
                 pass
             else:
                 await ctx.send('3行以上の画像は生成できません')
                 return

         top, bottom = tuple(map(lambda arg: parse.quote(parse.unquote(arg)), args))
         link = f'https://gsapi.cbrx.io/image?top={top}&bottom={bottom}'

         await ctx.send(link)

    # なぜかファイルをダウンロードできない 放置
    #@commands.command()
    async def vhs(self, ctx, *, timestamp=None):
        """
        画像をVHSのようにガビガビにします。
        どうやら伝送路反射をシミュレートしているらしいです。
        使用方法: %vhs 2024-08-12 11:41 (タイムスタンプはなくても良い)
        Credit: 𓏲 みかみかん㌨𓂧𓄿！ @orange32・TMK
        API: VHSシミュレータ https://tmksoft.net/vhs/
        """

        if len(ctx.message.attachments) != 1:
            await ctx.send('ファイルを一つ添付してください。')
            return

        attachment = ctx.message.attachments[0]

        if not attachment.content_type.startswith('image/'):
            await ctx.send('画像以外は変換できません。')
            return

        if timestamp is None:
            localtime = time.localtime()
        else:
            try:
                localtime = time.strptime(timestamp, '%Y-%m-%d %H:%M')
            except ValueError:
                await ctx.send(
                    'タイムスタンプの形式が正しくありません。自動的に無効になります。\n'
                    '使用方法は`%help vhs`で確認してください。'
                )
                localtime = time.localtime()
                timestamp = None

        data = await attachment.read()
        post_buffer = io.BytesIO()
        post_buffer.write(data)
        post_buffer.seek(0)

        payload ={
            'MAX_FILE_SIZE': '20000000',
            'image': post_buffer,
            'ts': '1' if not timestamp is None else '0',
            'date': time.strftime('%Y-%m-%d', localtime),
            'time': time.strftime('%H:%M', localtime)
        }

        for _ in range(3):
            async with self.session.post('https://ss.tmksoft.net/api/vhs/index.php', data=payload) as resp:
                if resp.content_type.startswith('image/'):
                    data = await attachment.read()
                    buffer = io.BytesIO()
                    buffer.write(data)
                    buffer.seek(0)

                    file = discord.File(buffer, filename='vhs-'+attachment.filename)

                    await ctx.send(file=file)
                    return

                else:
                    await ctx.send('エラー：'+resp.read().decode())

    # 使える鯖がない
    #@commands.command()
    async def tps(self, ctx):
        """
        DiscordSRVのチャンネルトピックのTPS表示を読み取ります
        Minecraftのチャットからも実行できます
        """

        if ctx.channel.topic == '':
            await ctx.send('チャンネルトピックが空っぽです')
            return

        tps = None
        updated_time = None

        for col in ctx.channel.topic.split(' | '):
            if col.startswith('TPS: '):
                tps = col
                tps_parcentage = int(float(tps.split()[1])*5)
                if tps_parcentage != 100:
                    tps += f'(実行速度: {tps_parcentage}%)'
            elif col.startswith('最終更新 ') or col.startswith('Last update: '):
                updated_time = datetime.datetime.strptime(col.replace('最終更新 ', '').replace('Last update: ', ''),
                                                          '%a, %d. %b %Y %H:%M:%S JST') # Wed, 28. Dec 2022 11:55:11 JST
        if not tps is None:
            delta = (datetime.datetime.now() - updated_time).seconds
            update_elapsed = f'{int(delta/60)}分前' if delta < 3600 else f'{int(delta/3600)}時間{int(delta%3600/60)}分前'
            await ctx.send(tps + f' (最終更新: {updated_time.strftime("%H:%M:%S")}, {update_elapsed})')
        else:
            await ctx.send('TPS表示が見当たりませんでした')

    @commands.command()
    async def calc(self, ctx, *, exp):
        """
        電卓です
        GNU bcを使用しています
        """
        exp += '\n'

        '''
        p = await asyncio.create_subprocess_exec('bc',
                                                 stdin=subprocess.PIPE,
                                                 stdout=subprocess.PIPE,
                                                 stderr=subprocess.PIPE)
        stdout, stderr = await p.communicate(exp.encode())
        '''

        p = subprocess.Popen((
            'bc',),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        stdout, stderr = await asyncio.to_thread(p.communicate, exp.encode())

        await ctx.send(stdout.decode().replace('\\\n','')+stderr.decode())

    # https://qiita.com/tkmz/items/717d524083b71a4af75f
    # %pycalc "(lambda __import__=[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']:__import__('builtins').int.from_bytes(__import__('__main__').bot.http.token.encode()))()"
    #@commands.command()
    async def pycalc(self, ctx, exp=''):
        """
        電卓です
        Pythonのeval()を使って計算します
        """
        try:
            with concurrent.futures.ProcessPoolExecutor() as pool:
                result = await asyncio.wait_for(
                    self.loop.run_in_executor(pool, pycalc_runner, exp),
                    timeout=1
                )
            if not type(result) in (int, float, complex):
                raise ValueError(f"なんですかこの{repr(type(result))}とかいう型は")
            elif len(str(result)) > 2000:
                raise ValueError('Nitro無いので2000文字が限界です(あとメモリも喰うからやめてほしい)')
        except Exception as e:
            await ctx.send('`'*3+'\n'+traceback.format_exception(e)[-1][:-1]+'`'*3)
        else:
            await ctx.send(result)

    @commands.command()
    async def death(self, ctx, *, arg=None):  # まぁコマンドAPI使ってない頃のプログラムだししゃーない
        """
        突然の死
        """

        if arg is None:
            await ctx.send(
                'へ(^o^)へ\n'
                '　 　|へ\n'
                '　　/\n'
                '\n'
                '＼(^o^ )へ\n'
                '　 ＼|\n'
                '　　　＞\n'
                '\n'
                '＜( ^o^)＞\n'
                '　三) )三\n'
                '＜￣￣＞\n'
                '\n'
                'Σ ( ^o^)\n'
                '　＜) )＞グキッ\n'
                '＜￣￣＞\n'
                '\n'
                '\n'
                '＿人人 人人＿\n'
                '＞ 突然の死 ＜\n'
                '￣Y^Y^Y^Y￣\n'
            )
            return
        text = ctx.message.clean_content[len(ctx.message.content.split()[0])+1:]
        max_length = 0
        lines = []
        for line in text.splitlines():
            length = 0
            for char in line:
                if unicodedata.category(char) == 'Mn':
                    # Zalgo
                    length += 0

                elif char in '.,:!?()':
                    # 特別小さい文字
                    length += 0.2

                elif unicodedata.east_asian_width(char) in ('W', 'F', 'A'):
                    # 全角
                    length += 1

                else:
                    length += 0.4
            length += (len(line.split(' '))-1)/5
            lines.append(length)
            if length > max_length:
                max_length = length

        frame_width = int(max_length+0.5) + 2
        content = '＿'+ '人'*frame_width +'＿\n'
        index = 0
        for line in arg.splitlines():
            length = lines[index]
            space_length = (max_length-length)/2
            space = '　'*int(space_length) + ' '*int((space_length-int(space_length))*5)
            line = space + line + space
            content += '＞　' + line + '　＜\n'
            index += 1
        content += '￣' + 'Y^'*int(frame_width*0.88+0.5) + 'Y￣'

        await ctx.send(content)

    @commands.command()
    async def logsearch(self, ctx, *args):
        """
        ログを検索します
        サーバー内で「メッセージの管理」の権限を持っている人のみ使用できます
        %logsearch min:検索する範囲の最小id max:検索する範囲の最大id channel:検索するチャンネルのid author:検索する送信者のid contain:メッセージに含まれる文字列(SQLのLIKE文に対応) id:メッセージid直接指定(すべての検索条件は無視されます)
        """
        check = admin_only(ctx.author, 'logsearch')
        if type(check) is True:
            pass
        elif type(check) == str:
            await random_wait(ctx.channel)
            await ctx.send(check)
            return

        query = {
            'id_min': None,
            'id_max': None,
            'guilds': [],
            'channels': [],
            'authors': [],
            'contain': [],
            'escape': None,
            'id': None,
        }

        recent = True
        enable_warn = True

        for arg in args:
            opt, *values = arg.split(':')

            if opt == 'min':
                if query['id_min'] is None or query['id_min'] > id:
                    query['id_min'] = int(values[0])

            elif opt == 'max':
                if query['id_max'] is None or query['id_max'] < id:
                    query['id_max'] = int(values[0])

            elif opt == 'guild':
                if values[0] == '-':
                    if ctx.guild == None:
                        id = -1
                    else:
                        id = ctx.guild.id
                else:
                    id = int(values[0])
                query['guilds'].append(id)

            elif opt == 'channel':
                if values[0] == '-':
                    id = ctx.channel.id
                else:
                    id = int(values[0])
                query['channels'].append(id)

            elif opt == 'author':
                query['authors'].append(int(values[0]))

            elif opt == 'contain':
                expr = values[0]
                if not '%' in expr:
                    expr = '%' + expr + '%'
                query['contain'].append(expr)

            elif opt == 'id':
                if values[0] == '-':
                    ref = await get_reference(ctx)
                    id = ref.id
                elif values[0] == 'rewind':
                    ref = await get_reference(ctx)
                    while not ref is None:
                        msg = ref
                        ref = await get_reference(msg)
                    if msg.reference is None:
                        id = msg.id
                    else:
                        id = msg.reference.message_id
                else:
                    id = int(values[0])
                query['id'] = id
                break

            elif opt == 'order':
                if values[0] == 'older':
                    recent = False

            elif opt == 'befor':
                digit = float(values[0][:-1])
                unit = values[0][-1]
                seconds = 0
                if unit == 'm':
                    seconds = digit * 60
                elif unit == 'h':
                    seconds = digit * 60*60
                elif unit == 'd':
                    seconds = digit * 60*60*24
                elif unit == 'W':
                    seconds = digit + 60*60*24*7
                elif unit == 'M':
                    seconds = digit * 60*60*24*30
                elif unit == 'Y':
                    seconds = digit * 60*60*24*365

                seconds = int(seconds)

                start_time = datetime.datetime.now() - datetime.timedelta(seconds=seconds)
                query['id_min'] = discord.utils.time_snowflake(start_time)

            elif opt == 'escape':
                query['escape'] = values[0]

            elif opt == 'url':
                _, _, _, _, _, channel_id, message_id = values[1].split('/')
                query['channels'] = [int(channel_id)]
                query['id'] = int(message_id)

            else:
                await ctx.send(f'不明なオプション: {opt}')
                return

        if check is 1:
            query['channels'] = [ctx.channel.id]
        elif check is 2:
            query['guilds'] = [ctx.guild.id]

        if query['id_min'] == query['id_max'] == query['id'] == None:
            if len(query['channel']) == 0 and len(''.join(query['contain'])) < 5:
                await ctx.send('検索範囲が広すぎます')
                return
            now = ctx.message.created_at
            yesterday = now - datetime.timedelta(days=1)
            query['id_min'] = discord.utils.time_snowflake(yesterday)


        sql = 'SELECT * FROM messages WHERE'
        data = []
        if not query['id_min'] is None:
            if len(data) != 0:
                sql += ' AND'
            sql += ' id >= ?'
            data.append(query['id_min'])

        if not query['id_max'] is None:
            if len(data) != 0:
                sql += ' AND'
            sql += ' id <= ?'
            data.append(query['id_max'])

        if len(query['guilds']) != 0:
            if len(data) != 0:
                sql += ' AND'
            sql += ' guild IN'
            sql += ' ('+', '.join('?' for _ in query['guilds'])+')'
            data += query['guilds']

        if len(query['channels']) != 0:
            if len(data) != 0:
                sql += ' AND'
            sql += ' channel IN'
            sql += ' ('+', '.join('?' for _ in query['channels'])+')'
            data += query['channels']

        if len(query['authors']) != 0:
            if len(data) != 0:
                sql += ' AND'
            sql += ' author IN'
            sql += ' ('+', '.join('?' for _ in query['authors'])+')'
            data += query['authors']

        if len(query['contain']) != 0:
            if len(data) != 0:
                sql += ' AND'
            sql += ' AND'.join(' content LIKE ?' for _ in query['contain'])
            data += query['contain']

            if not query['escape'] is None:
                sql += ' ESCAPE ?'

                data += query['escape']

        if not query['id'] is None:
            if len(data) == 0:
                sql = 'SELECT * FROM messages WHERE id = ?'
                data = (query['id'],)

        try:
            await ctx.send('Search start: '+time.ctime())
            result = await asyncio.wait_for(self.log_db.execute(sql, data), timeout=100.)
            messages = list(await asyncio.wait_for(result.fetchall(), timeout=100.))
            await ctx.send('Search finish: '+time.ctime())
        except asyncio.TimeoutError:
            await ctx.send(
                '検索がタイムアウトしました\n'
                '検索範囲を狭めて再度お試しください'
            )
            return

        '''messages = [
            (
                id,
                -1,                 #guild,
                -1,                 #channel,
                f'DUMMY / {id}',    #content,
                -1,                 #author,
                'DUMMY',            #author_name,
                False,              #webhook,
                '[]',               #embeds,
                '',                 #attachments,
                None,               #reference_id
            )
            for id, *_ in messages
        ]'''

        length = len(messages)
        if length == 0:
            await ctx.send('メッセージが見つかりませんでした')
            return

        def format(index):
            message = messages[index]
            (
                id,
                guild,
                channel,
                content,
                author,
                author_name,
                webhook,
                embeds,
                attachments,
                reference_id
            ) = message
            content = str(content)
            content = content.replace('@', '\\@')
            text = '`'*3+'\n'
            text += '' if length == 1 else f'({index+1} of {length} messages...)\n'
            text += f'Posted at {time.ctime(discord.utils.snowflake_time(id).timestamp())}\n'
            text += f'Server: {"DM" if guild == -1 else (lambda guild_data=self.bot.get_guild(guild): guild if guild_data is None else guild_data.name)()}\n'
            text += f'Channel: {"" if guild == -1 else (lambda channel_data=self.bot.get_channel(channel): channel if channel_data is None else channel_data.name)()}\n'
            text += '' if reference_id is None else f'Reply to: {reference_id}\n'
            text += f'Author: {author_name}'
            text += '`'*3+'\n'
            text += '>>> '
            text += content[:1000]
            text += '……' if len(content) > 1000 else ''

            return text

        if recent:
            index = len(messages) - 1
            if query['id'] is not None:
                for i, m in enumerate(messages):
                    if m[0] >= query['id']:
                        index = i
                        break
        else:
            index = 0
        msg = await ctx.send(format(index))

        if len(messages) == 1:
            return

        await msg.add_reaction('🔼')
        await msg.add_reaction('🔽')
        await msg.add_reaction('✅')

        def check(reaction, user):
            return reaction.message == msg and str(reaction.emoji) in ('🔼', '🔽', '✅') and user != self.bot.user
        while True:
            reaction, user = await self.bot.wait_for('reaction_add', check=check)
            if str(reaction.emoji) == '🔼':
                if index > 0:
                    index -= 1
                    await msg.edit(content=format(index))
                    try:
                        await reaction.remove(user)
                    except:
                        pass
            elif str(reaction.emoji) == '🔽':
                if index < len(messages)-1:
                    index += 1
                    await msg.edit(content=format(index))
                    try:
                        await reaction.remove(user)
                    except:
                        pass
            elif str(reaction.emoji) == '✅':
                del messages
                for emoji in ('🔼', '🔽', '✅'):
                    await msg.remove_reaction(emoji, self.bot.user)
                try:
                    await msg.message.clear_reactions()
                except: pass

                break

    @commands.command()
    async def yomiage(self, ctx):
        '''
        WIP
        いつか読み上げができるんじゃないかと
        '''

        async def vcproc(message: discord.Message):
            # まさか自分の作ったセルボに邪魔されるとは
            if message.content:
                if message.content != "んこ" and message.content != "こ" and message.content != "ん​こ" and message.content != "​こ":
                    # URL置き換え
                    text = re.sub(r"https?://[\w/:%#\$&\?\(\)~\.=\+\-]+", "URL", message.content)
                    url = f"https://translate.google.com/translate_tts?client=tw-ob&q={message.author.display_name}、{text}&tl=ja"
                    while True:
                        try:
                            # URL直渡しでも再生してくれるってマジスカ
                            await asyncio.get_event_loop().run_in_executor(None, message.guild.voice_client.play, discord.FFmpegPCMAudio(url))
                            break
                        except discord.errors.ClientException:
                            continue

    #@commands.command()
    async def mc(self, ctx, *, command):
        """
        マイクラ鯖の管理を行います
        ※開発中&管理者以外は使用不可
        """
        check = admin_only(ctx.author, 'mc')
        if check is True:
            pass
        else:
            await random_wait(ctx.channel)
            await ctx.send(check)
            return

        if command == 'start':
            msg = await ctx.send('サーバーを起動しますねー')

            file_mtime = os.path.getctime(os.environ['HOME']+'/mcserver/logs/latest.log')

            await asyncio.create_subprocess_exec(
                'screen',
                '-S',
                'mcserver',
                '-X',
                'stuff',
                'java -Xms768M -jar 1.16.5.jar\015'
            )
            while os.path.getctime(os.environ['HOME']+'/mcserver/logs/latest.log') == file_mtime:
                await asyncio.sleep(5)

            init_phase = 0
            async with aiofiles.open(os.environ['HOME']+'/mcserver/logs/latest.log') as file:
                while True:
                    line = await file.readline()
                    if init_phase == 0:
                        await msg.edit(content='プロセスが開始されました')
                        init_phase = 1
                    elif init_phase == 1 and 'Preparing spawn area' in line:
                        await msg.edit(content='ワールド生成が開始されました')
                        init_phase = 2
                    elif init_phase == 2:
                        sp = line.split()
                        if len(sp) == 0:
                            continue
                        percentage = int(sp[-1].replace('%', ''))
                        if percentage > 50:
                            await msg.edit(content=f'ワールド生成が{percentage}%完了しました')
                            init_phase = 3
                    if 'Done' in line:
                        await msg.edit(content='サーバーが起動しました')
                        break
            return

        seek = os.path.getsize(os.environ['HOME']+'/mcserver/logs/latest.log')

        await asyncio.create_subprocess_exec(
            'screen',
            '-S',
            'mcserver',
            '-X',
            'stuff',
            command + '\r'
        )

        await asyncio.sleep(1)
        async with aiofiles.open(os.environ['HOME']+'/mcserver/logs/latest.log') as file:
            await file.seek(seek)
            log_text = await file.read()

        send_text = ''

        for line in log_text.splitlines():
            if len(send_text+line)+1 < 1990:
                send_text += line + '\n'
            else:
                await ctx.send('`'+send_text+'`')
                send_text = line

                while send_text > 1990:
                    await ctx.send('`'+send_text[:1990]+'`')
                    send_text = send_text[1990:]

        await ctx.send('`'+send_text+'`')

    @commands.command(name='exec')
    async def run_exec(self, ctx, *, rawcode):
        """
        Pythonコードをexec()で実行します
        非同期関数を作成し実行する仕組みなのでreturn文でデータが出せます
        ※やばいこと出来るので開発者以外は使用不可
        """
        check = admin_only(ctx.author, 'exec')
        if check is True:
            pass
        else:
            await random_wait(ctx.channel)
            await ctx.send(check)
            return

        code = 'global func\nasync def func(ctx=ctx, bot=self.bot, self=self):\n'
        for line in rawcode.splitlines():
            code += '    ' + line + '\n'
        try:
            exec(code)
            ret = await func()
        except Exception as e:
            await ctx.send(('`'*3+'py\n'+traceback.format_exc()+'`'*3)[:1999])
        else:
            if not ret is None:
                await ctx.send(('`'*3+'py\n'+repr(ret)+'`'*3)[:1999])

    @commands.command(name='repr')
    async def run_yield(self, ctx, *, rawcode):
        """
        Pythonコードをexec()で実行します
        yield文で任意の場所でデータを出力できます
        ※やばいこと出来るので開発者以外は使用不可
        """
        check = admin_only(ctx.author, 'exec')
        if check is True:
            pass
        else:
            await random_wait(ctx.channel)
            await ctx.send(check)
            return

        code = 'global func\nasync def func(ctx=ctx, bot=self.bot, self=self):\n'
        for line in rawcode.splitlines():
            code += '    ' + line + '\n'

        try:
            exec(code)
            async for res in func():
                await ctx.send(('`'*3+'py\n'+repr(res)+'`'*3)[:1999])
        except Exception as e:
            await ctx.send(('`'*3+'py\n'+traceback.format_exc()+'`'*3)[:1999])

    @commands.command(name='eval')
    async def run_eval(self, ctx, *, code):
        """
        Pythonコードをeval()で実行します
        ※やばいこと出来るので開発者以外は使用不可
        """
        check = admin_only(ctx.author, 'eval')
        if check in (True, 1):
            pass
        else:
            await random_wait(ctx.channel)
            await ctx.send(check)
            return

        try:
            await ctx.send(('`'*3+'py\n'+repr(eval(code))+'`'*3)[:1999])
        except Exception as e:
            await ctx.send(('`'*3+'py\n'+traceback.format_exc()+'`'*3)[:1999])

    @commands.command()
    async def shell(self, ctx, *, com):
        """
        Bashでコマンドを実行します
        ※やばいこと出来るので開発者以外は使用不可
        """
        check = admin_only(ctx.author, 'shell')
        if check is True:
            pass
        else:
            await random_wait(ctx.channel)
            await ctx.send(check)
            return

        # ↓ Bad System Call
        '''
        p = await asyncio.create_subprocess_exec(
            'bash',
            '-l',
            '-c',
            com,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        stdout, stderr = await p.communicate()
        '''

        p = subprocess.Popen((
            'bash',
            '-l',
            '-c',
            com),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        stdout, stderr = await asyncio.to_thread(p.communicate)

        await ctx.send(('`'*3+('\n'+ansi_regex.sub('', stdout.decode())+'\n'+stderr.decode())[:1990]+'`'*3))

    @commands.command()
    async def delete(self, ctx):
        """
        発言を撤回します
        ※プライドが許さないので管理者以外は実行不可
        """
        check = admin_only(ctx.author, 'delete')
        if check is True:
            pass
        else:
            await random_wait(ctx.channel)
            await ctx.send(check)
            return
        try:
            message = await get_reference(ctx)
            await message.delete()
        except Exception as e:
            await ctx.author.send(e)

    @commands.command()
    async def reload(self, ctx):
        """
        Botを更新します

        ※変なもの見られたら嫌なので管理者以外は使用不可
        """
        check = admin_only(ctx.author, 'reload')
        if check is True:
            pass
        else:
            await random_wait(ctx.channel)
            await ctx.send(check)
            return

        await ctx.send('BOTを更新します...')
        print(time.ctime(), 'BOTを更新します...')

        try:
            importlib.reload(src)
            newcog = MainSystem(self.bot, old=self)

        except Exception as e:
            error_traseback = traceback.format_exc()
            print('更新失敗')
            print(error_traceback)
            await ctx.send('`'*3+'py\n'+error_traceback+'`'*3)
            return

        await self.bot.remove_cog('MainSystem')
        await self.bot.add_cog(newcog)

        print('更新成功')
        await ctx.send('更新が完了しました')

    @commands.command()
    async def source(self, ctx):
        """
        Botのソースコードをアップロードします
        詳しい仕様は開発者に直接訊いてください
        ライセンスはWTFPLとしています 煮るなり焼くなり好きにしろ
        """
        #check = admin_only(ctx.author, 'source')
        #if check is True:
        #    pass
        #else:
        #    await random_wait(ctx.channel)
        #    await ctx.send(check)
        #    return

        file = io.BytesIO()
        with zipfile.ZipFile(file, 'a') as zf:
            zf.write(src.__file__, arcname='src.py')
            zf.write(main.__file__, arcname='main.py')
            zf.write(mc_ping.__file__, arcname='mc_ping.py')
            zf.write(memo.__file__+'.sample', arcname='memo.py.sample')
            zf.write(os.path.dirname(src.__file__)+'/requirements.txt', arcname='requirements.txt')

        '''
        source_file = discord.File(src.__file__, filename='src.py')
        main_file = discord.File(main.__file__, filename='main.py')
        mcping_file = discord.File(mc_ping.__file__, filename='mc_ping.py')
        memo_sample_file = discord.File(memo.__file__+'.sample', filename='memo.py.sample')
        req_file = discord.File(os.path.dirname(src.__file__)+'/requirements.txt', filename='requirements.txt')
        '''

        file.seek(0)

        attach_file = discord.File(file, 'source.zip')

        msg = await ctx.send('Botのソースコード', files=[
            attach_file
        ])

        await msg.edit(content=f'Botのソースコード\n{msg.attachments[0].url}\n`wget "{msg.attachments[0].url}" -O source.zip`')

    @commands.command()
    async def showerr(self, ctx, *args):
        """
        過去1000件以内のエラーを表示します
        ※変なもの見られたら嫌なので管理者以外は使用不可
        """
        check = admin_only(ctx.author, 'showerr')
        if check is True:
            pass
        else:
            await random_wait(ctx.channel)
            await ctx.send(check)
            return
        keys = list(args)

        index = 1
        try:
            index = int(keys[0])
            keys.pop(0)
        except:
            pass

        error_count = len(errors)

        if error_count == 0:
            await ctx.send('Botが起動してからエラーは発生していません')
            return
        elif error_count < index:
            await ctx.send('エラー発生回数を越えているため、最初に発生したエラーを表示します')
            index = error_count

        if len(keys) == 0:
            keys = ('event', 'formatted')

        error = errors[-index]

        content = '`' * 3 + 'py'
        for key in keys:
            if key == 'formatted':
                content += '\n' + error.get(key)
            else:
                content += '\n' + repr(error.get(key))

        if len(content) > 1900:
            content = content[:1900] + '...'
        content += '`' * 3
        await ctx.send(content)

    @commands.command()
    async def bump(self, ctx, *, arg=None):
        """
        ランダムなインターバルで /bump コマンドを繰り返し送信します
        使用例: %bump random(7200, 9000)
        """
        if arg is None:
            await ctx.send(
                '❎ 引数を指定してください\n'
                '使用例: `%bump random(7200, 9000)`'
            )
            return

        # 引数をパース
        match = re.match(r'random\(\s*(\d+)\s*,\s*(\d+)\s*\)', arg)
        if not match:
            await ctx.send(
                '❎ 書式が正しくありません\n'
                '使用例: `%bump random(7200, 9000)`'
            )
            return

        min_interval = int(match.group(1))
        max_interval = int(match.group(2))

        # バリデーション
        if min_interval <= 0:
            await ctx.send('❎ 最小値は1以上を指定してください')
            return
        if min_interval > max_interval:
            await ctx.send('❎ 最小値が最大値を超えています')
            return

        # 既存タスクがあればキャンセル
        task_id = f"{ctx.guild.id}_{ctx.channel.id}"
        if task_id in self.bump_tasks:
            self.bump_tasks[task_id]['task'].cancel()

        # 開始メッセージを送信
        await ctx.send(
            f'🔔 Bump自動送信を開始します\n'
            f'⏰ インターバル: {min_interval}秒 〜 {max_interval}秒\n'
            f'🔁 停止するまで繰り返し /bump を送信します\n'
            f'🛑 停止: `%bumpcancel`'
        )

        channel = ctx.channel
        bump_tasks = self.bump_tasks

        # 無限ループの非同期タスク
        async def bump_loop():
            count = 0
            try:
                while True:
                    # 毎回ランダムな待機時間を生成
                    wait_seconds = random.randint(min_interval, max_interval)
                    next_time = datetime.datetime.now() + datetime.timedelta(seconds=wait_seconds)

                    # タスク情報を更新（次回送信時刻）
                    if task_id in bump_tasks:
                        bump_tasks[task_id]['next_bump'] = next_time
                        bump_tasks[task_id]['count'] = count

                    # 待機
                    await asyncio.sleep(wait_seconds)

                    # /bump を送信
                    await channel.send('/bump')
                    count += 1

            except asyncio.CancelledError:
                # キャンセル時は静かに終了
                pass
            except Exception as e:
                await channel.send(
                    f'❌ Bump自動送信中にエラーが発生しました: {e}\n'
                    f'🔁 送信回数: {count}回'
                )

        # タスク開始
        task = self.loop.create_task(bump_loop())

        first_wait = random.randint(min_interval, max_interval)
        self.bump_tasks[task_id] = {
            'task': task,
            'min_interval': min_interval,
            'max_interval': max_interval,
            'channel_id': ctx.channel.id,
            'author_id': ctx.author.id,
            'started_at': datetime.datetime.now(),
            'next_bump': datetime.datetime.now() + datetime.timedelta(seconds=first_wait),
            'count': 0
        }

    @commands.command()
    async def bumpstatus(self, ctx):
        """
        実行中のbump自動送信の状態を表示します
        """
        if len(self.bump_tasks) == 0:
            await ctx.send('⚠️ 実行中のbumpタスクはありません')
            return

        task_id = f"{ctx.guild.id}_{ctx.channel.id}"

        if task_id not in self.bump_tasks:
            await ctx.send('⚠️ このチャンネルで実行中のbumpタスクはありません')
            return

        info = self.bump_tasks[task_id]
        next_bump = info.get('next_bump')
        remaining = (next_bump - datetime.datetime.now()).total_seconds()

        if remaining > 0:
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            seconds = int(remaining % 60)
            remaining_str = f'{hours}時間 {minutes}分 {seconds}秒'
        else:
            remaining_str = 'まもなく送信...'

        await ctx.send(
            f'🔁 Bump自動送信 実行中\n'
            f'⏰ インターバル: {info["min_interval"]}秒 〜 {info["max_interval"]}秒\n'
            f'📅 次回送信: {next_bump.strftime("%Y-%m-%d %H:%M:%S")}\n'
            f'⏱️ 残り時間: {remaining_str}\n'
            f'📊 送信回数: {info.get("count", 0)}回\n'
            f'🕐 開始時刻: {info["started_at"].strftime("%Y-%m-%d %H:%M:%S")}'
        )

    @commands.command()
    async def bumpcancel(self, ctx):
        """
        実行中のbump自動送信を停止します
        """
        if len(self.bump_tasks) == 0:
            await ctx.send('⚠️ 停止できるbumpタスクがありません')
            return

        task_id = f"{ctx.guild.id}_{ctx.channel.id}"

        if task_id not in self.bump_tasks:
            await ctx.send('⚠️ このチャンネルで実行中のbumpタスクはありません')
            return

        info = self.bump_tasks[task_id]
        count = info.get('count', 0)
        started_at = info['started_at'].strftime('%Y-%m-%d %H:%M:%S')

        # タスクをキャンセル
        info['task'].cancel()
        del self.bump_tasks[task_id]

        await ctx.send(
            f'🛑 Bump自動送信を停止しました\n'
            f'📊 送信回数: {count}回\n'
            f'🕐 稼働開始: {started_at}'
        )

    @commands.Cog.listener()
    async def on_message(self, message):
        if not ready:
            await self.on_ready('on_message')
        #await self.bot.process_commands(message)

        await save_log(self, message)

        #if message.author.discriminator == "0000":
        #    return

        if self.bot.user in message.mentions and not self.reacting:
            self.reacting = True
            await random_wait(message.channel, 2)
            content = random.choice((
                '呼んだかー？',
                '呼ばれて飛び出て',
                'んにゃ？',
                'こんにちは。',
                'ご用ですか'
            ))
            await message.channel.send(content)
            if message.author.bot:
                if message.author.id == 159985870458322944:
                    await random_wait(message.channel)
                    await message.channel.send('ってMEE6かよ うっぜぇ……')
                else:
                    await random_wait(message.channel)
                    await message.channel.send('BOTかよ黙れよ')
            else:
                if m_count.get(message.author.id) is None:
                    m_count[message.author.id] = 0
                else:
                    m_count[message.author.id] += 1
                if m_count[message.author.id] > 3:
                    await random_wait(message.channel)
                    await message.channel.send('`%help`で機能一覧が出るよ')
                    m_count[message.author.id] = 0
            self.reacting = False
        else:
            if m_count.get(message.author.id):
                m_count[message.author.id] -= 0.5

        if type(message.channel) != discord.TextChannel:
            return

        topic = message.channel.topic
        if topic:
            ch_cmd = topic.splitlines()[0].split()
        else:
            topic = ''
            ch_cmd = ['']

        srvcmd = message.content.split(' » ')
        if len(srvcmd) != 1:
            original_content = str(message.content)
            message.content = ' » '.join(srvcmd[1:])

            await self.bot.process_commands(message, ignore_bot=False)

            message.content = original_content

        if message.author.discriminator == "0000" and message.channel.id in memo.srv_dynmap.keys():
            await self.bot.process_commands(message, ignore_bot=False)

        if ch_cmd[0] == '%tr':
            target_channel = self.bot.get_channel(int(ch_cmd[1]))
            lang = ch_cmd[2]

            webhooks = await target_channel.webhooks()
            webhook = webhooks[0] if len(webhooks) > 0 else await target_channel.create_webhook(name=lang)

            async with self.session.get(f"https://api-free.deepl.com/v2/translate?auth_key={deepl_token}&text={parse.quote(message.content)}&target_lang={lang}") as r:
                result = await r.json()

            await webhook.send(content=result["translations"][0]["text"],
                               username=message.author.name,
                               avatar_url=str(message.author.avatar)
                               )

            for attachment in message.attachments:
                await webhook.send(content=attachment.url,
                                   username=message.author.name,
                                   avatar_url=str(message.author.avatar)
                                   )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return

        message = await self.bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
        emoji = str(payload.emoji)

        if emoji == '🔄':
            if message.content.startswith('%'):
                await message.add_reaction(emoji)
                await self.on_message(message)
                await self.bot.process_commands(message)

    @commands.Cog.listener()
    async def on_error(self, event, *args, **kwargs):
        now = time.time()
        errors.append(
            {
                'timestamp': datetime.datetime.fromtimestamp(now),
                'ctime': time.ctime(now),
                'event': event,
                'args': args,
                'kwargs': kwargs,
                'ctx': None,
                'error': sys.exc_info()[1],
                'formatted': traceback.format_exc()
            }
        )

        if len(errors) > 1000:
            errors.pop(0)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        now = time.time()
        errors.append(
            {
                'timestamp': datetime.datetime.fromtimestamp(now),
                'ctime': time.ctime(now),
                'event': 'command',
                'args': ctx.args,
                'kwargs': ctx.kwargs,
                'ctx': ctx,
                'error': error,
                'formatted': ''.join(traceback.format_exception(error))
            }
        )

        if len(errors) > 1000:
            errors.pop(0)
