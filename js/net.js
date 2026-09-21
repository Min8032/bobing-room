/* =========================================================
 * net.js — 房间网络层（MQTT 公共代理中转，无需自建服务器、无需打洞）
 *
 * 为什么不用 P2P：PeerJS 依赖境外信令服务器 + STUN/TURN 打洞，
 * 国内移动网络（对称 NAT）下极不稳定。MQTT 模式下双方都只是
 * 普通的"向外连接"国内可达的代理服务器，任何网络都能通。
 *
 * 架构：房主浏览器仍是"游戏服务器"（掷骰判定/轮转在房主端），
 * EMQX 公共 broker 只负责按房间主题转发消息。
 *
 * 主题设计（前缀 bobing/v1/ 避免与他人及扑克/骰子版冲突）：
 *   bobing/v1/{密码}/h  —— 房主收件箱（加入者发布，房主订阅）
 *   bobing/v1/{密码}/r  —— 房间广播（房主发布，加入者订阅）
 * 私信：广播里带 to 字段，只有 id 匹配的加入者处理。
 * 在线状态：利用 MQTT 遗嘱（LWT）——异常断线时 broker 自动代发
 *   房主遗嘱 {t:'closed'} → 加入者得知房间关闭
 *   加入者遗嘱 {t:'bye'}  → 房主得知某人离开
 * ========================================================= */
const Net = (() => {
  'use strict';

  const BROKER = 'wss://broker.emqx.io:8084/mqtt';   // EMQX 免费公共代理（国内可达）
  const TOPIC_PREFIX = 'bobing/v1/';
  const JOIN_RETRY = 3;          // 加入请求最多重发次数
  const JOIN_TIMEOUT = 6000;     // 每次加入请求等待房主回应的超时

  const tIn  = code => TOPIC_PREFIX + code + '/h';   // 房主收件箱
  const tOut = code => TOPIC_PREFIX + code + '/r';   // 房间广播

  let client = null;     // mqtt.js 客户端
  let isHost = false;
  let myId = '';
  let handlers = {};     // 事件 -> [fn]
  let sigWatched = false;

  /* ---------- 事件 ---------- */
  function on(evt, fn) { (handlers[evt] = handlers[evt] || []).push(fn); }
  function emit(evt, ...args) { (handlers[evt] || []).forEach(fn => { try { fn(...args); } catch (e) {} }); }

  /* ---------- 底层 ---------- */
  function connect(willTopic, willPayload) {
    const c = mqtt.connect(BROKER, {
      clientId: 'bobing-' + Math.random().toString(36).slice(2, 12) + Date.now().toString(36),
      keepalive: 25,
      reconnectPeriod: 2000,
      connectTimeout: 8000,
      // 遗嘱：异常断线（锁屏被杀/断网）时由 broker 代发，QoS1
      will: willTopic
        ? { topic: willTopic, payload: JSON.stringify(willPayload), qos: 1, retain: false }
        : undefined,
    });
    c.on('error', () => {});   // 瞬时错误由重连机制处理，避免未捕获
    return c;
  }

  function pub(topic, obj) {
    if (client && client.connected) client.publish(topic, JSON.stringify(obj), { qos: 1 });
  }

  function parse(payload) {
    try { return JSON.parse(payload.toString()); } catch (e) { return null; }
  }

  /* ---------- 房主：创建房间 ---------- */
  function createRoom(code) {
    return new Promise((resolve, reject) => {
      destroyLocal();
      isHost = true;
      myId = rid();

      client = connect(tOut(code), { t: 'closed' });   // 房主遗嘱：房间关闭

      let settled = false;
      const timer = setTimeout(() => fail('连接服务器超时，请检查网络后重试'), 12000);
      const fail = msg => {
        if (settled) return;
        settled = true;
        try { client.end(true); } catch (e) {}
        client = null;
        reject(new Error(msg));
      };

      // 占用检测：先 ping 一下该密码是否已有房主（公共 broker 没有房间注册概念）
      let pongHeard = false;

      client.on('connect', () => {
        client.subscribe([tIn(code), tOut(code)], { qos: 1 }, err => {
          if (err) { clearTimeout(timer); fail('订阅失败，请重试'); return; }
          // 订阅成功后 ping 一次，等 2.5 秒看有没有现存房主应答
          pub(tIn(code), { t: 'ping', from: myId });
          setTimeout(() => {
            if (settled) return;
            clearTimeout(timer);
            settled = true;
            if (pongHeard) {
              try { client.end(true); } catch (e) {}
              client = null;
              reject(new Error('该房间密码已被占用，请换一个'));
            } else {
              resolve(myId);
            }
          }, 2500);
        });
      });

      // 初始连接的瞬时错误（如 connack timeout）交给 mqtt.js 自动重连，由总超时兜底
      client.on('error', () => {});

      client.on('message', (topic, payload) => {
        const data = parse(payload);
        if (!data || !data.t) return;
        // 房主只处理收件箱里的加入者消息 + 占用检测的 ping
        if (topic === tIn(code)) {
          if (data.t === 'ping') {
            // 已是房主（settled 后）才应答；创建探测期不应答自己
            if (settled && data.from !== myId) pub(tOut(code), { t: 'pong' });
          }
          else if (data.t === 'join') emit('join', data.from, data.name);
          else if (data.t === 'rollReq') emit('rollReq', data.from);
          else if (data.t === 'bye') emit('leave', data.from);
        } else if (topic === tOut(code)) {
          if (data.t === 'pong') pongHeard = true;
        }
      });
    });
  }

  /* ---------- 加入者：加入房间 ---------- */
  function joinRoom(code, name) {
    return new Promise((resolve, reject) => {
      destroyLocal();
      isHost = false;
      myId = rid();

      client = connect(tIn(code), { t: 'bye', from: myId });   // 加入者遗嘱：我离开了

      let settled = false;
      let attempts = 0;
      let attemptTimer = null;
      const timer = setTimeout(() => fail('连接服务器超时，请检查网络后重试'), 12000);
      const fail = msg => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        clearTimeout(attemptTimer);
        try { client.end(true); } catch (e) {}
        client = null;
        reject(new Error(msg));
      };

      client.on('connect', () => {
        client.subscribe(tOut(code), { qos: 1 }, err => {
          if (err) { clearTimeout(timer); fail('订阅失败，请重试'); return; }
          clearTimeout(timer);
          sendJoin();
        });
      });

      function sendJoin() {
        if (settled) return;
        attempts++;
        pub(tIn(code), { t: 'join', from: myId, name });
        // 等房主回 roster 才算真成功；超时重发（房主可能刚好断线）
        attemptTimer = setTimeout(() => {
          if (settled) return;
          if (attempts < JOIN_RETRY) sendJoin();
          else fail('房间不存在，请检查房间密码');
        }, JOIN_TIMEOUT);
      }

      // 初始连接的瞬时错误（如 connack timeout）交给 mqtt.js 自动重连，由总超时兜底
      client.on('error', () => {});

      client.on('message', (topic, payload) => {
        const data = parse(payload);
        if (!data || !data.t) return;
        if (data.to && data.to !== myId) return;   // 私信不是给我的

        if (data.t === 'roster') {
          if (!settled) {   // 第一个 roster = 加入成功
            settled = true;
            clearTimeout(timer);
            clearTimeout(attemptTimer);
            resolve(myId);
          }
          emit('roster', data);
        }
        else if (data.t === 'full') { clearTimeout(timer); clearTimeout(attemptTimer); emit('full'); }
        else if (data.t === 'closed') emit('closed');
      });
    });
  }

  /* ---------- 收发 ---------- */
  function send(obj) {              // 加入者 → 房主
    if (!client) return;
    obj.from = myId;
    pub(tIn(currentCode()), obj);
  }
  function sendTo(id, obj) {        // 房主 → 某个加入者（私信）
    obj.to = id;
    pub(tOut(currentCode()), obj);
  }
  function broadcast(obj) {         // 房主 → 全房间
    pub(tOut(currentCode()), obj);
  }

  function kick(id) { sendTo(id, { t: 'closed' }); }

  let roomCode = '';
  function currentCode() { return roomCode; }
  const _create = createRoom, _join = joinRoom;
  createRoom = code => { roomCode = code; return _create(code); };
  joinRoom = (code, name) => { roomCode = code; return _join(code, name); };

  /* ---------- 信令状态监控（MQTT 连接状态） ---------- */
  function watchSig() {
    if (sigWatched || !client) return;
    sigWatched = true;
    client.on('connect', () => emit('sig', true));
    client.on('close', () => emit('sig', false));
    client.on('offline', () => emit('sig', false));
  }

  /* ---------- 销毁 ---------- */
  function destroyLocal() {
    if (client) { try { client.end(true); } catch (e) {} client = null; }
    sigWatched = false;
  }

  function destroy() {
    if (client) {
      // 主动告别（比遗嘱更快到达）
      try {
        if (isHost) pub(tOut(roomCode), { t: 'closed' });
        else pub(tIn(roomCode), { t: 'bye', from: myId });
      } catch (e) {}
      setTimeout(destroyLocal, 200);   // 给告别消息一点发送时间
    }
    handlers = {};
    roomCode = '';
  }

  function rid() { return 'p' + Math.random().toString(36).slice(2, 10); }

  return {
    get myId() { return myId; },
    on, createRoom, joinRoom, send, sendTo, broadcast, kick, watchSig, destroy,
  };
})();
