import asyncio
import requests
from bot_instance import bot
from requests import get
import discord
from settings import url_api
@bot.command()
async def tempo(ctx):
    url = url_api + 'usertime'

    try:
        response = await asyncio.to_thread(get, f"{url}/{ctx.author.id}", timeout=5)
    except requests.exceptions.RequestException:
        await ctx.send("Não consegui falar com a API de tempo agora. Tenta de novo daqui a pouco.")
        return
    if response.status_code == 200:
        data = response.json()
        print(data)

        hours = int(data["time"] / 3600)
        minutes = int((data["time"] % 3600) / 60)
        seconds = int(data["time"] % 60)
        embed = discord.Embed(
                description=f"**{ctx.author}** disperdiçou um total de {hours} horas {minutes} minutos e {seconds} segundos no servidor.",
                color=discord.Color.blue()
            )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
                description=f"**{ctx.author}** Você ainda não particiou de nenhuma call nesse servidor. Parabéns!",
                color=discord.Color.blue()
            )
        await ctx.send(embed=embed)
