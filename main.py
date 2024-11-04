import discord
from discord.ext import commands
from token_bot import TOKEN_BOT

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='.', intents=intents)

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')
@bot.command()
async def repeat(ctx, arg):
    await ctx.send(arg)


bot.run(TOKEN_BOT)

