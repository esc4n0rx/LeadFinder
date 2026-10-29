# LeadFinder 0.5 — Operação comercial

## Fluxo de trabalho

1. **Leads → campanhas.** Combine texto, categoria, contato e etapa. Selecione registros entre páginas ou use **Selecionar filtrados**. **Criar campanha** transfere uma seleção de até 100 leads para Automação, onde mensagens e destinatários continuam sujeitos à revisão. O snapshot fixa telefone, destinatário e texto; alterações posteriores no catálogo não mudam um disparo já preparado.
2. **Ficha do lead.** Clique no estabelecimento para abrir dados, categorias, etapas, buscas de origem, anotações, lembretes e linha do tempo. Mensagens e campanhas aparecem pelo telefone normalizado do lead, com o status individual da tentativa. Simulações e destinatários fictícios ficam separados dos contatos reais.
3. **Ações em lote.** Até 1.000 leads por seleção. Adicione, remova ou substitua categorias e atualize contato/etapa. IDs e categorias são verificados antes de qualquer escrita; todas as alterações do lote são transacionais e restritas ao workspace.
4. **Recuperação de disparos.** Pause a execução, consulte o identificador de uma tentativa sem confirmação ou registre o resultado após conferi-lo no celular. Consultar e conciliar não enviam mensagens. **Retomar pendentes** preserva mensagens aceitas, simuladas ou encerradas e fica bloqueado enquanto houver uma tentativa incerta. Mensagens classificadas como não enviadas são encerradas como falha e não voltam à fila automaticamente.
5. **Funil comercial.** Novo, Contatado, Respondeu, Demonstração, Cliente e Perdido. Há coluna e filtro na tabela, mais Kanban com seletor acessível e movimentação por arrastar. Etapas de resposta/demonstração/cliente registradas pelo usuário também atualizam o contato como conversa. Um envio aceito sozinho marca apenas contato iniciado.
6. **Lembretes e agenda.** Cadastre a próxima ação pela ficha e acompanhe pendentes, vencidos ou concluídos em **Lembretes**. Agende campanhas já revisadas pela tela de Automação. Datas são persistidas em UTC; a interface usa o fuso do navegador. O aplicativo precisa estar aberto: ao iniciar novamente, agendas vencidas aguardam disponibilidade do workspace e conexão da integração, com nova verificação em até 60 segundos. Cancelar uma agenda impede sua execução. Não há serviço externo executando com o computador desligado.
7. **IA com contexto.** Em **Workspace**, salve produto, diferenciais, público, oferta/objetivo e tom. As próximas interações incluem esse contexto; cada turno guarda uma cópia para auditoria. **Mensagens com IA**, na seleção de leads, prepara uma nova conversa com os segmentos informados no Maps e grupos da seleção. Não há geração paga ou envio automático: o usuário revisa o briefing e envia ao modelo escolhido.
8. **CSV e backup.** CSV exporta a seleção ou os filtros atuais (até 10.000 resultados), com UTF-8/BOM, separador `;` e proteção contra execução de fórmulas. O backup `.lfbackup` é cifrado com senha de 12–200 caracteres, Fernet e chave derivada por PBKDF2-HMAC-SHA256 com salt aleatório e 600.000 iterações. Ele inclui dados do workspace, chaves das integrações de IA e perfil de autenticação do WhatsApp, sem contas/senhas de outros usuários. A chave de instalação não é exportada: cada arquivo usa uma chave interna própria para suas credenciais.

## Restauração

O arquivo é decifrado e validado em uma cópia temporária do SQLite antes de exibir a prévia. A prévia vale por 10 minutos e pertence ao usuário/workspace que a abriu. A confirmação exige senha da conta, senha do backup e o nome do workspace atual. A restauração substitui somente esse workspace, remapeando identificadores e preservando os demais usuários. Uma cópia cifrada anterior fica em `instance/backups/` e pode ser baixada pela interface, com a mesma senha do arquivo usado na restauração.

Buscas, disparos e gerações de IA precisam estar parados durante backup/restauração. Um bloqueio por workspace impede mutações concorrentes e o início de agendas durante a manutenção. O conector fecha o navegador sem logout para copiar os arquivos da sessão e restaura a conexão após exportar. Após importar, a integração fica desconectada até a ação explícita **Conectar / restaurar sessão**. Outro computador/sistema pode exigir novo QR, devido à proteção de credenciais do navegador.

Agendas restauradas não executam automaticamente. Execuções em andamento viram interrompidas; tentativas em envio ficam incertas. A fila restaurada fica parada para revisão. Arquivos/caminhos do ZIP e relações do banco são validados; entradas inválidas, arquivos adulterados, senha incorreta e vínculos externos ao pacote são rejeitados. O limite do arquivo é 64 MB, com até 128 MB expandidos. Caches e travas do Chrome ficam fora da cópia.

## Organização técnica

- `crm.py` / `crm_routes.py`: seleção, ficha, notas, etapas, lembretes, contexto e CSV.
- `campaigns.py` / `scheduler.py`: execução, pausa, conciliação e fila persistente `campaign_jobs`.
- `workspace_gate.py`: controle de operações concorrentes e manutenção por workspace.
- `backups.py` / `backup_routes.py`: cifragem, prévia, validação, importação e rollback de arquivos/banco.
- `crm.html`, `crm.js`, `crm.css`: telas do funil, lembretes, workspace e ficha.

A migração para o esquema 7 cria `.before-crm-backup.sqlite3` antes de alterar uma base existente. O startup preserva a regra de não retomar automaticamente campanhas que estavam em envio. Somente agendas criadas e autorizadas pelo usuário entram na fila automática.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/whatsapp_identity.cjs
node tests/whatsapp_bridge.cjs
.\.venv\Scripts\python.exe -m tests.browser_growth
```

Os testes usam workspaces descartáveis e provedores fictícios, incluindo geração de IA e envio de WhatsApp. Cobrem isolamento, CSV, contexto, conciliação sem reenvio, agendamento após reinício, rollback, backup entre workspaces, integridade dos vínculos, chaves de IA e arquivos da sessão.


## Correção da referência geográfica do CEP

O geocodificador espera o Maps selecionar o CEP e extrai seu ponto da URL final do local. A imagem de prévia (`og:image`) pode manter o centro regional inicial mesmo depois do carregamento e não é usada para calcular o raio. A coleta também aguarda a URL final dos estabelecimentos, inclusive em pesquisas com resultado único, antes de extrair coordenadas e identidade. O telefone é conferido nos controles explícitos de contato (rótulo, texto visível e link tel:), com uma espera adicional quando a linha ainda não carregou. Não há inferência a partir de números de endereço ou de avaliações.

A coleta mantém o filtro de raio e informa separadamente telefone não encontrado, fora do raio e coordenadas ausentes. Buscas antigas mantêm seus contadores e a referência usada na época; refaça a busca para aplicar a referência corrigida.

Regressões: `python -m unittest tests.test_geocoding tests.test_phase2` e `python -m tests.browser_maps_fields` (fixture Chromium sem rede).
