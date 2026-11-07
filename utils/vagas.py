"""Radar de vagas (CLT/PJ) -> canal #vagas.

As fontes (LinkedIn, Gupy, GitHub, Remotar, GeekHunter, InfoJobs, ATS de empresas, sites
internacionais de vagas remotas...) ficam em utils/vagas_fontes.py; aqui fica a parte do Discord.
- Cada vaga passa pelo motor do vaga.py: qual PDF enviar, o que você cobre, lacunas, nível.
- A mesma vaga anunciada em dois sites (mesmo título + empresa) só vira um card.
- Botões: ✅ Me candidatei / ✍️ Mensagem pro recrutador / 🗑️ Descartar
- Slash commands: /vagas aqui | status | agora | funil
"""

import asyncio
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from bot_instance import bot
from utils.freelas import DONOS, _salvar_json, CONFIG_PATH, config
from utils.vaga_match import avaliar, normaliza
from utils.vagas_fontes import CFG, FONTES, titulo_serve

RODAPE = "vaga:"  # marca os cards, para reconstruir vistos/funil a partir do canal

vistos = set()      # url da vaga
chaves = set()      # título+empresa normalizados (a mesma vaga em sites diferentes)
candidaturas = {}   # url -> {"fonte", "curriculo", "quando"}
estado = {"enviadas": 0, "rodando": False}
for _f in FONTES:
    estado[_f] = None
    estado[f"erro_{_f}"] = None


def chave(titulo, empresa):
    t = re.sub(r"[^a-z0-9]+", " ", normaliza(titulo or "").removeprefix("✅ "))
    e = re.sub(r"[^a-z0-9]+", " ", normaliza(empresa or ""))
    return f"{t.strip()}|{e.strip()}"

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
    if v["candidatos"] is not None:  # LinkedIn e GetOnBoard informam
        e.add_field(name="Candidatos", value=str(v["candidatos"]), inline=True)
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
    coletor = FONTES[fonte][1]
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
        k = chave(v["titulo"], v["empresa"])
        if v["empresa"] and k in chaves:
            continue  # mesma vaga já veio de outro site
        chaves.add(k)
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
                if e.author and e.author.name:
                    chaves.add(chave(e.title, e.author.name.rsplit(" • ", 1)[0]))
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
    devidas = [f for f in FONTES
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
grupo = app_commands.Group(name="vagas", description="Radar de vagas CLT/PJ (LinkedIn, Gupy, GeekHunter e mais)")


def _grupo_fontes(valor):
    if valor == "todas":
        return list(FONTES)
    if valor in ("br", "intl"):
        return [f for f, (_, _, g) in FONTES.items() if g == valor]
    return [valor]


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
    await rodar(list(FONTES))


@grupo.command(name="agora", description="Busca vagas agora")
@app_commands.choices(fonte=[  # o Discord aceita no máximo 25 opções
    app_commands.Choice(name="Todas (LinkedIn leva alguns minutos)", value="todas"),
    app_commands.Choice(name="Só as brasileiras", value="br"),
    app_commands.Choice(name="Só as internacionais (remoto)", value="intl"),
    *[app_commands.Choice(name=nome, value=f) for f, (nome, _, _) in FONTES.items()],
][:25])
async def cmd_agora(interaction: discord.Interaction, fonte: app_commands.Choice[str]):
    if not await _so_dono(interaction):
        return
    if _trava.locked():
        await interaction.response.send_message("⏳ Já tem uma busca rodando, espere ela terminar.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    res = await rodar(_grupo_fontes(fonte.value))
    linhas = [f"**{FONTES[f][0]}**: {n} vaga(s)" + (f" ⚠️ {estado['erro_' + f]}" if estado["erro_" + f] else "")
              for f, n in res.items()]
    await interaction.followup.send("\n".join(linhas)[:2000], ephemeral=True)


@grupo.command(name="status", description="Mostra como está o radar de vagas")
async def cmd_status(interaction: discord.Interaction):
    canal = bot.get_channel(CFG.get("canal_id", 0))
    e = discord.Embed(title="💼 Radar de vagas", color=0x0A66C2)
    e.add_field(name="Canal", value=canal.mention if canal else "não definido (/vagas aqui)", inline=True)
    e.add_field(name="Enviadas", value=str(estado["enviadas"]), inline=True)
    e.add_field(name="Buscando agora", value="sim" if estado["rodando"] else "não", inline=True)
    # uma linha por fonte na descrição (embed aceita só 25 campos)
    linhas = []
    for f, (nome, _, _) in FONTES.items():
        quando = f"<t:{int(estado[f].timestamp())}:R>" if estado[f] else "ainda não buscou"
        erro = estado["erro_" + f]
        linhas.append(f"{'⚠️' if erro else '✅' if estado[f] else '⏳'} **{nome}** — {quando} • a cada "
                      f"{CFG[f + '_horas']}h" + (f"\n  ↳ {erro[:120]}" if erro else ""))
    e.description = "\n".join(linhas)[:4000]
    e.add_field(name="Filtros",
                value=(f"aderência ≥ {CFG['min_aderencia']} • ≤ {CFG['max_candidatos']} candidatos (quando o site informa) • "
                       f"sem sênior/liderança • estágio incluso • remoto ou {', '.join(CFG['cidades'])} • "
                       "internacionais: só remoto aberto ao Brasil/LatAm/mundo"), inline=False)
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
