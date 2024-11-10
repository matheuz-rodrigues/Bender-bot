from bot_instance import bot
from bot_instance import discord
import datetime

@bot.command()
async def regras(ctx):
    if ctx.author.id == 796471574827237436 or ctx.author.id == 534878109611065354:
        await ctx.message.delete()
        embed = discord.Embed(
            title="📌 REGRAS 📌",
            description="""
            Bem-vindo(a) ao nosso servidor! Para garantir que todos tenham uma experiência agradável e produtiva, por favor, siga estas regras:
            
            **1.Respeito Mútuo**
            Trate todos os membros com respeito. Discriminação, assédio, ofensas ou comportamento tóxico não serão tolerados.
            
            **2.Sem Spam**
            Evite enviar mensagens repetidas, links irrelevantes ou promoções não autorizadas. O spam prejudica a comunicação e a experiência de todos.
            
            **3.Conteúdo Adequado**
            Compartilhe apenas conteúdo apropriado. Isso inclui textos, imagens, vídeos e links.
            
            **4.Canais e Temas**
            Utilize os canais para os propósitos apropriados. Mantenha as discussões dentro dos tópicos designados e evite desviar o assunto.
            
            **5.Privacidade e Segurança**
            Não compartilhe informações pessoais, tanto suas quanto de outros membros. Respeite a privacidade de todos.
            
            **6.Pirataria**
            Compartilhamento de conteúdo pirata é permitido.
            
            **7.Colaboração e Ajuda**
            Este é um espaço para aprendizado e crescimento. Ajude os outros membros, compartilhe conhecimento e colabore em projetos sempre que possível.
            
            **8.Siga as Diretrizes do Discord**
            Todas as regras e diretrizes do Discord devem ser seguidas. Qualquer violação pode resultar em ações disciplinares.
            
            
            **Divirta-se!**
            Este é um espaço para aprender e compartilhar. Aproveite a sua estadia e faça novas amizades! """,
                        color=discord.Color.blue()

        )
        embed.set_image(url="https://media1.tenor.com/m/9_FwJGoFUM4AAAAd/agora-eu-entendi-agora-eu-saquei.gif")
        await ctx.send(embed=embed)

