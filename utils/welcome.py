from  bot_instance import bot
import discord


@bot.event
async def on_member_join(member):
    channel_id = 1293004888716087298
    channel = bot.get_channel(channel_id)

    embed = discord.Embed(
        description=f" Acabou de ser commitado na {member.guild}! :space_invader:",
        color=discord.Color.blue()
    )
    embed.set_image(url="https://media.tenor.com/Qr56AbZspAoAAAAM/celebrate-futurama.gif")
    embed.set_author(name=member, icon_url=member.avatar.url)
    await channel.send(f"{member.mention}",embed=embed)
