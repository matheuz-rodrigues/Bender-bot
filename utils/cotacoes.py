import requests
import discord
from discord import app_commands
from bot_instance import bot

@bot.command()
async def cotacao(ctx, quantidade: str = None, moeda: str = None):

    moedasPossiveis = {"euro" : "EUR-BRL",
                       "dolar": "USD-BRL",
                       "franco": "CHF-BRL",
                       "libra": "GBP-BRL",
                       "bitcoin": "BTC-BRL",
                       "iene": "JPY-BRL"}

    if moeda is None:
        await ctx.send("Use **.cotacao 'quantidade' 'moeda'**, para fazer a conversão. "
                       "Por hora eu sei a cotação atualizada das 5 maiores moedas do mundo e do **Bitcoin**, sendo elas "
                       "**Dólar, Euro, Iene, Libra e Franco**", ephemeral=True)
    #elif quantidade != float:

    else:
        moeda = moeda.lower()
        moeda = moeda.replace("ó", "o")
        tipo = ""
        for chave in moedasPossiveis:
            if chave == moeda:
                tipo = moedasPossiveis[chave]

        #if usa como base o ultimo item do dicionario
        if chave == "iene"  and tipo == "":
          await ctx.send("Moeda Iválida, por favor tente novamente.", ephemeral=True)
        else:
            url = "https://economia.awesomeapi.com.br/json/last/" + tipo
            response = requests.get(url)
            dados = response.json()
            tipo = tipo.replace("-", "")
            convertido = float(dados[tipo]["bid"])
            nomemoeda = dados[tipo]['name']
            codigomoeda = dados[tipo]['code']
            quantidade = quantidade.replace(",", ".")
            valorreal = convertido*float(quantidade)
            await ctx.send(f"Na conversão {nomemoeda}. {quantidade} {codigomoeda} estão valendo R${valorreal:,.2f}")



@bot.tree.command(name="cotações", description="Use esse comando para saber o valor das moedas ao redor do mundo")
@app_commands.describe(quantidade= "Digite o número de reais que você quer converter", moeda="Escolha ver a cotação atualizada do Bitcoin, Dólar, Euro, Iene, Libra ou Franco")
async def cotacao(interaction: discord.Interaction, quantidade: str = None, moeda: str = None):

    moedasPossiveis = {"euro" : "EUR-BRL",
                       "dolar": "USD-BRL",
                       "franco": "CHF-BRL",
                       "libra": "GBP-BRL",
                       "bitcoin": "BTC-BRL",
                       "iene": "JPY-BRL"}
    if moeda is None:
        await interaction.response.send_message("Use **/cotacao 'Quantidade' 'Moeda'**, para fazer a conversão. "
                       "Por hora eu sei a cotação atualizada das 5 maiores moedas do mundo e do **Bitcoin**, sendo elas "
                       "**Dólar, Euro, Iene, Libra e Franco**", ephemeral=True)
    else:
        moeda = moeda.lower()
        moeda = moeda.replace("ó", "o")
        tipo = ""
        for chave in moedasPossiveis:
            if chave == moeda:
                tipo = moedasPossiveis[chave]
        #if usa como base o ultimo item do dicionario
        if chave == "iene"  and tipo == "":
          await interaction.response.send_message("Moeda Iválida, por favor tente novamente.", ephemeral=True)
        else:
            url = "https://economia.awesomeapi.com.br/json/last/" + tipo
            response = requests.get(url)
            dados = response.json()
            tipo = tipo.replace("-", "")
            convertido = float(dados[tipo]["bid"])
            nomemoeda = dados[tipo]['name']
            codigomoeda = dados[tipo]['code']
            valorreal = convertido * float(quantidade.replace(",", "."))
            await interaction.response.send_message(f"Na conversão {nomemoeda}. {quantidade} {codigomoeda} estão valendo R${valorreal:,.2f}")