from bot_instance import bot
from token_bot import TOKEN_BOT
from discord.ext import commands
from bot_instance import discord
from imports import *

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name=".ajuda"))
    print(f'Bot conectado como {bot.user}')

@bot.check
async def canais_autorizados(ctx):
    idsPermitidos = [1302789488866623488, 1303279261615915028, 1299532257408843867]
    if ctx.channel.id in idsPermitidos or ctx.author.id == 796471574827237436:
        return True
    return False
#Evita o erro de console event.check que o bot gera ao executar a função canais_autorizados
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        return


@bot.command()
async def ajuda(ctx):
    nome = ctx.author
    await  ctx.send(f"""Olá {nome.mention}, aqui está uma lista de comandos que você pode utilizar.\n
    **MINIGAMES**
    .ppt [Pedra, Papel, Tesoura] -> Jogue Pedra ou Papel ou Tesoura
    .coinflip [Cara ou Coroa] -> Jogue Cara ou Coroa
    .cotacao [Dólar, Euro, Iene, Libra, Franco e Bitcoin] -> Veja a cotação das moedas ao redor do mundo""")

bot.run(TOKEN_BOT)

