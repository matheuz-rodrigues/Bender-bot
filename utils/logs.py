import asyncio
from datetime import datetime

import discord
import requests

from bot_instance import bot
from token_bot import url_api

LOG_CHANNEL_ID = 1310813222370148403
# Horário de entrada de cada membro na call
voice_log = {}


def _formatar(segundos):
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


async def _salvar_tempo(member_id, segundos):
    try:
        # requests é bloqueante: roda em outra thread e com timeout para não derrubar o bot
        await asyncio.to_thread(
            requests.put, f"{url_api}usertime/{member_id}/{segundos}", timeout=5
        )
    except requests.exceptions.RequestException as e:
        print(f"[logs] não consegui salvar o tempo de call: {e}")


@bot.event
async def on_voice_state_update(member, before, after):
    log_channel = bot.get_channel(LOG_CHANNEL_ID)

    if before.channel is None and after.channel is not None:
        voice_log[member.id] = datetime.now()
        if log_channel:
            embed = discord.Embed(
                description=f"🔊 **{member.display_name}** entrou no canal **{after.channel.name}**. "
                            f"Espero que seja interessante, porque eu não estou prestando atenção!",
                color=discord.Color.green()
            )
            await log_channel.send(embed=embed)

    elif before.channel is not None and after.channel is None:
        entry_time = voice_log.pop(member.id, None)
        if entry_time:
            total_segundos = int((datetime.now() - entry_time).total_seconds())
            bot.loop.create_task(_salvar_tempo(member.id, total_segundos))

            if log_channel:
                embed = discord.Embed(
                    description=f"🔇 **{member.display_name}** finalmente deixou o canal **{before.channel.name}**. "
                                f"Ficou lá por {_formatar(total_segundos)}. Aposto que foi tão emocionante quanto assistir tinta secar!",
                    color=discord.Color.red()
                )
                await log_channel.send(embed=embed)
