from bot_instance import bot
from random import randint

@bot.command()
async def ppt(ctx, escolha: str = None):

    opcoes = ["pedra", "papel", "tesoura"]
    minhaEscolha = opcoes[randint(0, 2)]

    if escolha is None:
        await ctx.send("Digite **.ppt pedra, papel ou tesoura** para jogar comigo.")
        return
    elif escolha.lower() not in opcoes:
        await ctx.send("Opção Inválida, tente novamente.")
        return
    elif escolha.lower() == minhaEscolha:
        await ctx.send("Bom jogo, infelizmente empatamos!")
        #Caos que o bot perde
    elif escolha.lower() == "pedra" and minhaEscolha == "tesoura" \
    or escolha.lower() == "papel" and minhaEscolha == "pedra"\
    or escolha.lower() == "tesoura" and minhaEscolha == "papel":
        await ctx.send(f"Eu escolhi {minhaEscolha.capitalize()} e você {escolha.capitalize()}, parabéns pela Vitória.")
    else: await ctx.send(F"Eu escolhi {minhaEscolha.capitalize()} e você {escolha.capitalize()}, tenta na próxima otário.")


