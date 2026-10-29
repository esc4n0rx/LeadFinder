'use strict';

// Only protocol frames reach stdout. Never print QR payloads, auth state, or chats.
const readline = require('node:readline');
const { Client, LocalAuth } = require('whatsapp-web.js');
const QRCode = require('qrcode');
const {installMessageIdentity} = require('./message-identity.cjs');
const emit = frame => process.stdout.write(JSON.stringify(frame) + '\n');
console.log = () => {};
console.warn = () => {};
console.error = () => {};
let client = null;
let state = {status:'disconnected', qr:null, phone:null, error:null};
let expectedPhone = '';
let generation = 0;
let qrSequence = 0;
const acknowledgements = new Map();
let activeAttempt = null;

async function bounded(operation, milliseconds) {
  let timer;
  try {
    return await Promise.race([operation,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('confirmation_timeout')),milliseconds);})]);
  } finally { clearTimeout(timer); }
}

function observeOutgoing(message) {
  const attempt=activeAttempt, id=message?.id?._serialized;
  if (!attempt || !id || !message.fromMe || message.body!==attempt.body ||
      !attempt.recipients.has(message.to) || !Number.isFinite(message.timestamp) ||
      message.timestamp<attempt.startedAt) return;
  attempt.messages.set(id,message);
}

function diagnostic(error) {
  const detail=String(error?.message || '');
  if (/already running|SingletonLock|user data directory is already in use|ProcessSingleton/i.test(detail)) return 'A sessão está em uso por outro processo do navegador. Encerre a outra instância do LeadFinder e reconecte.';
  if (/timeout|timed out/i.test(detail)) return 'O WhatsApp Web demorou para responder. Confira a internet e tente reconectar.';
  if (/Target closed|Session closed|browser.*closed|Execution context was destroyed/i.test(detail)) return 'O navegador do WhatsApp foi encerrado ou recarregado. Reconecte para continuar.';
  if (/net::|ERR_|ENOTFOUND|ECONN/i.test(detail)) return 'Falha de rede ao acessar o WhatsApp Web. Confira a conexão com a internet.';
  return 'Falha ao inicializar o WhatsApp Web. Confira a conexão, a sessão e o navegador e tente reconectar.';
}

function publish(values) {
  state = {...state, ...values};
  emit({event:'state', state});
}

async function connect(command) {
  if (client) return state;
  if (!/^\d{8,15}$/.test(command.phone) || !/^workspace-\d+$/.test(command.clientId)) throw new Error('invalid_config');
  expectedPhone = command.phone;
  const currentGeneration = ++generation;
  publish({status:'starting', qr:null, phone:null, error:null});
  client = new Client({
    authStrategy: new LocalAuth({clientId:command.clientId, dataPath:command.authPath}),
    puppeteer: {headless:true, executablePath:command.browser, timeout:45000},
    authTimeoutMs:60000,
    qrMaxRetries:5,
    takeoverOnConflict:false,
    webVersionCache:{type:'local',path:command.cachePath},
    deviceName:'LeadFinder',
  });
  const liveClient = client;
  acknowledgements.clear();
  client.on('message_create', observeOutgoing);
  client.on('message_ack', (message,ack) => {
    observeOutgoing(message);
    const id=message?.id?._serialized;
    if (!id) return;
    acknowledgements.set(id,ack);
    if (acknowledgements.size>200) acknowledgements.delete(acknowledgements.keys().next().value);
  });
  const current = () => currentGeneration === generation && client === liveClient;
  client.on('qr', async qr => {
    const sequence=++qrSequence;
    const data = await QRCode.toDataURL(qr, {width:280, margin:2});
    if (current() && sequence===qrSequence && !['ready','authenticating','mismatch','error','disconnected'].includes(state.status)) publish({status:'qr', qr:data, phone:null, error:null});
  });
  client.on('authenticated', () => { qrSequence++; if (current()) publish({status:'authenticating', qr:null}); });
  client.on('ready', async () => {
    if (!current()) return;
    const phone = liveClient.info?.wid?.user;
    if (phone !== expectedPhone) {
      publish({status:'mismatch', qr:null, phone:phone || null, error:'A conta vinculada difere do número configurado. Desconecte e confira o número.'});
      return;
    }
    try {
      await liveClient.pupPage.evaluate(installMessageIdentity);
      if (current()) publish({status:'ready', qr:null, phone, error:null});
    } catch {
      if (current()) publish({status:'error',qr:null,error:'Não foi possível preparar a compatibilidade com esta versão do WhatsApp Web. Reconecte para continuar.'});
    }
  });
  client.on('auth_failure', () => { if (current()) publish({status:'error', qr:null, error:'A autenticação falhou. Desconecte e gere um novo QR code.'}); });
  client.on('disconnected', () => { if (current()) publish({status:'disconnected', qr:null, phone:null, error:'WhatsApp desconectado. Reconecte para enviar.'}); });
  client.initialize().catch(error => {
    if (current()) publish({status:'error', qr:null, error:diagnostic(error)});
  });
  return state;
}

async function handle(command) {
  if (command.action === 'connect') return connect(command);
  if (command.action === 'status') {
    if (state.status === 'ready') {
      const actual = await client.getState();
      if (actual !== 'CONNECTED') publish({status:'disconnected', qr:null, error:'A conexão com o WhatsApp foi perdida.'});
    }
    return state;
  }
  if (command.action === 'send') {
    if (state.status !== 'ready' || !client || state.phone !== command.senderPhone || await client.getState() !== 'CONNECTED') throw new Error('not_connected');
    if (!/^\d{8,15}$/.test(command.phone) || typeof command.body !== 'string' || !command.body.trim() || command.body.length > 8000) throw new Error('invalid_message');
    // Reapply after a Web reload; this is idempotent and never sends anything.
    await client.pupPage.evaluate(installMessageIdentity);
    const number = await client.getNumberId(command.phone);
    if (!number) return {rejected:true, error:'Este número não possui WhatsApp.'};
    // Correlate only this outgoing recipient/text/time window. Never retry sendMessage.
    const attempt={body:command.body,recipients:new Set([number._serialized]),startedAt:Math.floor(Date.now()/1000),messages:new Map()};
    if (typeof client.getContactLidAndPhone==='function') {
      try {
        const aliases=await bounded(client.getContactLidAndPhone([number._serialized]),3000);
        for (const alias of aliases) if (alias.pn===number._serialized && alias.lid) attempt.recipients.add(alias.lid);
      } catch {}
    }
    activeAttempt=attempt;
    let message=null, returnedId=null, sendError=false;
    try {
      try {
        message = await bounded(client.sendMessage(number._serialized, command.body, {sendSeen:false,waitUntilMsgSent:true}),20000);
        returnedId=message?.id?._serialized || null;
      } catch { sendError=true; }
      const deadline=Date.now()+25000;
      let nextLookup=0;
      while (Date.now()<deadline) {
        const candidate=returnedId?message:attempt.messages.size===1?[...attempt.messages.values()][0]:null;
        const id=returnedId || candidate?.id?._serialized;
        let ack=id?(acknowledgements.get(id) ?? candidate?.ack):undefined;
        // ACK events can be missed while WhatsApp updates its local message model.
        if (id && !(ack>=1) && ack!==-1 && Date.now()>=nextLookup && typeof client.getMessageById==='function') {
          nextLookup=Date.now()+2000;
          try { const latest=await bounded(client.getMessageById(id),2000);ack=acknowledgements.get(id) ?? latest?.ack ?? ack; } catch {}
        }
        if (ack>=1) return {messageId:id,ack};
        if (ack===-1) return {rejected:true,error:'O WhatsApp rejeitou a mensagem. Nenhum recebimento foi confirmado.'};
        if (state.status!=='ready') break;
        await new Promise(resolve=>setTimeout(resolve,250));
      }
      const observedId=returnedId || (attempt.messages.size===1?[...attempt.messages.keys()][0]:null);
      return {uncertain:true,messageId:observedId,error:!observedId?'O WhatsApp não retornou um identificador único para esta tentativa. Não foi possível vincular a confirmação. Confira no celular antes de repetir.':sendError?'O WhatsApp retornou um erro após a tentativa e não foi possível obter uma confirmação vinculada à mensagem. Ela pode ter sido entregue. Confira no celular antes de repetir.':'O servidor do WhatsApp não confirmou o recebimento em 25 segundos. A mensagem pode ter sido entregue. Confira no celular antes de repetir.'};
    } finally {
      activeAttempt=null;
    }
  }
  if (command.action === 'verify') {
    if (state.status!=='ready' || state.phone!==command.senderPhone || await client.getState()!=='CONNECTED') throw new Error('not_connected');
    if (typeof command.messageId!=='string' || !/^(true|false)_[^_]+@[^_]+_[^_]+(?:_[^_]+)?$/.test(command.messageId)) throw new Error('invalid_message');
    await client.pupPage.evaluate(installMessageIdentity);
    const message=await bounded(client.getMessageById(command.messageId),5000);
    if (!message || !message.fromMe || message.id?._serialized!==command.messageId) return {ack:0};
    return {ack:message.ack ?? 0,messageId:command.messageId};
  }
  if (command.action === 'disconnect') {
    generation++;
    const previous = client;
    client = null;
    let removed = false;
    if (previous) {
      try { await previous.logout(); removed = true; } catch { /* Local cleanup is handled by the owner process. */ }
      try { await previous.destroy(); } catch {}
    }
    publish({status:'disconnected', qr:null, phone:null, error:null});
    return {removed};
  }
  throw new Error('unsupported_action');
}

// Commands are serialized so disconnect cannot race an in-flight send.
let chain = Promise.resolve();
readline.createInterface({input:process.stdin}).on('line', line => {
  chain = chain.then(async () => {
    let command;
    try {
      command = JSON.parse(line);
      const data = await handle(command);
      emit({id:command.id, ok:true, data});
    } catch (error) {
      const message = error.message === 'not_connected' ? 'O WhatsApp não está conectado.' : 'Não foi possível concluir a operação no WhatsApp.';
      emit({id:command?.id, ok:false, error:message});
    }
  });
});
async function close() {
  generation++;
  if (client) { try { await client.destroy(); } catch {} }
  process.exit(0);
}
process.stdin.on('end', close);
process.on('SIGTERM', close);
process.on('SIGINT', close);
