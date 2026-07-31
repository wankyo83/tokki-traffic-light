const available = document.querySelector('#available');
const unavailable = document.querySelector('#unavailable');
const updated = document.querySelector('#updated');
const refresh = document.querySelector('#refresh');

function row(item, ok) {
  const node = document.createElement(ok ? 'a' : 'div');
  node.className = `row${ok ? ' link' : ''}`;
  if (ok) {
    node.href = item.url;
    node.target = '_blank';
    node.rel = 'noopener noreferrer';
  }
  const reason = ok ? '' : `<div class="reason">${escapeHtml(item.reason || '접속할 수 없습니다.')}</div>`;
  node.innerHTML = `<span class="state">${ok ? '✅' : '❌'}</span><div class="copy"><div class="name">${escapeHtml(item.name)}</div><div class="url">${escapeHtml(item.url)}</div>${reason}</div>${ok ? '<span class="arrow">›</span>' : ''}`;
  return node;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

async function load() {
  refresh.classList.add('spinning');
  try {
    const response = await fetch(`status.json?t=${Date.now()}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    available.replaceChildren(...data.services.filter(x => x.ok).map(x => row(x, true)));
    unavailable.replaceChildren(...data.services.filter(x => !x.ok).map(x => row(x, false)));
    const time = new Date(data.checkedAt);
    updated.textContent = `최근 검사: ${time.toLocaleString('ko-KR')}`;
  } catch (error) {
    available.innerHTML = `<div class="error">검사 결과를 불러오지 못했습니다.<br>${escapeHtml(error.message)}</div>`;
    unavailable.replaceChildren();
    updated.textContent = '검사 결과 불러오기 실패';
  } finally {
    refresh.classList.remove('spinning');
  }
}

refresh.addEventListener('click', load);
load();
setInterval(load, 60_000);
