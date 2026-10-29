# LeadFinder workspace design system

Referência: [Kargul Calendar Design](https://github.com/kargulstudio/calender-app-design),
commit `b4a9e8bb927724cf69ba34013b221114ab9456c3`. A composição e os tokens neutros
foram adaptados ao fluxo de descoberta de estabelecimentos. A marca usa verde.
Créditos e licenças estão em [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Estrutura

- Barra superior de 53 px: marca, título da seção, acesso ao filtro e nova busca.
- Sidebar de 240 px: catálogo, histórico, tema e menu do usuário com perfil e saída.
- Header: nome do workspace atual e título da seção; no celular, nome do workspace acima do título.
- Área central: formulário de descoberta e progresso da coleta.
- Resumo lateral de 304 px: totais reais de estabelecimentos, telefones e websites.
- Catálogo abaixo: busca, filtro por coleta, tabela, detalhes e paginação.

A interface usa divisórias de 1 px para organizar as áreas. Superfícies grandes
não têm cartões elevados ou cantos exagerados. Controles usam raio de 8 px;
diálogos, 12 px. Sombra fica reservada a diálogos e toasts.

## Tokens e temas

`leadfinder/static/css/app.css` concentra os valores semânticos. Novos componentes
devem usar variáveis, sem definir uma paleta independente.

| Token | Uso | Claro | Escuro |
|---|---|---|---|
| `--bg-app` | Shell, sidebar, resumo | `#f8f8f8` | `#121212` |
| `--bg-surface` | Conteúdo, tabela, diálogos | `#ffffff` | `#181818` |
| `--bg-selected` | Navegação selecionada | `#eaeae6` | `#262624` |
| `--border-hairline` | Divisórias | `#e5e7e1` | `#2a2a28` |
| `--text-primary` | Texto principal | `#1d1d1d` | `#ededed` |
| `--text-secondary` | Texto de apoio | `#757575` | `#9a9a9a` |
| `--brand` | Ações, links e foco | `#168153` | `#6bd4a5` |

`data-theme="light|dark"` no elemento `html` seleciona o tema. O script externo
`theme.js` aplica a preferência antes do CSS carregar. Na primeira visita, segue
o sistema operacional. O controle **Modo escuro** salva a escolha na chave
`leadfinder-theme` do `localStorage`. Sem acesso ao storage, a troca continua
funcionando na aba atual. Mudanças da preferência são sincronizadas entre abas;
mudanças do sistema são seguidas enquanto não houver escolha manual.

## Tipografia e componentes

Geist variável, armazenada e servida localmente. Peso padrão 500, espaçamento
entre letras de aproximadamente -2%, títulos e seções entre 16 e 20 px, controles
e texto entre 12 e 14 px. Textos longos usam entrelinha de 1.45 a 1.7.

Ícones SVG compartilham `currentColor` e traço de 1.7 px, com tamanhos de 14 a
22 px. O arquivo `templates/icons.html` contém os símbolos reutilizáveis.
O destaque de ação usa verde com realce superior discreto. Estados de sucesso,
erro e resultado parcial usam tokens de estado; o texto comunica o resultado
sem depender apenas da cor.

## Interação e responsividade

- **Nova busca** foca o termo e retorna ao catálogo a partir do histórico.
- **Ctrl K / Cmd K** foca o filtro do catálogo.
- **Escape** fecha os detalhes; o foco retorna ao botão que abriu o diálogo.
- O tema usa um `switch` acessível por teclado e informa seu estado com `aria-checked`.
- Todos os controles têm foco visível. Existe um link para pular ao conteúdo.
- Até 900 px, o resumo passa para baixo do formulário.
- Até 760 px, a navegação vira uma faixa horizontal e os campos se reorganizam.
- A tabela mantém suas colunas e permite rolagem horizontal dentro do contêiner.
- Em dispositivos de toque, campos usam fonte mínima de 16 px para evitar zoom.
- `prefers-reduced-motion` desativa transições e animações.

Execute `python -m tests.browser_smoke` para verificar os dois temas, persistência,
preferência do sistema, storage indisponível, navegação e larguras de 320 a 1920 px.

## Contas e filtros da fase 2

As telas de boas-vindas, cadastro, login, setup e perfil usam os mesmos tokens e
a mesma fonte, com estilos de composição em `static/css/auth.css`. Formulários
informam erros junto aos campos, não repopulam senhas e mantêm autocomplete próprio
para usuário, senha atual e senha nova. O setup só aparece até a criação do workspace.

O formulário de descoberta agrupa CEP e raio em um `fieldset` opcional. Confirmar
o CEP apresenta endereço e referência aproximada. A região por texto fica inativa
quando o CEP é preenchido para comunicar qual origem será usada. A confirmação
mostra estado de carregamento. Filtros por telefone usam controles nativos acessíveis.
O histórico apresenta CEP, raio e quantidades ignoradas por motivo.

## Mensagens e WhatsApp

A versão 0.3 adiciona Mensagens e Automação ao grupo Conexões da sidebar. O editor
divide biblioteca, texto e prévia com cliente fictício. As variáveis aparecem em
botões pequenos, e a prévia é texto escapado, sem renderizar HTML.

Automação apresenta configuração e revisão lado a lado no desktop, empilhadas no
mobile. Mensagens selecionadas recebem números que indicam a sequência. Rascunhos
salvam a personalização antes do envio; a revisão distingue Simulação local de
Envio real e mostra resultados por mensagem.

Perfil e Integrações usam abas no mesmo nível. A tela de WhatsApp agrupa nome,
número, ações de conexão e QR. QR e credenciais nunca aparecem em toasts ou logs.
Os estados de conexão são explícitos e a ação de envio real fica desabilitada
enquanto a integração não estiver conectada.

Os componentes usam os tokens existentes em `outreach.css`, sem paleta separada.
`python -m tests.browser_outreach` verifica as novas telas com provedor fictício;
nenhum envio real é feito pelo teste visual.


## Assistente de campanhas e IA

Integrações usam a mesma área central do workspace, com abas WhatsApp/Inteligência artificial. Cartões mostram chave salva, modelo, teste e atualização de catálogo, sem exibir credenciais completas. Mensagens tem alternância entre Editor e Assistente de IA. O assistente reúne histórico de campanhas, seletor de provedor, conversa e sugestões com ação explícita de revisão no editor. Sugestões usam os mesmos tokens, bordas, tipografia e temas; erros ficam na conversa. As colunas se empilham em telas menores, sem rolagem horizontal da página.


O assistente usa adaptações nativas dos componentes ChatComposer, PromptBar, LoadingState, RecommendationCard e SearchList do Beautiful UI. A transcrição ocupa o espaço rolável do painel e o compositor permanece acessível. O histórico vira gaveta no celular; a configuração de IA usa cartões e um diálogo com busca de modelos. Consulte `docs/BEAUTIFUL_UI.md` para origem e licença.
