#!/usr/bin/env python3
"""
Coletor de licitações ABERTAS do PNCP (Portal Nacional de Contratações Públicas).

- Usa o endpoint oficial /contratacoes/proposta: só traz licitações que ainda
  estão recebendo propostas (nada de editais já encerrados).
- Varre estado por estado (27 UFs) com paginação de 50 itens (máximo da API).
- Filtra por engenharia/obras com palavras inteiras (sem falsos positivos
  como "ubs" dentro de "substituição" ou "obra" dentro de "cobrança").
- Grava licitacoes.json, que o index.html lê.

Variáveis de ambiente (opcionais):
  FILTRO=engenharia|todas   (padrão: engenharia)
  DIAS_A_FRENTE=90          (considera propostas que encerram em até N dias)
"""
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_URL = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
FILTRO = os.getenv("FILTRO", "engenharia").strip().lower()
DIAS_A_FRENTE = int(os.getenv("DIAS_A_FRENTE", "90"))
TAMANHO_PAGINA = 50  # máximo aceito pela API de contratações
PAUSA = 0.3          # segundos entre páginas (a API limita rajadas)
SAIDA = Path(__file__).with_name("licitacoes.json")

UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]

# ----------------------------------------------------------------------------
# PALAVRAS-CHAVE (edite à vontade). O texto é comparado em minúsculas e SEM
# acentos, então escreva sem acento. "\b" = início/fim de palavra.
# ----------------------------------------------------------------------------

# Termos que, sozinhos, caracterizam obra/serviço de engenharia.
FORTES = [
    r"(?<!mao de )\bobras?\b", r"\bengenharia\b", r"\bpaviment", r"\brecapeamento",
    r"\basfalt", r"\bcbuq\b", r"\btapa[- ]?buracos?\b", r"\bfresagem", r"\bterraplen",
    r"\bterraplan", r"\bdrenagem", r"\bmacrodrenagem", r"\bsaneamento", r"\besgot",
    r"\badutora", r"\bestacao (?:elevatoria|de tratamento)", r"\babastecimento de agua",
    r"\bpontes?\b", r"\bviaduto", r"\bpassarela", r"\bmuro de arrimo", r"\btalude",
    r"\bciclovia", r"\bcalcadas?\b", r"\bsubestacao", r"\bestrutura metalica",
    r"\bconcreto armado", r"\bsondagem", r"\btopografi", r"\bprojeto (?:executivo|basico)",
    r"\bfiscalizacao de obra", r"\bgerenciamento de obra", r"\bimpermeabilizacao",
    r"\bmanutencao predial", r"\bedificac", r"\bmeio[- ]fio", r"\bsarjeta",
    r"\bsinalizacao viaria", r"\biluminacao publica", r"\burbanizacao",
    r"\bhidrossanitari", r"\binstalacoes eletricas", r"\bmicrorrevestimento",
]

# Termos "fracos": só valem quando aparece um LUGAR junto com uma AÇÃO
# (ex.: "reforma" + "escola"), para não pegar "reforma administrativa".
LUGARES = (
    r"\b(?:escolas?|creches?|ubs|unidades? basicas?|unidades? de saude|postos? de saude|"
    r"hospital|hospitais|pracas?|quadras?|ginasios?|predios?|cemiterios?|mercados?|"
    r"bibliotecas?|estadios?|rodoviaria|telhados?|coberturas?|muros?|banheiros?|"
    r"patios?|quartel|delegacia|forum|fachadas?)\b"
)
ACOES = (
    r"\b(?:construcao|reforma|ampliacao|requalificacao|revitalizacao|restauro|"
    r"restauracao|demolicao)\b"
)

# Compras de material/serviços comuns que NÃO são obra (só descartam se o texto
# não mencionar "obra" ou "engenharia").
EXCLUIR = (
    r"\b(?:aquisicao|compra|fornecimento|locacao)\s+de\s+(?:medicamentos?|generos? alimenticios|"
    r"veiculos?|material de expediente|mobiliario|computadores?|equipamentos? de informatica|"
    r"material de limpeza|uniformes?|combustiveis?|material escolar|material hospitalar|"
    r"merenda|pneus|material de construcao)"
)

CATEGORIAS = [
    ("Pavimentação", [r"\bpaviment", r"\brecapeamento", r"\basfalt", r"\bcbuq\b", r"\btapa[- ]?buraco",
                      r"\bterrapl", r"\bfresagem", r"\bmeio[- ]fio", r"\bsarjeta", r"\bsinalizacao viaria",
                      r"\bmicrorrevestimento"]),
    ("Saneamento", [r"\bdrenagem", r"\bmacrodrenagem", r"\bsaneamento", r"\besgot", r"\badutora",
                    r"\bestacao (?:elevatoria|de tratamento)", r"\babastecimento de agua", r"\bgalerias?\b"]),
    ("Infraestrutura/OAE", [r"\bpontes?\b", r"\bviaduto", r"\bpassarela", r"\bmuro de arrimo", r"\btalude",
                            r"\bobra de arte", r"\bciclovia", r"\bsubestacao", r"\biluminacao publica",
                            r"\bsondagem", r"\btopografi"]),
    ("Edificações", [r"\bedificac", r"\bmanutencao predial", r"\bimpermeabilizacao", r"\bestrutura metalica",
                     r"\bconcreto armado", r"\bhidrossanitari", r"\binstalacoes eletricas"]),
]


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


FORTES_RE = [re.compile(p) for p in FORTES]
LUGARES_RE = re.compile(LUGARES)
ACOES_RE = re.compile(ACOES)
EXCLUIR_RE = re.compile(EXCLUIR)
OBRA_RE = re.compile(r"(?<!mao de )\bobras?\b|\bengenharia\b")
CATEGORIAS_RE = [(nome, [re.compile(p) for p in pads]) for nome, pads in CATEGORIAS]


def classificar(objeto: str):
    """Devolve a categoria, ou None se o objeto não parece obra/engenharia."""
    t = normalizar(objeto)
    forte = any(rx.search(t) for rx in FORTES_RE)
    contexto = bool(LUGARES_RE.search(t) and ACOES_RE.search(t))
    if not (forte or contexto):
        return None
    if EXCLUIR_RE.search(t) and not OBRA_RE.search(t):
        return None
    for nome, regexes in CATEGORIAS_RE:
        if any(rx.search(t) for rx in regexes):
            return nome
    if contexto:
        return "Edificações"
    return "Outros"


class ErroApi(Exception):
    pass


def consultar(sessao: requests.Session, params: dict, tentativas: int = 5) -> dict:
    ultimo = ""
    for i in range(tentativas):
        try:
            r = sessao.get(BASE_URL, params=params, timeout=40)
        except requests.RequestException as e:
            ultimo = str(e)
        else:
            if r.status_code == 200:
                return r.json()
            if r.status_code == 204:
                return {"data": [], "totalPaginas": 0}
            if r.status_code in (429, 500, 502, 503, 504):
                ultimo = f"HTTP {r.status_code}"
                try:
                    espera = int(r.headers.get("Retry-After", "0"))
                except ValueError:
                    espera = 0
                if espera:
                    time.sleep(min(espera, 60))
            else:
                raise ErroApi(f"HTTP {r.status_code}: {r.text[:200]}")
        time.sleep(min(2 ** (i + 1), 30))
    raise ErroApi(f"falhou após {tentativas} tentativas ({ultimo})")


def coletar_uf(sessao, uf: str, data_final: str) -> list:
    itens, pagina = [], 1
    while True:
        corpo = consultar(sessao, {
            "dataFinal": data_final,
            "uf": uf,
            "pagina": pagina,
            "tamanhoPagina": TAMANHO_PAGINA,
        })
        dados = corpo.get("data") or []
        itens.extend(dados)
        total = corpo.get("totalPaginas") or 0
        if not dados or pagina >= total:
            return itens
        pagina += 1
        time.sleep(PAUSA)


def converter(item: dict, categoria: str):
    org = item.get("orgaoEntidade") or {}
    uni = item.get("unidadeOrgao") or {}
    cnpj, ano, seq = org.get("cnpj"), item.get("anoCompra"), item.get("sequencialCompra")
    id_ = item.get("numeroControlePNCP") or (f"{cnpj}-{ano}-{seq}" if cnpj and ano and seq else None)
    if not id_:
        return None
    link = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}" if cnpj and ano and seq else "https://pncp.gov.br"
    return {
        "id": id_,
        "fonte": "PNCP",
        "modalidade": item.get("modalidadeNome") or "",
        "orgao": org.get("razaoSocial") or "",
        "uf": uni.get("ufSigla") or "",
        "municipio": uni.get("municipioNome") or "",
        "categoria": categoria,
        "objeto": item.get("objetoCompra") or "",
        "valor_estimado": item.get("valorTotalEstimado") or 0,
        "data_publicacao": item.get("dataPublicacaoPncp") or "",
        "data_abertura": item.get("dataAberturaProposta") or "",
        "data_encerramento": item.get("dataEncerramentoProposta") or "",
        "situacao": item.get("situacaoCompraNome") or "",
        "link": link,
        "link_origem": item.get("linkSistemaOrigem") or "",
    }


def carregar_anterior() -> list:
    try:
        dados = json.loads(SAIDA.read_text(encoding="utf-8"))
        return dados["licitacoes"] if isinstance(dados, dict) else dados
    except Exception:
        return []


def main() -> int:
    if FILTRO not in ("engenharia", "todas"):
        print("FILTRO deve ser 'engenharia' ou 'todas'", file=sys.stderr)
        return 2

    agora = datetime.now(timezone(timedelta(hours=-3)))  # horário de Brasília
    data_final = (agora + timedelta(days=DIAS_A_FRENTE)).strftime("%Y%m%d")
    sessao = requests.Session()
    sessao.headers.update({"User-Agent": "RadarLicitacoes/3.0 (uso pessoal)", "Accept": "application/json"})

    anterior = carregar_anterior()
    resultado, falhas, total_api = {}, [], 0

    for uf in UFS:
        try:
            brutos = coletar_uf(sessao, uf, data_final)
        except ErroApi as e:
            print(f"[{uf}] ERRO: {e}", file=sys.stderr)
            falhas.append(uf)
            continue
        total_api += len(brutos)
        mantidos = 0
        for item in brutos:
            categoria = classificar(item.get("objetoCompra", ""))
            if categoria is None and FILTRO == "todas":
                categoria = "Outros"
            if categoria is None:
                continue
            conv = converter(item, categoria)
            if conv:
                resultado[conv["id"]] = conv
                mantidos += 1
        print(f"[{uf}] {len(brutos)} abertas na API, {mantidos} após o filtro")

    if len(falhas) > len(UFS) // 2:
        print("Muitas UFs falharam; mantendo o arquivo anterior sem alterações.", file=sys.stderr)
        return 1

    # UFs que falharam: preserva o que já existia delas, para não sumirem do site.
    for item in anterior:
        if item.get("uf") in falhas and item.get("id") not in resultado:
            resultado[item["id"]] = item

    lista = sorted(resultado.values(), key=lambda x: (x.get("data_encerramento") or "9999", x.get("id")))
    saida = {
        "atualizado_em": agora.isoformat(timespec="seconds"),
        "filtro": FILTRO,
        "total_na_api": total_api,
        "ufs_com_falha": falhas,
        "licitacoes": lista,
    }
    tmp = SAIDA.with_suffix(".tmp")
    tmp.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(SAIDA)
    print(f"Concluído: {len(lista)} licitações salvas (de {total_api} abertas na API). Falhas: {falhas or 'nenhuma'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
