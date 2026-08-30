const addresses = document.querySelector('#addresses');
const updated = document.querySelector('#updated');
const duration = document.querySelector('#duration');
const refresh = document.querySelector('#refresh');
const healthyCount = document.querySelector('#healthy-count');
const verifyingCount = document.querySelector('#verifying-count');
const blockedCount = document.querySelector('#blocked-count');

function addressRow(group) {
  const node = document.createElement('div');
  node.className = 'row address-row';
  const stateView = {
    healthy: {icon: '✅', label: '정상', badge: 'healthy'},
    verifying: {icon: '🔄', label: '새 주소 확인 중', badge: 'verifying'},
    stale: {icon: '⚠️', label: '접속 차단', badge: 'stale'},
    unavailable: {icon: '❌', label: '접속 차단', badge: 'unavailable'},
  }[group.state] ?? {icon: '⚠️', label: '확인 필요', badge: 'stale'};
  const activeAddress = group.activeBaseUrl
    ? `<a class="url address-link" href="${escapeHtml(group.activeBaseUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(group.activeBaseUrl)}</a>`
    : '<div class="url">확정 주소 없음</div>';
  const candidate = group.candidateBaseUrl
    ? `<div class="candidate">새 주소 후보: <a href="${escapeHtml(group.candidateBaseUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(group.candidateBaseUrl)}</a> · ${group.candidateConfirmations}/${group.candidateConfirmationsRequired}회 확인</div>`
    : '';
  const error = group.reason && group.state !== 'healthy'
    ? `<div class="reason ${group.state === 'verifying' ? 'warning' : ''}">${group.errorCode ? `${escapeHtml(group.errorCode)} · ` : ''}${escapeHtml(group.reason)}</div>`
    : '';
  const source = group.sourceUrl
    ? `<a class="source-link" href="${escapeHtml(group.sourceUrl)}" target="_blank" rel="noopener noreferrer">주소 출처: ${escapeHtml(group.sourceName || '안내 페이지')}</a>`
    : '';

  node.innerHTML = `
    <span class="state">${stateView.icon}</span>
    <div class="copy">
      <div class="name">${escapeHtml(group.name)} 주소 확인 <span class="badge ${stateView.badge}">${stateView.label}</span></div>
      ${activeAddress}${candidate}${error}${source}
    </div>
    <button class="copy-button" type="button">복사</button>`;

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
  return String(value).replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
}

async function load() {
  refresh.classList.add('spinning');
  try {
    const response = await fetch(`status.json?t=${Date.now()}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const groups = data.groups || [];
    addresses.replaceChildren(...groups.map(addressRow));
    const time = new Date(data.checkedAt);
    updated.textContent = `최근 주소 확인: ${time.toLocaleString('ko-KR')}`;
    duration.textContent = data.durationMs ? `소요: ${Math.round(data.durationMs / 1000)}초` : '';
    healthyCount.textContent = groups.filter(group => group.state === 'healthy').length;
    verifyingCount.textContent = groups.filter(group => group.state === 'verifying').length;
    blockedCount.textContent = groups.filter(group => group.state === 'stale' || group.state === 'unavailable').length;
  } catch (error) {
    addresses.innerHTML = `<div class="error">주소 확인 결과를 불러오지 못했습니다.<br>${escapeHtml(error.message)}</div>`;
    updated.textContent = '주소 확인 결과 불러오기 실패';
    duration.textContent = '';
  } finally {
    refresh.classList.remove('spinning');
  }
}

refresh.addEventListener('click', load);
load();
setInterval(load, 60_000);
