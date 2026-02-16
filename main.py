import src
import discord
from discord.ext import commands
import asyncio
from memo import token, token_s, developer

allowed_users = list(developer)

class myBot(commands.Bot):
    async def process_commands(self, message, ignore_bot=True):
        if message.author.bot and ignore_bot:
            return
        if not message.author.id in allowed_users:
            pass
#            return
        ctx = await self.get_context(message)
        await self.invoke(ctx)

bot = myBot(command_prefix='%', activity=discord.CustomActivity('こんにちは世界'))

if token_s:
    client = discord.Client(status=discord.Status.dnd, activity=discord.CustomActivity('ゲームうまくなりたいね…'))
else:
    client = None

@bot.event
async def setup_hook():
    await bot.add_cog(src.MainSystem(bot, sub_account=client))

    if token_s:
        asyncio.create_task(client.start(token_s))

@bot.event
async def on_message(message):
    await bot.process_commands(message)

    for func in bot.get_cog('MainSystem').tasks.values():
        await func(message)

if not client is None:
    @client.event
    async def on_message(message):
        await asyncio.sleep(1)
        if not message in bot.cached_messages:
            await src.save_log(bot.get_cog('MainSystem'), message)

        for func in bot.get_cog('MainSystem').sub_account_tasks.values():
            await func(message)

if __name__ == '__main__':
    bot.run(token)
