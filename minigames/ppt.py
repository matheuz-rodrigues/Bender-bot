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
