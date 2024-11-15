from  bot_instance import bot
import discord
from discord.utils import get

@bot.event
async def on_member_join(member):
    channel_id = 1293004888716087298
    channel = bot.get_channel(channel_id)
    role1 = get(member.guild.roles, name="Pequeno Gafanhoto")
    role2 = get(member.guild.roles, name="GarticMod")
    user_id = member.id
    user = await member.guild.fetch_member(user_id)
    await user.add_roles(role1)
    await user.add_roles(role2)

    embed = discord.Embed(
        description=f" Acabou de ser commitado na {member.guild}! :space_invader:",
        color=discord.Color.blue()
    )
    embed.set_image(url="https://media.tenor.com/Qr56AbZspAoAAAAM/celebrate-futurama.gif")
    embed.set_author(name=member, icon_url=member.avatar.url)
    await channel.send(f"{member.mention}",embed=embed)