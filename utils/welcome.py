from  bot_instance import bot
import discord

@bot.event
async def on_member_join(ctx):
    channel_id = 1293004888716087298
    await bot.get_channel(channel_id).send(f"{ctx.mention} acabou de ser commitado na {ctx.guild}! :space_invader:")