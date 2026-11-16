# Feed RSS - editais IFSC (Criciúma e Tubarão)

Só cursos de tecnologia, técnicos não integrados e FIC/qualificação.

## Publicar
1. Crie um repositório no GitHub e suba esta pasta.
2. Settings > Pages > Branch `main`, pasta `/docs`.
3. Actions > "Atualizar feed IFSC" > Run workflow (depois roda sozinho todo dia).
4. Assine `https://SEU-USUARIO.github.io/SEU-REPO/feed.xml` no Feedly/Inoreader.

## Testar localmente
    pip install -r requirements.txt
    python ifsc_feed.py --url "<link do PDF do edital>"
    python -m unittest

## Se a listagem do site não for lida
O site pode montar a lista com JavaScript. Nesse caso cole os links dos PDFs em
`extra_urls.txt` ou ajuste `LISTING_URLS` em `ifsc_feed.py`.
