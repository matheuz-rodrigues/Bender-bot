"""Liga/desliga a máquina de desenvolvimento (EC2 proapp-dev): .ligar, .desligar, .maquina

Só o criador pode usar. A credencial AWS (usuário IAM bender-ec2) só consegue ligar,
desligar e consultar essa instância. Chamadas à API da AWS assinadas na mão (SigV4),
sem boto3, para não pesar na RAM da Discloud.
"""

import asyncio
import datetime
import hashlib
import hmac
import urllib.parse
import xml.etree.ElementTree as ET

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


async def _em_thread(funcao, *args, **kwargs):
    return await asyncio.to_thread(funcao, *args, **kwargs)


def _configurado():
    return all([AWS_EC2_KEY_ID, AWS_EC2_SECRET, AWS_EC2_INSTANCE])


async def _pode_usar(ctx):
    if ctx.author.id != CRIADOR_ID:
        await ctx.send("Essa máquina é do meu criador, saco de carne. Tira a mão.")
        return False
    if not _configurado():
        await ctx.send("Faltam as variáveis AWS_EC2_* no ambiente. Nem eu ligo máquina sem chave.")
        return False
    return True


@bot.command(name="maquina")
async def maquina(ctx):
    if not await _pode_usar(ctx):
        return
    try:
        estado = await _em_thread(_estado)
        await ctx.send(f"Máquina proapp-dev: **{ESTADOS.get(estado, estado)}**")
    except Exception as e:
        await ctx.send(f"A AWS me ignorou: `{e}`")


@bot.command(name="ligar")
async def ligar(ctx):
    if not await _pode_usar(ctx):
        return
    try:
        estado = await _em_thread(_estado)
        if estado in ("running", "pending"):
            await ctx.send(f"Já tá {ESTADOS[estado]}, gênio. Abre o app do Claude e vai trabalhar.")
            return
        if estado == "stopping":
            await ctx.send("Ela ainda tá desligando. Espera um minuto e manda `.ligar` de novo.")
            return
        await _em_thread(_chamar_ec2, "StartInstances", **{"InstanceId.1": AWS_EC2_INSTANCE})
        msg = await ctx.send("🟡 Ligando a proapp-dev...")
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
        await ctx.send(f"Não consegui ligar: `{e}`")


@bot.command(name="desligar")
async def desligar(ctx):
    if not await _pode_usar(ctx):
        return
    try:
        estado = await _em_thread(_estado)
        if estado in ("stopped", "stopping"):
            await ctx.send(f"Já tá {ESTADOS[estado]}. Quer que eu desligue o quê, a tua cabeça?")
            return
        await _em_thread(_chamar_ec2, "StopInstances", **{"InstanceId.1": AWS_EC2_INSTANCE})
        await ctx.send("🟠 Desligando a proapp-dev. Os arquivos ficam salvos no disco.")
    except Exception as e:
        await ctx.send(f"Não consegui desligar: `{e}`")
