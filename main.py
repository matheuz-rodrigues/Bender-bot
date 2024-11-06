from bot_instance import bot
from minigames.ppt import ppt
from minigames import coinflip
from utils import cotacoes
from utils import welcome
from token_bot import TOKEN_BOT

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')



@bot.command()
async def ajuda(ctx):
    nome = ctx.author
    await  ctx.send(f"""Olá {nome.mention}, aqui está uma lista de comandos que você pode utilizar.\n
    **MINIGAMES**
    .ppt [Pedra, Papel, Tesoura] -> Jogue Pedra ou Papel ou Tesoura
    .coinflip [Cara ou Coroa] -> Jogue Cara ou Coroa""")

bot.run(TOKEN_BOT)

