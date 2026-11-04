"""Divulgação semiautomática do perfil nos subs de [For Hire].

O bot NÃO posta no Reddit (post automatizado de autopromoção dá ban/shadowban).
Ele avisa no canal quando já pode postar de novo em cada sub, entrega título e texto
prontos (com variações) e um botão que abre o Reddit com o título preenchido.
Você revisa, cola o texto e envia.

- Lembrete automático a cada `intervalo_dias` por sub (padrão 7).
- Botões: ✅ Postei / 🔁 Outra versão
- Slash commands: /divulgar agora <sub> | /portfolio <idioma>
"""

import random
import urllib.parse
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from bot_instance import bot
from utils.freelas import DONOS, PERFIL, config, _salvar_json, CONFIG_PATH

PADRAO = {
    "intervalo_dias": 7,
    "taxa": "$15/hr",
    "taxa_tarefa": "$20",
    "taxa_br": "R$ 50/h",
    "subs": [
        {"nome": "forhire", "modelo": "completo",
         "titulo": "[For Hire] Full-Stack Developer | Node.js/NestJS, React/Next.js, C#/.NET, Python scraping & automation | {taxa}"},
        {"nome": "B2BForHire", "modelo": "completo",
         "titulo": "[For Hire] Full-Stack Developer – web apps, REST APIs, automation & AI integrations | {taxa}"},
        {"nome": "slavelabour", "modelo": "tarefa",
         "titulo": "[OFFER] Python scraping, automations, bots and small web apps/APIs | from {taxa_tarefa} per task"},
    ],
}
for _k, _v in PADRAO.items():
    config.setdefault("divulgacao", {}).setdefault(_k, _v)
DIV = config["divulgacao"]

RODAPE = "divulgar:"  # usado para reconstruir o histórico a partir do canal depois de um deploy
ultimos = {}          # sub (minúsculo) -> datetime do último lembrete

# ---------------------------------------------------------------------------
# Textos (tudo verdadeiro, tirado dos currículos)
# ---------------------------------------------------------------------------
SERVICOS = [
    "**Web apps & dashboards** – React, Next.js, Tailwind CSS",
    "**REST APIs & backends** – Node.js (NestJS/Express), C#/ASP.NET, Python",
    "**Web scraping & automation** – Python (Selenium, BeautifulSoup, Requests), bots, scheduled jobs, ETL",
    "**AI integrations** – LLM APIs (Gemini/OpenAI), document reading, chatbots",
    "**Integrations & infra** – payments/webhooks, Google APIs, PostgreSQL, MySQL, SQL Server, MongoDB, Docker, AWS/Azure",
]
PROJETOS = [
    "Gym-management SaaS taken from zero to production in 3 months (Next.js + NestJS), with a Google Calendar integration that saves ~10h/week of admin work",
    "ArenaHub – SaaS for sports venues with AI invoice reading (Gemini) and automated PIX payments reconciled via webhooks",
    "Corporate C#/.NET system with 500+ active users, plus its migration to NestJS/Next.js with RabbitMQ messaging",
]
ABERTURAS = [
    "Hi! I'm Matheus, a full-stack developer from Brazil with production experience building SaaS products, REST APIs and automations.",
    "Hey there! I'm Matheus, a full-stack developer (Brazil, UTC-3) who ships production web apps, APIs and automation scripts.",
    "Hi, I'm Matheus – full-stack developer from Brazil. I build web apps, backends and automations that are already running in production.",
]
FECHAMENTOS = [
    "Send me a DM with what you need and I'll reply with an estimate the same day.",
    "DM me a short description of your project and I'll get back to you with a plan and a quote today.",
    "Got a project or a task you've been putting off? DM me and I'll send an estimate within a few hours.",
]


def _links():
    return f"LinkedIn: https://{PERFIL['linkedin']}\nGitHub: https://{PERFIL['github']}"


def gerar_post(sub_cfg):
    servicos = SERVICOS[:]
    random.shuffle(servicos)
    if sub_cfg.get("modelo") == "tarefa":
        corpo = (
            f"{random.choice(ABERTURAS)}\n\n"
            "**Tasks I can do quickly:**\n"
            "- Scrape a website into CSV/Excel/Google Sheets (Python)\n"
            "- Automate a repetitive task, report or spreadsheet\n"
            "- Discord/Telegram bots and small integrations (webhooks, APIs)\n"
            "- Fix bugs or add features in React, Node.js, Python or C#/.NET projects\n\n"
            f"**Price:** from {DIV['taxa_tarefa']} per task, fixed price agreed before I start.\n\n"
            f"{random.choice(FECHAMENTOS)}\n\n{_links()}"
        )
    else:
        projetos = PROJETOS[:]
        random.shuffle(projetos)
        corpo = (
            f"{random.choice(ABERTURAS)}\n\n"
            "**What I can do for you**\n" + "\n".join(f"- {s}" for s in servicos) + "\n\n"
            "**Recent work**\n" + "\n".join(f"- {p}" for p in projetos) + "\n\n"
            f"**Rate:** {DIV['taxa']}, or a fixed price per project (small tasks from $50). "
            "Clear communication in English and Portuguese, working hours that overlap with the US.\n\n"
            f"{random.choice(FECHAMENTOS)}\n\n{_links()}"
        )
    titulo = sub_cfg["titulo"].format(taxa=DIV["taxa"], taxa_tarefa=DIV["taxa_tarefa"])
    return titulo, corpo


def gerar_portfolio(idioma):
    if idioma == "PT":
        return (
            "Sou desenvolvedor Full Stack com sistemas em produção:\n"
            "- SaaS de gestão de academias levado do zero à produção em 3 meses (Next.js + NestJS), com integração ao Google Agenda que economiza ~10h por semana\n"
            "- ArenaHub: SaaS para arenas esportivas com leitura de nota fiscal por IA (Gemini) e PIX automático via webhook\n"
            "- Sistema corporativo em C#/.NET com mais de 500 usuários ativos, migrando para NestJS/Next.js com RabbitMQ\n\n"
            "Stack: Node.js, NestJS, React, Next.js, C#/.NET, Python (scraping e automação), PostgreSQL, MySQL, SQL Server, Docker, AWS e Azure.\n"
            f"Valor: {DIV['taxa_br']} ou preço fechado por projeto.\n\n"
            f"LinkedIn: {PERFIL['linkedin']}\nGitHub: {PERFIL['github']}"
        )
    if idioma == "ES":
        return (
            "Soy desarrollador Full Stack con sistemas en producción:\n"
            "- SaaS de gestión de gimnasios llevado de cero a producción en 3 meses (Next.js + NestJS), con integración a Google Calendar que ahorra ~10h por semana\n"
            "- ArenaHub: SaaS para canchas deportivas con lectura de facturas por IA (Gemini) y pagos automáticos vía webhooks\n"
            "- Sistema corporativo en C#/.NET con más de 500 usuarios activos\n\n"
            "Stack: Node.js, NestJS, React, Next.js, C#/.NET, Python (scraping y automatización), PostgreSQL, MySQL, SQL Server, Docker, AWS y Azure.\n"
            f"Tarifa: {DIV['taxa']} o precio cerrado por proyecto.\n\n"
            f"LinkedIn: {PERFIL['linkedin']}\nGitHub: {PERFIL['github']}"
        )
    return (
        "I'm a full-stack developer with systems running in production:\n"
        + "\n".join(f"- {p}" for p in PROJETOS) + "\n\n"
        "Stack: Node.js, NestJS, React, Next.js, C#/.NET, Python (scraping & automation), PostgreSQL, MySQL, SQL Server, Docker, AWS and Azure.\n"
        f"Rate: {DIV['taxa']} or a fixed price per project.\n\n"
        f"LinkedIn: {PERFIL['linkedin']}\nGitHub: {PERFIL['github']}"
    )

# ---------------------------------------------------------------------------
# Mensagem do lembrete
# ---------------------------------------------------------------------------
def _sub_cfg(nome):
    return next((s for s in DIV["subs"] if s["nome"].lower() == nome.lower()), None)


def montar_lembrete(sub_cfg):
    titulo, corpo = gerar_post(sub_cfg)
    url = (f"https://www.reddit.com/r/{sub_cfg['nome']}/submit?type=TEXT&"
           + urllib.parse.urlencode({"title": titulo}))
    embed = discord.Embed(
        title=f"📣 Hora de divulgar no r/{sub_cfg['nome']}",
        description=(
            "1. Clique em **Abrir no Reddit** (o título já vai preenchido)\n"
            "2. Copie o texto acima e cole no corpo do post\n"
            "3. Revise e envie. Depois clique em **✅ Postei**\n\n"
            f"**Título:**\n```\n{titulo}\n```"
            "Confira as regras do sub na barra lateral antes de postar."
        ),
        color=0xFF4500,
    )
    embed.set_footer(text=f"{RODAPE}{sub_cfg['nome']}")
    view = DivulgarView()
    view.add_item(discord.ui.Button(label="Abrir no Reddit", emoji="🔗", url=url[:512]))
    return f"```md\n{corpo}\n```", embed, view


class DivulgarView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction):
        if interaction.user.id not in DONOS:
            await interaction.response.send_message("Só o dono pode usar isso.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Postei", emoji="✅", style=discord.ButtonStyle.success, custom_id="divulgar:postei")
    async def postei(self, interaction, button):
        embed = interaction.message.embeds[0]
        embed.color = 0x2ECC71
        embed.title = embed.title.replace("📣 Hora de divulgar", "✅ Divulgado")
        sub = (embed.footer.text or "").split(":", 1)[-1].split(" ")[0]
        embed.set_footer(text=f"{RODAPE}{sub} • postado em {datetime.now():%d/%m %H:%M}")
        await interaction.response.edit_message(embed=embed)

    @discord.ui.button(label="Outra versão", emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="divulgar:outra")
    async def outra(self, interaction, button):
        embed = interaction.message.embeds[0]
        sub = (embed.footer.text or "").split(":", 1)[-1].split(" ")[0]
        cfg = _sub_cfg(sub)
        if cfg is None:
            await interaction.response.send_message("Esse sub não está mais na configuração.", ephemeral=True)
            return
        conteudo, novo_embed, view = montar_lembrete(cfg)
        await interaction.response.edit_message(content=conteudo, embed=novo_embed, view=view)

# ---------------------------------------------------------------------------
# Loop de lembretes
# ---------------------------------------------------------------------------
async def _enviar_lembrete(sub_cfg):
    canal = bot.get_channel(config.get("canal_id", 0))
    if canal is None:
        return False
    conteudo, embed, view = montar_lembrete(sub_cfg)
    await canal.send(content=conteudo, embed=embed, view=view)
    ultimos[sub_cfg["nome"].lower()] = datetime.now(timezone.utc)
    return True


async def _recuperar_historico():
    canal = bot.get_channel(config.get("canal_id", 0))
    if canal is None:
        return
    try:
        async for msg in canal.history(limit=1000):
            if msg.author.id != bot.user.id:
                continue
            for emb in msg.embeds:
                rodape = (emb.footer.text or "") if emb.footer else ""
                if rodape.startswith(RODAPE):
                    sub = rodape[len(RODAPE):].split(" ")[0].lower()
                    if sub not in ultimos or msg.created_at > ultimos[sub]:
                        ultimos[sub] = msg.created_at
    except discord.HTTPException as e:
        print(f"[divulgar] não consegui ler o histórico: {e}")


@tasks.loop(minutes=30)
async def lembretes():
    agora = datetime.now(timezone.utc)
    intervalo = timedelta(days=DIV.get("intervalo_dias", 7))
    for sub_cfg in DIV["subs"]:
        ultimo = ultimos.get(sub_cfg["nome"].lower())
        if ultimo is None or agora - ultimo >= intervalo:
            await _enviar_lembrete(sub_cfg)


@lembretes.before_loop
async def _antes():
    await bot.wait_until_ready()
    await _recuperar_historico()


@bot.listen("on_ready")
async def _iniciar():
    bot.add_view(DivulgarView())
    if not lembretes.is_running():
        lembretes.start()

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------
grupo = app_commands.Group(name="divulgar", description="Divulgação do seu perfil nos subs de For Hire")


async def _subs_autocomplete(interaction, atual):
    return [app_commands.Choice(name=f"r/{s['nome']}", value=s["nome"])
            for s in DIV["subs"] if atual.lower() in s["nome"].lower()][:25]


@grupo.command(name="agora", description="Gera agora o post pronto para um sub")
@app_commands.describe(sub="Subreddit")
@app_commands.autocomplete(sub=_subs_autocomplete)
async def cmd_agora(interaction: discord.Interaction, sub: str):
    if interaction.user.id not in DONOS:
        await interaction.response.send_message("Só o dono pode usar isso.", ephemeral=True)
        return
    cfg = _sub_cfg(sub)
    if cfg is None:
        await interaction.response.send_message("Sub não configurado.", ephemeral=True)
        return
    ok = await _enviar_lembrete(cfg)
    await interaction.response.send_message(
        "📣 Post pronto no canal de freelas." if ok else "Canal não configurado (/freelas aqui).", ephemeral=True)


@grupo.command(name="taxa", description="Muda o seu valor por hora no post (ex.: $20/hr)")
@app_commands.describe(valor="Ex.: $15/hr, $20/hr")
async def cmd_taxa(interaction: discord.Interaction, valor: str):
    if interaction.user.id not in DONOS:
        await interaction.response.send_message("Só o dono pode usar isso.", ephemeral=True)
        return
    DIV["taxa"] = valor.strip()
    _salvar_json(CONFIG_PATH, config)
    await interaction.response.send_message(
        f"💲 Taxa agora é **{DIV['taxa']}** (até o próximo deploy; para fixar, mude no freelas_config.json).",
        ephemeral=True)


bot.tree.add_command(grupo)


@bot.tree.command(name="portfolio", description="Gera seu resumo de portfólio para colar numa resposta")
@app_commands.describe(idioma="Idioma do texto")
@app_commands.choices(idioma=[
    app_commands.Choice(name="Português", value="PT"),
    app_commands.Choice(name="English", value="EN"),
    app_commands.Choice(name="Español", value="ES"),
])
async def cmd_portfolio(interaction: discord.Interaction, idioma: app_commands.Choice[str]):
    await interaction.response.send_message(f"```md\n{gerar_portfolio(idioma.value)}\n```", ephemeral=True)
