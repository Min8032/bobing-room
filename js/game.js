/* =========================================================
 * game.js — 中秋博饼游戏逻辑
 * 规则（厦门经典玩法，6 颗骰子，按 4 点数量和组合判定）：
 *   状元插金花(4个4+2个1) > 六红(6个4) > 六勃黑(6个同非4)
 *   > 五红(5个4) > 五子(5个同非4) > 状元/四红(4个4) > 对堂(123456)
 *   > 三红(3个4) > 四进(4个同非4) > 二举(2个4) > 一秀(1个4) > 无奖
 * 玩法：轮流掷骰，无限轮转，只有房主可解散房间；
 *       最多 16 人，中途可加入（排最后）/退出（后面自动顶上）。
 * 房主端为权威状态（掷骰/轮转/判定），其他人只收状态同步。
 * ========================================================= */
(() => {
  'use strict';

  /* ---------- 常量 ---------- */
  const DICE_DIR = 'assets/dice/';
  const MAX_PLAYERS = 16;
  const DICE_NUM = 6;                       // 博饼固定 6 颗骰子
  const EMOJIS = ['🦊', '🐼', '🐯', '🦁', '🐸', '🐰', '🐵', '🐨',
                  '🐷', '🐮', '🐔', '🐧', '🦄', '🐲', '🦉', '🐳'];
  const CODE_RE = /^[A-Za-z0-9]{4,12}$/;    // 房间密码：4~12 位数字或字母

  /* ---------- 页面状态 ---------- */
  const S = {
    code: '',
    isHost: false,
    players: [],       // [{id,name,emoji}]（以房主广播为准，顺序=座位顺序）
    hostId: '',
    turn: '',          // 当前轮到谁的 id
    lastRoll: null,    // {seq, playerId, name, emoji, dice:[...], result, level}
    sigLost: false,
  };

  /* ---------- 房主权威数据（仅房主使用） ---------- */
  const H = {
    players: new Map(),  // id -> {id,name,emoji}
    order: [],           // 座位顺序（加入顺序，退出后后面自动顶上）
    turnIdx: 0,          // 当前轮到 order 里的第几人
    rollSeq: 0,
    lastRoll: null,
  };

  /* ---------- DOM ---------- */
  const $ = id => document.getElementById(id);
  const el = {
    lobby: $('lobby'), table: $('table'),
    nickname: $('nickname'), roomCode: $('roomCode'),
    btnCreate: $('btnCreate'), btnJoin: $('btnJoin'), lobbyMsg: $('lobbyMsg'),
    roomInfo: $('roomInfo'), btnLeave: $('btnLeave'),
    rowTop: $('rowTop'), rowBottom: $('rowBottom'),
    resultName: $('resultName'), resultWho: $('resultWho'),
    bowlDice: $('bowlDice'), bowlHint: $('bowlHint'),
    statusBar: $('statusBar'),
    sfxRoll: $('sfxRoll'),
  };

  /* ---------- 工具 ---------- */
  const diceSrc = n => DICE_DIR + n + '.png';
  const me = () => S.players.find(p => p.id === Net.myId);
  const isMyTurn = () => S.turn && S.turn === Net.myId;

  // 摇 6 颗骰子（加密随机数）
  function rollDice() {
    const rnd = new Uint32Array(DICE_NUM);
    crypto.getRandomValues(rnd);
    return Array.from(rnd, v => (v % 6) + 1);
  }

  /* ---------- 博饼判定 ---------- */
  function bobingResult(dice) {
    const cnt = [0, 0, 0, 0, 0, 0, 0];
    dice.forEach(d => cnt[d]++);
    const fours = cnt[4];
    const sorted = dice.slice().sort((a, b) => a - b);
    const straight = [1, 2, 3, 4, 5, 6].every((v, i) => sorted[i] === v);
    const sameN = n => { for (let v = 1; v <= 6; v++) if (v !== 4 && cnt[v] === n) return true; return false; };

    if (fours === 4 && cnt[1] === 2) return { name: '状元插金花', level: 12 };
    if (fours === 6) return { name: '六红·满堂红', level: 11 };
    if (sameN(6)) return { name: '六勃黑', level: 10 };
    if (fours === 5) return { name: '五红', level: 9 };
    if (sameN(5)) return { name: '五子登科', level: 8 };
    if (fours === 4) return { name: '状元', level: 7 };
    if (straight) return { name: '对堂', level: 6 };
    if (fours === 3) return { name: '三红', level: 5 };
    if (sameN(4)) return { name: '四进', level: 4 };
    if (fours === 2) return { name: '二举', level: 3 };
    if (fours === 1) return { name: '一秀', level: 2 };
    return { name: '无奖', level: 0 };
  }

  /* ---------- 房主防锁屏（屏幕常亮，尽力而为） ---------- */
  let wakeLock = null;
  async function keepAwake() {
    if (!('wakeLock' in navigator)) return;
    try { wakeLock = await navigator.wakeLock.request('screen'); } catch (e) {}
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && S.isHost && S.code) keepAwake();
  });

  /* =========================================================
   * 房主逻辑
   * ========================================================= */
  function hostSetup(code, name) {
    S.isHost = true; S.code = code;
    H.players.clear(); H.order = []; H.turnIdx = 0; H.rollSeq = 0; H.lastRoll = null;
    hostAddPlayer(Net.myId, name);
    keepAwake();
    hostBroadcastRoster();   // 房主本地立即看到自己

    Net.on('sig', ok => { S.sigLost = !ok; render(); });

    Net.on('join', (id, pname) => {
      if (H.players.size >= MAX_PLAYERS) {
        Net.sendTo(id, { t: 'full' });
        setTimeout(() => Net.kick(id), 300);
        return;
      }
      hostAddPlayer(id, pname);   // 中途加入：排到最后
      hostBroadcastRoster();
    });

    Net.on('rollReq', id => hostDoRoll(id));

    Net.on('leave', id => {
      const idx = H.order.indexOf(id);
      if (idx === -1) return;
      H.players.delete(id);
      H.order.splice(idx, 1);
      if (H.order.length > 0) {
        if (idx < H.turnIdx) H.turnIdx--;                    // 前面的人走了，索引前移
        else if (idx === H.turnIdx) H.turnIdx %= H.order.length;  // 轮到的人走了，下一位顶上
      } else {
        H.turnIdx = 0;
      }
      hostBroadcastRoster();
    });
  }

  function hostAddPlayer(id, name) {
    const emoji = EMOJIS[H.order.length % EMOJIS.length];
    const clean = (name || '').trim().slice(0, 8) || ('玩家' + (H.order.length + 1));
    H.players.set(id, { id, name: clean, emoji });
    H.order.push(id);
  }

  // 掷骰（只有轮到的人才有效；房主自己的按钮和加入者的 rollReq 都走这里）
  function hostDoRoll(id) {
    if (H.order.length === 0) return;
    if (H.order[H.turnIdx] !== id) return;        // 没轮到你，忽略
    const dice = rollDice();
    const res = bobingResult(dice);
    const p = H.players.get(id);
    H.rollSeq++;
    H.lastRoll = { seq: H.rollSeq, playerId: id, name: p.name, emoji: p.emoji,
                   dice, result: res.name, level: res.level };
    H.turnIdx = (H.turnIdx + 1) % H.order.length;  // 轮换下一位，无限循环
    hostBroadcastRoster();
  }

  function hostRosterData() {
    return {
      t: 'roster',
      host: Net.myId,
      turn: H.order[H.turnIdx] || '',
      lastRoll: H.lastRoll,
      players: H.order.map(id => {
        const p = H.players.get(id);
        return { id: p.id, name: p.name, emoji: p.emoji };
      }),
    };
  }

  function hostBroadcastRoster() {
    const data = hostRosterData();
    Net.broadcast(data);
    applyRoster(data);       // 房主自己本地应用
  }

  /* =========================================================
   * 加入者逻辑
   * ========================================================= */
  function clientSetup(code) {
    S.isHost = false; S.code = code;

    Net.on('sig', ok => { S.sigLost = !ok; render(); });
    Net.on('roster', applyRoster);
    Net.on('full', () => fatalBack('房间已满（最多 ' + MAX_PLAYERS + ' 人）'));
    Net.on('closed', () => fatalBack('房主已解散房间'));
  }

  /* =========================================================
   * 状态应用与渲染
   * ========================================================= */
  let lastSeenSeq = 0;

  function applyRoster(data) {
    S.players = data.players;
    S.hostId = data.host || '';
    S.turn = data.turn || '';
    const isNewRoll = data.lastRoll && data.lastRoll.seq !== lastSeenSeq;
    S.lastRoll = data.lastRoll || null;
    if (isNewRoll) lastSeenSeq = S.lastRoll.seq;
    render(isNewRoll);
  }

  function render(newRoll) {
    el.roomInfo.textContent = '房间 ' + S.code + '（点我复制）';
    renderPlayers();
    renderCenter(newRoll);
    renderStatus();
    el.btnLeave.textContent = S.isHost ? '解散房间' : '离开房间';
  }

  // 上下两排玩家：前一半上排，后一半下排
  function renderPlayers() {
    const n = S.players.length;
    const half = Math.ceil(n / 2);
    renderRow(el.rowTop, S.players.slice(0, half));
    renderRow(el.rowBottom, S.players.slice(half));
  }

  function renderRow(rowEl, list) {
    rowEl.innerHTML = '';
    for (const p of list) rowEl.appendChild(playerSlot(p));
  }

  function playerSlot(p) {
    const div = document.createElement('div');
    const isTurn = p.id === S.turn;
    div.className = 'pslot' + (isTurn ? ' turn' : '') + (p.id === Net.myId ? ' me' : '');
    const hostTag = (p.id === S.hostId) ? '<span class="tag-host">房主</span>' : '';
    const meTag = (p.id === Net.myId) ? '<span class="tag-me">我</span>' : '';
    let html =
      '<div class="p-avatar">' + p.emoji + '</div>' +
      '<div class="p-name">' + escapeHtml(p.name) + hostTag + meTag + '</div>';
    if (isTurn) {
      // 轮到谁，"开始掷骰子"按钮就显示在谁的中间靠右
      const canClick = (p.id === Net.myId);
      html += '<button class="roll-btn" ' + (canClick ? '' : 'disabled') + '>' +
              (canClick ? '🎲 掷骰子' : '掷骰中…') + '</button>';
    }
    div.innerHTML = html;
    const btn = div.querySelector('.roll-btn');
    if (btn && p.id === Net.myId) btn.addEventListener('click', onRollClick);
    return div;
  }

  const rollAnim = { raf: 0, seq: 0 };
  const bowlWrap = () => el.bowlDice && el.bowlDice.parentElement;

  function stopRollAnim() {
    if (rollAnim.raf) cancelAnimationFrame(rollAnim.raf);
    rollAnim.raf = 0;
    const wrap = bowlWrap();
    if (wrap) wrap.classList.remove('rattling');
  }

  function placeDie(img, x, y, r) {
    img.style.left = x + '%';
    img.style.top = y + '%';
    img.style.setProperty('--r', r + 'deg');
  }

  function paintDice(dice, seq, settle) {
    el.bowlDice.innerHTML = '';
    if (!dice) return;
    dice.forEach((v, i) => {
      const img = document.createElement('img');
      img.src = diceSrc(v);
      img.alt = String(v);
      const pos = dicePos(seq, i);
      placeDie(img, pos.x, pos.y, pos.r);
      if (settle) img.classList.add('settle');
      el.bowlDice.appendChild(img);
    });
  }

  function showResultText(roll) {
    if (roll) {
      el.resultName.textContent = roll.result;
      el.resultName.className = 'result-name lv' + roll.level;
      el.resultWho.textContent = roll.emoji + ' ' + roll.name + ' 掷出';
    } else {
      el.resultName.textContent = '博饼';
      el.resultName.className = 'result-name lv0';
      el.resultWho.textContent = '中秋快乐';
    }
  }

  function rattlePos(i) {
    const ang = Math.random() * Math.PI * 2;
    const rr = 6 + Math.random() * 16;
    return {
      x: 50 + Math.cos(ang) * rr,
      y: 54 + Math.sin(ang) * rr * 0.84,
      r: Math.round((Math.random() - 0.5) * 220),
      v: 1 + Math.floor(Math.random() * 6),
    };
  }

  function playRollAnim(roll) {
    stopRollAnim();
    rollAnim.seq = roll.seq;
    showResultText(null);
    el.resultName.textContent = '摇骰中';
    el.resultWho.textContent = '';
    el.bowlHint.textContent = '';
    const wrap = bowlWrap();
    if (wrap) wrap.classList.add('rattling');
    paintDice([1, 2, 3, 4, 5, 6], roll.seq, false);
    const imgs = Array.from(el.bowlDice.querySelectorAll('img'));
    playRollSfx();
    const t0 = performance.now();
    const DURATION = 780;
    const STEP = 48;
    let last = 0;
    const tick = now => {
      if (rollAnim.seq !== roll.seq) return;
      const elapsed = now - t0;
      if (elapsed >= DURATION) {
        rollAnim.raf = 0;
        if (wrap) wrap.classList.remove('rattling');
        showResultText(roll);
        paintDice(roll.dice, roll.seq, true);
        return;
      }
      if (now - last >= STEP) {
        last = now;
        imgs.forEach((img, i) => {
          const p = rattlePos(i);
          img.src = diceSrc(p.v);
          placeDie(img, p.x, p.y, p.r);
        });
      }
      rollAnim.raf = requestAnimationFrame(tick);
    };
    rollAnim.raf = requestAnimationFrame(tick);
  }

  function renderCenter(newRoll) {
    if (newRoll && S.lastRoll) {
      playRollAnim(S.lastRoll);
      return;
    }
    if (rollAnim.raf && S.lastRoll && S.lastRoll.seq === rollAnim.seq) return;
    stopRollAnim();
    showResultText(S.lastRoll);
    if (S.lastRoll) {
      paintDice(S.lastRoll.dice, S.lastRoll.seq, false);
      el.bowlHint.textContent = '';
    } else {
      el.bowlDice.innerHTML = '';
      const turnP = S.players.find(p => p.id === S.turn);
      el.bowlHint.textContent = turnP
        ? (turnP.id === Net.myId ? '轮到你掷骰子！' : '等待 ' + turnP.name + ' 掷骰…')
        : '';
    }
  }

  // 碗底中央一簇：中心 1 颗 + 周围 5 颗（所有端同一伪随机，互不重叠）
  function dicePos(seq, i) {
    const rand = mulberry32(seq * 100 + i);
    const cx = 50, cy = 57;          // 碗底中心
    if (i === 0) {
      return { x: cx + (rand() - 0.5) * 2.2, y: cy + (rand() - 0.5) * 2.2,
               r: Math.round((rand() - 0.5) * 24) };
    }
    const ang = ((i - 1) / 5) * Math.PI * 2 - Math.PI / 2 + (rand() - 0.5) * 0.18;
    const rr = 17.6 + (rand() - 0.5) * 1.2;
    return {
      x: cx + Math.cos(ang) * rr,
      y: cy + Math.sin(ang) * rr * 0.86,
      r: Math.round((rand() - 0.5) * 28),
    };
  }
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  function renderStatus() {
    if (S.sigLost) {
      el.statusBar.textContent = '⚠️ 与服务器连接中断，自动重连中…（恢复前新朋友进不来）';
      return;
    }
    const turnP = S.players.find(p => p.id === S.turn);
    const who = turnP ? (turnP.id === Net.myId ? '你' : turnP.name) : '…';
    el.statusBar.textContent = '共 ' + S.players.length + ' 人 · 轮到 ' + who + ' 掷骰' +
      (S.isHost ? '（你是房主，只有你能解散房间）' : '');
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* =========================================================
   * 屏幕切换与异常退出
   * ========================================================= */
  function showScreen(name) {
    el.lobby.classList.toggle('hidden', name !== 'lobby');
    el.table.classList.toggle('hidden', name !== 'table');
  }

  function fatalBack(msg) {
    alert(msg);
    backToLobby();
  }

  function backToLobby() {
    stopRollAnim();
    Net.destroy();
    S.code = ''; S.players = []; S.turn = ''; S.lastRoll = null; S.sigLost = false;
    lastSeenSeq = 0;
    el.btnCreate.disabled = false;
    el.btnJoin.disabled = false;
    showScreen('lobby');
  }

  /* =========================================================
   * 事件绑定
   * ========================================================= */
  function readInputs() {
    const name = el.nickname.value.trim();
    const code = el.roomCode.value.trim();
    if (!name) { el.lobbyMsg.textContent = '先起个昵称吧'; return null; }
    if (!CODE_RE.test(code)) { el.lobbyMsg.textContent = '房间密码需为 4~12 位数字或字母'; return null; }
    localStorage.setItem('bobing_name', name);
    localStorage.setItem('bobing_code', code);
    return { name, code };
  }

  function onRollClick() {
    if (!isMyTurn()) return;
    unlockAudio();
    if (S.isHost) hostDoRoll(Net.myId);      // 房主直接本地掷
    else Net.send({ t: 'rollReq' });          // 加入者向房主请求掷骰
  }

  /* ---------- 骰子碰撞声（首次点击解锁，之后各端掷骰都能响） ---------- */
  let audioUnlocked = false;
  function unlockAudio() {
    if (audioUnlocked || !el.sfxRoll) return;
    audioUnlocked = true;
    el.sfxRoll.volume = 0.85;
    const p = el.sfxRoll.play();
    if (p && p.then) p.then(() => { el.sfxRoll.pause(); el.sfxRoll.currentTime = 0; }).catch(() => {});
  }
  function playRollSfx() {
    if (!el.sfxRoll) return;
    try {
      el.sfxRoll.currentTime = 0;
      el.sfxRoll.play().catch(() => {});
    } catch (e) {}
  }
  document.addEventListener('touchstart', unlockAudio, { once: true, passive: true });
  document.addEventListener('click', unlockAudio, { once: true });

  el.btnCreate.addEventListener('click', async () => {
    const v = readInputs(); if (!v) return;
    el.btnCreate.disabled = true; el.btnJoin.disabled = true;
    el.lobbyMsg.textContent = '创建中…';
    try {
      await Net.createRoom(v.code);
      hostSetup(v.code, v.name);
      showScreen('table');
      render(false);
    } catch (e) {
      el.lobbyMsg.textContent = e.message || '创建失败，请重试';
      el.btnCreate.disabled = false; el.btnJoin.disabled = false;
    }
  });

  el.btnJoin.addEventListener('click', async () => {
    const v = readInputs(); if (!v) return;
    el.btnCreate.disabled = true; el.btnJoin.disabled = true;
    el.lobbyMsg.textContent = '加入中…';
    clientSetup(v.code);   // 先注册消息回调：roster 可能与加入成功同时到达
    try {
      await Net.joinRoom(v.code, v.name);
      showScreen('table');
      render(false);
    } catch (e) {
      el.lobbyMsg.textContent = e.message || '加入失败，请重试';
      el.btnCreate.disabled = false; el.btnJoin.disabled = false;
    }
  });

  el.btnLeave.addEventListener('click', () => {
    const msg = S.isHost ? '确定解散房间吗？所有人都会被请出' : '确定离开房间吗？';
    if (!confirm(msg)) return;
    if (S.isHost) Net.broadcast({ t: 'closed' });
    backToLobby();
  });

  el.roomInfo.addEventListener('click', () => {
    const copy = () => {
      el.statusBar.textContent = '房间密码 ' + S.code + ' 已复制，发给小伙伴吧';
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(S.code).then(copy).catch(copy);
    } else copy();
  });

  // 在房间内误刷新/关闭时给个提示
  window.addEventListener('beforeunload', e => {
    if (S.code) { e.preventDefault(); e.returnValue = ''; }
  });

  /* ---------- 初始化 ---------- */
  el.nickname.value = localStorage.getItem('bobing_name') || '';
  el.roomCode.value = localStorage.getItem('bobing_code') || '';
  showScreen('lobby');
})();
