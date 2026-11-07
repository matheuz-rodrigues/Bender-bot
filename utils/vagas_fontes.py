"""Coletores do radar de vagas (usados pelo utils/vagas.py).

Cada coletor recebe o set de URLs já vistas e devolve uma lista de vagas no formato:
    {"fonte", "url", "titulo", "empresa", "local", "publicada", "candidatos", "descricao", "logo"}
São síncronos (rodam em thread). O filtro de aderência/senioridade é feito depois, no vagas.py;
aqui cada coletor só descarta o que é velho demais ou fora da região (presencial longe de você).

Fontes brasileiras
- LinkedIn ........ endpoint público de visitante, últimas 24h, com nº de candidatos
- Gupy ............ busca pública do portal (portal.gupy.io)
- GitHub .......... issues dos repositórios de vagas da comunidade (backend-br, frontendbr...);
                    usa GITHUB_TOKEN do ambiente se existir (sem ele, 60 req/h, que basta)
- Remotar ......... API pública (api.remotar.com.br)
- Programathor .... lista pública + JSON-LD da página da vaga
- GeekHunter ...... dados embutidos na página de busca (stream RSC do Next.js)
- InfoJobs ........ HTML da busca (home office + Pará), mais recentes primeiro
- Catho ........... HTML da busca na sua cidade (a busca geral não diz se é remota)
- Vagas.com.br .... HTML da busca "home office"
- Trampos.co ...... API pública, categorias Programação/TI
- Empresas ........ ATS públicos de empresas (Greenhouse, Lever, Ashby), lista no config
Fontes LatAm/internacionais (remoto aberto a quem está no Brasil)
- GetOnBoard, Himalayas, Remotive, RemoteOK, Jobicy, Working Nomads, We Work Remotely

Testadas e descartadas (nov/2026): Indeed, Glassdoor, Jooble, Jora, Startup.jobs (Cloudflare/403);
Coodesh (API exige login); BNE (só vagas antigas do SINE com título genérico); Empregos.com.br
(ignora o filtro de home office); Solides, InHire, Revelo (sem lista pública); Adzuna, Careerjet,
Findwork (exigem chave de API).
"""

import html
import json
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from utils.freelas import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
LI_BUSCA = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_VAGA = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
GUPY_BUSCA = "https://portal.gupy.io/api/job-search/jobs"
GH_ISSUES = "https://api.github.com/repos/{}/issues"
REMOTAR_BUSCA = "https://api.remotar.com.br/jobs"
PT_BASE = "https://programathor.com.br"

# O título precisa ser de vaga de desenvolvimento
TITULO_DEV = re.compile(
    r"desenvolv|developer|\bdev\b|engenheir[oa] de software|software engineer|programador|"
    r"full[\s-]?stack|back[\s-]?end|front[\s-]?end|analista de (sistemas|desenvolvimento)|\.net|\bc#|node|react|python|"
    r"est[aá]gi\w* (em |de )?(ti\b|tecnologia|software|sistemas|programa|desenvolv|computa)|"
    r"trainee (de |em )?(ti\b|tecnologia|software|desenvolv)",
    re.I)
# Stack principal que você não tem, quando está no título
TITULO_FORA = re.compile(
    r"\bjava\b(?!script)|spring|\bruby\b|\brails\b|\bphp\b|laravel|flutter|\bdart\b|kotlin|\bswift\b|\bios\b|android|"
    r"\bgo\b|golang|\brust\b|elixir|advpl|tlpp|protheus|delphi|\bsap\b|abap|salesforce|oracle pl/?sql|\bcobol\b|mainframe|"
    r"\bqa\b|\btester\b|dados|\bdata\b|devops|\bsre\b|mobile|"
    # cargos de chefia (o vaga_match não pega os termos em inglês)
    r"\blead\b|\bprincipal\b|\bhead\b|\bmanager\b|\bdirector\b|gerente|coordenador|diretor|l[ií]der",
    re.I)
REMOTO = re.compile(r"\bremot[oa]\b|\bremote\b|home[\s-]?office|100% remot|trabalho remoto|work from home|anywhere", re.I)
# Vaga remota internacional que aceita quem mora no Brasil
ABERTA_BR = re.compile(
    r"brazil|brasil|latam|latin america|am[eé]rica latina|south america|americas\b|worldwide|anywhere|global|utc\s?-\s?3",
    re.I)

PADRAO = {
    "canal_id": 0,
    "min_aderencia": 5,
    "max_candidatos": 30,
    "idade_maxima_horas": 48,
    # de quantas em quantas horas cada fonte é consultada
    "linkedin_horas": 2, "gupy_horas": 1, "github_horas": 1, "remotar_horas": 1, "programathor_horas": 2,
    "geekhunter_horas": 1, "infojobs_horas": 2, "catho_horas": 6, "vagascom_horas": 3, "trampos_horas": 3,
    "empresas_horas": 6, "getonbrd_horas": 3, "himalayas_horas": 3, "remotive_horas": 3, "remoteok_horas": 3,
    "jobicy_horas": 3, "workingnomads_horas": 3, "wwr_horas": 3,
    # fontes com pouco volume olham mais para trás (repetidas são barradas pelo histórico do canal)
    "github_idade_horas": 168, "programathor_idade_horas": 96, "empresas_idade_horas": 168,
    "trampos_idade_horas": 168, "infojobs_idade_horas": 120, "catho_idade_horas": 168,
    "vagascom_idade_horas": 168, "getonbrd_idade_horas": 168, "remotive_idade_horas": 168,
    "workingnomads_idade_horas": 168, "wwr_idade_horas": 96,
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
    "github": ["backend-br/vagas", "frontendbr/vagas", "react-brasil/vagas", "nodejsdevbr/vagas"],
    "remotar": ["desenvolvedor", "developer", "full stack", "estágio desenvolvimento"],
    "geekhunter": ["desenvolvedor", "full stack", "react", "node", ".net", "python"],
    # termos das fontes internacionais (Himalayas)
    "internacional": ["full stack", "react", "node", "typescript", "python", ".net"],
    # ATS públicos: slug da empresa em cada plataforma
    "empresas": {
        "greenhouse": ["quintoandar", "stone", "c6bank", "inter", "xpinc", "vtex", "ebanx", "gympass",
                       "wildlifestudios", "jusbrasil", "rdstation", "blip", "gitlab", "remote"],
        "lever": ["neon", "swile"],
        "ashby": ["supabase"],
    },
}
for _k, _v in PADRAO.items():
    config.setdefault("vagas", {}).setdefault(_k, _v)
CFG = config["vagas"]

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def _get(url, params=None, json_=False, tentativas=3, headers=None):
    for n in range(tentativas):
        try:
            r = requests.get(url, params=params, timeout=30,
                             headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                                      "Accept": "application/json" if json_ else "*/*", **(headers or {})})
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


def _na_regiao(texto):
    t = (texto or "").lower()
    return any(c.lower() in t for c in CFG["cidades"]) or any(
        re.search(rf"(?<![a-z]){re.escape(e.lower())}(?![a-z])", t) for e in CFG["estados"])


def _aberta_br(local):
    """Remota internacional: aceita se cita Brasil/LatAm/mundo, ou se não restringe nada."""
    t = (local or "").strip()
    return not t or bool(ABERTA_BR.search(t)) or bool(re.fullmatch(r"(100% )?remot[eo]\.?", t, re.I))


def titulo_serve(titulo):
    return bool(TITULO_DEV.search(titulo or "")) and not TITULO_FORA.search(titulo or "")


def _data(valor):
    """ISO 8601, epoch (s ou ms) ou RFC 822 -> datetime UTC (ou None)."""
    if valor in (None, ""):
        return None
    try:
        if isinstance(valor, (int, float)) or str(valor).isdigit():
            n = int(valor)
            return datetime.fromtimestamp(n / 1000 if n > 10**11 else n, timezone.utc)
        txt = str(valor).strip()
        if re.match(r"\d{4}/\d{2}/\d{2}", txt):
            txt = txt.replace("/", "-", 2)
        try:
            d = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        except ValueError:
            d = parsedate_to_datetime(txt)
        return d if d.tzinfo else d.replace(tzinfo=timezone(timedelta(hours=-3)))  # sites BR: horário de Brasília
    except (ValueError, TypeError, OverflowError):
        return None


def _data_relativa(txt):
    """'Publicada há 3 horas', 'Hoje', 'Ontem', 'Há 2 dias', 'Publicada em 05/11', '14/10/2026'."""
    t, agora = (txt or "").lower(), datetime.now(timezone.utc)
    if "hoje" in t or "minuto" in t:
        return agora
    if "ontem" in t:
        return agora - timedelta(days=1)
    m = re.search(r"(\d+)\s*(hora|dia|semana|m[eê]s)", t)
    if m:
        n, u = int(m.group(1)), m.group(2)
        return agora - timedelta(hours=n) if u == "hora" else agora - timedelta(
            days=n * {"dia": 1, "semana": 7}.get(u, 30))
    m = re.search(r"(\d{2})/(\d{2})(?:/(\d{4}))?", t)
    if m:
        ano = int(m.group(3) or agora.year)
        d = datetime(ano, int(m.group(2)), int(m.group(1)), 12, tzinfo=timezone.utc)
        return d.replace(year=ano - 1) if d > agora + timedelta(days=1) else d
    return None


def _limite(fonte):
    horas = CFG.get(f"{fonte}_idade_horas") or CFG["idade_maxima_horas"]
    return datetime.now(timezone.utc) - timedelta(hours=horas)


def _velha(pub, fonte):
    return pub is not None and pub < _limite(fonte)


def _quando(pub):
    return f"<t:{int(pub.timestamp())}:R>" if pub else ""


def _vaga(fonte, url, titulo, empresa="", local="", pub=None, descricao="", candidatos=None, logo=None):
    return {"fonte": fonte, "url": url, "titulo": _limpa(titulo), "empresa": _limpa(empresa),
            "local": _limpa(local), "publicada": _quando(pub) if isinstance(pub, datetime) else (pub or ""),
            "candidatos": candidatos, "descricao": descricao or "", "logo": logo}


def _local_ok(local, remoto):
    return remoto or _na_regiao(local)


def _dic(x):
    return x if isinstance(x, dict) else {}


def _sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))

# ---------------------------------------------------------------------------
# Brasil
# ---------------------------------------------------------------------------
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
        if not _local_ok(local, remoto):
            continue
        vagas.append(_vaga(
            "LinkedIn", url, titulo,
            _campo(r'class="topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', corpo)
            or _campo(r'class="topcard__flavor"[^>]*>(.*?)</span>', corpo),
            ("Remoto • " if remoto else "") + local,
            _campo(r'class="posted-time-ago__text[^"]*"[^>]*>(.*?)</span>', corpo),
            descricao, int(digitos) if digitos else None))
    return vagas


def coletar_gupy(ja_vistos):
    vagas, nesta_busca = [], set()
    cidades = {c.lower() for c in CFG["cidades"]}
    estados = {e.lower() for e in CFG["estados"]}
    for termo in CFG["gupy"]:
        dados = _get(GUPY_BUSCA, {"jobName": termo, "limit": 50, "offset": 0}, json_=True)
        for j in dados.get("data", []):
            url = (j.get("jobUrl") or "").split("?")[0]
            if not url or url in ja_vistos or url in nesta_busca:
                continue
            nesta_busca.add(url)
            pub = _data(j.get("publishedDate"))
            if _velha(pub, "gupy"):
                continue
            modelo = j.get("workplaceType") or ""
            cidade, uf = (j.get("city") or ""), (j.get("state") or "")
            if modelo != "remote" and cidade.lower() not in cidades and uf.lower() not in estados:
                continue  # presencial/híbrido fora da sua região
            nomes = {"remote": "Remoto", "hybrid": "Híbrido", "on-site": "Presencial"}
            vagas.append(_vaga("Gupy", url, j.get("name"), j.get("careerPageName"),
                               nomes.get(modelo, modelo) + (f" • {cidade}/{uf}" if cidade else ""),
                               pub, _limpa(j.get("description", "")), logo=j.get("careerPageLogo")))
        time.sleep(2)
    return vagas


def coletar_github(ja_vistos):
    vagas = []
    headers = {"Accept": "application/vnd.github+json"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"
    for repo in CFG["github"]:
        issues = _get(GH_ISSUES.format(repo), {"state": "open", "per_page": 50, "sort": "created"},
                      json_=True, headers=headers)
        for i in issues:
            url = i.get("html_url") or ""
            if i.get("pull_request") or not url or url in ja_vistos:
                continue
            pub = _data(i.get("created_at"))
            if _velha(pub, "github"):
                break  # vem ordenado do mais novo pro mais velho
            etiquetas = [l["name"] for l in i.get("labels", [])]
            titulo = (i.get("title") or "").strip()
            # título no padrão "[Local] Cargo na Empresa"; o local também pode vir nas labels
            local = (re.match(r"\s*\[([^\]]+)\]", titulo) or [None, ""])[1]
            remoto = any(REMOTO.search(t) for t in etiquetas + [local])
            if not _local_ok(local, remoto):
                continue
            empresa = (re.search(r"\b(?:na|no|at|@)\s+([^|\-–—\[\]]+)$", titulo) or [None, ""])[1]
            vagas.append(_vaga("GitHub", url, re.sub(r"^\s*\[[^\]]+\]\s*", "", titulo),
                               empresa.strip() or repo.split("/")[0],
                               ("Remoto" if remoto else local) + f" • {repo}", pub,
                               " ".join(etiquetas) + "\n" + (i.get("body") or "")))
        time.sleep(1)
    return vagas


def coletar_remotar(ja_vistos):
    vagas, nesta_busca = [], set()
    nomes = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial", "on-site": "Presencial"}
    for termo in CFG["remotar"]:
        dados = _get(REMOTAR_BUSCA, {"search": termo}, json_=True)
        for j in dados.get("data", []):
            url = f"https://remotar.com.br/job/{j.get('id')}"
            if not j.get("id") or url in ja_vistos or url in nesta_busca or j.get("expired"):
                continue
            nesta_busca.add(url)
            pub = _data(j.get("createdAt"))
            if _velha(pub, "remotar"):
                continue
            modelo = j.get("type") or ""
            cidade, uf = (j.get("city") or ""), (j.get("state") or "")
            if not _local_ok(f"{cidade} {uf}", modelo == "remote"):
                continue
            requisitos = " ".join(r.get("description") or "" for r in j.get("jobRequirements") or [])
            empresa = (j.get("company") or {}).get("name") or j.get("companyDisplayName") or ""
            vagas.append(_vaga("Remotar", url, j.get("title"), empresa,
                               nomes.get(modelo, modelo) + (f" • {cidade}/{uf}" if cidade else ""),
                               pub, _limpa(j.get("description")) + " " + requisitos))
        time.sleep(1.5)
    return vagas


_descartadas = set()  # páginas de vaga já abertas e recusadas (evita reabrir a cada busca)


def _jsonld_vaga(pagina):
    for bruto in re.findall(r'<script type="application/ld\+json">(.*?)</script>', pagina, re.S):
        try:
            d = json.loads(bruto, strict=False)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            return d
    return {}


def coletar_programathor(ja_vistos):
    vagas = []
    corpo = _get(f"{PT_BASE}/jobs")
    for bloco in re.findall(r'<div class="cell-list[^"]*">(.*?)</a>', corpo, re.S):
        caminho = _campo(r'href="(/jobs/\d+[^"]*)"', bloco)
        url = PT_BASE + caminho
        if not caminho or url in ja_vistos or url in _descartadas:
            continue
        titulo = re.sub(r"\s+NOVA$", "", _campo(r"<h3[^>]*>(.*?)</h3>", bloco))
        local = _campo(r"fa-map-marker-alt'></i>(.*?)</span>", bloco)
        if not titulo_serve(titulo) or not _local_ok(local, bool(REMOTO.search(local))):
            _descartadas.add(url)
            continue
        try:
            pagina = _get(url)
        except requests.RequestException:
            continue
        time.sleep(1.2)
        ld = _jsonld_vaga(pagina)
        pub = _data(ld.get("datePosted"))
        if pub and pub.date() < _limite("programathor").date():
            _descartadas.add(url)  # a lista mistura vagas antigas em destaque no topo
            continue
        tags = re.findall(r"class='tag-list[^']*'>(.*?)</span>", bloco)
        vagas.append(_vaga("Programathor", url, titulo, _campo(r"fa-briefcase'></i>(.*?)</span>", bloco),
                           local, f"<t:{int(pub.timestamp())}:D>" if pub else "",
                           " ".join(tags) + "\n" + _limpa(ld.get("description")),
                           logo=(ld.get("hiringOrganization") or {}).get("logo")))
    return vagas


def _rsc(pagina, contem):
    """Stream RSC (self.__next_f.push) de uma página Next.js, só nos pedaços que têm `contem`
    (decodificar a página inteira custa ~25 MB de pico; a Discloud dá 100 MB pro bot todo)."""
    # cortes de string em vez de regex: um (?:[^"\\]|\\.)* sobre 400 KB empilha um retrocesso
    # por caractere e sobe a memória em ~25 MB
    partes = []
    for pedaco in pagina.split('self.__next_f.push([1,"')[1:]:
        fim = pedaco.find('"])</script>')
        if fim > 0 and contem in pedaco[:fim]:
            partes.append(json.loads(f'"{pedaco[:fim]}"'))
    return "".join(partes)


def coletar_geekhunter(ja_vistos):
    vagas, nesta_busca = [], set()
    niveis = {"intern": "Estágio", "entry": "Júnior", "mid": "Pleno", "senior": "Sênior"}
    modos = {"remote": "Remoto", "remote-in-city": "Remoto (na cidade)", "hybrid": "Híbrido", "on-site": "Presencial"}
    buscas = [{"searchTerm": t, "workModality": "remote"} for t in CFG["geekhunter"]]
    buscas += [{"searchTerm": "desenvolvedor", "cityName": c} for c in CFG["cidades"][:1]]
    for params in buscas:
        texto = _rsc(_get("https://www.geekhunter.com/pt/vagas", params), "PublicJob")
        for m in re.finditer(r'"data":\[\{"__typename":"PublicJob"', texto):
            try:
                lista, _ = json.JSONDecoder().raw_decode(texto, m.start() + len('"data":'))
            except ValueError:
                continue
            for item in lista:
                job = _dic(_dic(item).get("atsJob"))
                det = _dic(job.get("atsJobDetail")) or job
                empresa_slug = _dic(job.get("company")).get("slug") or ""
                url = f"https://www.geekhunter.com/pt/{empresa_slug}/jobs/{job.get('jobSlug')}"
                if not job.get("jobSlug") or url in ja_vistos or url in nesta_busca:
                    continue
                nesta_busca.add(url)
                pub = _data(job.get("publishedAt") or job.get("firstCreatedAt"))
                if _velha(pub, "geekhunter"):
                    continue
                modo = det.get("workModality") or ""
                cidades = [_limpa(json.dumps(c, ensure_ascii=False)) for c in det.get("atsJobCities") or []]
                cidade = ", ".join(re.findall(r'"name": "([^"]+)"', " ".join(cidades)))[:80]
                if not _local_ok(cidade or params.get("cityName", ""), modo.startswith("remote")):
                    continue
                skills = [_dic(_dic(s).get("atsSkill")).get("name", "") for s in det.get("atsJobSkills") or []]
                vagas.append(_vaga(
                    "GeekHunter", url, det.get("title"),
                    _dic(job.get("company")).get("name") or empresa_slug.replace("-", " ").title(),
                    " • ".join(x for x in (modos.get(modo, modo), cidade, niveis.get(det.get("experienceLevel"), ""))
                               if x),
                    pub, " ".join(skills) + "\n" + (det.get("description") or "")))
            break
        time.sleep(1.5)
    return vagas


def coletar_infojobs(ja_vistos):
    vagas, nesta_busca = [], set()
    for pagina_url in ("https://www.infojobs.com.br/vagas-de-emprego-desenvolvedor-trabalho-home-office.aspx",
                       "https://www.infojobs.com.br/vagas-de-emprego-desenvolvedor-em-para.aspx"):
        corpo = _get(pagina_url, {"campo": "griddate", "orden": "desc"})  # mais recentes primeiro
        for bloco in re.split(r'<div id="vacancy\d+"', corpo)[1:]:
            caminho = _campo(r'data-href="([^"]+)"', bloco)
            url = "https://www.infojobs.com.br" + caminho
            if not caminho or url in ja_vistos or url in nesta_busca:
                continue
            nesta_busca.add(url)
            pub = _data(_campo(r'class="js_date" data-value="([^"]+)"', bloco))
            if _velha(pub, "infojobs"):
                break
            # cartão: empresa, depois <div class="mb-8"> local </div>, depois tags (salário, formação, modalidade)
            local = _campo(r'<div class="mb-8">(.*?)</div>', bloco)
            tags = _campo(r'<div class="d-inline-flex flex-wrap mb-8[^"]*"[^>]*>(.*?)</div>\s*</div>', bloco)
            remoto = bool(REMOTO.search(tags) or REMOTO.search(local) or "todo brasil" in local.lower())
            titulo = _campo(r'js_vacancyTitle[^>]*>(.*?)</h2>', bloco)
            if not _local_ok(local, remoto) or not titulo_serve(titulo):
                continue
            # o cartão só traz ~150 caracteres; a descrição inteira fica na página da vaga
            try:
                descricao = _campo(r'<p class="[^"]*white-space-pre-line[^"]*">(.*?)</p>', _get(url))
                time.sleep(1)
            except requests.RequestException:
                descricao = ""
            sem_selo = re.sub(r'\s(?:data-bs-)?title="[^"]*"', "", bloco)  # tooltip do selo tem HTML dentro
            vagas.append(_vaga("InfoJobs", url, titulo,
                               _campo(r'<div class="text-body">\s*<a[^>]*>(.*?)</a>', sem_selo),
                               ("Home office • " if remoto else "") + local, pub,
                               descricao or _campo(r'<div class="text-medium">(.*?)</div>', bloco)))
        time.sleep(1.5)
    return vagas


def coletar_catho(ja_vistos):
    # a busca geral da Catho não diz se a vaga é remota (o filtro é só no JS); fica a busca da sua cidade
    vagas, nesta_busca = [], set()
    for cidade in CFG["cidades"][:1]:
        slug = re.sub(r"[^a-z]+", "-", _sem_acento(cidade).lower()).strip("-")
        uf = next((e for e in CFG["estados"] if len(e) == 2), "").lower()
        corpo = _get(f"https://www.catho.com.br/vagas/desenvolvedor/{slug}-{uf}/", {"order": "dataAtualizacao"})
        for bloco in re.split(r"<li data-offer-item=", corpo)[1:]:
            caminho = _campo(r'<h2 class="title_offer">\s*<a href="([^"]+)"', bloco)
            url = "https://www.catho.com.br" + caminho
            if not caminho or url in ja_vistos or url in nesta_busca:
                continue
            nesta_busca.add(url)
            pub = _data_relativa(_campo(r'<span class="tag [^"]*">(Publicada[^<]*)</span>', bloco))
            if _velha(pub, "catho"):
                continue
            local = _campo(r'i_job_location"></span>\s*(?:<strong>[^<]*</strong>\s*-\s*)?([^<]*)</p>', bloco)
            texto = _limpa(bloco)
            if not _local_ok(local, bool(REMOTO.search(texto))):
                continue
            vagas.append(_vaga("Catho", url, _campo(r'data-navigation-offer>(.*?)</a>', bloco),
                               _campo(r'<p class="mb-2">\s*<span class="text-12">(.*?)</span>', bloco),
                               local, pub, texto[:1500]))
        time.sleep(2)
    return vagas


def coletar_vagascom(ja_vistos):
    # os filtros por query string (?m[]=Home Office) dão 403; as URLs "amigáveis" funcionam
    vagas, nesta_busca = [], set()
    for termo in ("desenvolvedor", "programador"):
        corpo = _get(f"https://www.vagas.com.br/vagas-de-{termo}-home-office")
        for bloco in re.split(r'<li class="vaga\b', corpo)[1:]:
            caminho = _campo(r'href="(/vagas/v\d+/[^"]+)"', bloco)
            url = "https://www.vagas.com.br" + caminho
            if not caminho or url in ja_vistos or url in nesta_busca:
                continue
            nesta_busca.add(url)
            pub = _data_relativa(_campo(r'class="data-publicacao"[^>]*>(?:\s*<i[^>]*></i>)?(.*?)</span>', bloco))
            if _velha(pub, "vagascom"):
                continue
            local = _campo(r'class="vaga-local"[^>]*>(?:\s*<i[^>]*></i>)?\s*([^<]*)', bloco)
            if not _local_ok(local, bool(REMOTO.search(local))):
                continue
            vagas.append(_vaga("Vagas.com.br", url, _campo(r'<a[^>]*class="link-detalhes-vaga"[^>]*>(.*?)</a>', bloco)
                               or _campo(r'title="([^"]+)"', bloco),
                               _campo(r'class="emprVaga"[^>]*>(.*?)</span>', bloco), local, pub,
                               _campo(r'class="nivelVaga"[^>]*>(.*?)</span>', bloco) + " " +
                               _campo(r'class="detalhes"[^>]*>(.*?)</div>', bloco)))
        time.sleep(2)
    return vagas


def coletar_trampos(ja_vistos):
    vagas = []
    for pagina in range(1, 6):
        dados = _get("https://www.trampos.co/api/v2/opportunities", {"page": pagina}, json_=True)
        lista = dados.get("opportunities") or []
        for j in lista:
            if j.get("category_slug") not in ("programacao", "ti"):
                continue
            url = f"https://trampos.co/oportunidades/{j.get('id')}"
            if url in ja_vistos:
                continue
            pub = _data(j.get("published_at"))
            if _velha(pub, "trampos"):
                continue
            local = f"{j.get('city') or ''}/{j.get('state') or ''}".strip("/")
            remoto = bool(j.get("home_office") or j.get("remote") or REMOTO.search(f"{j.get('name')} {local}"))
            if not _local_ok(local, remoto):
                continue
            emp = j.get("company") or {}
            vagas.append(_vaga("Trampos", url, j.get("name"), j.get("custom_company_name") or emp.get("name", ""),
                               ("Remoto • " if remoto else "") + local, pub,
                               f"{j.get('type_name', '')} {j.get('category_name', '')} {j.get('salary', '')}"))
        if not lista:
            break
        time.sleep(1.5)
    return vagas


def coletar_empresas(ja_vistos):
    """ATS públicos (Greenhouse, Lever, Ashby) de empresas listadas em CFG['empresas']."""
    vagas, emp = [], CFG["empresas"]
    for slug in emp.get("greenhouse", []):
        try:
            # lista sem descrição (com content=true a Stone sozinha passa de 2 MB); a descrição
            # só é baixada para as vagas que passam no filtro, para caber nos 100 MB da Discloud
            dados = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", json_=True)
        except requests.RequestException:
            continue
        for j in dados.get("jobs", []):
            url = j.get("absolute_url") or ""
            if not url or url in ja_vistos or not titulo_serve(j.get("title")):
                continue
            pub = _data(j.get("first_published") or j.get("updated_at"))
            local = (j.get("location") or {}).get("name", "")
            if _velha(pub, "empresas") or not _local_ok(local, bool(REMOTO.search(local)) and _aberta_br(local)):
                continue
            try:
                conteudo = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{j.get('id')}",
                                json_=True).get("content") or ""
            except requests.RequestException:
                conteudo = ""
            vagas.append(_vaga("Greenhouse", url, j.get("title"), j.get("company_name") or slug, local, pub,
                               _limpa(html.unescape(conteudo))))
        del dados
        time.sleep(1)
    for slug in emp.get("lever", []):
        try:
            dados = _get(f"https://api.lever.co/v0/postings/{slug}", {"mode": "json"}, json_=True)
        except requests.RequestException:
            continue
        for j in dados:
            url = j.get("hostedUrl") or ""
            if not url or url in ja_vistos or not titulo_serve(j.get("text")):
                continue
            pub = _data(j.get("createdAt"))
            local = (j.get("categories") or {}).get("location", "")
            remoto = j.get("workplaceType") == "remote" and (j.get("country") in (None, "", "BR") or _aberta_br(local))
            if _velha(pub, "empresas") or not _local_ok(local, remoto):
                continue
            listas = " ".join(_limpa(x.get("content")) for x in j.get("lists") or [])
            vagas.append(_vaga("Lever", url, j.get("text"), slug.title(),
                               ("Remoto • " if remoto else "") + local, pub,
                               (j.get("descriptionPlain") or "") + " " + listas))
        time.sleep(1)
    for slug in emp.get("ashby", []):
        try:
            dados = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", json_=True)
        except requests.RequestException:
            continue
        for j in dados.get("jobs", []):
            url = j.get("jobUrl") or ""
            if not url or url in ja_vistos or not j.get("isListed", True) or not titulo_serve(j.get("title")):
                continue
            pub = _data(j.get("publishedAt"))
            local = j.get("location") or ""
            remoto = bool(j.get("isRemote") or REMOTO.search(local)) and _aberta_br(local)
            if _velha(pub, "empresas") or not _local_ok(local, remoto):
                continue
            vagas.append(_vaga("Ashby", url, j.get("title"), slug.title(), local, pub, j.get("descriptionPlain") or ""))
        time.sleep(1)
    return vagas

# ---------------------------------------------------------------------------
# LatAm / internacionais (remoto)
# ---------------------------------------------------------------------------
def coletar_getonbrd(ja_vistos):
    vagas = []
    for pagina in (1, 2):
        dados = _get("https://www.getonbrd.com/api/v0/categories/programming/jobs",
                     {"per_page": 100, "page": pagina, "country_code": "BR", "expand": '["company"]'}, json_=True)
        for j in dados.get("data", []):
            a = j.get("attributes") or {}
            url = (j.get("links") or {}).get("public_url") or f"https://www.getonbrd.com/jobs/{j.get('id')}"
            if url in ja_vistos or not titulo_serve(a.get("title")):
                continue
            pub = _data(a.get("published_at"))
            if _velha(pub, "getonbrd"):
                continue
            paises = ", ".join(a.get("countries") or [])
            if not a.get("remote") and not _na_regiao(paises):
                continue
            empresa = (((a.get("company") or {}).get("data") or {}).get("attributes") or {}).get("name", "")
            vagas.append(_vaga("GetOnBoard", url, a.get("title"), empresa, f"Remoto • {paises}", pub,
                               " ".join(_limpa(a.get(k)) for k in ("description", "projects", "functions", "desirable")),
                               candidatos=a.get("applications_count")))
        if pagina >= ((dados.get("meta") or {}).get("total_pages") or 1):
            break
        time.sleep(1.5)
    return vagas


def coletar_himalayas(ja_vistos):
    vagas, nesta_busca = [], set()
    for termo in CFG["internacional"]:
        dados = _get("https://himalayas.app/jobs/api/search", {"q": termo, "country": "BR"}, json_=True)
        for j in dados.get("jobs", []):
            url = j.get("applicationLink") or j.get("guid") or ""
            if not url or url in ja_vistos or url in nesta_busca or not titulo_serve(j.get("title")):
                continue
            nesta_busca.add(url)
            pub = _data(j.get("pubDate"))
            if _velha(pub, "himalayas"):
                continue
            sen = " ".join(j.get("seniority") or [])
            vagas.append(_vaga("Himalayas", url, j.get("title"), j.get("companyName"),
                               f"Remoto • {j.get('employmentType') or ''}", pub,
                               f"{sen}\n" + _limpa(j.get("description")), logo=j.get("companyLogo")))
        time.sleep(1.5)
    return vagas


def coletar_remotive(ja_vistos):
    vagas = []
    dados = _get("https://remotive.com/api/remote-jobs", {"category": "software-dev", "limit": 200}, json_=True)
    for j in dados.get("jobs", []):
        url = j.get("url") or ""
        if not url or url in ja_vistos or not titulo_serve(j.get("title")):
            continue
        pub = _data(j.get("publication_date"))
        local = j.get("candidate_required_location") or ""
        if _velha(pub, "remotive") or not _aberta_br(local):
            continue
        vagas.append(_vaga("Remotive", url, j.get("title"), j.get("company_name"), f"Remoto • {local}", pub,
                           " ".join(j.get("tags") or []) + "\n" + _limpa(j.get("description")),
                           logo=j.get("company_logo")))
    return vagas


def coletar_remoteok(ja_vistos):
    vagas = []
    for j in _get("https://remoteok.com/api", json_=True)[1:]:  # o 1º item é o aviso legal
        url = j.get("url") or ""
        if not url or url in ja_vistos or not titulo_serve(j.get("position")):
            continue
        pub = _data(j.get("date") or j.get("epoch"))
        local = j.get("location") or ""
        if _velha(pub, "remoteok") or not _aberta_br(local):
            continue
        vagas.append(_vaga("RemoteOK", url, j.get("position"), j.get("company"), f"Remoto • {local or 'Worldwide'}",
                           pub, " ".join(j.get("tags") or []) + "\n" + _limpa(j.get("description")),
                           logo=j.get("company_logo") or None))
    return vagas


def coletar_jobicy(ja_vistos):
    vagas, nesta_busca = [], set()
    for geo in ("brazil", "latam", "anywhere"):
        dados = _get("https://jobicy.com/api/v2/remote-jobs", {"count": 100, "geo": geo, "industry": "dev"}, json_=True)
        for j in dados.get("jobs", []):
            url = j.get("url") or ""
            if not url or url in ja_vistos or url in nesta_busca or not titulo_serve(j.get("jobTitle")):
                continue
            nesta_busca.add(url)
            pub = _data(j.get("pubDate"))
            if _velha(pub, "jobicy"):
                continue
            vagas.append(_vaga("Jobicy", url, j.get("jobTitle"), j.get("companyName"),
                               f"Remoto • {j.get('jobGeo') or ''}", pub,
                               f"{j.get('jobLevel') or ''}\n" + _limpa(j.get("jobDescription")),
                               logo=j.get("companyLogo")))
        time.sleep(1.5)
    return vagas


def coletar_workingnomads(ja_vistos):
    vagas = []
    for j in _get("https://www.workingnomads.com/api/exposed_jobs/", json_=True):
        url = j.get("url") or ""
        if not url or url in ja_vistos or j.get("category_name") not in (None, "", "Development") \
                or not titulo_serve(j.get("title")):
            continue
        pub = _data(j.get("pub_date"))
        local = j.get("location") or ""
        if _velha(pub, "workingnomads") or not _aberta_br(local):
            continue
        vagas.append(_vaga("WorkingNomads", url, j.get("title"), j.get("company_name"), f"Remoto • {local}"[:200],
                           pub, (j.get("tags") or "") + "\n" + _limpa(j.get("description"))))
    return vagas


def coletar_wwr(ja_vistos):
    vagas = []
    for cat in ("remote-full-stack-programming-jobs", "remote-back-end-programming-jobs",
                "remote-front-end-programming-jobs"):
        raiz = ET.fromstring(_get(f"https://weworkremotely.com/categories/{cat}.rss").encode())
        for item in raiz.iter("item"):
            url = (item.findtext("link") or "").strip()
            bruto = item.findtext("title") or ""
            empresa, _, titulo = bruto.partition(": ")
            if not url or url in ja_vistos or not titulo_serve(titulo or bruto):
                continue
            pub = _data(item.findtext("pubDate"))
            local = item.findtext("region") or ""
            if _velha(pub, "wwr") or not _aberta_br(local):
                continue
            vagas.append(_vaga("WeWorkRemotely", url, titulo or bruto, empresa if titulo else "",
                               f"Remoto • {local}", pub, _limpa(item.findtext("description"))))
        time.sleep(1)
    return vagas


# chave -> (nome, coletor, grupo). Ordem de execução: rápidas primeiro, LinkedIn por último.
FONTES = {
    "gupy": ("Gupy", coletar_gupy, "br"),
    "remotar": ("Remotar", coletar_remotar, "br"),
    "github": ("GitHub", coletar_github, "br"),
    "geekhunter": ("GeekHunter", coletar_geekhunter, "br"),
    "programathor": ("Programathor", coletar_programathor, "br"),
    "infojobs": ("InfoJobs", coletar_infojobs, "br"),
    "catho": ("Catho", coletar_catho, "br"),
    "vagascom": ("Vagas.com.br", coletar_vagascom, "br"),
    "trampos": ("Trampos", coletar_trampos, "br"),
    "empresas": ("Empresas (Greenhouse/Lever/Ashby)", coletar_empresas, "br"),
    "getonbrd": ("GetOnBoard", coletar_getonbrd, "intl"),
    "himalayas": ("Himalayas", coletar_himalayas, "intl"),
    "remotive": ("Remotive", coletar_remotive, "intl"),
    "remoteok": ("RemoteOK", coletar_remoteok, "intl"),
    "jobicy": ("Jobicy", coletar_jobicy, "intl"),
    "workingnomads": ("Working Nomads", coletar_workingnomads, "intl"),
    "wwr": ("We Work Remotely", coletar_wwr, "intl"),
    "linkedin": ("LinkedIn", coletar_linkedin, "br"),
}
