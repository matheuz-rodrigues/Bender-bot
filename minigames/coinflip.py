from bot_instance import bot
from random import choice
from time import sleep

@bot.command()
async def coinflip(ctx, escolha: str = None):

    if(escolha is None):
        await ctx.send("**.coinflip + sua escolha(cara,coroa)**")
    if(escolha.lower() == "cara" or escolha.lower() == "coroa"):
        await ctx.send(f"A moeda foi lançada...")
        sleep(2)
        moeda = choice(["cara", "coroa"])
        if(moeda == escolha.lower()):
            await ctx.send(f"Resultado: **{moeda} **Você venceu!**")
        else:
            await ctx.send(f"Resultado: **{moeda} Voce perdeu!**")
    else:
        await ctx.send("Opção Inválida, tente novamente.")
