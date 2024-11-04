from bot_instance import bot
from minigames.ppt import ppt
from token_bot import TOKEN_BOT

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')

bot.run(TOKEN_BOT)

