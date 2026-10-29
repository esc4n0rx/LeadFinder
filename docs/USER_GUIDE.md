# Guia de uso do LeadFinder

[← Voltar à apresentação do projeto](../README.md)

Um caçador de leads local e open source. Pesquise um termo no Google Maps, visite os estabelecimentos encontrados e organize as informações públicas em uma base SQLite.

**Versão 0.6:** agente transversal em uma aba própria, execução de ações auditáveis, funis segmentados e edição/exclusão revisada de leads. Inclui descoberta e categorias, leads com ficha e ações em lote, funil comercial, lembretes, campanhas com pausa/recuperação/agendamento, contexto de produto para IA e exportação/backup cifrado. Mantém contas e workspaces isolados, WhatsApp e assistente com OpenAI, OpenRouter e Claude. A integração atual não inclui caixa de entrada ou leitura automática de respostas.

Veja o [guia de Agentes e edição de leads](AGENTS_GUIDE.md) e o [fluxo dos oito recursos, regras de recuperação e backup](GROWTH_PHASE.md).

## Rodar localmente

Requer **Python 3.11+** e conexão com a internet para consultar o Maps.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m leadfinder
```

Para a integração nativa de WhatsApp, instale também **Node.js 22.12+** e suas dependências (o frontend continua sem build Node):

```powershell
$env:PUPPETEER_SKIP_DOWNLOAD = "true"
npm.cmd ci --prefix leadfinder/integrations/whatsapp
```

No macOS/Linux, use `npm` em vez de `npm.cmd`. O bridge reutiliza o Chromium instalado pelo Playwright. Sem as dependências Node, catálogo e simulação continuam funcionando; a tela de integração informa como instalar o conector.

Abra **http://127.0.0.1:5000**. No macOS/Linux, use `.venv/bin/python` no lugar de `.\.venv\Scripts\python.exe`.

## Conta e primeiro acesso

1. Na tela de boas-vindas, escolha **Criar minha conta**.
2. Informe nome, nome de usuário, email e senha (8 a 128 caracteres).
3. Crie seu workspace no primeiro acesso. Ele aparece no header da aplicação.
4. Nas próximas visitas, entre com **nome de usuário e senha**.
5. No rodapé da sidebar, abra o menu do usuário para editar o perfil ou sair. Alterações de perfil exigem a senha atual e renovam a sessão; alterar a senha também revoga sessões anteriores.

Cada conta possui um workspace e vê apenas seu catálogo, buscas e estatísticas. As senhas são armazenadas com hash scrypt. As sessões duram até 7 dias e podem ser revogadas ao sair. O email é cadastral: esta versão não envia verificação nem recuperação por email. O banco e os dados permanecem na instalação local; criar uma conta não publica o workspace na internet.

**Base da fase 1:** na primeira inicialização da versão 0.2, a migração cria um backup ao lado do banco, com o sufixo `.phase1-backup.sqlite3`, antes de alterar o esquema. A primeira conta criada recebe os dados anteriores ao concluir o setup, com um aviso na tela. Contas seguintes começam vazias. Registros antigos sem telefone são preservados; o filtro **Com telefone** do catálogo pode ocultá-los.

## Fazer uma busca

1. Informe um termo, como `lojas de açaí`.
2. Opcionalmente, informe uma região, como `Irajá, Rio de Janeiro`. Sem região, os resultados dependem da localização determinada pelo Google.
3. Para restringir a área, informe um **CEP brasileiro** e um **raio entre 0,5 e 50 km**. Use **Confirmar CEP** para conferir o endereço e as coordenadas aproximadas. O CEP prevalece sobre a região por texto.
4. **Ignorar locais sem telefone** vem ativado. Desmarque se quiser coletar locais sem esse dado.
5. Escolha o limite de 10, 30, 50 ou 100 leads aceitos e inicie a busca.
6. Acompanhe a coleta. Os leads aparecem conforme as páginas são lidas.
7. Consulte o catálogo, filtre por texto, busca ou telefone e abra os detalhes para copiar o telefone ou visitar o Maps/site.

### Como o raio é aplicado

A BrasilAPI confirma o endereço do CEP. O Google Maps confirma a área postal e seu centro aproximado. As coordenadas genéricas de cidade eventualmente devolvidas pelo serviço de CEP não são usadas. A referência fica em cache por CEP enquanto o processo está aberto.

Antes de salvar cada estabelecimento, o servidor verifica a distância de Haversine em relação ao centro confirmado. O raio é **em linha reta**, não distância por ruas. Locais fora do raio ou sem coordenadas verificáveis são ignorados. Se o CEP não puder ser confirmado, a operação informa o erro e não inicia uma busca ampla. O histórico guarda CEP, raio, referência usada e totais ignorados por motivo.

Para tentar atingir o limite de leads aceitos, a coleta pode examinar até 3 vezes o limite, com mínimo de 100 e máximo de 300 candidatos quando há filtros. O Google pode oferecer menos resultados; a coleta não promete cobrir todos os locais da área.

## WhatsApp, mensagens e automação

### Conectar sua conta

1. Abra o menu do usuário → **Ajustes do perfil** → **Integrações**.
2. Cadastre seu nome de envio e seu número com DDD/código do país e salve.
3. Clique em **Conectar / restaurar sessão**.
4. No celular, abra WhatsApp → Aparelhos conectados → Conectar aparelho e escaneie o QR code.
5. Aguarde o estado **Conectado**. O número vinculado precisa ser o mesmo número configurado.

A implementação usa [whatsapp-web.js](https://wwebjs.dev/guide/) e `LocalAuth`. É uma integração pelo WhatsApp Web, não a API oficial WhatsApp Business. A sessão é guardada em `instance/whatsapp/`, isolada por workspace e ignorada pelo Git. O QR fica só em memória; não é salvo no banco nem impresso no terminal. Ao reiniciar o servidor, as integrações habilitadas restauram automaticamente a sessão existente. Navegar entre telas ou sair da conta do LeadFinder não desconecta o WhatsApp. O botão **Desconectar** remove o vínculo local explicitamente. Se o WhatsApp revogar o vínculo, será necessário escanear um novo QR.

O nome de envio é uma configuração do LeadFinder, não altera o nome do perfil no WhatsApp. Para trocar o número, desconecte primeiro. **Desconectar** fecha a conexão e remove as credenciais locais deste workspace; se estiver offline, remova também o aparelho pelo celular quando necessário. Faça uso responsável com destinatários que esperam suas mensagens.

### Criar mensagens

Na sidebar, abra **Mensagens**, dê um nome ao modelo e escreva o texto. O editor oferece uma prévia com um cliente fictício e botões para inserir variáveis:

| Variável | Substituição |
|---|---|
| `{{nome}}`, `{{empresa}}` | Nome do estabelecimento; não inventa nome de uma pessoa |
| `{{telefone}}` | Telefone do destinatário |
| `{{endereco}}`, `{{categoria}}`, `{{site}}` | Dados disponíveis do local |
| `{{meu_nome}}` | Nome da integração; na simulação sem integração, nome do usuário |
| `{{workspace}}` | Nome do workspace atual |

Campos ausentes ficam vazios. Apenas essas variáveis são substituídas, sem executar Jinja, HTML ou código. Cada modelo aceita até 4.000 caracteres; após personalização, o limite é 8.000. Modelos arquivados deixam de aparecer na seleção e não alteram disparos já preparados.

### Preparar e executar um disparo

1. Abra **Automação** e informe o nome do disparo.
2. Escolha explicitamente **Simulação local · sem envio**, **Enviar pelo WhatsApp · número de teste** ou **Enviar pelo WhatsApp · leads do catálogo**. Para o número de teste, informe o telefone com DDD/código do país e conecte a integração; esse modo envia de verdade somente após a revisão e o clique em iniciar.
3. Selecione de 1 a 5 mensagens na ordem desejada. Cada destinatário receberá essa sequência.
4. Para envio real, selecione até 100 estabelecimentos do seu workspace, usando o filtro de busca se desejar. Telefones inválidos ou repetidos são excluídos e informados na revisão. Telefones brasileiros com DDD recebem o prefixo 55; para internacionais, use `+código do país`.
5. Clique em **Preparar e revisar disparo**. Isso salva um rascunho com uma cópia imutável dos textos personalizados e dos destinatários. Ainda não envia nada.
6. Confira os textos e execute a simulação ou inicie o disparo real. Envios reais só são liberados com integração ativa e o número remetente correto.

**Simulação local:** permite personalizar o nome e, opcionalmente, o telefone com DDD ou código do país. O telefone aparece na revisão e na variável `{{telefone}}`. A simulação continua local, sem chamada ao provedor nem envio ao número informado. Funciona sem WhatsApp conectado e registra resultados como **Simulado** e **Simulação concluída · sem envio**. Para refinar o texto, edite o modelo e prepare outro disparo.

**Envio real:** sequencial, com intervalo configurável de 3 a 120 segundos, e uma execução por workspace por vez. A conexão e o remetente são conferidos antes de iniciar e entre mensagens. **Aceita pelo WhatsApp** exige identificador e confirmação de recebimento pelo servidor (ACK ≥ 1); não confirma entrega nem leitura pelo cliente. Esta versão não possui inbox nem acompanhamento posterior de recibos.

**Cancelamento e falhas:** o cancelamento preserva os resultados e impede mensagens seguintes; uma mensagem que já entrou em envio pode terminar. Se houver timeout ou encerramento durante a tentativa, o resultado fica **Sem confirmação** e a execução para. Confira o WhatsApp antes de preparar outro envio para aquele destinatário. Não há reenvio automático, retomada automática ou garantia de envio exatamente uma vez perante falhas de rede. A retomada manual executa somente os pendentes, após conferir as tentativas sem confirmação; mensagens anteriores não são repetidas.

Os disparos continuam no servidor se a aba for fechada ou o usuário sair da conta. Encerrar o processo interrompe a execução; no próximo início, execuções ativas são marcadas como interrompidas e tentativas em andamento ficam sem confirmação. Modelos, rascunhos, resultados, integração e destinatários sempre pertencem ao workspace autenticado.

As bases anteriores são migradas com backup antes das alterações. O esquema atual é o 8; a última migração cria `.before-agents-backup.sqlite3`. Consulte os detalhes de recuperação em [AGENTS_GUIDE.md](AGENTS_GUIDE.md).

## Inteligência artificial para campanhas

Em **Perfil → Integrações → Inteligência artificial**, cadastre a chave de API da OpenAI, OpenRouter ou Anthropic/Claude, escolha o modelo e teste a conexão. A lista inicial foi pesquisada em **28/10/2026**; **Atualizar modelos** consulta o catálogo do provedor. O teste de conexão consulta os modelos sem gerar texto.

Na sidebar, abra **Agentes**, selecione o provedor e converse sobre produto, público, oferta e objetivo. Cadastre primeiro o contexto em **Workspace**. O agente consulta os registros e pode salvar mensagens, criar categorias e funis segmentados, organizar leads, adicionar notas e lembretes e preparar disparos. As ações executadas aparecem na conversa. Envios reais, agendamentos, retomadas e exclusões exigem revisão e confirmação humana na interface.

**Mensagens** mantém a biblioteca e o editor manual. As conversas anteriores continuam em Agentes. O chat mantém o compositor visível; Enter envia e Shift+Enter quebra a linha. No celular, o botão de conversas abre o histórico. Os componentes foram adaptados do Beautiful UI, com licença e origem em [BEAUTIFUL_UI.md](BEAUTIFUL_UI.md).

As chaves ficam cifradas com Fernet e nunca são devolvidas completas ao navegador. Preserve o banco e o arquivo `.ai-credentials.key` no backup da pasta `instance/`. A migração para o esquema 5 cria `.before-ai-backup.sqlite3`. Saldo e limites são os da API cadastrada; uma assinatura de aplicativo de chat não configura esta conexão.

Veja os modelos pesquisados, endpoints, fontes oficiais, privacidade e testes em [docs/AI_INTEGRATIONS.md](AI_INTEGRATIONS.md).

## Dados coletados

Quando presentes na página pública: nome, categoria, telefone comercial, endereço, website, nota, quantidade de avaliações, horários, Plus Code, coordenadas do estabelecimento, descrição, preço, características e status exibido pelo Maps. Cada registro guarda também sua URL de origem, primeira/última coleta e buscas em que foi encontrado.

Campos ausentes permanecem vazios. Não há inferência de números, e-mails ou dados indisponíveis. Coordenadas são lidas do identificador do local na URL, nunca do centro do mapa. A coleta não visita sites externos para enriquecer dados nem guarda textos/autores de avaliações.

O catálogo deduplica pelo identificador do estabelecimento dentro de cada workspace, usando a URL como fallback quando não houver identificador. Repetir uma busca atualiza os campos disponíveis e preserva informações coletadas anteriormente. URLs sem identificador podem produzir duplicidades quando o Google altera o caminho. Os resultados refletem os candidatos apresentados pelo Maps; não são uma varredura geográfica completa.

## Configuração

Variáveis de ambiente opcionais (veja `.env.example`; o arquivo não é carregado automaticamente):

| Variável | Padrão | Uso |
|---|---|---|
| `LEADFINDER_DATABASE` | `instance/leadfinder.sqlite3` | Caminho da base local |
| `LEADFINDER_HEADLESS` | `true` | `false` abre o navegador durante a coleta |
| `LEADFINDER_BROWSER_CHANNEL` | vazio | `chrome` ou `msedge` para navegador instalado |
| `LEADFINDER_PORT` | `5000` | Porta do servidor local |
| `LEADFINDER_SECURE_COOKIES` | `false` | `true` exige HTTPS para os cookies; use em uma implantação HTTPS |
| `LEADFINDER_NODE_BINARY` | `node` no PATH | Caminho opcional para Node.js 22.12+ |
| `LEADFINDER_WHATSAPP_BROWSER` | Chromium do Playwright | Caminho opcional para Chrome/Chromium da integração |

Exemplo no PowerShell:

```powershell
$env:LEADFINDER_HEADLESS = "false"
$env:LEADFINDER_BROWSER_CHANNEL = "msedge"
.\.venv\Scripts\python.exe -m leadfinder
```

O servidor Waitress escuta apenas em `127.0.0.1`, com múltiplas contas locais e **um processo de aplicação**, uma coleta por workspace e até duas coletas simultâneas no servidor. Não execute múltiplos servidores apontando para a mesma base. Uma interrupção é aplicada entre operações do navegador; uma navegação pode levar até 45 segundos para terminar. Fechar somente a aba web ou sair da conta mantém a coleta ativa. Encerrar o processo interrompe o trabalho e, na próxima abertura, a busca é marcada como interrompida; os leads salvos são preservados. Não há retomada automática de execuções interrompidas; pendentes podem ser retomados após revisão.

Para backup, encerre o servidor antes de copiar a pasta `instance/`, incluindo o banco e `.session-secret`. A chave é gerada localmente e preserva os tokens CSRF entre reinicializações. A pasta, os bancos e a chave são ignorados pelo Git para evitar publicação de contatos e credenciais.

## Estrutura

```text
leadfinder/
  __init__.py              # Factory e composição das dependências
  __main__.py              # Entrada do servidor local
  models.py                # Registro de domínio
  repository.py            # Persistência SQLite e consultas parametrizadas
  schema.sql               # Esquema inicial (user_version=1)
  services.py              # Coleta em background, progresso e cancelamento
  accounts.py              # Contas, sessões revogáveis e propriedade dos workspaces
  auth.py                  # Login, cadastro, setup e perfil com CSRF
  migrations.py            # Migração transacional e preservação do catálogo v1
  geography.py             # CEP, raio e distância de Haversine
  outreach.py              # Modelos, snapshots de disparos e configuração de integração
  campaigns.py             # Execução sequencial e resultados persistentes por mensagem
  outreach_routes.py       # Rotas autenticadas de mensagens, integração e disparos
  integrations/
    whatsapp_runtime.py    # Comunicação privada Python ↔ Node por stdin/stdout
    whatsapp/              # Bridge whatsapp-web.js, package.json e lockfile
  routes.py                # Validação, API e proteções HTTP
  collectors/
    google_maps.py         # Navegação e seletores do Maps
    geocoding.py           # Confirmação do centro da área postal no Maps
    parsing.py             # Normalização pura dos dados públicos
  templates/index.html     # Interface Flask/Jinja
  static/css/app.css        # Design escuro e responsivo
  static/js/app.js          # Catálogo, polling, detalhes e toasts
tests/                     # Persistência, API, fluxo de coleta e parsing
```

Flask + SQLite da biblioteca padrão + Playwright. Frontend em HTML, CSS e JavaScript, sem build Node ou CDN. A interface adapta o design system do [Kargul Calendar Design](https://github.com/kargulstudio/calender-app-design), com fonte Geist servida localmente, superfícies neutras e verde como destaque. Inclui temas claro e escuro: o controle **Modo escuro** fica na navegação lateral e salva a preferência no navegador. Na primeira visita, segue o tema do sistema. O botão **Nova busca** foca o formulário; **Ctrl K / Cmd K** abre o filtro do catálogo. Há navegação por teclado, estados vazios, toasts, progresso e suporte a movimento reduzido.

Consulte os [tokens e padrões de interface](DESIGN_SYSTEM.md) e os [créditos e licenças de terceiros](../THIRD_PARTY_NOTICES.md).

O coletor e o resolvedor de CEP são injetados na factory; testes podem substituir serviços externos. Escritas de leads e vínculos com buscas são transacionais. Conexões SQLite não são compartilhadas entre threads. Consultas usam parâmetros, são limitadas ao workspace autenticado e o frontend escapa os textos coletados. Mutações HTTP exigem token CSRF por sessão; os cookies de autenticação são HttpOnly/SameSite=Lax, e apenas hashes de tokens ficam no banco. O servidor limita tentativas de login, valida o host local e envia uma Content Security Policy restritiva.

## Verificação

### Categorias e acompanhamento de leads

Em **Estabelecimentos**, use **Gerenciar categorias** para criar, renomear ou excluir grupos. Escolha uma categoria em **Salvar na categoria** antes de iniciar a busca: os resultados entram nesse grupo automaticamente. A categoria de organização não altera a classificação informada pelo Google Maps. Um lead encontrado novamente pode pertencer a vários grupos; a coleta preserva os anteriores.

A home **Estabelecimentos** é dedicada à extração. Ao concluir uma busca com resultados, o aplicativo abre **Leads**, filtrado pela busca. No histórico, **Ver leads** abre essa mesma tabela. Na sidebar, **Leads** abre a tabela com categorias, contatos, localização, avaliações e datas. Combine os filtros de texto, categoria e status, navegue pelas páginas ou use **Organizar** para ajustar os grupos de um estabelecimento. Excluir um grupo preserva os leads. Os registros antigos começam sem categoria e podem ser organizados pela mesma tela. Use **Editar** para corrigir os dados de um estabelecimento e **Excluir** para revisar e apagar um lead ou uma seleção. Disparos pendentes destes contatos precisam ser cancelados ou concluídos antes da exclusão.

Os status são **Sem contato**, **Contato iniciado** e **Já houve conversa**. Um envio real aceito pelo WhatsApp marca o contato como iniciado, inclusive no histórico existente. Simulações, envios incertos e testes com cliente fictício não alteram contatos reais. A confirmação de conversa é manual; o aplicativo não infere uma resposta a partir de um envio. A migração para o esquema 6 cria o backup `.before-categories-backup.sqlite3` antes de atualizar uma base existente.

Teste de interface com dados temporários, sem buscas externas ou mensagens reais:

```powershell
.\.venv\Scripts\python.exe -m tests.browser_directory
```

### Agentes

Converse pela aba **Agentes** usando a API já conectada em Integrações. O agente consulta e organiza leads, busca estabelecimentos (inclusive por CEP/raio), salva mensagens, cria funis segmentados, notas, lembretes e rascunhos de disparos. Cada ação mostra seu resultado na conversa. Envios reais, agendamentos, retomadas e exclusões são propostas para revisão e confirmação pelos botões da interface; responder “sim” no chat não inicia essas ações.

A aba **Mensagens** mantém o editor e a biblioteca de modelos. As conversas antigas continuam disponíveis em Agentes. Os funis criados aparecem no seletor de **Funil comercial**, com as etapas comerciais existentes.

```powershell
.\.venv\Scripts\python.exe -m tests.browser_agents
```

### Testes automatizados

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes unitários não dependem de resultados reais do Google. Para verificar a integração externa, rode o app e pesquise um termo específico com uma região e limite de 10 locais. Compare telefone/endereço nos detalhes com a página de origem. O Google pode alterar DOM, resultados, idioma e telas de consentimento; seletores ficam isolados em `collectors/google_maps.py` para facilitar manutenção. Uma falha externa é exibida no histórico e não apaga os leads salvos.

Verificações opcionais com Chromium instalado:

```powershell
# Fluxo web desktop/mobile com dados fictícios em uma base temporária.
.\.venv\Scripts\python.exe -m tests.browser_smoke
# Consulta real de até 3 cafeterias em Irajá/RJ, sem alterar o catálogo.
.\.venv\Scripts\python.exe -m tests.live_maps
# Validação real de CEP + raio + telefone com até 3 leads em base temporária.
.\.venv\Scripts\python.exe -m tests.live_phase2
# UI de mensagens/disparos com provedor fictício, sem mensagens reais.
.\.venv\Scripts\python.exe -m tests.browser_outreach
# Exercita o protocolo e ACKs com SDK em memória, sem rede.
node tests/whatsapp_bridge.cjs
# Compatibilidade dos identificadores atuais/anteriores do WhatsApp Web.
node tests/whatsapp_identity.cjs

# Gera QR real em sessão temporária, sem escanear, vincular conta ou enviar.
.\.venv\Scripts\python.exe -m tests.live_whatsapp_qr
```

As capturas do teste visual e os resultados do teste externo ficam em `test-results/`, ignorado pelo Git. A integração usa a [biblioteca oficial do Playwright para Python](https://playwright.dev/python/docs/library).

Conexões e disparos têm histórico persistente com horários, transições e erros nas próprias telas. O histórico guarda os últimos 2.000 eventos por workspace e mostra até 100 por execução/conexão, sem QR, credenciais ou texto das mensagens nos eventos. A migração para o esquema 4 cria um backup `.phase3-backup.sqlite3`. O conector espera o resultado de envio da biblioteca e pode recuperar a confirmação por eventos de saída/ACK ou consulta do mesmo ID quando o retorno vier vazio ou falhar após o envio. A recuperação exige um único evento do mesmo destinatário, texto e janela de tempo; eventos ambíguos ou de outras conversas não confirmam a tentativa. Não há uma segunda chamada de envio. Envios reais exigem identificador e confirmação do servidor do WhatsApp (ACK de servidor ou superior); isso não confirma entrega ou leitura. Se essa confirmação não chegar em 25 segundos, a execução fica pausada e sem repetição automática.

O lockfile da integração fixa as dependências. Puppeteer é atualizado por override explícito para 25.16.0, validado com a geração real de QR. Para conferir o conjunto instalado: `npm audit --omit=dev --prefix leadfinder/integrations/whatsapp`. O teste da fila usa um adaptador fictício: o envio real após pareamento precisa ser validado pelo dono da conta, com um destinatário de teste autorizado.

## Limitações da coleta

Esta versão utiliza as páginas públicas do Google Maps pelo navegador. Não exige chave de API, conta ou login. Não resolve CAPTCHA, não contorna bloqueios e não usa proxies ou técnicas de evasão. Quando uma verificação é identificada, a busca para e informa o motivo. Erros em páginas individuais produzem resultado parcial. Faça uso responsável dos dados públicos e observe as condições aplicáveis da fonte; a licença deste projeto cobre o código, não concede direitos sobre dados de terceiros.

## Contribuir

Veja [CONTRIBUTING.md](../CONTRIBUTING.md). Licença [MIT](../LICENSE).
