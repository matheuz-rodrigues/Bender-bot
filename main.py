from bot_instance import bot
from token_bot import TOKEN_BOT
from imports import *

@bot.event
async def on_ready():
    await bot.tree.sync()
    await bot.change_presence(activity=discord.Game(name=".ajuda"))
    print(f'Bot conectado como {bot.user}')

@bot.check
async def canais_autorizados(ctx):
    idsPermitidos = [1302789488866623488, 1303279261615915028, 1299532257408843867]
    if ctx.channel.id in idsPermitidos or ctx.author.id == 796471574827237436 or ctx.author.id == 534878109611065354:
        return True
    return False
#Evita o erro de console event.check que o bot gera ao executar a função canais_autorizados
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        return

@bot.command()
async def ajuda(ctx):
    file = discord.File(r"C:\Users\mathe\PycharmProjects\botDc\bender.png", filename="bender.png")
    embed = discord.Embed(
        title="Central de Ajuda - Comandos Disponíveis",
        description=f"Olá {ctx.author.mention}, aqui está a lista de comandos que você pode utilizar!",
        color=discord.Color.blue()
    )

    embed.set_image(url="attachment://bender.png")

    embed.add_field(
        name="🎮 **Minigames**",
        value=(
            "🔹 **.ppt [Pedra, Papel, Tesoura]**\n"
            "Jogue Pedra, Papel ou Tesoura comigo.\n\n"
            "🔹 **.coinflip [Cara ou Coroa]**\n"
            "Teste sua sorte com Cara ou Coroa.\n"
        ),
        inline=False
    )

    embed.add_field(
        name="🛠️ **Utilidades**",
        value=(
            "🔹 **.cotacao [Dólar, Euro, Iene, Libra, Franco, Bitcoin]**\n"
            "Veja a cotação das principais moedas ao redor do mundo."
        ),
        inline=False
    )

    embed.set_footer(text="Digite os comandos acima para interagir comigo!")

    await ctx.send(f"{ctx.author.mention}", embed=embed, file=file)


bot.run(TOKEN_BOT)

