"""Liga/desliga a máquina de desenvolvimento (EC2 proapp-dev).

Comandos: .ligar, .desligar, .status (apelido .maquina) e /ligar, /desligar, /status.

Só o criador pode usar. A credencial AWS (usuário IAM bender-ec2) só consegue ligar,
desligar e consultar essa instância. Chamadas à API da AWS assinadas na mão (SigV4),
sem boto3, para não pesar na RAM da Discloud.
"""

import asyncio
import datetime
import hashlib
import hmac
import re
import urllib.parse
import xml.etree.ElementTree as ET

import discord
import requests

from bot_instance import bot
from settings import AWS_EC2_KEY_ID, AWS_EC2_SECRET, AWS_EC2_REGION, AWS_EC2_INSTANCE

CRIADOR_ID = 796471574827237436
ESTADOS = {
    "pending": "🟡 ligando",
    "running": "🟢 ligada",
    "stopping": "🟠 desligando",
    "stopped": "⚫ desligada",
    "shutting-down": "🔴 sendo destruída",
    "terminated": "🔴 destruída",
}


def _h(chave, msg):
    return hmac.new(chave, msg.encode(), hashlib.sha256).digest()


def _chamar_ec2(acao, **params):
    """Chama a API Query do EC2 com assinatura SigV4 e devolve o XML da resposta."""
    host = f"ec2.{AWS_EC2_REGION}.amazonaws.com"
    params = {"Action": acao, "Version": "2016-11-15", **params}
    agora = datetime.datetime.now(datetime.timezone.utc)
    amz_date = agora.strftime("%Y%m%dT%H%M%SZ")
    dia = agora.strftime("%Y%m%d")

    q = lambda s: urllib.parse.quote(str(s), safe="-_.~")
    query = "&".join(f"{q(k)}={q(v)}" for k, v in sorted(params.items()))
    cabecalhos = f"host:{host}\nx-amz-date:{amz_date}\n"
    assinados = "host;x-amz-date"
    requisicao = "\n".join(["GET", "/", query, cabecalhos, assinados, hashlib.sha256(b"").hexdigest()])
    escopo = f"{dia}/{AWS_EC2_REGION}/ec2/aws4_request"
    a_assinar = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, escopo, hashlib.sha256(requisicao.encode()).hexdigest()]
    )
    chave = _h(_h(_h(_h(f"AWS4{AWS_EC2_SECRET}".encode(), dia), AWS_EC2_REGION), "ec2"), "aws4_request")
    assinatura = hmac.new(chave, a_assinar.encode(), hashlib.sha256).hexdigest()

    r = requests.get(
        f"https://{host}/?{query}",
        headers={
            "x-amz-date": amz_date,
            "Authorization": f"AWS4-HMAC-SHA256 Credential={AWS_EC2_KEY_ID}/{escopo}, "
            f"SignedHeaders={assinados}, Signature={assinatura}",
        },
        timeout=20,
    )
    if r.status_code != 200:
        erro = ET.fromstring(r.text).find(".//{*}Message") if r.text.startswith("<") else None
        raise RuntimeError(erro.text if erro is not None else f"HTTP {r.status_code}")
    return ET.fromstring(r.text)


def _estado():
    xml = _chamar_ec2("DescribeInstances", **{"InstanceId.1": AWS_EC2_INSTANCE})
    return xml.find(".//{*}instanceState/{*}name").text


# Preços on-demand em sa-east-1 (tabela de preços da AWS, nov/2026).
PRECO_HORA_USD = {"m7i-flex.large": 0.15262}
PRECO_DISCO_GB_MES_USD = 0.152  # gp3
DISCO_GB = 40  # tamanho do EBS (o DescribeInstances não informa; ler exigiria ec2:DescribeVolumes)
def _usd(valor, casas=2):
    return f"US$ {valor:.{casas}f}".replace(".", ",")


REGEX_DATA_GMT = re.compile(r"\((\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) GMT\)")


def _detalhes():
    """Estado, tipo, desde quando está ligada e por que/quando desligou (dados do DescribeInstances)."""
    xml = _chamar_ec2("DescribeInstances", **{"InstanceId.1": AWS_EC2_INSTANCE})
    inst = xml.find(".//{*}instancesSet/{*}item")
    texto = lambda caminho: (inst.find(caminho).text if inst.find(caminho) is not None else "") or ""
    return {
        "estado": texto("{*}instanceState/{*}name"),
        "tipo": texto("{*}instanceType"),
        "ligada_em": texto("{*}launchTime"),
        "transicao": texto("{*}reason"),
        "motivo": texto("{*}stateReason/{*}code"),
        "disco_gb": DISCO_GB,
    }


def _texto_status(d, agora=None):
    """Monta a resposta do /status. Horários em formato do Discord (<t:...>), que aparecem no fuso de quem lê."""
    agora = agora or datetime.datetime.now(datetime.timezone.utc)
    linhas = [f"**proapp-dev**: {ESTADOS.get(d['estado'], d['estado'])}"]
    preco = PRECO_HORA_USD.get(d["tipo"])

    if d["estado"] in ("running", "pending") and d["ligada_em"]:
        inicio = datetime.datetime.fromisoformat(d["ligada_em"].replace("Z", "+00:00"))
        minutos = max(0, int((agora - inicio).total_seconds() // 60))
        duracao = f"{minutos // 60}h {minutos % 60:02d}min" if minutos >= 60 else f"{minutos} min"
        linhas.append(f"⏱️ Ligada há **{duracao}** (desde <t:{int(inicio.timestamp())}:t>)")
        if preco:
            linhas.append(f"💸 Esta sessão até agora: **≈ {_usd(minutos / 60 * preco)}**")
        linhas.append("💤 Desliga sozinha após 30 min sem uso do Claude.")
    elif d["estado"] == "stopped":
        quando = REGEX_DATA_GMT.search(d["transicao"])
        if d["motivo"] == "Client.InstanceInitiatedShutdown":
            como = "desligou sozinha (ficou parada)"
        elif d["motivo"] == "Client.UserInitiatedShutdown":
            como = "foi desligada por comando"
        else:
            como = "desligada"
        if quando:
            fim = datetime.datetime.strptime(quando.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
            linhas.append(f"🛑 {como.capitalize()} <t:{int(fim.timestamp())}:R> (<t:{int(fim.timestamp())}:t>)")
        else:
            linhas.append(f"🛑 {como.capitalize()}.")
        linhas.append("Use `/ligar` para subir de novo (~1 min).")

    custo = []
    if preco:
        custo.append(f"{_usd(preco, 3)}/h ligada")
    if d["disco_gb"]:
        custo.append(f"disco {d['disco_gb']} GB ≈ {_usd(d['disco_gb'] * PRECO_DISCO_GB_MES_USD)}/mês")
    if custo:
        linhas.append(f"-# {d['tipo']} · {' · '.join(custo)}")
    return "\n".join(linhas)


async def _em_thread(funcao, *args, **kwargs):
    return await asyncio.to_thread(funcao, *args, **kwargs)


def _faltando():
    """Nomes das variáveis obrigatórias que não chegaram ao bot (nunca mostra valores)."""
    valores = {"AWS_EC2_KEY_ID": AWS_EC2_KEY_ID, "AWS_EC2_SECRET": AWS_EC2_SECRET, "AWS_EC2_INSTANCE": AWS_EC2_INSTANCE}
    return [nome for nome, valor in valores.items() if not valor]


def _msg_sem_config(faltando):
    return (
        f"Faltam estas variáveis no ambiente: {', '.join(f'`{n}`' for n in faltando)}. "
        "Nem eu ligo máquina sem chave. (Na Discloud, variável nova só vale depois de um novo deploy.)"
    )


MSG_NAO_E_CRIADOR = "Essa máquina é do meu criador, saco de carne. Tira a mão."


# --- lógica comum: `enviar(texto)` manda uma mensagem e devolve um objeto com .edit(content=...) ---

async def _status(enviar):
    try:
        await enviar(_texto_status(await _em_thread(_detalhes)))
    except Exception as e:
        await enviar(f"A AWS me ignorou: `{e}`")


async def _ligar(enviar):
    try:
        estado = await _em_thread(_estado)
        if estado in ("running", "pending"):
            await enviar(f"Já tá {ESTADOS[estado]}, gênio. Abre o app do Claude e vai trabalhar.")
            return
        if estado == "stopping":
            await enviar("Ela ainda tá desligando. Espera um minuto e manda ligar de novo.")
            return
        await _em_thread(_chamar_ec2, "StartInstances", **{"InstanceId.1": AWS_EC2_INSTANCE})
        msg = await enviar("🟡 Ligando a proapp-dev...")
        for _ in range(36):  # até 3 min
            await asyncio.sleep(5)
            estado = await _em_thread(_estado)
            if estado == "running":
                await msg.edit(
                    content="🟢 proapp-dev ligada. Em ~1 min a sessão **proapp-dev** aparece no app do Claude "
                    "(Code → Remote Control). Desliga sozinha após 30 min parada."
                )
                return
        await msg.edit(content=f"Demorou demais. Estado atual: {ESTADOS.get(estado, estado)}")
    except Exception as e:
        await enviar(f"Não consegui ligar: `{e}`")


async def _desligar(enviar):
    try:
        estado = await _em_thread(_estado)
        if estado in ("stopped", "stopping"):
            await enviar(f"Já tá {ESTADOS[estado]}. Quer que eu desligue o quê, a tua cabeça?")
            return
        await _em_thread(_chamar_ec2, "StopInstances", **{"InstanceId.1": AWS_EC2_INSTANCE})
        await enviar("🟠 Desligando a proapp-dev. Os arquivos ficam salvos no disco.")
    except Exception as e:
        await enviar(f"Não consegui desligar: `{e}`")


# --- comandos de ponto: .ligar / .desligar / .status (.maquina continua como apelido) ---

async def _pode_usar(ctx):
    if ctx.author.id != CRIADOR_ID:
        await ctx.send(MSG_NAO_E_CRIADOR)
        return False
    if faltando := _faltando():
        await ctx.send(_msg_sem_config(faltando))
        return False
    return True


@bot.command(name="status", aliases=["maquina"])
async def status(ctx):
    if await _pode_usar(ctx):
        await _status(ctx.send)


@bot.command(name="ligar")
async def ligar(ctx):
    if await _pode_usar(ctx):
        await _ligar(ctx.send)


@bot.command(name="desligar")
async def desligar(ctx):
    if await _pode_usar(ctx):
        await _desligar(ctx.send)


# --- comandos de barra: /ligar | /desligar | /status ---

async def _slash_pode_usar(interaction):
    """Recusa quem não é o criador (resposta só ele vê) e já 'segura' a interação (AWS pode passar de 3 s)."""
    if interaction.user.id != CRIADOR_ID:
        await interaction.response.send_message(MSG_NAO_E_CRIADOR, ephemeral=True)
        return False
    if faltando := _faltando():
        await interaction.response.send_message(_msg_sem_config(faltando), ephemeral=True)
        return False
    await interaction.response.defer(thinking=True)
    return True


def _enviar_slash(interaction):
    async def enviar(texto):
        return await interaction.followup.send(texto, wait=True)
    return enviar


@bot.tree.command(name="ligar", description="Liga a máquina proapp-dev (só o criador)")
async def slash_ligar(interaction: discord.Interaction):
    if await _slash_pode_usar(interaction):
        await _ligar(_enviar_slash(interaction))


@bot.tree.command(name="desligar", description="Desliga a máquina proapp-dev (só o criador)")
async def slash_desligar(interaction: discord.Interaction):
    if await _slash_pode_usar(interaction):
        await _desligar(_enviar_slash(interaction))


@bot.tree.command(name="status", description="Mostra se a máquina proapp-dev está ligada (só o criador)")
async def slash_status(interaction: discord.Interaction):
    if await _slash_pode_usar(interaction):
        await _status(_enviar_slash(interaction))
