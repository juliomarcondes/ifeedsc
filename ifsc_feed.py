#!/usr/bin/env python3
"""
Feed RSS de editais do IFSC para Criciuma e Tubarao.

Mantem apenas cursos de tecnologia (programacao, desenvolvimento, informatica,
redes, dados etc.) que sejam TECNICOS (subsequente/concomitante) ou
profissionalizantes (FIC / qualificacao). Descarta tecnico integrado ao ensino
medio, graduacao, pos e editais de selecao de servidores/tutores/bolsistas.

Uso:
    python ifsc_feed.py                 # varre a listagem + extra_urls.txt
    python ifsc_feed.py --url <PDF>     # testa um unico edital e mostra o resultado
"""
import argparse
import io
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin
from xml.sax.saxutils import escape

BASE = Path(__file__).resolve().parent
OUT = BASE / "docs"
STATE_FILE = OUT / "state.json"
FEED_FILE = OUT / "feed.xml"
EXTRA_URLS_FILE = BASE / "extra_urls.txt"

# ---------------------------------------------------------------- configuracao
# Paginas que listam editais. Ajuste conforme o que voce confirmar no navegador.
LISTING_URLS = [
    "https://www.ifsc.edu.br/editais-com-inscricoes-abertas",
    "https://www.ifsc.edu.br/editais",
]
FEED_TITLE = "Editais IFSC - Tecnologia (Criciuma e Tubarao)"
FEED_LINK = "https://www.ifsc.edu.br/editais-com-inscricoes-abertas"
FEED_DESC = ("Cursos tecnicos (nao integrados) e profissionalizantes de tecnologia "
             "nos campi Criciuma e Tubarao do IFSC.")
MAX_ITEMS = 60

TARGET_CAMPI = ["criciuma", "tubarao"]
ALL_CAMPI = [
    "ararangua", "cacador", "canoinhas", "chapeco", "criciuma", "florianopolis",
    "garopaba", "gaspar", "itajai", "jaragua do sul", "joinville", "lages",
    "palhoca", "sao carlos", "sao jose", "sao lourenco do oeste",
    "sao miguel do oeste", "tubarao", "urupema", "xanxere",
]
CAMPUS_LABEL = {"criciuma": "Criciúma", "tubarao": "Tubarão"}

# Palavras-chave (aplicadas ao texto SEM acentos e em minusculas).
KEYWORDS = [
    r"inform[a]tica", r"programa[c]ao", r"programador", r"desenvolvimento (de )?(web|sistemas|software|aplicativos|jogos|mobile)",
    r"desenvolvedor", r"analise e desenvolvimento", r"sistemas? (de informacao|para internet)",
    r"software", r"\bweb\b", r"front-?end", r"back-?end", r"full-?stack",
    r"\bpython\b", r"\bjava\b", r"javascript", r"\bphp\b", r"\bhtml\b", r"\bsql\b", r"\bgit\b",
    r"controle de versao", r"banco de dados", r"redes de computadores", r"computa[c]ao",
    r"ciencia de dados", r"analise de dados", r"inteligencia artificial",
    r"machine learning", r"seguranca da informacao", r"ciberseguranca", r"\blinux\b",
    r"\barduino\b", r"robotica", r"internet das coisas", r"\biot\b", r"aplicativos? mobile",
    r"logica de programacao", r"\bcloud\b|computacao em nuvem", r"\bdevops\b", r"\bti\b",
    r"testes? de software", r"ux ?/? ?ui|design de interface",
]
KEYWORD_RE = re.compile("|".join(f"(?:{k})" for k in KEYWORDS))

# Linhas que citam informatica apenas como pre-requisito / nocao basica.
EXCLUDE_LINE_RE = re.compile(
    r"pre-?requisit|nocoes? de informatica|conhecimentos? (basicos? )?(de|em) informatica|"
    r"saber usar (o )?computador|acesso a (computador|internet)|"
    r"\bbacharelado\b|\blicenciatura\b|superior de tecnologia|\bengenharia\b|"
    r"\bespecializacao\b|\bmestrado\b|\bdoutorado\b"
)
INTEGRADO_RE = re.compile(r"integrad")
# Editais inteiros que nao interessam (selecao de pessoal, pos etc.).
STAFF_HEAD_RE = re.compile(
    r"concurso publico|tutor(es|ia)?\b|bolsista|professor substituto|professor visitante|"
    r"pos-graduacao|especializacao|mestrado|doutorado|processo seletivo simplificado"
)

# ---------------------------------------------------------------- utilidades


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- classificacao


def edital_level(head_norm: str) -> str:
    """Tipo do edital: 'tecnico', 'fic' ou 'outro'."""
    if re.search(r"subsequente|concomitante", head_norm):
        return "tecnico"
    if re.search(r"qualificacao profissional|formacao inicial|\bfic\b|extensao", head_norm):
        return "fic"
    return "outro"


def skip_reason(url: str, text: str):
    """Retorna motivo para ignorar o edital inteiro, ou None."""
    head = norm(text[:2500])
    if re.search(r"integrad|[_-]int[_-]", norm(url)):
        return "integrado (url)"
    if re.search(r"cursos? tecnicos? integrados?|tecnico integrado", head) and not re.search(
        r"subsequente|concomitante|qualificacao|formacao inicial", head
    ):
        return "integrado (texto)"
    if STAFF_HEAD_RE.search(norm(text[:1500])):
        return "selecao de pessoal/pos"
    return None


def find_hits(text: str):
    """Procura linhas de tecnologia dentro das secoes dos campi alvo.

    Retorna lista de (campus, trecho).
    """
    lines = [l.strip() for l in text.splitlines()]
    nlines = [norm(l) for l in lines]
    current = None
    hits, seen = [], set()

    for i, (raw, nl) in enumerate(zip(lines, nlines)):
        if not nl:
            continue

        # Atualiza o campus corrente (cabecalho "Campus X" ou linha de tabela iniciada por X)
        found = [(nl.find(c), c) for c in ALL_CAMPI if re.search(rf"\b{re.escape(c)}\b", nl)]
        if found:
            pos, camp = min(found)
            is_heading = bool(re.match(r"^(c[a]mpus|campus)\s+", nl))
            if is_heading or nl.startswith(camp):
                current = camp

        # Fim da tabela de vagas: numeracao de clausula (4.2 ...), ANEXO ou titulo em caixa alta
        if not found and re.match(r"^(ANEXO\b|\d+(\.\d+)+\s|\d{1,2}\s+[A-Z\u00c0-\u00dc]{3,})", raw):
            current = None

        if current not in TARGET_CAMPI:
            continue
        if not KEYWORD_RE.search(nl) or EXCLUDE_LINE_RE.search(nl):
            continue

        context = " ".join(nlines[max(0, i - 2): i + 1])
        if INTEGRADO_RE.search(context):
            continue

        # Junta a linha anterior so quando o nome do curso quebrou em duas linhas
        # (linha atual nao comeca por campus e a anterior tambem nao).
        starts_campus = any(nl.startswith(c) for c in ALL_CAMPI) or nl.startswith("campus")
        prev_starts_campus = i > 0 and (
            any(nlines[i - 1].startswith(c) for c in ALL_CAMPI) or nlines[i - 1].startswith("campus")
        )
        if i > 0 and lines[i - 1] and not starts_campus and not prev_starts_campus:
            snippet = f"{lines[i - 1]} {raw}"
        else:
            snippet = raw
        snippet = re.sub(r"\s+", " ", snippet)[:180]
        key = (current, norm(snippet))
        if key not in seen:
            seen.add(key)
            hits.append((current, snippet))
    return hits


def edital_number(text: str, url: str) -> str:
    m = re.search(
        r"edital[^\n]{0,40}?n[\u00ba\u00b0o.]*\s*(\d+\s*/\s*[A-Za-z]+\s*/\s*\d{4}(?:\s*/\s*\d)?)",
        text[:3000], re.I)
    if m:
        return re.sub(r"\s+", "", m.group(1))
    return url.rstrip("/").split("/")[-1]


def inscricao_dates(text: str):
    m = re.search(r"(\d{2}/\d{2}(?:/\d{4})?\s*(?:a|ao|at[e\u00e9])\s*\d{2}/\d{2}/\d{4})", text[:5000])
    return re.sub(r"\s+", " ", m.group(1)) if m else None


def analyze(url: str, text: str):
    """Retorna (status, item|None). status: 'match' | 'no_match' | 'skip:<motivo>'."""
    reason = skip_reason(url, text)
    if reason:
        return f"skip:{reason}", None
    hits = find_hits(text)
    if not hits:
        return "no_match", None

    head = norm(text[:2500])
    level = {"tecnico": "Técnico", "fic": "FIC", "outro": "Curso"}[edital_level(head)]
    num = edital_number(text, url)
    campi = sorted({CAMPUS_LABEL[c] for c, _ in hits})
    dates = inscricao_dates(text)

    lines = [f"Edital {num} ({level}) - {', '.join(campi)}"]
    for camp, snip in hits[:12]:
        lines.append(f"- {CAMPUS_LABEL[camp]}: {snip}")
    if dates:
        lines.append(f"Inscrições (primeiro período de datas do edital): {dates}. Confira no PDF.")
    lines.append("Inscrição: https://sistemadeingresso.ifsc.edu.br/")

    item = {
        "url": url,
        "title": f"[{level}] Edital {num} - {', '.join(campi)}: tecnologia",
        "description": "\n".join(lines),
        "found": now_utc().isoformat(),
    }
    return "match", item


# ---------------------------------------------------------------- rede


def http_get(url: str, timeout: int = 60):
    import requests
    return requests.get(url, timeout=timeout, headers={"User-Agent": "ifsc-feed/1.0 (uso pessoal)"})


def pdf_text(content: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def collect_links():
    from bs4 import BeautifulSoup
    links = []
    for page in LISTING_URLS:
        try:
            r = http_get(page, 30)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[aviso] nao consegui abrir {page}: {e}", file=sys.stderr)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(page, a["href"])
            nh = norm(href)
            if ("/documents/" in nh or nh.endswith(".pdf")) and "calendario" not in nh:
                links.append(href)
    if EXTRA_URLS_FILE.exists():
        for line in EXTRA_URLS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                links.append(line)
    return list(dict.fromkeys(links))


# ---------------------------------------------------------------- feed e estado


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"processed": {}, "items": []}


def save_state(state):
    OUT.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def write_feed(items):
    items = sorted(items, key=lambda x: x["found"], reverse=True)[:MAX_ITEMS]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        f"<title>{escape(FEED_TITLE)}</title>",
        f"<link>{escape(FEED_LINK)}</link>",
        f"<description>{escape(FEED_DESC)}</description>",
        "<language>pt-BR</language>",
        f"<lastBuildDate>{format_datetime(now_utc())}</lastBuildDate>",
    ]
    for it in items:
        dt = datetime.fromisoformat(it["found"])
        parts += [
            "<item>",
            f"<title>{escape(it['title'])}</title>",
            f"<link>{escape(it['url'])}</link>",
            f'<guid isPermaLink="true">{escape(it["url"])}</guid>',
            f"<pubDate>{format_datetime(dt)}</pubDate>",
            f"<description>{escape(it['description'])}</description>",
            "</item>",
        ]
    parts.append("</channel></rss>")
    OUT.mkdir(parents=True, exist_ok=True)
    FEED_FILE.write_text("\n".join(parts), encoding="utf-8")


def process_url(url: str):
    r = http_get(url)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        return "skip:nao e PDF", None
    return analyze(url, pdf_text(r.content))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="testa um unico edital e imprime o resultado")
    args = ap.parse_args()

    if args.url:
        status, item = process_url(args.url)
        print("status:", status)
        if item:
            print(item["title"])
            print(item["description"])
        return

    state = load_state()
    links = collect_links()
    print(f"{len(links)} links candidatos")
    for url in links:
        if url in state["processed"]:
            continue
        try:
            status, item = process_url(url)
        except Exception as e:  # noqa: BLE001
            print(f"[erro] {url}: {e}", file=sys.stderr)
            continue  # tenta de novo na proxima execucao
        state["processed"][url] = {"status": status, "at": now_utc().isoformat()}
        print(f"{status:28s} {url}")
        if item:
            state["items"].append(item)

    save_state(state)
    write_feed(state["items"])
    print(f"feed: {FEED_FILE} ({len(state['items'])} itens)")


if __name__ == "__main__":
    main()
