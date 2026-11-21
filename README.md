# Radar de Licitações

Site que mostra, em um só lugar, as licitações **abertas** (ainda recebendo propostas) publicadas no PNCP, de todos os estados. Um robô em Python coleta os dados automaticamente 3 vezes ao dia e o site só lê o resultado.

## Arquivos

| Arquivo | Função |
|---|---|
| `index.html` | O site (filtros, funil de status, exportar CSV) |
| `coletor.py` | Robô que consulta a API oficial do PNCP e gera `licitacoes.json` |
| `requirements.txt` | Dependência do robô (`requests`) |
| `.github/workflows/coletar.yml` | Agenda o robô no GitHub (07h, 12h e 18h de Brasília) |

## Publicar de graça (GitHub Pages) — passo a passo

1. Crie uma conta em github.com e um repositório **novo**, ex.: `radar-licitacoes`.
2. Envie todos os arquivos desta pasta (inclusive a pasta `.github`) para o repositório.
   - Pelo site: *Add file → Upload files*. A pasta `.github` precisa ser arrastada junto; se o navegador não enviar pastas ocultas, crie o arquivo manualmente em *Add file → Create new file* com o nome `.github/workflows/coletar.yml` e cole o conteúdo.
3. Vá em **Settings → Pages**, em *Source* escolha **Deploy from a branch**, branch `main`, pasta `/ (root)`.
4. Vá em **Settings → Actions → General → Workflow permissions** e marque **Read and write permissions**.
5. Vá na aba **Actions → Coletar licitações → Run workflow** para rodar a primeira coleta. Leva alguns minutos.
6. Seu site fica em `https://SEU-USUARIO.github.io/radar-licitacoes/`.

Dali em diante ele se atualiza sozinho.

> Repositórios públicos têm Actions e Pages gratuitos. Os dados são públicos (PNCP), mas o **status do funil** (Nova/Orçando/Descartada) fica só no seu navegador (localStorage) — não é compartilhado entre computadores.

## Rodar no seu computador

```bash
pip install -r requirements.txt
python coletor.py              # gera licitacoes.json (~ alguns minutos)
python -m http.server 8000     # abra http://localhost:8000
```

(Abrir o `index.html` com duplo clique não carrega o JSON por restrição do navegador; use o servidor acima ou o botão *Importar JSON*.)

## Ajustes

Variáveis do coletor (no workflow ou no terminal):

- `FILTRO=todas` — traz **todas** as licitações abertas, não só engenharia.
- `DIAS_A_FRENTE=90` — considera propostas que encerram em até N dias.

As palavras-chave de engenharia ficam no topo do `coletor.py` (listas `FORTES`, `LUGARES`, `ACOES`, `EXCLUIR`). Escreva sem acento; o texto é normalizado antes da comparação.

## O que mudou em relação ao seu código original

- Usa `/contratacoes/proposta` (só licitações **ainda abertas**) em vez de "publicadas nos últimos 3 dias".
- Varre por UF, com página de 50 (limite da API) e novas tentativas em erro/limite de requisições. O original parava em silêncio no primeiro erro.
- Filtro por palavra inteira e sem acento: antes "ubs" casava com "substituição" e "obra" com "cobrança".
- O site não apaga mais o histórico: o status que você marca fica salvo por ID e não se perde quando o JSON é atualizado.
- Textos vindos da API são escapados (evita injeção de HTML) e o CSV protege contra fórmulas do Excel.
- A fonte Compras.gov.br foi removida: o PNCP já reúne as contratações da Lei 14.133 de todos os órgãos, inclusive os federais. Licitações da Lei 8.666 antiga e portais próprios de alguns estados (ex.: BEC/SP, que não publica no PNCP) podem ficar de fora.
