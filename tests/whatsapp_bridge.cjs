'use strict';

// Exercise the real bridge protocol against an in-memory SDK, never WhatsApp.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {EventEmitter} = require('node:events');
let instance, input, hook, fastClock=false, clock=0, sends=0, lookup=null;
const frames=[];
class FakeClient extends EventEmitter {
  constructor() { super();instance=this;this.info={wid:{user:'5521999991111'}};this.pupPage={evaluate:async()=>true}; }
  async initialize() { this.emit('ready'); }
  async getState() { return 'CONNECTED'; }
  async getNumberId(phone) { return {_serialized:phone+'@c.us'}; }
  async sendMessage(_,__,options) { sends++;assert.equal(options.waitUntilMsgSent,true);return hook(); }
  async getMessageById(id) { return lookup?lookup(id):null; }
  async getContactLidAndPhone() { return [{pn:'5521988882222@c.us',lid:'123456@lid'}]; }
  async destroy() {}
}
class TestDate extends Date { static now() { return fastClock?(clock+=6000):Date.now(); } }
const context={
  require(name) {
    if(name==='node:readline')return {createInterface:()=>({on:(_,callback)=>{input=callback;}})};
    if(name==='whatsapp-web.js')return {Client:FakeClient,LocalAuth:class {}};
    if(name==='qrcode')return {};
    if(name==='./message-identity.cjs')return require('../leadfinder/integrations/whatsapp/message-identity.cjs');
    throw new Error('Unexpected dependency: '+name);
  },
  process:{stdout:{write:line=>frames.push(JSON.parse(line))},stdin:{on(){}},on(){},exit(){}},
  console:{log(){},warn(){},error(){}},
  Date:TestDate, clearTimeout, setTimeout:(callback)=>setTimeout(callback,1),
};
vm.runInNewContext(fs.readFileSync('leadfinder/integrations/whatsapp/bridge.cjs','utf8'),context);
let sequence=0;
async function command(action,values={}) {
  const id=String(++sequence);input(JSON.stringify({id,action,...values}));
  for(let i=0;i<1000;i++) {
    const result=frames.find(frame=>frame.id===id);
    if(result)return result;
    await new Promise(resolve=>setTimeout(resolve,1));
  }
  throw new Error('Protocol timeout');
}
(async()=>{
  assert.equal((await command('connect',{phone:'5521999991111',clientId:'workspace-1'})).ok,true);
  hook=()=>{const message={id:{_serialized:'test-accepted'},ack:0};instance.emit('message_ack',message,1);return message;};
  const params={phone:'5521988882222',body:'Fixture only',senderPhone:'5521999991111'};
  let result=await command('send',params);
  assert.equal(result.data.messageId,'test-accepted');assert.equal(result.data.ack,1);
  const outgoing=(id,to='5521988882222@c.us',body='Fixture only')=>({id:{_serialized:id},fromMe:true,to,body,timestamp:Math.floor(Date.now()/1000),ack:0});
  hook=()=>{const m=outgoing('empty-return');instance.emit('message_create',m);instance.emit('message_ack',m,2);return undefined;};
  result=await command('send',params);assert.equal(result.data.messageId,'empty-return');
  hook=()=>{const m=outgoing('throw-after-send','123456@lid');instance.emit('message_ack',m,1);throw new Error('post_send_model_error');};
  result=await command('send',params);assert.equal(result.data.messageId,'throw-after-send');
  lookup=id=>({id:{_serialized:id},ack:1});
  hook=()=>({id:{_serialized:'missed-ack'},ack:0});
  result=await command('send',params);assert.equal(result.data.messageId,'missed-ack');lookup=null;
  fastClock=true;
  hook=()=>{const m=outgoing('other-recipient','5511999999999@c.us');instance.emit('message_ack',m,2);return undefined;};
  result=await command('send',params);assert.equal(result.data.uncertain,true);
  hook=()=>{instance.emit('message_ack',outgoing('different-body','5521988882222@c.us','Different'),2);return undefined;};
  result=await command('send',params);assert.equal(result.data.uncertain,true);
  hook=()=>{const m=outgoing('old-message');m.timestamp=1;instance.emit('message_ack',m,2);return undefined;};
  result=await command('send',params);assert.equal(result.data.uncertain,true);
  hook=()=>{for(const id of ['ambiguous-a','ambiguous-b'])instance.emit('message_ack',outgoing(id),1);return undefined;};
  result=await command('send',params);assert.equal(result.data.uncertain,true);

  hook=()=>({id:{_serialized:'test-unconfirmed'},ack:0});
  result=await command('send',params);
  assert.equal(result.data.uncertain,true);assert.equal(result.data.messageId,'test-unconfirmed');
  hook=()=>({id:{_serialized:'test-rejected'},ack:-1});
  result=await command('send',params);assert.equal(result.data.rejected,true);
  result=await command('send',{...params,senderPhone:'5521000000000'});assert.equal(result.ok,false);
  assert.equal(sends,10,'Each command must call sendMessage only once; no retries');
  const canonical='true_123456@lid_FIXTURE_out';
  lookup=id=>({id:{_serialized:id},ack:2,fromMe:true});
  result=await command('verify',{messageId:canonical,senderPhone:params.senderPhone});assert.equal(result.data.ack,2);
  lookup=id=>({id:{_serialized:id},ack:2,fromMe:false});
  result=await command('verify',{messageId:canonical,senderPhone:params.senderPhone});assert.equal(result.data.ack,0);
  result=await command('verify',{messageId:'invalid',senderPhone:params.senderPhone});assert.equal(result.ok,false);
  assert.equal(sends,10,'Read-only verification must never send');
  console.log('PASS native bridge: server ACK required; timeout uncertain; rejection explicit; sender checked. No network or real messages.');
})().catch(error=>{console.error(error);process.exitCode=1;});
