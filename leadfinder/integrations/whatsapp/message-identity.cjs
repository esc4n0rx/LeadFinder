'use strict';

// Executed inside WhatsApp Web, after the SDK has injected WWebJS.
// Recent MsgKey versions expose toString() instead of _serialized. The SDK
// still uses _serialized both for its send result lookup and message events.
function installMessageIdentity() {
  const MsgKey = window.require('WAWebMsgKey');
  const valid = value => typeof value === 'string' && /^(true|false)_[^_]+@[^_]+_[^_]+(?:_[^_]+)?$/.test(value);
  const identity = key => {
    if (valid(key?._serialized)) return key._serialized;
    const value = key?.toString?.();
    return valid(value) ? value : null;
  };
  if (!('_serialized' in MsgKey.prototype)) {
    Object.defineProperty(MsgKey.prototype, '_serialized', {
      configurable: true,
      get() {
        const value = this.toString();
        return valid(value) ? value : undefined;
      },
      set(value) {
        // Older SDK/Web constructors assign an own field during construction.
        Object.defineProperty(this, '_serialized', {value,writable:true,configurable:true,enumerable:true});
      },
    });
  }
  const original = window.WWebJS.getMessageModel;
  if (!original.leadfinderIdentity) {
    const normalized = function(message) {
      const model = original(message);
      const id = identity(message.id);
      // Prototype getters disappear when Puppeteer serializes the result.
      if (id) model.id = {...model.id, _serialized:id};
      return model;
    };
    normalized.leadfinderIdentity = true;
    window.WWebJS.getMessageModel = normalized;
  }
  return true;
}

module.exports = {installMessageIdentity};
