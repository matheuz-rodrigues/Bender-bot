
from bot_instance import bot
import discord
from datetime import datetime, timedelta
from requests import put,get

url = "https://sz71bpkh-3000.brs.devtunnels.ms"
# Dicionário para armazenar horários de entrada
voice_log = {}

voice_log = {}  # Inicialização do dicionário

@bot.event
async def on_voice_state_update(member, before, after):
    log_channel_id = 1310813222370148403
    log_channel = bot.get_channel(log_channel_id)

    if before.channel is None and after.channel is not None:

        voice_log[member.id] = datetime.now()

        embed = discord.Embed(
            description=f"🔊 **{member.display_name}** entrou no canal **{after.channel.name}**. "
                        f"Espero que seja interessante, porque eu não estou prestando atenção!",
            color=discord.Color.green()
        )
        await log_channel.send(embed=embed)

    elif before.channel is not None and after.channel is None:
        entry_time = voice_log.pop(member.id, None)
        if entry_time:
            duration = datetime.now() - entry_time
            formatted_duration = str(duration).split('.')[0]  # Formato HH:MM:SS
            hours_to_seconds = str(formatted_duration).split(":")[0] * 3600 #hours to seconds
            minutes_to_seconds = str(formatted_duration).split(":")[1] * 60 #minutes to seconds
            seconds = str(formatted_duration).split(":")[2] #seconds
            total_seconds_time = int(hours_to_seconds) + int(minutes_to_seconds) + int(seconds)
            response = put(f"{url}/usertime/{member.id}/{total_seconds_time}")

            embed = discord.Embed(
                description=f"🔇 **{member.display_name}** finalmente deixou o canal **{before.channel.name}**. "
                            f"Ficou lá por {formatted_duration}. Aposto que foi tão emocionante quanto assistir tinta secar!",
                color=discord.Color.red()
            )
            await log_channel.send(embed=embed) 
