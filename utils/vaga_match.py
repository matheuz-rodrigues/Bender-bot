"""Motor de aderência de vagas (portado de Desktop/curriculos/vaga.py).

Diz qual dos 4 currículos enviar, o que a vaga pede e você cobre, as lacunas e a senioridade.
Mantenha em sincronia com o vaga.py se mudar os pesos lá.
"""

import re
import unicodedata

CURRICULOS = {
    "dotnet": {
        "arquivo": "Matheus Rodrigues - Desenvolvedor Full Stack (C#, .NET).pdf",
        "peso": {
            "c#": 4, "csharp": 4, ".net": 4, "dotnet": 4, "asp.net": 4, "mvc": 2,
            "entity framework": 3, "blazor": 2, "angularjs": 3, "sql server": 3,
            "azure": 2, "xamarin": 1, "wpf": 1, "totvs": 3, "erp": 2,
        },
    },
    "react": {
        "arquivo": "Matheus Rodrigues - Desenvolvedor Full Stack (React, Next.js, NestJS).pdf",
        "peso": {
            "react": 4, "next.js": 4, "nextjs": 4, "nestjs": 4, "nest.js": 4,
            "typescript": 3, "tailwind": 2, "front-end": 2, "frontend": 2,
            "styled-components": 1, "redux": 1, "vite": 1, "spa": 1,
        },
    },
    "backend": {
        "arquivo": "Matheus Rodrigues - Desenvolvedor Backend (Node.js, Python).pdf",
        "peso": {
            "node": 4, "node.js": 4, "express": 3, "python": 4, "django": 2,
            "fastapi": 2, "flask": 2, "api rest": 3, "restful": 2, "microservi": 2,
            "rabbitmq": 3, "kafka": 1, "postgres": 2, "mongodb": 2, "back-end": 2,
            "backend": 2, "prisma": 2,
        },
    },
    "geral": {
        "arquivo": "Matheus Rodrigues - Desenvolvedor Full Stack.pdf",
        # "full-stack" e "developer": vagas internacionais escrevem assim
        "peso": {"full stack": 4, "fullstack": 4, "full-stack": 4, "desenvolvedor": 1, "developer": 1},
    },
}

TENHO = {
    "javascript", "typescript", "node", "node.js", "express", "nestjs", "next.js",
    "react", "tailwind", "c#", ".net", "asp.net", "angularjs", "python",
    "postgres", "postgresql", "mysql", "sql server", "mongodb", "sql",
    "docker", "azure", "aws", "linux", "git", "ci/cd", "rabbitmq", "jest",
    "api rest", "restful", "prisma", "clean code", "scrum", "jira", "pwa",
}

NAO_TENHO = {
    "java", "spring", "spring boot", "kotlin", "swift", "flutter", "dart",
    "php", "laravel", "ruby", "rails", "go", "golang", "rust", "elixir",
    "angular 2", "vue", "svelte", "react native", "kubernetes", "terraform",
    "graphql", "redis", "elasticsearch", "kafka", "salesforce", "sap", "delphi",
}

ESTAGIO = ("estágio", "estagio", "estagiário", "estagiario", "trainee")

SENIORIDADE = {
    # estágio/trainee aceitos (no vaga.py original eram descartados)
    "estágio": 1, "estagio": 1, "estagiário": 1, "trainee": 1,
    "júnior": 3, "junior": 3, "jr": 2, "pleno": 2, "pl": 1,
    "sênior": -2, "senior": -2, "sr": -1, "especialista": -2,
    "tech lead": -3, "líder técnico": -3, "arquiteto": -3, "staff": -3,
}


def normaliza(t):
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def contem(termo, n):
    """Termos curtos alfanuméricos exigem fronteira de palavra ("pl" não casa "plataforma")."""
    t = normaliza(termo)
    if len(t) <= 3 and t.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", n) is not None
    return t in n


def _senioridade(n):
    return [(k, v) for k, v in SENIORIDADE.items() if contem(k, n)]


def avaliar(titulo, descricao):
    """Retorna dict com currículo, aderência, cobertas, lacunas e nível."""
    n = normaliza(f"{titulo}\n{descricao}")
    pontos = {}
    for nome, cfg in CURRICULOS.items():
        pontos[nome] = sum(p for termo, p in cfg["peso"].items() if contem(termo, n))
    melhor = max(pontos.items(), key=lambda x: x[1])
    cv = melhor[0] if melhor[1] else "geral"

    # Senioridade: o título manda (descrição de vaga pleno costuma citar "sênior" em outro contexto)
    sen = _senioridade(normaliza(titulo)) or _senioridade(n)
    soma = sum(v for _, v in sen)
    eh_estagio = any(contem(t, normaliza(titulo)) for t in ESTAGIO)
    if eh_estagio:
        soma = max(soma, 1)  # "estágio" no título vale mais que um "sênior" citado na descrição
    return {
        "curriculo": cv,
        "arquivo": CURRICULOS[cv]["arquivo"],
        "aderencia": melhor[1],
        "cobertas": sorted({t for t in TENHO if contem(t, n)}),
        "lacunas": sorted({t for t in NAO_TENHO if contem(t, n)}),
        "senioridade": soma,
        "rotulos_nivel": [k for k, _ in sen],
        "nivel": "estágio/trainee" if eh_estagio else
                 "júnior/pleno" if soma > 0 else ("fora da faixa" if soma < 0 else "não declarado"),
    }
