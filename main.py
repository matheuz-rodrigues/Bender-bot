from bot_instance import bot
from minigames.ppt import ppt
from token_bot import TOKEN_BOT

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')

@bot.command()
async def ajuda(ctx):
    await ctx.send("**MINIGAMES**\n")
    await ctx.send(".ppt [Pedra, Papel, Tesoura] -> Jogue Pedra ou Papel ou Tesoura\n")
    await ctx.send(".coinflip [Cara ou Coroa] -> Jogue Cara ou Coroa")

bot.run(TOKEN_BOT)

