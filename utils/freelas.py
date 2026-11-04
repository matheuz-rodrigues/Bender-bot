"""Radar de freelas: monitora o Reddit e posta no Discord as vagas que batem com o currículo.

- Lê o RSS público dos subreddits (uma requisição para todos, sem API key).
- Dá uma nota para cada post com base nas habilidades do currículo (pesos abaixo).
- Posta um card com nota, skills que bateram, orçamento detectado e idioma.
- Botões: ⭐ Interessa / 🗑️ Ignorar / ✍️ Rascunho (gera uma proposta em PT ou EN).
- Slash commands: /freelas aqui | status | agora | pausar | retomar | nota_minima
"""

import asyncio
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import discord
import requests
from discord import app_commands
from discord.ext import tasks

from bot_instance import bot

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "freelas_config.json")
STATE_PATH = os.path.join(BASE_DIR, "freelas_vistos.json")
DONOS = {796471574827237436, 534878109611065354}
ATOM = "{http://www.w3.org/2005/Atom}"
USER_AGENT = "python:bender-freela-radar:1.0 (personal RSS reader)"
MAX_VISTOS = 3000

# ---------------------------------------------------------------------------
# Perfil (tirado dos currículos em Desktop/curriculos)
# peso 3 = stack principal | 2 = forte | 1 = complementar
# ---------------------------------------------------------------------------
HABILIDADES = [
    # rótulo, peso, padrões (regex, sem diferenciar maiúsculas)
    ("Node.js", 3, [r"node(\.?js)?"]),
    ("NestJS", 3, [r"nest(\.?js)?"]),
    ("Express", 2, [r"express(\.?js)?"]),
    ("TypeScript", 3, [r"typescript", r"\bts\b"]),
    ("JavaScript", 2, [r"javascript", r"vanilla js"]),
    ("React", 3, [r"react(\.?js)?"]),
    ("Next.js", 3, [r"next\.?js"]),
    ("C#", 3, [r"c#", r"csharp"]),
    (".NET", 3, [r"\.net\b", r"dotnet", r"asp\.net"]),
    ("Python", 3, [r"python"]),
    ("API REST", 3, [r"\bapis?\b", r"rest(ful)?\s*api", r"backend", r"back-end"]),
    ("Full Stack", 2, [r"full[\s-]?stack"]),
    ("Web scraping", 3, [r"scrap(er|ing|e)", r"crawler", r"selenium", r"beautiful\s?soup", r"playwright", r"puppeteer"]),
    ("Automação", 3, [r"automa(tion|te|ção|cao|tizar)", r"\bbot\b", r"\bbots\b", r"zapier", r"n8n"]),
    ("ETL / Dados", 2, [r"\betl\b", r"data pipeline", r"pipeline de dados", r"data entry", r"planilha", r"spreadsheet"]),
    ("IA / LLM", 3, [r"\bllms?\b", r"openai", r"chatgpt", r"\bgpt\b", r"gemini", r"claude", r"chatbot", r"\bai agent", r"agente de ia", r"\brag\b"]),
    ("SaaS", 2, [r"\bsaas\b", r"mvp", r"web app", r"web application", r"aplica(ção|cao) web", r"sistema web"]),
    ("Integrações", 2, [r"integra(tion|te|ção|cao)", r"webhooks?", r"stripe", r"asaas", r"\bpix\b", r"google calendar", r"google sheets"]),
    ("PostgreSQL", 2, [r"postgres(ql)?"]),
    ("MySQL", 2, [r"mysql"]),
    ("SQL Server", 2, [r"sql server", r"mssql", r"\bsql\b"]),
    ("MongoDB", 2, [r"mongo(db)?"]),
    ("Prisma", 1, [r"prisma"]),
    ("Docker", 2, [r"docker", r"container"]),
    ("AWS", 2, [r"\baws\b", r"lambda", r"\bs3\b", r"\bec2\b"]),
    ("Azure", 2, [r"azure"]),
    ("RabbitMQ", 2, [r"rabbitmq", r"message queue", r"mensageria"]),
    ("Tailwind", 1, [r"tailwind"]),
    ("Angular", 1, [r"angular"]),
    ("Java / Spring", 1, [r"\bjava\b", r"spring\s?boot"]),
    ("Testes / QA", 1, [r"\bqa\b", r"jest", r"unit tests?", r"testes?", r"cypress"]),
    ("Linux / DevOps", 1, [r"linux", r"ci/cd", r"devops", r"\bvps\b", r"deploy"]),
    ("Dashboard", 1, [r"dashboard", r"painel", r"admin panel"]),
    ("Landing page / site", 1, [r"landing page", r"website", r"\bsite\b"]),
]
_HAB_RX = [(r, p, re.compile("|".join(f"(?<![\\w]){x}(?![\\w])" for x in pats), re.I))
           for r, p, pats in HABILIDADES]

# Sinais de que NÃO é pra você (fora da stack ou sem pagamento)
EXCLUIR = re.compile(
    r"\[\s*for\s*hire\s*\]|\bunpaid\b|equity only|rev(enue)?\s*share|\bfor exposure\b|"
    r"\bvoluntário\b|sem remunera|\bwordpress\b|\bshopify\b|\bwix\b|\bunity\b|\bunreal\b|"
    r"\bvideo edit|\bthumbnail|\bvoice ?over|\bugc\b|\bcontent creator|\bcopywrit|"
    r"\bseo\b|\bsocial media manager|\bgraphic design|\blogo design|\billustrat",
    re.I,
)

ORCAMENTO = re.compile(
    r"(?:US\$|R\$|\$|€|£|USD\s?)\s?\d[\d.,]*\s?k?"
    r"(?:\s?(?:-|–|to|a|até)\s?(?:US\$|R\$|\$|€|£)?\s?\d[\d.,]*\s?k?)?"
    r"(?:\s?(?:/|per\s|por\s)\s?(?:h|hr|hour|hora|mo|month|mês|week|semana|project|projeto))?",
    re.I,
)

PADRAO_CONFIG = {
    "canal_id": 0,
    "mencao": "",
    "intervalo_segundos": 300,
    "nota_minima": 3,
    "subreddits": [
        {"nome": "forhire", "titulo": r"\[\s*hiring\s*\]"},
        {"nome": "freelance_forhire", "titulo": r"\[\s*hiring\s*\]"},
        {"nome": "hiring", "titulo": r"\[\s*hiring\s*\]"},
        {"nome": "jobbit", "titulo": r"\[\s*hiring\s*\]"},
        {"nome": "slavelabour", "titulo": r"\[\s*task\s*\]"},
        {"nome": "RemoteJobs", "titulo": r"\[\s*hiring\s*\]|\bfreelance\b|\bcontract(or)?\b|\bpart[- ]time\b"},
        {"nome": "brdev", "titulo": r"\bfreela\b|\bcontrat(o|a|ando|ar)\b|\b(procuro|procura-se|preciso de|buscando)\s+(um\s+|uma\s+)?(dev|desenvolvedor|desenvolvedora|programador|programadora)\b|\bor[cç]amento\b|\bprojeto pago\b|\[\s*(vaga|freela)\s*\]"},
    ],
}

PERFIL = {
    "github": "github.com/matheuz-rodrigues",
    "linkedin": "linkedin.com/in/matheuz-rodrigues-dev",
}

# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
estado = {"ultima": None, "erro": None, "enviados": 0, "pausado": False, "analisados": 0}


def _ler_json(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def _salvar_json(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def carregar_config():
    cfg = _ler_json(CONFIG_PATH, None)
    if cfg is None:
        cfg = json.loads(json.dumps(PADRAO_CONFIG))
        _salvar_json(CONFIG_PATH, cfg)
    return cfg


config = carregar_config()
vistos = _ler_json(STATE_PATH, {})

# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------
def _limpar_html(texto):
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    texto = re.sub(r"\s+", " ", html.unescape(texto)).strip()
    return re.sub(r"submitted by .*$", "", texto).strip()


def _baixar_feed(subs):
    url = f"https://www.reddit.com/r/{'+'.join(subs)}/new/.rss?limit=100"
    for tentativa in range(4):
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        if r.status_code == 429 and tentativa < 3:
            time.sleep(15 * (tentativa + 1))
            continue
        r.raise_for_status()
        break
    raiz = ET.fromstring(r.content)
    posts = []
    for e in raiz.findall(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link")
        autor = e.find(f"{ATOM}author/{ATOM}name")
        cat = e.find(f"{ATOM}category")
        posts.append({
            "id": e.findtext(f"{ATOM}id", ""),
            "titulo": html.unescape(e.findtext(f"{ATOM}title", "")),
            "url": link.get("href") if link is not None else "",
            "autor": (autor.text or "?").removeprefix("/u/") if autor is not None else "?",
            "texto": _limpar_html(e.findtext(f"{ATOM}content", "")),
            "data": e.findtext(f"{ATOM}published", "") or e.findtext(f"{ATOM}updated", ""),
            "sub": cat.get("term", "?") if cat is not None else "?",
        })
    return posts

# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------
def analisar(post):
    """Retorna dict com nota/skills, ou None se o post não serve."""
    subcfg = next((s for s in config["subreddits"] if s["nome"].lower() == post["sub"].lower()), None)
    if subcfg and subcfg.get("titulo") and not re.search(subcfg["titulo"], post["titulo"], re.I):
        return None
    texto = f"{post['titulo']} {post['texto']}"
    if EXCLUIR.search(texto):
        return None

    skills = [(rotulo, peso) for rotulo, peso, rx in _HAB_RX if rx.search(texto)]
    # Skills no título valem o dobro: é o que o cliente mais quer
    titulo_hits = {rotulo for rotulo, _, rx in _HAB_RX if rx.search(post["titulo"])}
    pontos = sum(p * (2 if r in titulo_hits else 1) for r, p in skills)
    if pontos < config.get("nota_minima", 3):
        return None

    orc = ORCAMENTO.search(texto)
    return {
        "pontos": pontos,
        "estrelas": max(1, min(5, round(pontos / 3))),
        "skills": [r for r, _ in sorted(skills, key=lambda s: -s[1])],
        "orcamento": orc.group(0).strip(" ,.;") if orc else None,
        "idioma": detectar_idioma(post),
    }


def detectar_idioma(post):
    if post["sub"].lower() == "brdev":
        return "PT"
    t = f" {post['titulo']} {post['texto']} ".lower()
    pt = sum(t.count(w) for w in (" de ", " para ", " que ", " com ", "ção", " você", " preciso", " um ", " uma "))
    en = sum(t.count(w) for w in (" the ", " and ", " for ", " with ", " you ", " need ", " looking ", " we "))
    return "PT" if pt > en else "EN"


def montar_embed(post, a):
    cores = {5: 0x2ECC71, 4: 0x2ECC71, 3: 0xF1C40F, 2: 0xE67E22, 1: 0x95A5A6}
    texto = post["texto"]
    if len(texto) > 700:
        texto = texto[:700].rsplit(" ", 1)[0] + "…"
    e = discord.Embed(
        title=post["titulo"][:256],
        url=post["url"],
        description=texto or "_(sem texto)_",
        color=cores[a["estrelas"]],
    )
    e.set_author(name=f"r/{post['sub']} • u/{post['autor']}")
    e.add_field(name="Match", value=f"{'★' * a['estrelas']}{'☆' * (5 - a['estrelas'])}  ({a['pontos']} pts)", inline=True)
    e.add_field(name="Orçamento", value=a["orcamento"] or "não informado", inline=True)
    e.add_field(name="Idioma", value="🇧🇷 PT" if a["idioma"] == "PT" else "🇺🇸 EN", inline=True)
    e.add_field(name="Suas skills que batem", value=", ".join(a["skills"][:12])[:1024], inline=False)
    e.set_footer(text="Radar de freelas • responda rápido, quem chega primeiro leva")
    if post["data"]:
        try:
            e.timestamp = datetime.fromisoformat(post["data"].replace("Z", "+00:00"))
        except ValueError:
            pass
    return e


def gerar_rascunho(titulo, skills, idioma):
    principais = ", ".join(skills[:4]) or "desenvolvimento web"
    if idioma == "PT":
        return (
            f"Olá! Vi seu post \"{titulo[:80]}\" e acho que consigo ajudar.\n\n"
            f"Sou desenvolvedor Full Stack e trabalho no dia a dia com {principais}. "
            "Tenho sistemas em produção: um SaaS de gestão de academias que levei do zero à produção em 3 meses "
            "(Next.js + NestJS) e o ArenaHub, plataforma com integração de IA (Gemini) e PIX automático via webhook. "
            "Também atendo sistemas corporativos em C#/.NET com mais de 500 usuários ativos.\n\n"
            "Para o seu caso, eu começaria por [ESCREVA AQUI 1 FRASE SOBRE O PROBLEMA DELE].\n\n"
            "Posso te mandar uma estimativa de prazo e valor ainda hoje. Podemos conversar por DM?\n\n"
            f"GitHub: {PERFIL['github']}\nLinkedIn: {PERFIL['linkedin']}"
        )
    return (
        f"Hi! I saw your post \"{titulo[:80]}\" and I think I can help.\n\n"
        f"I'm a full-stack developer working daily with {principais}. "
        "I have shipped production systems: a gym-management SaaS I took from zero to production in 3 months "
        "(Next.js + NestJS), and ArenaHub, a platform with AI integration (Gemini) and automated payments via webhooks. "
        "I also maintain a C#/.NET corporate system with 500+ active users.\n\n"
        "For your project, I'd start by [WRITE 1 SENTENCE ABOUT THEIR SPECIFIC PROBLEM].\n\n"
        "Happy to send a time and cost estimate today. Can we chat in DM?\n\n"
        f"GitHub: {PERFIL['github']}\nLinkedIn: {PERFIL['linkedin']}"
    )

# ---------------------------------------------------------------------------
# Botões (persistentes: continuam funcionando depois de reiniciar o bot)
# ---------------------------------------------------------------------------
def _campo(embed, nome):
    return next((f.value for f in embed.fields if f.name == nome), "")


class FreelaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction):
        if interaction.user.id not in DONOS:
            await interaction.response.send_message("Esses botões são só pro dono do radar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Interessa", emoji="⭐", style=discord.ButtonStyle.success, custom_id="freela:interessa")
    async def interessa(self, interaction, button):
        embed = interaction.message.embeds[0]
        embed.color = 0x5865F2
        embed.set_footer(text=f"⭐ Marcado por {interaction.user.display_name} • {datetime.now():%d/%m %H:%M}")
        await interaction.response.edit_message(embed=embed)
        try:
            await interaction.message.pin(reason="Freela marcado como interessante")
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Ignorar", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id="freela:ignorar")
    async def ignorar(self, interaction, button):
        await interaction.message.delete()

    @discord.ui.button(label="Rascunho", emoji="✍️", style=discord.ButtonStyle.primary, custom_id="freela:rascunho")
    async def rascunho(self, interaction, button):
        embed = interaction.message.embeds[0]
        idioma = "PT" if "PT" in _campo(embed, "Idioma") else "EN"
        skills = [s.strip() for s in _campo(embed, "Suas skills que batem").split(",") if s.strip()]
        texto = gerar_rascunho(embed.title or "", skills, idioma)
        await interaction.response.send_message(
            f"Rascunho ({idioma}). Personalize a parte entre colchetes antes de enviar:\n```\n{texto}\n```\n🔗 {embed.url}",
            ephemeral=True,
        )

# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------
async def checar(forcar_envio=False):
    canal = bot.get_channel(config.get("canal_id", 0))
    if canal is None:
        estado["erro"] = "Canal não configurado. Use /freelas aqui no canal desejado."
        return 0

    primeira_vez = not vistos and not forcar_envio
    try:
        posts = await asyncio.to_thread(_baixar_feed, [s["nome"] for s in config["subreddits"]])
    except Exception as e:
        estado["erro"] = f"{type(e).__name__}: {e}"[:300]
        print(f"[freelas] erro ao ler Reddit: {estado['erro']}")
        return 0

    estado["erro"] = None
    estado["ultima"] = datetime.now(timezone.utc)
    enviados = 0
    for post in sorted(posts, key=lambda p: p["data"]):
        if post["id"] in vistos:
            continue
        vistos[post["id"]] = int(time.time())
        estado["analisados"] += 1
        a = analisar(post)
        if a is None or primeira_vez:
            continue
        await canal.send(content=config.get("mencao") or None, embed=montar_embed(post, a), view=FreelaView())
        enviados += 1
        await asyncio.sleep(1)

    if len(vistos) > MAX_VISTOS:
        for k in sorted(vistos, key=vistos.get)[: len(vistos) - MAX_VISTOS]:
            del vistos[k]
    _salvar_json(STATE_PATH, vistos)
    estado["enviados"] += enviados
    if primeira_vez:
        print(f"[freelas] primeira execução: {len(vistos)} posts marcados como vistos.")
    return enviados


@tasks.loop(seconds=300)
async def radar():
    if not estado["pausado"]:
        await checar()


@radar.before_loop
async def _antes():
    await bot.wait_until_ready()


@bot.listen("on_ready")
async def _iniciar_radar():
    bot.add_view(FreelaView())
    if not radar.is_running():
        radar.change_interval(seconds=max(60, int(config.get("intervalo_segundos", 300))))
        radar.start()

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------
grupo = app_commands.Group(name="freelas", description="Radar de freelas do Reddit")


async def _so_dono(interaction):
    if interaction.user.id not in DONOS:
        await interaction.response.send_message("Só o dono do radar pode usar isso.", ephemeral=True)
        return False
    return True


@grupo.command(name="aqui", description="Define este canal como destino dos freelas")
async def cmd_aqui(interaction: discord.Interaction):
    if not await _so_dono(interaction):
        return
    config["canal_id"] = interaction.channel_id
    _salvar_json(CONFIG_PATH, config)
    await interaction.response.send_message("📡 Beleza! Os freelas vão chegar neste canal.", ephemeral=True)


@grupo.command(name="status", description="Mostra como está o radar")
async def cmd_status(interaction: discord.Interaction):
    canal = bot.get_channel(config.get("canal_id", 0))
    ultima = f"<t:{int(estado['ultima'].timestamp())}:R>" if estado["ultima"] else "ainda não checou"
    e = discord.Embed(title="📡 Radar de freelas", color=0xFF4500)
    e.add_field(name="Situação", value="⏸️ Pausado" if estado["pausado"] else "▶️ Rodando", inline=True)
    e.add_field(name="Canal", value=canal.mention if canal else "não definido", inline=True)
    e.add_field(name="Última checagem", value=ultima, inline=True)
    e.add_field(name="Posts analisados", value=str(estado["analisados"]), inline=True)
    e.add_field(name="Enviados", value=str(estado["enviados"]), inline=True)
    e.add_field(name="Nota mínima", value=f"{config.get('nota_minima', 3)} pts", inline=True)
    e.add_field(name="Subreddits", value=", ".join(f"r/{s['nome']}" for s in config["subreddits"]), inline=False)
    if estado["erro"]:
        e.add_field(name="⚠️ Último erro", value=estado["erro"], inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


@grupo.command(name="agora", description="Checa o Reddit agora")
async def cmd_agora(interaction: discord.Interaction):
    if not await _so_dono(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    n = await checar(forcar_envio=True)
    msg = f"✅ Checagem feita: {n} freela(s) novo(s)." if not estado["erro"] else f"⚠️ {estado['erro']}"
    await interaction.followup.send(msg, ephemeral=True)


@grupo.command(name="pausar", description="Pausa o radar")
async def cmd_pausar(interaction: discord.Interaction):
    if not await _so_dono(interaction):
        return
    estado["pausado"] = True
    await interaction.response.send_message("⏸️ Radar pausado.", ephemeral=True)


@grupo.command(name="retomar", description="Retoma o radar")
async def cmd_retomar(interaction: discord.Interaction):
    if not await _so_dono(interaction):
        return
    estado["pausado"] = False
    await interaction.response.send_message("▶️ Radar rodando de novo.", ephemeral=True)


@grupo.command(name="nota_minima", description="Quantos pontos um post precisa para ser enviado")
@app_commands.describe(pontos="Ex.: 3 = pelo menos uma skill principal; 6 = mais exigente")
async def cmd_nota(interaction: discord.Interaction, pontos: app_commands.Range[int, 1, 30]):
    if not await _so_dono(interaction):
        return
    config["nota_minima"] = pontos
    _salvar_json(CONFIG_PATH, config)
    await interaction.response.send_message(f"🎯 Nota mínima agora é {pontos} pts.", ephemeral=True)


bot.tree.add_command(grupo)
