'use strict';
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {installMessageIdentity} = require('../leadfinder/integrations/whatsapp/message-identity.cjs');

for (const legacy of [false,true]) {
  class MsgKey {
    constructor() {
      this.fromMe=true;
      this.remote={_serialized:'123456@lid'};
      this.id='FIXTURE';
      this.self='out';
      this.$1=null;
      if (legacy) this._serialized='true_123456@lid_FIXTURE_out';
    }
    toString() { return 'true_123456@lid_FIXTURE_out'; }
  }
  const key=new MsgKey(), messages=new Map([[key.toString(),{id:key,ack:3}]]);
  const window={
    require(name) { assert.equal(name,'WAWebMsgKey');return MsgKey; },
    WWebJS:{getMessageModel:message=>({id:{...message.id,remote:message.id.remote._serialized},ack:message.ack})},
  };
  const context=vm.createContext({window});
  const install=()=>vm.runInContext('('+installMessageIdentity.toString()+')()',context);
  install();
  const wrapped=window.WWebJS.getMessageModel;
  install();assert.equal(window.WWebJS.getMessageModel,wrapped,'Installation must be idempotent');
  assert.equal(new MsgKey()._serialized,key.toString(),'Future keys must work, including legacy constructor assignment');
  const sent=messages.get(key._serialized);
  assert.ok(sent,'SDK must locate the outgoing message with the current MsgKey shape');
  const serialized=JSON.parse(JSON.stringify(window.WWebJS.getMessageModel(sent)));
  assert.equal(serialized.id._serialized,key.toString(),'Canonical ID must survive the browser/Node transport');
  assert.equal(serialized.ack,3);
  assert.equal(serialized.id.remote,'123456@lid');
  const invalid={remote:{_serialized:'123456@lid'},toString:()=> '[object Object]'};
  assert.equal(window.WWebJS.getMessageModel({id:invalid,ack:0}).id._serialized,undefined);
}
console.log('PASS WhatsApp message identity: new and legacy keys; browser serialization; idempotence; invalid IDs rejected. No network.');
