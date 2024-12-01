import requests
from bot_instance import bot
from requests import get
import discord

@bot.command()
async def tempo(ctx):
    url = "https://sz71bpkh-3000.brs.devtunnels.ms/usertime"

    response = get(f"{url}/{ctx.author.id}")
    if response.status_code == 200:
        data = response.json()
        data = data['response']

        hours = int(data["time"] / 3600)
        minutes = int((data["time"] % 3600) / 60)
        seconds = int(data["time"] % 60)
        embed = discord.Embed(
                description=f"**{ctx.author}** disperdiçou um total de {hours}:{minutes}:{seconds} no servidor.",
                color=discord.Color.blue()
            )
        await ctx.send(embed=embed)