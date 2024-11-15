from bot_instance import bot


@bot.command()
async def clear(ctx, amount: int= None):
    # Limita a quantidade de mensagens a apagar

    if amount is None:
        await ctx.send("Por favor, especifique um número válido de mensagens para apagar (mínimo 1).")
        return
    elif amount < 1:
        await ctx.send("Por favor, especifique um número válido de mensagens para apagar (mínimo 1).")
        return
    else:
        if (ctx.author.guild_permissions.administrator == True):
           await ctx.channel.purge(limit=amount+1)
        else: await ctx.send(f"{ctx.author.mention}, você não tem permissão para executar esse comando, trouxa.")