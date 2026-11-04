"""Radar de freelas: monitora o Reddit e posta no Discord as vagas que batem com o currículo.

- Lê o RSS público do Reddit (sem API key) em GRUPOS de subreddits (multireddit r/a+b+c).
- O RSS sem login aceita ~1 requisição por minuto, então os grupos são lidos em rodízio.
- Filtra por intenção de contratar (EN/PT/ES/DE/FR) e dá nota pelas habilidades do currículo.
- Posta um card com nota, skills, orçamento e idioma, com botões:
  ⭐ Interessa / 🗑️ Ignorar / ✍️ Rascunho (proposta em PT, EN ou ES).
- Slash commands: /freelas aqui | status | agora | pausar | retomar | nota_minima
"""

import asyncio
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

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
USER_AGENT = "python:bender-freela-radar:1.1 (personal RSS reader)"
MAX_VISTOS = 5000
INTERVALO_MINIMO_REDDIT = 65  # segundos entre requisições (limite do RSS sem login)

# ---------------------------------------------------------------------------
# Perfil (tirado dos currículos em Desktop/curriculos)
# peso 3 = stack principal | 2 = forte | 1 = complementar
# ---------------------------------------------------------------------------
HABILIDADES = [
    # rótulo, peso, padrões (regex, sem diferenciar maiúsculas)
    ("Node.js", 3, [r"node(\.?js)?"]),
    ("NestJS", 3, [r"nest(\.?js)?"]),
    ("Express", 2, [r"express(\.?js)?"]),
    ("TypeScript", 3, [r"typescript"]),
    ("JavaScript", 2, [r"javascript", r"vanilla js"]),
    ("React", 3, [r"react(\.?js)?", r"react native"]),
    ("Next.js", 3, [r"next\.?js"]),
    ("C#", 3, [r"c#", r"csharp"]),
    (".NET", 3, [r"\.net\b", r"dotnet", r"asp\.net"]),
    ("Python", 3, [r"python", r"django", r"flask", r"fastapi"]),
    ("API REST", 3, [r"apis?", r"rest(ful)?\s*api", r"backend", r"back-end"]),
    ("Full Stack", 2, [r"full[\s-]?stack"]),
    ("Web scraping", 3, [r"scrap(er|ers|ing|e)", r"crawler", r"selenium", r"beautiful\s?soup", r"playwright", r"puppeteer"]),
    ("Automação", 3, [r"automa(tion|tions|te|ted|ção|cao|ções|tizar|tización|tisierung)", r"bot", r"bots", r"zapier", r"n8n", r"make\.com", r"rpa"]),
    ("ETL / Dados", 2, [r"etl", r"data pipeline", r"pipeline de dados", r"planilhas?", r"spreadsheets?", r"excel"]),
    ("IA / LLM", 3, [r"llms?", r"openai", r"chatgpt", r"gpt", r"gemini", r"claude", r"chatbots?", r"ai agents?", r"agentes? de ia", r"rag", r"\bia\b", r"\bai\b"]),
    ("SaaS / Web app", 2, [r"saas", r"mvp", r"web ?app", r"web application", r"aplica(ção|cao) web", r"sistema web", r"aplicación web", r"plataforma"]),
    ("Integrações", 2, [r"integra(tion|tions|te|ção|cao|ções|ción)", r"webhooks?", r"stripe", r"asaas", r"pix", r"google calendar", r"google sheets", r"whatsapp"]),
    ("PostgreSQL", 2, [r"postgres(ql)?", r"supabase"]),
    ("MySQL", 2, [r"mysql"]),
    ("SQL Server", 2, [r"sql server", r"mssql", r"sql"]),
    ("MongoDB", 2, [r"mongo(db)?"]),
    ("Prisma", 1, [r"prisma"]),
    ("Docker", 2, [r"docker", r"containers?"]),
    ("AWS", 2, [r"aws", r"lambda", r"s3", r"ec2"]),
    ("Azure", 2, [r"azure"]),
    ("RabbitMQ", 2, [r"rabbitmq", r"message queue", r"mensageria"]),
    ("Tailwind", 1, [r"tailwind"]),
    ("Angular", 1, [r"angular"]),
    ("Java / Spring", 1, [r"java", r"spring\s?boot"]),
    ("Testes / QA", 1, [r"qa", r"jest", r"unit tests?", r"testes?", r"cypress"]),
    ("Linux / DevOps", 1, [r"linux", r"ci/cd", r"devops", r"vps", r"deploy"]),
    ("Dashboard", 1, [r"dashboards?", r"painel", r"admin panel"]),
    ("Site / Landing page", 1, [r"landing pages?", r"websites?", r"site", r"sitio web", r"página web"]),
    ("Discord / Telegram", 2, [r"discord", r"telegram"]),
]


def _rx(padroes):
    # remove \b explícitos e aplica bordas que funcionam com c#, .net, etc.
    limpos = [p.replace(r"\b", "") for p in padroes]
    return re.compile("|".join(f"(?<![\\w]){p}(?![\\w])" for p in limpos), re.I)


_HAB_RX = [(r, p, _rx(pats)) for r, p, pats in HABILIDADES]

# Título precisa indicar que ALGUÉM QUER CONTRATAR (EN / PT / ES / DE / FR)
INTENCAO = re.compile(
    r"\[\s*(hiring|task|paid|job|gig|vaga|freela|oferta|empleo|trabajo)\s*\]|"
    r"\bhiring\b|\bwe'?re hiring\b|"
    r"\b(looking for|need|needed|seeking|searching for|want to hire|hire)\s+(an?\s+|some\s+)?"
    r"(experienced\s+|senior\s+|skilled\s+|freelance\s+)?"
    r"(dev|devs|developer|developers|programmer|coder|engineer|freelancer|someone to (build|create|make|develop|fix|automate|scrape))\b|"
    r"\b(developer|programmer|freelancer|dev)\s+(needed|wanted|required)\b|"
    r"\bpaid\s+(gig|project|task|work)\b|\bwill pay\b|\bbudget\b|"
    # PT
    r"\bfreela\b|\bcontrat(o|a|ando|ar|amos|a-se)\b|"
    r"\b(procuro|procura-se|preciso de|precisamos de|buscando|procurando)\s+(um\s+|uma\s+|alguém\s+)?"
    r"(dev|desenvolvedor|desenvolvedora|programador|programadora|freelancer|freela|pessoa)\b|"
    r"\bor[cç]amento\b|\bprojeto pago\b|\bvaga\s+(remota|freela|pj|de dev|para dev)\b|"
    # ES
    r"\b(busco|buscamos|necesito|necesitamos|se busca|buscando)\s+(un\s+|una\s+|a\s+)?"
    r"(dev|desarrollador|desarrolladora|programador|programadora|freelancer|freelance)\b|"
    r"\bproyecto (pago|remunerado)\b|\bcontratar\b|"
    # DE / FR
    r"\b(suche|suchen)\s+(einen\s+|eine\s+)?(entwickler|programmierer|freelancer)\b|\bfreelancer gesucht\b|"
    r"\b(cherche|recherche|cherchons)\s+(un\s+|une\s+)?(développeur|développeuse|dev|freelance)\b|\bmission freelance\b",
    re.I,
)

# Sinais de que NÃO é pra você: quem está procurando trabalho, sem pagamento ou fora da área
EXCLUIR = re.compile(
    r"\[\s*(for\s*hire|offer|forhire)\s*\]|\bfor hire\b|\bhire me\b|\bavailable for (work|hire|freelance)\b|"
    r"\blooking for (a |an )?(new |remote |part[- ]time |full[- ]time )?(job|work|gig|opportunit|internship|role)|"
    r"\b(procuro|buscando|procurando) (emprego|trabalho|est[aá]gio|oportunidade|vaga)\b|"
    r"\b(busco|buscando) (trabajo|empleo|pr[aá]cticas)\b|\bsuche (job|arbeit|stelle)\b|"
    r"\bunpaid\b|equity only|rev(enue)?\s*share|\bfor exposure\b|\bvolunt[aá]rio\b|sem remunera|sin pago|"
    r"\bwordpress\b|\bshopify\b|\bwix\b|\bunity\b|\bunreal\b|\broblox\b|"
    r"\bvideo edit|\bthumbnail|\bvoice ?over|\bugc\b|\bcontent creator|\bcopywrit|\bappointment setter|"
    r"\bseo\b|\bsocial media manager|\bgraphic design|\blogo design|\billustrat|\bcold call|\bsales rep|\bsetters?\b|"
    r"\bclosers?\b|\bvoice\b|\brecruit|\bvirtual assistant|\bcustomer (support|service)|\bdata entry|"
    r"\btutor|\btranslat|\binterpret|\bproject manager\b",
    re.I,
)
# No corpo do post só derruba por falta de pagamento (citar "WordPress" no texto não deve excluir)
SEM_PAGAMENTO = re.compile(
    r"\bunpaid\b|equity only|rev(enue)?\s*share|\bfor exposure\b|\bvolunt[aá]rio\b|sem remunera|sin pago", re.I
)

ORCAMENTO = re.compile(
    r"(?:US\$|R\$|\$|€|£|USD\s?|EUR\s?)\s?\d[\d.,]*\s?k?"
    r"(?:\s?(?:-|–|to|a|até|hasta)\s?(?:US\$|R\$|\$|€|£)?\s?\d[\d.,]*\s?k?)?"
    r"(?:\s?(?:/|per\s|por\s)\s?(?:h|hr|hour|hora|mo|month|mês|mes|week|semana|project|projeto|proyecto))?",
    re.I,
)

# Idioma "padrão" de cada sub (o resto é detectado pelo texto)
IDIOMA_SUB = {
    "brdev": "PT", "programacao": "PT", "devpt": "PT",
    "devsarg": "ES", "chileit": "ES", "programacion": "ES",
    "de_edv": "DE", "informatik": "DE", "developpeurs": "FR",
}
BANDEIRAS = {"PT": "🇧🇷 PT", "EN": "🇺🇸 EN", "ES": "🇪🇸 ES", "DE": "🇩🇪 DE", "FR": "🇫🇷 FR"}

PADRAO_CONFIG = {
    "canal_id": 0,
    "mencao": "",
    "nota_minima": 5,
    "idade_maxima_horas": 24,
    "grupos": [
        {"nome": "Vagas e freelas (EN)", "subs": [
            "forhire", "freelance_forhire", "hiring", "jobbit", "slavelabour", "RemoteJobs",
            "remotepython", "PythonJobs", "DoneDirtCheap", "B2BForHire", "techjobs", "devopsjobs", "WorkOnline"]},
        {"nome": "Brasil, Portugal, LatAm e Europa", "subs": [
            "brdev", "programacao", "devpt", "devsarg", "chileIT", "programacion",
            "de_EDV", "informatik", "developpeurs"]},
        {"nome": "Negócios pedindo dev", "subs": [
            "SaaS", "smallbusiness", "sideprojects", "startups", "Entrepreneur",
            "n8n", "webscraping", "automation", "Discord_Bots"]},
    ],
}

PERFIL = {
    "github": "github.com/matheuz-rodrigues",
    "linkedin": "linkedin.com/in/matheuz-rodrigues-dev",
}

# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
estado = {
    "ultima": None, "erro": None, "enviados": 0, "pausado": False, "analisados": 0,
    "proximo_grupo": 0, "por_grupo": {},
}
_trava_reddit = asyncio.Lock()
_ultima_requisicao = 0.0


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
    for chave, valor in PADRAO_CONFIG.items():
        cfg.setdefault(chave, json.loads(json.dumps(valor)))
    return cfg


config = carregar_config()
vistos = _ler_json(STATE_PATH, {})  # url do post -> timestamp

# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------
def _limpar_html(texto):
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    texto = re.sub(r"\s+", " ", html.unescape(texto)).strip()
    return re.sub(r"submitted by .*$", "", texto).strip()


def _baixar_feed(subs):
    url = f"https://www.reddit.com/r/{'+'.join(subs)}/new/.rss?limit=100"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
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


async def _baixar_com_limite(subs):
    """Respeita ~1 requisição/minuto ao Reddit, mesmo com o loop e o /freelas agora juntos."""
    global _ultima_requisicao
    async with _trava_reddit:
        espera = INTERVALO_MINIMO_REDDIT - (time.monotonic() - _ultima_requisicao)
        if espera > 0:
            await asyncio.sleep(espera)
        try:
            return await asyncio.to_thread(_baixar_feed, subs)
        finally:
            _ultima_requisicao = time.monotonic()

# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------
def _data(post):
    try:
        return datetime.fromisoformat(post["data"].replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def analisar(post):
    """Retorna dict com nota/skills, ou None se o post não serve."""
    if not INTENCAO.search(post["titulo"]):
        return None
    texto = f"{post['titulo']} {post['texto']}"
    if EXCLUIR.search(post["titulo"]) or SEM_PAGAMENTO.search(post["texto"]):
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
    t = f" {post['titulo']} {post['texto']} ".lower()
    marcas = {
        "PT": (" de ", " para ", " que ", " com ", "ção", " você", " preciso", " uma ", " não "),
        "ES": (" de ", " para ", " que ", " con ", "ción", " necesito", " una ", " busco", " el ", " los "),
        "EN": (" the ", " and ", " for ", " with ", " you ", " need ", " looking ", " we "),
        "DE": (" der ", " die ", " und ", " mit ", " ich ", " wir ", " suche "),
        "FR": (" le ", " la ", " et ", " avec ", " pour ", " nous ", " cherche "),
    }
    contagem = {lang: sum(t.count(w) for w in ws) for lang, ws in marcas.items()}
    padrao = IDIOMA_SUB.get(post["sub"].lower())
    if padrao:
        contagem[padrao] += 3  # o idioma do sub desempata
    return max(contagem, key=contagem.get)


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
    e.add_field(name="Idioma", value=BANDEIRAS.get(a["idioma"], a["idioma"]), inline=True)
    e.add_field(name="Suas skills que batem", value=", ".join(a["skills"][:12])[:1024], inline=False)
    e.set_footer(text="Radar de freelas • responda rápido, quem chega primeiro leva")
    d = _data(post)
    if d:
        e.timestamp = d
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
    if idioma == "ES":
        return (
            f"¡Hola! Vi tu publicación \"{titulo[:80]}\" y creo que puedo ayudarte.\n\n"
            f"Soy desarrollador Full Stack y trabajo a diario con {principais}. "
            "Tengo sistemas en producción: un SaaS de gestión de gimnasios que llevé de cero a producción en 3 meses "
            "(Next.js + NestJS) y ArenaHub, una plataforma con integración de IA (Gemini) y pagos automáticos vía webhooks. "
            "También mantengo un sistema corporativo en C#/.NET con más de 500 usuarios activos.\n\n"
            "Para tu proyecto, empezaría por [ESCRIBE 1 FRASE SOBRE SU PROBLEMA].\n\n"
            "Puedo enviarte una estimación de plazo y costo hoy mismo. ¿Hablamos por DM?\n\n"
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
        campo = _campo(embed, "Idioma")
        idioma = "PT" if "PT" in campo else "ES" if "ES" in campo else "EN"
        skills = [s.strip() for s in _campo(embed, "Suas skills que batem").split(",") if s.strip()]
        texto = gerar_rascunho(embed.title or "", skills, idioma)
        await interaction.response.send_message(
            f"Rascunho ({idioma}). Personalize a parte entre colchetes antes de enviar:\n```\n{texto}\n```\n🔗 {embed.url}",
            ephemeral=True,
        )

# ---------------------------------------------------------------------------
# Busca
# ---------------------------------------------------------------------------
async def checar_grupo(indice):
    """Lê um grupo de subs e envia os posts relevantes. Retorna quantos enviou."""
    canal = bot.get_channel(config.get("canal_id", 0))
    if canal is None:
        estado["erro"] = "Canal não configurado. Use /freelas aqui no canal desejado."
        return 0

    grupo = config["grupos"][indice]
    try:
        posts = await _baixar_com_limite(grupo["subs"])
    except Exception as e:  # 429/403 do Reddit, rede, XML inválido
        estado["erro"] = f"[{grupo['nome']}] {type(e).__name__}: {e}"[:300]
        print(f"[freelas] {estado['erro']}")
        return 0

    estado["erro"] = None
    estado["ultima"] = datetime.now(timezone.utc)
    limite = datetime.now(timezone.utc) - timedelta(hours=config.get("idade_maxima_horas", 24))
    enviados = 0
    for post in sorted(posts, key=lambda p: p["data"]):
        chave = post["url"]
        if not chave or chave in vistos:
            continue
        vistos[chave] = int(time.time())
        estado["analisados"] += 1
        d = _data(post)
        if d and d < limite:
            continue
        a = analisar(post)
        if a is None:
            continue
        await canal.send(content=config.get("mencao") or None, embed=montar_embed(post, a), view=FreelaView())
        enviados += 1
        await asyncio.sleep(1)

    if len(vistos) > MAX_VISTOS:
        for k in sorted(vistos, key=vistos.get)[: len(vistos) - MAX_VISTOS]:
            del vistos[k]
    _salvar_json(STATE_PATH, vistos)
    estado["enviados"] += enviados
    estado["por_grupo"][grupo["nome"]] = {"posts": len(posts), "enviados": enviados, "quando": estado["ultima"]}
    return enviados


async def _recuperar_vistos_do_canal():
    """Depois de um deploy o arquivo de vistos some; reconstrói a partir dos cards já enviados."""
    canal = bot.get_channel(config.get("canal_id", 0))
    if canal is None:
        return
    try:
        async for msg in canal.history(limit=500):
            if msg.author.id == bot.user.id:
                for emb in msg.embeds:
                    if emb.url:
                        vistos.setdefault(emb.url, int(time.time()))
    except discord.HTTPException as e:
        print(f"[freelas] não consegui ler o histórico do canal: {e}")


@tasks.loop(seconds=INTERVALO_MINIMO_REDDIT + 10)
async def radar():
    if estado["pausado"] or not config["grupos"]:
        return
    indice = estado["proximo_grupo"] % len(config["grupos"])
    estado["proximo_grupo"] = indice + 1
    await checar_grupo(indice)


@radar.before_loop
async def _antes():
    await bot.wait_until_ready()
    await _recuperar_vistos_do_canal()


@bot.listen("on_ready")
async def _iniciar_radar():
    bot.add_view(FreelaView())
    if not radar.is_running():
        radar.start()

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------
grupo_cmd = app_commands.Group(name="freelas", description="Radar de freelas do Reddit")


async def _so_dono(interaction):
    if interaction.user.id not in DONOS:
        await interaction.response.send_message("Só o dono do radar pode usar isso.", ephemeral=True)
        return False
    return True


async def _checar_todos():
    total = 0
    for i in range(len(config["grupos"])):
        total += await checar_grupo(i)
    return total


@grupo_cmd.command(name="aqui", description="Define este canal como destino dos freelas")
async def cmd_aqui(interaction: discord.Interaction):
    if not await _so_dono(interaction):
        return
    config["canal_id"] = interaction.channel_id
    _salvar_json(CONFIG_PATH, config)
    estado["erro"] = None
    await interaction.response.send_message(
        "📡 Beleza! Os freelas vão chegar neste canal (busca completa leva ~3 min).\n\n"
        "Para não perder essa configuração a cada deploy, coloque no `freelas_config.json`:\n"
        f"`\"canal_id\": {interaction.channel_id}`",
        ephemeral=True,
    )
    await _checar_todos()


@grupo_cmd.command(name="status", description="Mostra como está o radar")
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
    for g in config["grupos"]:
        info = estado["por_grupo"].get(g["nome"])
        resumo = (f"{info['posts']} posts lidos, {info['enviados']} enviados • <t:{int(info['quando'].timestamp())}:R>"
                  if info else "aguardando a vez no rodízio")
        e.add_field(name=g["nome"], value=f"{resumo}\n{', '.join('r/' + s for s in g['subs'])}"[:1024], inline=False)
    if estado["erro"]:
        e.add_field(name="⚠️ Último erro", value=estado["erro"], inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


@grupo_cmd.command(name="agora", description="Busca em todos os grupos agora (leva ~3 min por causa do limite do Reddit)")
async def cmd_agora(interaction: discord.Interaction):
    if not await _so_dono(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    n = await _checar_todos()
    msg = f"✅ Busca completa: {n} freela(s) novo(s)." if not estado["erro"] else f"⚠️ {estado['erro']}"
    await interaction.followup.send(msg, ephemeral=True)


@grupo_cmd.command(name="pausar", description="Pausa o radar")
async def cmd_pausar(interaction: discord.Interaction):
    if not await _so_dono(interaction):
        return
    estado["pausado"] = True
    await interaction.response.send_message("⏸️ Radar pausado.", ephemeral=True)


@grupo_cmd.command(name="retomar", description="Retoma o radar")
async def cmd_retomar(interaction: discord.Interaction):
    if not await _so_dono(interaction):
        return
    estado["pausado"] = False
    await interaction.response.send_message("▶️ Radar rodando de novo.", ephemeral=True)


@grupo_cmd.command(name="nota_minima", description="Quantos pontos um post precisa para ser enviado")
@app_commands.describe(pontos="Ex.: 3 = pelo menos uma skill principal; 6 = mais exigente")
async def cmd_nota(interaction: discord.Interaction, pontos: app_commands.Range[int, 1, 30]):
    if not await _so_dono(interaction):
        return
    config["nota_minima"] = pontos
    _salvar_json(CONFIG_PATH, config)
    await interaction.response.send_message(f"🎯 Nota mínima agora é {pontos} pts.", ephemeral=True)


bot.tree.add_command(grupo_cmd)
