# Integrações de inteligência artificial

Pesquisa conferida em **28/10/2026**. Modelos e disponibilidade podem mudar; o catálogo pode ser atualizado na tela usando a chave do próprio workspace. As sugestões iniciais não garantem acesso nem saldo.

| Provedor | Modelos recentes verificados | Integração implementada |
| --- | --- | --- |
| OpenAI · ChatGPT | `gpt-6.1-terra`, `gpt-6.1-sol`, `gpt-6-astra`, `gpt-6-luna` | `POST https://api.openai.com/v1/responses`, Bearer, JSON Schema estrito, `store: false` |
| Anthropic · Claude | `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-opus-5-5`, `claude-fable-5-1` | `POST https://api.anthropic.com/v1/messages`, Bearer, `anthropic-version: 2026-10-21`; workspace Anthropic opcional |
| OpenRouter | Catálogo de vários fornecedores; verificadas as opções `openai/gpt-6.1-terra` e `anthropic/claude-sonnet-5.5` | `POST https://openrouter.ai/api/v1/chat/completions`, Bearer; histórico no formato de mensagens |

Os modelos iniciais escolhidos para redação são Terra e Sonnet. Isso é uma escolha do projeto para o fluxo de escrita, não uma garantia de que sejam os melhores para toda campanha. Não há fallback automático para outro provedor, modelo ou chave.

## Configuração

Em **Perfil → Integrações → Inteligência artificial**:

1. Crie uma chave na plataforma de API do provedor e cole no formulário correspondente.
2. Selecione o modelo sugerido ou informe outro ID de modelo de texto.
3. Salve e use **Testar conexão**. O teste consulta o catálogo sem gerar texto; confirma autenticação e presença do modelo, mas não comprova saldo para geração. No OpenRouter, consulta primeiro `GET /key`, pois o catálogo de modelos pode ser público.
4. **Atualizar modelos** consulta `GET /models` do provedor com a chave salva. A atualização não altera a seleção automaticamente: escolha o modelo e salve.
5. Chaves Anthropic que exigem seleção de workspace podem preencher `anthropic-workspace-id` nas opções do formulário.

Uma assinatura do aplicativo de chat não configura uma chave nesta plataforma. Saldo, acesso e faturamento seguem a conta de API do fornecedor. Nenhuma geração ocorre ao abrir a página, salvar a integração ou reiniciar o servidor.

## Conversa e revisão

Em **Mensagens → Assistente de IA**, selecione o provedor conectado e conte sobre produto, público, diferencial, oferta e objetivo. O assistente pode pedir informações e propor de uma a cinco mensagens com benefício concreto e CTA. O prompt orienta a não inventar preços, resultados, urgência ou garantias.

As conversas ficam no SQLite do workspace. Cada chamada envia o pedido atual e até 12 interações completas recentes, limitadas a aproximadamente 40 mil caracteres de histórico. Trocar o provedor faz a próxima chamada usar o provedor escolhido e esse contexto. O catálogo de leads e os contatos não são anexados automaticamente.

O resultado é exibido como texto, sem executar HTML ou ações. **Usar no editor** preenche um novo rascunho; o usuário revisa e salva pelo fluxo normal de Mensagens. O assistente não envia WhatsApp, não inicia disparos e não salva modelos sozinho. Se a IA responder fora da estrutura esperada, o texto é mostrado com aviso e sem sugestões acionáveis.

## Persistência e credenciais

- Esquema SQLite 5: `ai_integrations`, `ai_threads` e `ai_turns`, com chaves e conversas isoladas por workspace.
- Migração preserva a base anterior em `.before-ai-backup.sqlite3`.
- Chaves são cifradas com Fernet; a chave local fica em `.ai-credentials.key`, ao lado do banco. API e frontend só recebem uma indicação dos últimos quatro caracteres.
- Preserve o banco **e** `.ai-credentials.key` no backup. Se a chave local desaparecer, o aplicativo bloqueia a leitura em vez de criar outra chave silenciosamente.
- Remover uma integração apaga sua chave cifrada da configuração atual; conversas e backups anteriores não são removidos.
- Endpoints HTTPS são fixos; a aplicação não aceita URLs de API arbitrárias e não segue redirecionamentos com credenciais.
- Corpos de erros do fornecedor, chaves e prompts não são impressos nos logs da aplicação. Conversas e sugestões são armazenadas localmente como parte do produto.

## Erros e concorrência

Uma geração por workspace. Pedidos têm identificadores idempotentes: repetir o mesmo pedido com o mesmo identificador retorna o registro existente, sem nova chamada de geração. Não há repetição automática em timeout, limite, cota, falha de rede ou reinício. A falha aparece na conversa. O fornecedor pode ter processado uma chamada cujo resultado não chegou; consulte o histórico antes de repetir.

Gerações pendentes na inicialização ficam como interrompidas/falhas, sem retomada paga. Resultados truncados, modelos inválidos ou variáveis desconhecidas não geram modelos salvos.

## Fontes oficiais

- [Catálogo OpenAI](https://developers.openai.com/api/docs/models) e [GPT-6.1 Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra).
- [Geração de texto e Responses API](https://developers.openai.com/api/docs/guides/text).
- [Modelos Claude](https://platform.claude.com/docs/en/models/overview), [autenticação](https://platform.claude.com/docs/en/api/overview) e [Messages API](https://platform.claude.com/docs/en/api/messages/create).
- [Autenticação da chave OpenRouter](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key).
- [Catálogo OpenRouter](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties) e [Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion).
- [Terra no OpenRouter](https://openrouter.ai/openai/gpt-6.1-terra) e [Sonnet 5.5 no OpenRouter](https://openrouter.ai/anthropic/claude-sonnet-5.5).

## Validação

`python -m unittest tests.test_ai` verifica contratos dos três provedores, criptografia, isolamento, histórico, idempotência, concorrência e erros usando transporte injetado. `python -m tests.browser_ai` valida o fluxo web com dados temporários e sem chamadas pagas ou envio WhatsApp. Nenhum teste considera uma chave fictícia uma validação contra a API real: autenticação e geração reais dependem da chave cadastrada pelo usuário.


## Agente transversal — v0.6

O chat principal agora fica na aba Agentes. Configurações, modelos e conversas anteriores são reutilizados. O editor de Mensagens mantém a biblioteca; modelos podem ser criados e salvos pelo agente por ferramentas nativas. Veja [protocolos, ações e confirmações](AGENTS_GUIDE.md). Links antigos `/messages?tab=assistant&conversation=...` redirecionam para Agentes.
