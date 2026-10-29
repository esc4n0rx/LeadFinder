# Beautiful UI no LeadFinder

Componentes consultados no registro oficial em 28/10/2026 e adaptados para os templates Jinja, CSS nativo e JavaScript do Flask. A paleta semântica e os temas do LeadFinder foram mantidos. A licença MIT original está em `leadfinder/static/licenses/beautiful-ui-LICENSE.txt` e acompanha o pacote.

| Original | Aplicação no LeadFinder | SHA-256 do conteúdo consultado (prefixo) |
| --- | --- | --- |
| [ChatComposer](https://www.beautifului.dev/r/chat-composer.json) | Painel com cabeçalho, transcrição rolável e compositor que mantém sua posição | `1b8ac6cd342a5cca` |
| [PromptBar](https://www.beautifului.dev/r/prompt-bar.json) | Campo de mensagem, seletor de provedor/modelo e ação de envio | `1f2ff02adae3f1fe` |
| [LoadingState](https://www.beautifului.dev/r/loading-state.json) | Grade de pixels e tempo real de espera durante uma geração pendente | `eb1bdcddcd2dbdfe` |
| [RecommendationCard](https://www.beautifului.dev/r/recommendation-card.json) | Cartões de rascunho com revisão no editor e cópia do texto | `fe4c56f271f147bb` |
| [SearchList](https://www.beautifului.dev/r/search.json) | Filtro das conversas e combobox de modelos com navegação por teclado | `9fdb3720c5bc06f6` |

Fontes: [galeria](https://www.beautifului.dev/), [registro](https://www.beautifului.dev/r/registry.json), [repositório](https://github.com/slev12397/beautiful-ui), [licença](https://www.beautifului.dev/license).

## Organização

- `static/js/beautiful-ui.js`: funções de apresentação, loader, conteúdo seguro e cartão de sugestão.
- `static/css/beautiful-ui.css`: estilos dos componentes adaptados, com suporte a movimento reduzido.
- `static/js/ai-chat.js`: conversas, rascunhos, ações do compositor, consulta de resultados e estado de navegação.
- `static/js/ai-settings.js`: cartões de provedores, diálogo e busca de modelos.
- `static/css/ai-workspace.css`: composição responsiva no workspace.

Os estados visuais são ligados às requisições reais: o loader aparece somente enquanto há geração pendente, com tempo decorrido real. As respostas são exibidas quando a API conclui; não há animação que simule streaming nem dados de demonstração no produto. Nenhuma função dos exemplos de ferramentas, fontes externas ou ditado foi incluída como botão sem implementação.

## Comportamento

O chat ocupa a altura disponível e mantém o campo de mensagem no painel. A transcrição rola separadamente. Enter envia e Shift+Enter quebra a linha; composição de caracteres por IME não envia. O pedido aparece de imediato e o texto digitado para a próxima interação é preservado. A rolagem acompanha novas mensagens quando o usuário está no final; quem lê mensagens anteriores pode voltar ao fim pelo botão correspondente.

A lista de conversas pode ser recolhida no desktop e abre como gaveta no celular, com busca local e fechamento por Escape. A aba ativa e a conversa possuem URL recuperável. Sugestões só viram modelos salvos após revisão no editor.

As integrações apresentam um cartão por provedor. A configuração abre em diálogo com chave protegida, combobox de modelos, teste de conexão e atualização de catálogo. Alterações não salvas desabilitam teste e atualização, para não testar uma configuração anterior sem avisar. Fechar o diálogo limpa o campo da chave.

## Validação

`python -m tests.browser_ai` usa transporte e chaves fictícios. Verifica fluxo de configuração, seleção de modelos por teclado, contexto, estados pendentes, rascunho preservado, revisão e salvamento, Escape, busca de conversas, temas e permanência do compositor na viewport em diferentes larguras. Nenhuma geração paga ou mensagem WhatsApp é feita nesses testes.
