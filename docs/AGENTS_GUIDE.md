# Agentes e gestão de leads — v0.6

## Uso

Conecte a API de OpenAI, OpenRouter ou Claude em Perfil → Integrações → Inteligência artificial. A aba Agentes reutiliza o provedor, o modelo e as credenciais já configurados. O modelo deve suportar ferramentas. A integração usa Responses com function calling na OpenAI, tool_use/tool_result na Anthropic e tool_calls no OpenRouter. Não faz tentativas pagas automáticas em caso de erro.

Exemplos de pedidos:

- “Busque 30 cafeterias no CEP 21235-112, em um raio de 3 km, e salve na categoria Cafeterias.”
- “Crie uma mensagem curta para apresentar meu produto e convidar para uma demonstração.”
- “Organize estes leads no estágio Demonstração e crie o funil Cafeterias com telefone.”
- “Anote na ficha que este cliente pediu um retorno e crie um lembrete para amanhã às 14h.”
- “Prepare um disparo com esta mensagem para os leads da categoria Restaurantes.”

Os funis são visões segmentadas por texto, categoria, contato e presença de telefone, com as seis etapas já existentes. O seletor em Funil comercial permite alternar entre eles. O filtro digitado no quadro é combinado com o segmento e permanece ativo ao carregar mais cartões.

## Execução e revisão

As ferramentas consultam serviços do próprio domínio e são limitadas ao workspace autenticado. O modelo não recebe uma ferramenta genérica de SQL, arquivos, comandos, URLs ou credenciais. Textos externos são tratados como dados no prompt. Argumentos são validados no servidor e o resultado de cada ação é persistido antes da próxima etapa do modelo.

Consultas e alterações solicitadas, como criar mensagens, categorias, notas, lembretes, funis e organizar leads, podem ser executadas durante a conversa. O usuário vê registros concluídos, falhos, interrompidos ou pendentes, com links para os recursos criados. Uma falha posterior da API preserva e mostra as ações que já ocorreram.

Envios reais, agendas, retomadas e exclusões exigem uma proposta, revisão dos destinatários/textos ou leads, e clique humano em Confirmar ação. Não existe ferramenta para o modelo confirmar a própria proposta. Propostas expiram em 15 minutos e são invalidadas se os registros revisados mudarem. O número de telefone, os textos e os resultados da campanha seguem as validações existentes do WhatsApp. Iniciar execução não equivale a entrega ou leitura. Campanhas são acompanhadas em Automação.

Cada pedido tem chave de idempotência; repetições da requisição não geram outra chamada ao modelo. Escritas idênticas na mesma rodada não são repetidas. O ciclo aceita até 10 etapas e 16 ferramentas, no máximo 4 por resposta. Há limite de 180 segundos, verificado entre chamadas. Uma chamada de rede em andamento pode terminar depois desse limite. Ações interrompidas no reinício não são repetidas automaticamente. Um novo pedido do usuário é uma nova operação; confira os resultados anteriores antes de repetir.

O histórico mantém texto de conversa, provedor, modelo, uso reportado, contexto de produto e auditoria das ações. O raciocínio interno não é salvo; itens criptografados exigidos pelo protocolo Responses ficam apenas na memória daquela requisição. Os dados consultados podem ser enviados ao provedor selecionado para que ele opere o workspace.

## Leads e extração

A home mantém os filtros, progresso e resumo da coleta. A tabela foi concentrada em Leads; uma coleta concluída com resultados abre a tabela filtrada pela busca quando o usuário ainda está na home. Navegar para outra área durante a coleta não é interrompido.

Editar permite corrigir nome, telefone, endereço, categoria do Maps, site, horários, descrição, coordenadas, nota e quantidade de avaliações. A identidade da origem, link do Maps e datas de coleta são preservados. Uma nova coleta pode atualizar os campos corrigidos. Modelos e textos já preparados em campanhas são snapshots e não mudam com a edição do lead.

Excluir aceita um lead ou até 1.000 selecionados e sempre mostra a lista antes da confirmação. A revisão usa uma impressão do registro e de sua última atividade. Os vínculos de buscas, categorias, notas, lembretes e perfil comercial são removidos em uma transação. O histórico e os textos das campanhas são preservados. Há bloqueio quando existem tentativas pendentes, em envio ou sem confirmação em campanhas ativas destes telefones; cancele ou conclua essas campanhas antes de excluir.

## Migração e backup

O esquema 8 acrescenta lead_funnels e ai_tool_calls. Antes da migração de uma base existente, o arquivo `.before-agents-backup.sqlite3` é criado. As tabelas e os registros anteriores permanecem preservados.

O backup portátil passa ao formato 8 e continua aceitando arquivos de formato 7. Inclui funis e auditoria das ações. Categorias dos filtros são remapeadas na restauração; um segmento cuja categoria foi removida não é ampliado para todos os leads. Propostas pendentes e execuções interrompidas são restauradas como canceladas, sem aprovação ou execução automática. Links históricos das ações importadas não são tratados como IDs atuais; consulte os recursos pelas abas. As demais regras de criptografia e restauração atômica permanecem em `GROWTH_PHASE.md`.

## Validação

`tests/test_agents.py` usa transportes nativos simulados para os três provedores, bancos temporários e WhatsApp fictício. `tests/browser_agents.py` cobre mensagens/funis criados, histórico, links antigos, revisão/execução, edição/exclusão, extração para Leads e responsividade. `tests/browser_ai.py` mantém a regressão das integrações e conversas anteriores. Nenhum desses testes exige credenciais reais ou envia mensagens externas.

## Protocolos consultados

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Anthropic tool definitions](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- [OpenRouter tool calling](https://openrouter.ai/docs/guides/features/tool-calling)
