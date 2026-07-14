// /console/app.js

function appendMessage(role, text) {
  const wrap = document.querySelector('#chat'); // 你的訊息容器
  const item = document.createElement('div');
  item.className = `msg ${role}`;
  item.textContent = text;
  wrap.appendChild(item);
  // 讓畫面像 ChatGPT 一樣自動滾到底
  requestAnimationFrame(() => {
    wrap.scrollTop = wrap.scrollHeight;
  });
}

// 送出訊息時
async function sendMessage(q) {
  appendMessage('user', q);

  const token = window.__token; // 你現有的存放方式
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({ message: q })
  });

  // 即使後端 200 / 500，都避免阻斷 UI
  let data = { text: '系統繁忙，稍後再試。' };
  try { data = await resp.json(); } catch (_) {}

  appendMessage('assistant', data.text || '(沒有內容)');
}
