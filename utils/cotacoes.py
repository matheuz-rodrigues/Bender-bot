from sys import breakpointhook
import requests
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










