# Robô de Controle de Apólices THI / PHAS

Aplicativo local para Windows que consulta e-mails IMAP SSL, seleciona anexos PDF da Finlândia Seguros, classifica documentos com OpenRouter multimodal, extrai dados com saída estruturada, organiza PDFs e atualiza um Excel operacional preservando colunas manuais.

> O projeto não contém credenciais. A primeira execução operacional exige configuração do `.env`, acesso à conta e um modelo OpenRouter que aceite PDFs e structured outputs. Faça primeiro um dry-run com documentos reais e revise as saídas antes de ativar tarefas agendadas.

## Arquitetura

`app.main` orquestra `email_client` (IMAP UID, sem depender de UNSEEN), `attachment_processor` (validação e papéis por IA), `pdf_processor` (até 3 páginas da apólice), `openrouter_client` + `prompt` (PDFs multimodais, schema), `models`/`validator` (Pydantic), `file_manager` (SHA-256 e publicação) e planilhas `excel_apolices` e `excel_robot_control`. Há retries limitados para IMAP e OpenRouter, logs rotativos e pasta temporária por mensagem.

## Instalação (Windows)

1. Instale Python 3.12 (marque “Add Python to PATH”).
2. Extraia/clonar o repositório para um diretório local permanente.
3. Execute `instalar.bat`.
4. Edite `.env` com credenciais IMAP, chave OpenRouter e caminhos.
5. Execute `python -m app.main --test` e depois `executar_dry_run.bat`.

Dependências: Python 3.12+, IMAP SSL, acesso HTTPS ao OpenRouter, permissão de escrita no diretório de documentos e no Excel. A conta do Windows que executa as tarefas precisa manter acesso a esses locais.

## Configuração `.env`

Copie `.env.example` para `.env` (o instalador faz isso). Preencha `EMAIL_USER`, `EMAIL_PASSWORD`, `OPENROUTER_API_KEY`; confirme `PASTA_RAIZ`, `CONTROLE_APOLICES`, remetentes permitidos e nomes THI/PHAS. `OPENROUTER_MODEL` é configurável, por exemplo `google/gemini-2.5-flash`; confirme no catálogo OpenRouter suporte a anexos PDF e JSON Schema. `DRY_RUN=true` ativa modo simulação também na execução normal. Não compartilhe nem versione `.env`.

## Uso e testes

```powershell
.venv\Scripts\python.exe -m app.main --test
.venv\Scripts\python.exe -m app.main --dry-run
.venv\Scripts\python.exe -m app.main
```

`--test` é um smoke test offline. `--dry-run` conecta, baixa e analisa, mas não publica arquivos, altera planilha nem registra sucesso; deixa temporários disponíveis para diagnóstico. Execução normal exige credenciais. Testes unitários: `pytest -q`.

## Agendamento Windows

Depois da instalação e validação manual, abra PowerShell na pasta do projeto e execute `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` se sua política permitir; então `./instalar_tarefa_windows.ps1`. Ele registra tarefas diárias às 06:00 e 21:00 com diretório correto e `IgnoreNew`. O Task Scheduler pode solicitar senha/permissões para executar sem sessão interativa; revise a identidade e configure-a no próprio Windows. Para remover, `./remover_tarefas_windows.ps1`.

## Estrutura de dados e planilhas

- `controle_robo.xlsx`, aba `EMAILS_PROCESSADOS`: message-id/UID, hashes, estado (`PENDENTE`, `PROCESSANDO`, `SUCESSO`, `ERRO`, `IGNORADO`), erro e destino. É criado sob demanda.
- `controle_apolices.xlsx`: operacional existente é aberto e preservado; o robô atualiza exclusivamente as dez colunas gerenciadas. Campos recebidos como null não apagam valores existentes; as demais colunas, linhas e conteúdo manual não são alterados. Antes de salvar, cria cópia em `backups/`; grava em temporário, valida e substitui atomicamente.
- `data/temp/<id>/`: anexos e resposta JSON; mantido em erro e removido após sucesso (configurável).
- `logs/robo.log`: log rotativo. O `.gitignore` exclui dados locais sensíveis.

A chave lógica de atualização usa empresa+SEI+concorrência; sem SEI, empresa+concorrência+órgão. Correspondência ambígua ou chave ausente não altera a planilha. A publicação do par PDF também evita sobrescrita de um destino com conteúdo diferente.

## Funcionamento da IA

Classifica anexos PDFs por conteúdo; exige exatamente uma apólice e um boleto. Envia até três páginas da apólice e o boleto inteiro como PDFs, solicita schema JSON estrito no OpenRouter e valida com Pydantic. Dados mínimos para publicação: empresa (tipo THI/PHAS), órgão, concorrência normalizada e datas. Sem confiança/dados suficientes, mantém temporários e registra erro para revisão, sem publicar. A chave nunca é incluída nos logs.

## Troubleshooting

- **Login IMAP:** confirme host/porta SSL, senha, autenticação externa/app password e permissões da caixa.
- **Remetentes não encontrados:** ajuste `ALLOWED_SENDER_DOMAINS` separado por vírgula; a busca percorre mensagens da pasta, incluindo lidas.
- **HTTP 400/402/429 OpenRouter:** confirme suporte do modelo a PDF/structured outputs, créditos/rate limits e limites de contexto.
- **Excel bloqueado:** feche o workbook no Excel e tente de novo; nenhuma alteração parcial é gravada.
- **POSSIVEL_DUPLICATA ou erro de classificação:** consulte `logs/robo.log` e `data/temp/<id>/resultado.json`, revise manualmente.
- **Task Scheduler:** confira conta, caminho da pasta, permissões de rede/arquivos e histórico da tarefa.

O robô não envia e-mails, não altera mensagens no servidor e não move/apaga mensagens. Uma execução sem mensagem nova não chama o OpenRouter.
