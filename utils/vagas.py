"""Radar de vagas (CLT/PJ): LinkedIn + Gupy -> canal #vagas.

- LinkedIn: endpoint público de visitante (o mesmo do radar.py), últimas 24h,
  descarta vagas com muitos candidatos.
- Gupy: busca pública do portal (portal.gupy.io), vagas remotas ou na sua cidade.
- Cada vaga passa pelo motor do vaga.py: qual PDF enviar, o que você cobre, lacunas, nível.
- Botões: ✅ Me candidatei / ✍️ Mensagem pro recrutador / 🗑️ Descartar
- Slash commands: /vagas aqui | status | agora | funil
"""

import asyncio
import html
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import discord
import requests
from discord import app_commands
from discord.ext import tasks

from bot_instance import bot
from utils.freelas import DONOS, config, _salvar_json, CONFIG_PATH
from utils.vaga_match import avaliar

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
LI_BUSCA = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_VAGA = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
GUPY_BUSCA = "https://portal.gupy.io/api/job-search/jobs"
RODAPE = "vaga:"  # marca os cards, para reconstruir vistos/funil a partir do canal

# O título precisa ser de vaga de desenvolvimento
TITULO_DEV = re.compile(
    r"desenvolv|developer|\bdev\b|engenheir[oa] de software|software engineer|programador|"
    r"full[\s-]?stack|back[\s-]?end|front[\s-]?end|analista de (sistemas|desenvolvimento)|\.net|\bc#|node|react|python",
    re.I)
# Stack principal que você não tem, quando está no título
TITULO_FORA = re.compile(
    r"\bjava\b(?!script)|spring|\bruby\b|\brails\b|\bphp\b|laravel|flutter|\bdart\b|kotlin|\bswift\b|\bios\b|android|"
    r"\bgo\b|golang|\brust\b|elixir|advpl|tlpp|protheus|delphi|\bsap\b|abap|salesforce|oracle pl/?sql|\bcobol\b|mainframe|"
    r"\bqa\b|\btester\b|dados|\bdata\b|devops|\bsre\b|mobile",
    re.I)
REMOTO = re.compile(r"\bremot[oa]\b|\bremote\b|home[\s-]?office|100% remot|trabalho remoto|work from home|anywhere", re.I)

PADRAO = {
    "canal_id": 0,
    "min_aderencia": 5,
    "max_candidatos": 30,
    "linkedin_horas": 2,
    "gupy_horas": 1,
    "idade_maxima_horas": 48,
    "cidades": ["Belém", "Ananindeua"],
    "estados": ["PA", "Pará"],
    "linkedin": [
        ["desenvolvedor full stack junior", "Brazil"],
        ["desenvolvedor full stack pleno", "Brazil"],
        ["desenvolvedor backend node.js", "Brazil"],
        ["desenvolvedor react next.js", "Brazil"],
        ["desenvolvedor .net c#", "Brazil"],
        ["desenvolvedor python", "Brazil"],
        ["desenvolvedor full stack", "Belém, Pará, Brazil"],
    ],
    "gupy": [
        "desenvolvedor full stack", "desenvolvedor backend", "desenvolvedor node",
        "desenvolvedor react", "desenvolvedor .net", "desenvolvedor c#",
        "desenvolvedor python", "desenvolvedor junior", "desenvolvedor pleno",
    ],
}
for _k, _v in PADRAO.items():
    config.setdefault("vagas", {}).setdefault(_k, _v)
CFG = config["vagas"]

vistos = set()      # url da vaga
candidaturas = {}   # url -> {"fonte", "curriculo", "quando"}
estado = {"linkedin": None, "gupy": None, "erro_linkedin": None, "erro_gupy": None,
          "enviadas": 0, "rodando": False}

# ---------------------------------------------------------------------------
# Coleta (síncrona; roda em thread para não travar o bot)
# ---------------------------------------------------------------------------
def _get(url, params=None, json_=False, tentativas=3):
    for n in range(tentativas):
        try:
            r = requests.get(url, params=params, timeout=25,
                             headers={"User-Agent": UA, "Accept": "application/json" if json_ else "*/*"})
            if r.status_code == 429:
                time.sleep(20 * (n + 1))
                continue
            if not r.ok:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            return r.json() if json_ else r.text
        except requests.RequestException:
            if n == tentativas - 1:
                raise
            time.sleep(3)
    raise requests.HTTPError("HTTP 429 (limite persistente)")


def _limpa(txt):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", txt or "")).replace("\xa0", " ")).strip()


def _campo(padrao, corpo):
    m = re.search(padrao, corpo, re.S)
    return _limpa(m.group(1)) if m else ""


def coletar_linkedin(ja_vistos):
    vagas, ids = [], []
    for termo, local in CFG["linkedin"]:
        for start in (0, 25, 50):
            corpo = _get(LI_BUSCA, {"keywords": termo, "location": local, "f_TPR": "r86400", "start": start})
            novos = re.findall(r'jobs/view/[^"?]*?-(\d{8,})', corpo)
            if not novos:
                break
            ids += novos
            time.sleep(1.5)
    for jid in dict.fromkeys(ids):
        url = f"https://www.linkedin.com/jobs/view/{jid}"
        if url in ja_vistos:
            continue
        try:
            corpo = _get(LI_VAGA.format(jid))
        except requests.RequestException:
            continue
        time.sleep(1.2)
        cand_txt = _campo(r'class="num-applicants__caption[^"]*"[^>]*>(.*?)</', corpo)
        digitos = "".join(c for c in cand_txt if c.isdigit())
        titulo = (_campo(r'class="top-card-layout__title[^"]*"[^>]*>(.*?)</h[12]>', corpo)
                  or _campo(r'class="topcard__title"[^>]*>(.*?)</h[12]>', corpo))
        local = _campo(r'class="topcard__flavor topcard__flavor--bullet"[^>]*>(.*?)</span>', corpo)
        descricao = _campo(r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', corpo)
        remoto = bool(REMOTO.search(titulo) or REMOTO.search(descricao))
        # o filtro de remoto do LinkedIn (f_WT) é ignorado para visitante: decide pelo texto
        if not remoto and not _na_regiao(local):
            continue
        vagas.append({
            "fonte": "LinkedIn",
            "url": url,
            "titulo": titulo,
            "empresa": _campo(r'class="topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', corpo)
                       or _campo(r'class="topcard__flavor"[^>]*>(.*?)</span>', corpo),
            "local": ("Remoto • " if remoto else "") + local,
            "publicada": _campo(r'class="posted-time-ago__text[^"]*"[^>]*>(.*?)</span>', corpo),
            "candidatos": int(digitos) if digitos else None,
            "descricao": descricao,
            "logo": None,
        })
    return vagas


def _na_regiao(texto):
    t = (texto or "").lower()
    return any(c.lower() in t for c in CFG["cidades"]) or any(
        re.search(rf"(?<![a-z]){re.escape(e.lower())}(?![a-z])", t) for e in CFG["estados"])


def titulo_serve(titulo):
    return bool(TITULO_DEV.search(titulo)) and not TITULO_FORA.search(titulo)


def coletar_gupy(ja_vistos):
    vagas, limite = [], datetime.now(timezone.utc) - timedelta(hours=CFG["idade_maxima_horas"])
    cidades = {c.lower() for c in CFG["cidades"]}
    estados = {e.lower() for e in CFG["estados"]}
    nesta_busca = set()
    for termo in CFG["gupy"]:
        dados = _get(GUPY_BUSCA, {"jobName": termo, "limit": 50, "offset": 0}, json_=True)
        for j in dados.get("data", []):
            url = (j.get("jobUrl") or "").split("?")[0]
            if not url or url in ja_vistos or url in nesta_busca:
                continue
            nesta_busca.add(url)
            try:
                pub = datetime.fromisoformat(j["publishedDate"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                pub = None
            if pub and pub < limite:
                continue
            modelo = j.get("workplaceType") or ""
            cidade, uf = (j.get("city") or ""), (j.get("state") or "")
            if modelo != "remote" and cidade.lower() not in cidades and uf.lower() not in estados:
                continue  # presencial/híbrido fora da sua região
            nomes = {"remote": "Remoto", "hybrid": "Híbrido", "on-site": "Presencial"}
            local = nomes.get(modelo, modelo) + (f" • {cidade}/{uf}" if cidade else "")
            vagas.append({
                "fonte": "Gupy",
                "url": url,
                "titulo": (j.get("name") or "").strip(),
                "empresa": (j.get("careerPageName") or "").strip(),
                "local": local,
                "publicada": f"<t:{int(pub.timestamp())}:R>" if pub else "",
                "candidatos": None,
                "descricao": _limpa(j.get("description", "")),
                "logo": j.get("careerPageLogo"),
            })
        time.sleep(2)
    return vagas

# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------
def montar_card(v, a):
    cor = 0x2ECC71 if a["aderencia"] >= 12 else 0xF1C40F if a["aderencia"] >= 8 else 0x95A5A6
    if v["fonte"] == "LinkedIn":
        cor = cor if cor != 0x95A5A6 else 0x0A66C2
    e = discord.Embed(title=f"{v['titulo']}"[:256], url=v["url"], color=cor)
    e.set_author(name=f"{v['empresa'] or 'Empresa não informada'} • {v['fonte']}"[:256])
    if v.get("logo"):
        e.set_thumbnail(url=v["logo"])
    e.add_field(name="📎 Envie", value=f"**{a['curriculo']}**\n`{a['arquivo']}`", inline=False)
    e.add_field(name="Aderência", value=f"{a['aderencia']} pts", inline=True)
    e.add_field(name="Nível", value=a["nivel"], inline=True)
    if v["fonte"] == "LinkedIn":
        e.add_field(name="Candidatos", value=str(v["candidatos"]) if v["candidatos"] is not None else "?", inline=True)
    e.add_field(name="Local", value=v["local"] or "—", inline=True)
    e.add_field(name="Publicada", value=v["publicada"] or "—", inline=True)
    e.add_field(name="✅ Você cobre", value=(", ".join(a["cobertas"][:14]) or "—")[:1024], inline=False)
    if a["lacunas"]:
        e.add_field(name="⚠️ Lacunas", value=", ".join(a["lacunas"][:8])[:1024], inline=False)
    e.set_footer(text=f"{RODAPE}{v['fonte'].lower()}")
    return e


def mensagem_recrutador(titulo, empresa, cobertas):
    stack = ", ".join(cobertas[:4]) or "desenvolvimento full stack"
    msg = (f"Olá! Me candidatei à vaga de {titulo} na {empresa}. Trabalho com {stack} em produção "
           "(SaaS do zero ao ar em 3 meses e sistema .NET com 500+ usuários). "
           "Acho que posso contribuir rápido no time. Podemos conversar?")
    return msg if len(msg) <= 300 else msg[:297] + "..."  # limite da nota de conexão do LinkedIn


class VagaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction):
        if interaction.user.id not in DONOS:
            await interaction.response.send_message("Só o dono pode usar isso.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Me candidatei", emoji="✅", style=discord.ButtonStyle.success, custom_id="vaga:candidatei")
    async def candidatei(self, interaction, button):
        e = interaction.message.embeds[0]
        fonte = (e.footer.text or "").split(":", 1)[-1].split(" ")[0]
        cv = next((f.value.split("**")[1] for f in e.fields if f.name == "📎 Envie" and "**" in f.value), "geral")
        e.color = 0x5865F2
        e.title = f"✅ {e.title}"[:256] if not (e.title or "").startswith("✅") else e.title
        e.set_footer(text=f"{RODAPE}{fonte} • candidatura {datetime.now():%d/%m/%Y}")
        candidaturas[e.url] = {"fonte": fonte, "curriculo": cv, "quando": datetime.now(timezone.utc)}
        await interaction.response.edit_message(embed=e)
        try:
            await interaction.message.pin(reason="Candidatura enviada")
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Mensagem pro recrutador", emoji="✍️", style=discord.ButtonStyle.primary, custom_id="vaga:mensagem")
    async def mensagem(self, interaction, button):
        e = interaction.message.embeds[0]
        empresa = (e.author.name or "").split(" • ")[0] if e.author else "empresa"
        cobertas = next((f.value for f in e.fields if f.name == "✅ Você cobre"), "").split(", ")
        texto = mensagem_recrutador((e.title or "").removeprefix("✅ "), empresa, [c for c in cobertas if c != "—"])
        busca = "https://www.linkedin.com/search/results/people/?" + urllib.parse.urlencode(
            {"keywords": f"recrutador tech {empresa}"})
        await interaction.response.send_message(
            f"Nota de conexão ({len(texto)}/300). Mande para alguém de RH/tech da empresa:\n```\n{texto}\n```\n"
            f"🔎 Achar a pessoa: {busca}", ephemeral=True)

    @discord.ui.button(label="Descartar", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id="vaga:descartar")
    async def descartar(self, interaction, button):
        await interaction.message.delete()

# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
async def _processar(fonte):
    canal = bot.get_channel(CFG.get("canal_id", 0))
    if canal is None:
        estado[f"erro_{fonte}"] = "Canal não configurado. Use /vagas aqui."
        return 0
    coletor = coletar_linkedin if fonte == "linkedin" else coletar_gupy
    try:
        vagas = await asyncio.to_thread(coletor, set(vistos))
    except Exception as ex:
        estado[f"erro_{fonte}"] = f"{type(ex).__name__}: {ex}"[:300]
        print(f"[vagas] {fonte}: {estado[f'erro_{fonte}']}")
        return 0
    estado[f"erro_{fonte}"] = None
    estado[fonte] = datetime.now(timezone.utc)

    boas = []
    for v in vagas:
        vistos.add(v["url"])
        if not v["titulo"] or not titulo_serve(v["titulo"]):
            continue
        if v["candidatos"] is not None and v["candidatos"] > CFG["max_candidatos"]:
            continue
        a = avaliar(v["titulo"], v["descricao"])
        if a["aderencia"] < CFG["min_aderencia"] or a["senioridade"] < 0:
            continue
        boas.append((v, a))

    # melhores primeiro; no LinkedIn, empate desempata por menos candidatos
    boas.sort(key=lambda x: (-x[1]["aderencia"], x[0]["candidatos"] if x[0]["candidatos"] is not None else 9999))
    for v, a in boas:
        await canal.send(embed=montar_card(v, a), view=VagaView())
        await asyncio.sleep(1)
    estado["enviadas"] += len(boas)
    return len(boas)


async def _recuperar_do_canal():
    canal = bot.get_channel(CFG.get("canal_id", 0))
    if canal is None:
        return
    try:
        async for msg in canal.history(limit=2000):
            if msg.author.id != bot.user.id:
                continue
            for e in msg.embeds:
                rodape = (e.footer.text or "") if e.footer else ""
                if not rodape.startswith(RODAPE) or not e.url:
                    continue
                vistos.add(e.url)
                if "candidatura" in rodape:
                    cv = next((f.value.split("**")[1] for f in e.fields if f.name == "📎 Envie" and "**" in f.value), "geral")
                    candidaturas[e.url] = {"fonte": rodape[len(RODAPE):].split(" ")[0], "curriculo": cv,
                                           "quando": msg.edited_at or msg.created_at}
    except discord.HTTPException as ex:
        print(f"[vagas] não consegui ler o histórico: {ex}")


_trava = asyncio.Lock()


async def rodar(fontes):
    async with _trava:  # nunca duas buscas ao mesmo tempo (evita 429)
        estado["rodando"] = True
        try:
            return {f: await _processar(f) for f in fontes}
        finally:
            estado["rodando"] = False


@tasks.loop(minutes=15)
async def agendador():
    agora = datetime.now(timezone.utc)
    devidas = [f for f in ("gupy", "linkedin")
               if estado[f] is None or agora - estado[f] >= timedelta(hours=CFG[f"{f}_horas"])]
    if devidas and not _trava.locked():
        await rodar(devidas)


@agendador.before_loop
async def _antes():
    await bot.wait_until_ready()
    await _recuperar_do_canal()


@bot.listen("on_ready")
async def _iniciar():
    bot.add_view(VagaView())
    if not agendador.is_running():
        agendador.start()

# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------
grupo = app_commands.Group(name="vagas", description="Radar de vagas CLT/PJ (LinkedIn + Gupy)")


async def _so_dono(interaction):
    if interaction.user.id not in DONOS:
        await interaction.response.send_message("Só o dono pode usar isso.", ephemeral=True)
        return False
    return True


@grupo.command(name="aqui", description="Define este canal como destino das vagas")
async def cmd_aqui(interaction: discord.Interaction):
    if not await _so_dono(interaction):
        return
    CFG["canal_id"] = interaction.channel_id
    _salvar_json(CONFIG_PATH, config)
    await interaction.response.send_message(
        "💼 Beleza! As vagas vão chegar aqui. Buscando agora (LinkedIn leva alguns minutos).\n\n"
        f"Para não perder isso a cada deploy, coloque no `freelas_config.json` em `vagas`:\n"
        f"`\"canal_id\": {interaction.channel_id}`", ephemeral=True)
    await _recuperar_do_canal()
    await rodar(["gupy", "linkedin"])


@grupo.command(name="agora", description="Busca vagas agora")
@app_commands.choices(fonte=[
    app_commands.Choice(name="Todas", value="todas"),
    app_commands.Choice(name="Gupy (rápido)", value="gupy"),
    app_commands.Choice(name="LinkedIn (alguns minutos)", value="linkedin"),
])
async def cmd_agora(interaction: discord.Interaction, fonte: app_commands.Choice[str]):
    if not await _so_dono(interaction):
        return
    if _trava.locked():
        await interaction.response.send_message("⏳ Já tem uma busca rodando, espere ela terminar.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    fontes = ["gupy", "linkedin"] if fonte.value == "todas" else [fonte.value]
    res = await rodar(fontes)
    linhas = [f"**{f}**: {n} vaga(s)" + (f" ⚠️ {estado['erro_' + f]}" if estado["erro_" + f] else "")
              for f, n in res.items()]
    await interaction.followup.send("\n".join(linhas), ephemeral=True)


@grupo.command(name="status", description="Mostra como está o radar de vagas")
async def cmd_status(interaction: discord.Interaction):
    canal = bot.get_channel(CFG.get("canal_id", 0))
    e = discord.Embed(title="💼 Radar de vagas", color=0x0A66C2)
    e.add_field(name="Canal", value=canal.mention if canal else "não definido (/vagas aqui)", inline=True)
    e.add_field(name="Enviadas", value=str(estado["enviadas"]), inline=True)
    e.add_field(name="Buscando agora", value="sim" if estado["rodando"] else "não", inline=True)
    for f, nome in (("gupy", "Gupy"), ("linkedin", "LinkedIn")):
        quando = f"<t:{int(estado[f].timestamp())}:R>" if estado[f] else "ainda não buscou"
        txt = f"última: {quando} • a cada {CFG[f + '_horas']}h"
        if estado["erro_" + f]:
            txt += f"\n⚠️ {estado['erro_' + f]}"
        e.add_field(name=nome, value=txt, inline=False)
    e.add_field(name="Filtros",
                value=(f"aderência ≥ {CFG['min_aderencia']} • LinkedIn ≤ {CFG['max_candidatos']} candidatos • "
                       f"sem sênior/estágio • Gupy: remoto ou {', '.join(CFG['cidades'])}"), inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


@grupo.command(name="funil", description="Suas candidaturas registradas pelo botão ✅")
async def cmd_funil(interaction: discord.Interaction):
    if not candidaturas:
        await interaction.response.send_message(
            "Nenhuma candidatura registrada ainda. Clique em **✅ Me candidatei** nos cards.", ephemeral=True)
        return
    agora = datetime.now(timezone.utc)
    semana = sum(1 for c in candidaturas.values() if agora - c["quando"] <= timedelta(days=7))
    por_fonte, por_cv = {}, {}
    for c in candidaturas.values():
        por_fonte[c["fonte"]] = por_fonte.get(c["fonte"], 0) + 1
        por_cv[c["curriculo"]] = por_cv.get(c["curriculo"], 0) + 1
    e = discord.Embed(title="📊 Funil de candidaturas", color=0x5865F2)
    e.add_field(name="Total", value=str(len(candidaturas)), inline=True)
    e.add_field(name="Últimos 7 dias", value=str(semana), inline=True)
    e.add_field(name="Por fonte", value="\n".join(f"{k}: {v}" for k, v in por_fonte.items()), inline=False)
    e.add_field(name="Por currículo", value="\n".join(f"{k}: {v}" for k, v in sorted(por_cv.items(), key=lambda x: -x[1])), inline=False)
    e.set_footer(text="Os cards de candidatura ficam fixados no canal")
    await interaction.response.send_message(embed=e, ephemeral=True)


bot.tree.add_command(grupo)
