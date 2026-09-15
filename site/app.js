const mangaAddresses = document.querySelector('#manga-addresses');
const mediaAddresses = document.querySelector('#media-addresses');
const updated = document.querySelector('#updated');
const duration = document.querySelector('#duration');
const refresh = document.querySelector('#refresh');
const healthyCount = document.querySelector('#healthy-count');
const verifyingCount = document.querySelector('#verifying-count');
const blockedCount = document.querySelector('#blocked-count');
const verificationStatusUrl = 'https://dc-toki-mangayomi-total-toki-manga-test.pages.dev/status/address-verification.json';

function verificationView(group, verification) {
  if (!verification) return {label: 'NAS 확인 대기', badge: 'nas-pending', detail: '아직 NAS 직접 확인 결과가 없습니다.'};
  if (!sameAddress(group.activeBaseUrl, verification.baseUrl)) {
    return {label: 'NAS 재확인 대기', badge: 'nas-pending', detail: '최신 주소가 바뀌어 새 주소 확인 결과를 기다리고 있습니다.'};
  }
  const views = {
    verified: {label: 'NAS 확인 정상', badge: 'nas-verified'},
    limited: {label: 'NAS 확인 제한', badge: 'nas-limited'},
    mismatch: {label: 'NAS 구조 불일치', badge: 'nas-mismatch'},
    unreachable: {label: 'NAS 접속 실패', badge: 'nas-unreachable'},
    pending: {label: 'NAS 확인 대기', badge: 'nas-pending'},
  };
  const view = views[verification.state] || views.pending;
  const checkedAt = verification.checkedAt ? new Date(verification.checkedAt).toLocaleString('ko-KR') : '시간 정보 없음';
  const response = verification.responseSeconds ? ` · ${verification.responseSeconds}초` : '';
  return {...view, detail: `${verification.reason || view.label} (${checkedAt}${response})`};
}

function sameAddress(left, right) {
  try {
    const normalize = value => {
      const url = new URL(value);
      return `${url.protocol}//${url.hostname.replace(/^www\./i, '').toLowerCase()}${url.port ? `:${url.port}` : ''}`;
    };
    return Boolean(left && right && normalize(left) === normalize(right));
  } catch {
    return false;
  }
}

function addressRow(group, verification) {
  const node = document.createElement('div');
  node.className = 'row address-row';
  const stateView = {
    healthy: {icon: '✅', label: '정상', badge: 'healthy'},
    manual: {icon: '📌', label: '수동 등록', badge: 'healthy'},
    verifying: {icon: '🔄', label: '새 주소 확인 중', badge: 'verifying'},
    stale: {icon: '⚠️', label: '참조처 확인 실패', badge: 'stale'},
    unavailable: {icon: '❌', label: '확정 주소 없음', badge: 'unavailable'},
  }[group.state] ?? {icon: '⚠️', label: '확인 필요', badge: 'stale'};
  const nasView = verificationView(group, verification);
  const activeAddress = group.activeBaseUrl
    ? `<a class="url address-link" href="${escapeHtml(group.activeBaseUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(group.activeBaseUrl)}</a>`
    : '<div class="url">확정 주소 없음</div>';
  const candidate = group.candidateBaseUrl
    ? `<div class="candidate">새 주소 후보: <a href="${escapeHtml(group.candidateBaseUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(group.candidateBaseUrl)}</a> · 직접 확인 필요</div>`
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
      <div class="name">${escapeHtml(group.name)} 주소 확인 <span class="badge ${stateView.badge}">${stateView.label}</span><span class="badge nas ${nasView.badge}" title="${escapeHtml(nasView.detail)}">${nasView.label}</span></div>
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
    const cacheBuster = Date.now();
    const [response, verificationResponse] = await Promise.all([
      fetch(`status.json?t=${cacheBuster}`, {cache: 'no-store'}),
      fetch(`${verificationStatusUrl}?t=${cacheBuster}`, {cache: 'no-store'}).catch(() => null),
    ]);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const verificationData = verificationResponse?.ok ? await verificationResponse.json().catch(() => null) : null;
    const verificationByKey = new Map((verificationData?.checks || []).map(check => [check.key, check]));
    const groups = data.groups || [];
    const mediaKeys = new Set(['linkkf', 'ani24']);
    const mediaGroups = groups.filter(group => group.category === 'media' || mediaKeys.has(group.key));
    const mangaGroups = groups.filter(group => group.category !== 'media' && !mediaKeys.has(group.key));
    mangaAddresses.replaceChildren(...mangaGroups.map(group => addressRow(group, verificationByKey.get(group.key))));
    mediaAddresses.replaceChildren(...mediaGroups.map(group => addressRow(group, verificationByKey.get(group.key))));
    const time = new Date(data.checkedAt);
    updated.textContent = `최근 주소 확인: ${time.toLocaleString('ko-KR')}`;
    const nasTime = verificationData?.checks?.length && verificationData.generatedAt
      ? `NAS 직접 확인: ${new Date(verificationData.generatedAt).toLocaleString('ko-KR')}`
      : 'NAS 직접 확인: 첫 결과 대기 중';
    duration.textContent = `${data.durationMs ? `주소 안내처 소요: ${Math.round(data.durationMs / 1000)}초 · ` : ''}${nasTime}`;
    healthyCount.textContent = groups.filter(group => group.state === 'healthy').length;
    verifyingCount.textContent = groups.filter(group => group.state === 'verifying').length;
    blockedCount.textContent = groups.filter(group => group.state === 'stale' || group.state === 'unavailable').length;
  } catch (error) {
    const errorView = `<div class="error">주소 확인 결과를 불러오지 못했습니다.<br>${escapeHtml(error.message)}</div>`;
    mangaAddresses.innerHTML = errorView;
    mediaAddresses.innerHTML = errorView;
    updated.textContent = '주소 확인 결과 불러오기 실패';
    duration.textContent = '';
  } finally {
    refresh.classList.remove('spinning');
  }
}

refresh.addEventListener('click', load);
load();
setInterval(load, 60_000);
