const available = document.querySelector('#available');
const unavailable = document.querySelector('#unavailable');
const addresses = document.querySelector('#addresses');
const updated = document.querySelector('#updated');
const duration = document.querySelector('#duration');
const refresh = document.querySelector('#refresh');
const healthyCount = document.querySelector('#healthy-count');
const staleCount = document.querySelector('#stale-count');
const downCount = document.querySelector('#down-count');

function row(item, ok) {
  const node = document.createElement(ok ? 'a' : 'div');
  node.className = `row${ok ? ' link' : ''}`;
  if (ok) {
    node.href = item.url;
    node.target = '_blank';
    node.rel = 'noopener noreferrer';
  }
  const protectedState = item.state === 'stale' || item.state === 'verifying';
  const icon = protectedState ? '⚠️' : ok ? '✅' : '❌';
  const reason = item.reason ? `<div class="reason ${protectedState ? 'warning' : ''}">${escapeHtml(item.reason)}</div>` : '';
  const lastSuccess = item.lastSuccessfulAt ? `<div class="last-success">마지막 정상: ${formatTime(item.lastSuccessfulAt)}</div>` : '';
  node.innerHTML = `<span class="state">${icon}</span><div class="copy"><div class="name">${escapeHtml(item.name)}</div><div class="url">${escapeHtml(item.url)}</div>${reason}${lastSuccess}</div>${ok ? '<span class="arrow">›</span>' : ''}`;
  return node;
}

function addressRow(group) {
  const node = document.createElement('div');
  node.className = 'row address-row';
  const state = group.state === 'healthy' ? '정상' : group.state === 'verifying' ? '새 주소 확인 중' : group.state === 'stale' ? '마지막 정상 주소 보호 중' : '확인 필요';
  const icon = group.state === 'healthy' ? '✅' : group.state === 'unavailable' ? '❌' : '⚠️';
  const candidate = group.candidateBaseUrl
    ? `<div class="candidate">후보: ${escapeHtml(group.candidateBaseUrl)} · ${group.candidateConfirmations}/${group.candidateConfirmationsRequired}회 확인</div>`
    : '';
  node.innerHTML = `<span class="state">${icon}</span><div class="copy"><div class="name">${escapeHtml(group.name)} <span class="badge ${escapeHtml(group.state)}">${state}</span></div><div class="url">${escapeHtml(group.activeBaseUrl || '확정 주소 없음')}</div>${candidate}</div><button class="copy-button" type="button">복사</button>`;
  const button = node.querySelector('.copy-button');
  button.disabled = !group.activeBaseUrl;
  button.addEventListener('click', async () => {
    await navigator.clipboard.writeText(group.activeBaseUrl);
    button.textContent = '완료';
    setTimeout(() => { button.textContent = '복사'; }, 1000);
  });
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
    const groups = data.groups || [];
    const protectedGroups = groups.filter(x => x.state === 'stale' || x.state === 'verifying');
    addresses.replaceChildren(...groups.map(addressRow));
    available.replaceChildren(...data.services.filter(x => x.ok).map(x => row(x, true)));
    unavailable.replaceChildren(...data.services.filter(x => !x.ok).map(x => row(x, false)));
    const time = new Date(data.checkedAt);
    updated.textContent = `최근 검사: ${time.toLocaleString('ko-KR')}`;
    duration.textContent = data.durationMs ? `검사 소요: ${Math.round(data.durationMs / 1000)}초` : '';
    healthyCount.textContent = groups.filter(x => x.state === 'healthy').length;
    staleCount.textContent = protectedGroups.length;
    downCount.textContent = groups.filter(x => x.state === 'unavailable').length;
  } catch (error) {
    addresses.innerHTML = `<div class="error">최신 주소를 불러오지 못했습니다.</div>`;
    available.innerHTML = `<div class="error">검사 결과를 불러오지 못했습니다.<br>${escapeHtml(error.message)}</div>`;
    unavailable.replaceChildren();
    updated.textContent = '검사 결과 불러오기 실패';
    duration.textContent = '';
  } finally {
    refresh.classList.remove('spinning');
  }
}

refresh.addEventListener('click', load);
load();
setInterval(load, 60_000);

function formatTime(value) {
  return new Date(value).toLocaleString('ko-KR');
}
