import requests
import discord
from discord import app_commands
from bot_instance import bot

@bot.command()
async def cotacao(ctx, moeda: str = None):

    moedasPossiveis = {"euro" : "EUR-BRL",
                       "dolar": "USD-BRL",
                       "franco": "CHF-BRL",
                       "libra": "GBP-BRL",
                       "bitcoin": "BTC-BRL",
                       "iene": "JPY-BRL"}
    if moeda is None:
        await ctx.send("Use **.cotacao 'moeda'**, para ver a cotação. "
                       "Por hora eu sei a cotação atualizada das 5 maiores moedas do mundo e do **Bitcoin**, sendo elas "
                       "**Dólar, Euro, Iene, Libra e Franco**")
    else:
        moeda = moeda.lower()
        moeda = moeda.replace("ó", "o")
        tipo = ""
        for chave in moedasPossiveis:
            if chave == moeda:
                tipo = moedasPossiveis[chave]
        #if usa como base o ultimo item do dicionario
        if chave == "iene"  and tipo == "":
          await ctx.send("Moeda Iválida, por favor tente novamente.")
        else:
            url = "https://economia.awesomeapi.com.br/json/last/" + tipo
            response = requests.get(url)
            dados = response.json()
            convertido = float(dados[tipo.replace("-", "")]["bid"])
            await ctx.send(f"Na conversão {dados[tipo.replace("-", "")]['name']}. O {dados[tipo.replace("-", "")]['code']} está valendo R${convertido:.2f}")

@bot.tree.command(name="cotações", description="Use esse comando para saber o valor das moedas ao redor do mundo")
@app_commands.describe(moeda="Escolha ver a cotação atualizada do Bitcoin, Dólar, Euro, Iene, Libra ou Franco")
async def cotacao(interaction: discord.Interaction, moeda: str = None):

    moedasPossiveis = {"euro" : "EUR-BRL",
                       "dolar": "USD-BRL",
                       "franco": "CHF-BRL",
                       "libra": "GBP-BRL",
                       "bitcoin": "BTC-BRL",
                       "iene": "JPY-BRL"}
    if moeda is None:
        await interaction.response.send_message("Use **.cotacao 'moeda'**, para ver a cotação. "
                       "Por hora eu sei a cotação atualizada das 5 maiores moedas do mundo e do **Bitcoin**, sendo elas "
                       "**Dólar, Euro, Iene, Libra e Franco**")
    else:
        moeda = moeda.lower()
        moeda = moeda.replace("ó", "o")
        tipo = ""
        for chave in moedasPossiveis:
            if chave == moeda:
                tipo = moedasPossiveis[chave]
        #if usa como base o ultimo item do dicionario
        if chave == "iene"  and tipo == "":
          await interaction.response.send_message("Moeda Iválida, por favor tente novamente.")
        else:
            url = "https://economia.awesomeapi.com.br/json/last/" + tipo
            response = requests.get(url)
            dados = response.json()
            convertido = float(dados[tipo.replace("-", "")]["bid"])
            await interaction.response.send_message(f"Na conversão {dados[tipo.replace("-", "")]['name']}. O {dados[tipo.replace("-", "")]['code']} está valendo R${convertido:.2f}")