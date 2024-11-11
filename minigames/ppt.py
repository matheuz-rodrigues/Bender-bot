import discord
from discord import app_commands
from bot_instance import bot
from random import randint

@bot.tree.command(name="ppt", description="Jogar Pedra, Papel ou Tesoura")
@app_commands.describe(escolha="Escolha entre pedra, papel ou tesoura")
async def ppt(interaction: discord.Interaction, escolha: str = None):
    opcoes = ["pedra", "papel", "tesoura"]
    minhaEscolha = opcoes[randint(0, 2)]

    if escolha is None:
        await interaction.response.send_message("Use **/ppt** seguido de sua escolha (pedra, papel ou tesoura) para jogar.", ephemeral=True)
        return

    escolha = escolha.lower()
    if escolha not in opcoes:
        await interaction.response.send_message("Opção inválida, tente novamente com 'pedra', 'papel' ou 'tesoura'.", ephemeral=True)
        return

    if escolha == minhaEscolha:
        await interaction.response.send_message("Bom jogo, infelizmente empatamos!")
    elif (escolha == "pedra" and minhaEscolha == "tesoura") or \
         (escolha == "papel" and minhaEscolha == "pedra") or \
         (escolha == "tesoura" and minhaEscolha == "papel"):
        await interaction.response.send_message(f"Eu escolhi {minhaEscolha.capitalize()} e você {escolha.capitalize()}. Parabéns pela vitória!")
    else:
        await interaction.response.send_message(f"Eu escolhi {minhaEscolha.capitalize()} e você {escolha.capitalize()}. Tenta na próxima, otário.")

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
