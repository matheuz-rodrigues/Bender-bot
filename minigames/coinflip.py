from bot_instance import bot
import discord
from discord import app_commands
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

@bot.tree.command(name='coinflip', description="Jogue Cara ou Coroa comigo")
@app_commands.describe(escolha="Escolha entre cara ou coroa")
async def coinflip(interaction: discord.Interaction, escolha: str = None):
    if escolha is None:
        await interaction.response.send_message("Use **/coinflip** seguido de sua escolha (cara ou coroa).", ephemeral=True)
        return

    escolha = escolha.lower()
    if escolha in ["cara", "coroa"]:
        await interaction.response.send_message("A moeda foi lançada...")
        sleep(2)

        moeda = choice(["cara", "coroa"])

        if moeda == escolha:
            await interaction.followup.send(f"Resultado: **{moeda.capitalize()}**. Você venceu!")
        else:
            await interaction.followup.send(f"Resultado: **{moeda.capitalize()}**. Você perdeu!")
    else:
        await interaction.response.send_message("Opção inválida. Tente novamente com 'cara' ou 'coroa'.", ephemeral=True)

