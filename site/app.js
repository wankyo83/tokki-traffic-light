const mangaAddresses = document.querySelector('#manga-addresses');
const mediaAddresses = document.querySelector('#media-addresses');
const updated = document.querySelector('#updated');
const updatedAge = document.querySelector('#updated-age');
const duration = document.querySelector('#duration');
const freshnessWarning = document.querySelector('#freshness-warning');
const refresh = document.querySelector('#refresh');
const healthyCount = document.querySelector('#healthy-count');
const verifyingCount = document.querySelector('#verifying-count');
const blockedCount = document.querySelector('#blocked-count');
const expectedGitHubIntervalMinutes = 60;
const delayedAfterMinutes = 90;
const criticalAfterMinutes = 150;
const adminApi = document.querySelector('#admin-api');
const adminToken = document.querySelector('#admin-token');
const adminSite = document.querySelector('#admin-site');
const adminUrl = document.querySelector('#admin-url');
const adminSubmit = document.querySelector('#admin-submit');
const adminResult = document.querySelector('#admin-result');
adminApi.value = localStorage.getItem('tokki-admin-api') || '';

function relativeAge(milliseconds) {
  const minutes = Math.max(0, Math.floor(milliseconds / 60_000));
  if (minutes < 1) return '방금 전';
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours < 24) return remainder ? `${hours}시간 ${remainder}분 전` : `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  return `${days}일 ${hours % 24}시간 전`;
}

function showGitHubFreshness(checkedAt) {
  const checkedTime = new Date(checkedAt);
  const ageMs = Date.now() - checkedTime.getTime();
  const ageMinutes = ageMs / 60_000;
  const valid = Number.isFinite(checkedTime.getTime()) && ageMs >= -60_000;

  if (!valid) {
    updated.textContent = 'NAS 주소 검사: 시간 정보 없음';
    updatedAge.textContent = '';
    updatedAge.className = 'freshness-critical';
    freshnessWarning.hidden = false;
    freshnessWarning.className = 'freshness-warning critical';
    freshnessWarning.textContent = 'NAS 주소 검사 시각을 확인할 수 없습니다.';
    return;
  }

  updated.textContent = `NAS 주소 검사: ${checkedTime.toLocaleString('ko-KR')}`;
  updatedAge.textContent = `마지막 검사 ${relativeAge(ageMs)} · 예정 주기 ${expectedGitHubIntervalMinutes}분`;
  updatedAge.className = ageMinutes >= criticalAfterMinutes
    ? 'freshness-critical'
    : ageMinutes >= delayedAfterMinutes ? 'freshness-late' : '';

  if (ageMinutes < delayedAfterMinutes) {
    freshnessWarning.hidden = true;
    freshnessWarning.textContent = '';
    freshnessWarning.className = 'freshness-warning';
    return;
  }

  freshnessWarning.hidden = false;
  freshnessWarning.className = `freshness-warning${ageMinutes >= criticalAfterMinutes ? ' critical' : ''}`;
  freshnessWarning.textContent = `NAS 주소 검사가 ${relativeAge(ageMs)}에 실행된 뒤 갱신되지 않았습니다. 아래 주소는 마지막 확인 결과입니다.`;
}

function addressRow(group) {
  const node = document.createElement('div');
  node.className = 'row address-row';
  const stateView = {
    healthy: {icon: '✅', label: '정상', badge: 'healthy'},
    manual: {icon: '📌', label: '수동 등록', badge: 'healthy'},
    verifying: {icon: '🔄', label: '새 주소 확인 중', badge: 'verifying'},
    stale: {icon: '⚠️', label: '참조처 확인 실패', badge: 'stale'},
    unavailable: {icon: '❌', label: '확정 주소 없음', badge: 'unavailable'},
  }[group.state] ?? {icon: '⚠️', label: '확인 필요', badge: 'stale'};
  const activeAddress = group.activeBaseUrl
    ? `<a class="url address-link" href="${escapeHtml(group.activeBaseUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(group.activeBaseUrl)}</a>`
    : '<div class="url">확정 주소 없음</div>';
  const candidate = group.candidateBaseUrl
    ? `<div class="candidate">새 주소 후보: <a href="${escapeHtml(group.candidateBaseUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(group.candidateBaseUrl)}</a> · 직접 확인 필요</div>`
    : '';
  const error = group.reason && (group.state !== 'healthy' || /guide unavailable|guide challenged|failed/i.test(group.reason))
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
    const cacheBuster = Date.now();
    const response = await fetch(`status.json?t=${cacheBuster}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const groups = data.groups || [];
    const selectedSite = adminSite.value;
    adminSite.replaceChildren(...groups.map(group => {
      const option = document.createElement('option');
      option.value = group.key;
      option.textContent = group.name;
      return option;
    }));
    if (groups.some(group => group.key === selectedSite)) adminSite.value = selectedSite;
    const mediaKeys = new Set(['linkkf', 'ani24', 'tvroom', 'tvwiki', 'anilife']);
    const mediaGroups = groups.filter(group => group.category === 'media' || mediaKeys.has(group.key));
    const mangaGroups = groups.filter(group => group.category !== 'media' && !mediaKeys.has(group.key));
    mangaAddresses.replaceChildren(...mangaGroups.map(addressRow));
    mediaAddresses.replaceChildren(...mediaGroups.map(addressRow));
    showGitHubFreshness(data.checkedAt);
    duration.textContent = data.durationMs ? `전체 검사 소요: ${Math.round(data.durationMs / 1000)}초` : '';
    healthyCount.textContent = groups.filter(group => group.state === 'healthy' || group.state === 'manual').length;
    verifyingCount.textContent = groups.filter(group => group.state === 'verifying').length;
    blockedCount.textContent = groups.filter(group => group.state === 'stale' || group.state === 'unavailable').length;
  } catch (error) {
    const errorView = `<div class="error">주소 확인 결과를 불러오지 못했습니다.<br>${escapeHtml(error.message)}</div>`;
    mangaAddresses.innerHTML = errorView;
    mediaAddresses.innerHTML = errorView;
    updated.textContent = '주소 확인 결과 불러오기 실패';
    updatedAge.textContent = '';
    updatedAge.className = 'freshness-critical';
    freshnessWarning.hidden = false;
    freshnessWarning.className = 'freshness-warning critical';
    freshnessWarning.textContent = '최신 주소 검사 결과를 불러오지 못했습니다.';
    duration.textContent = '';
  } finally {
    refresh.classList.remove('spinning');
  }
}

refresh.addEventListener('click', load);
adminSubmit.addEventListener('click', async () => {
  adminResult.textContent = '';
  let base;
  try {
    base = new URL(adminApi.value.trim());
    if (base.protocol !== 'https:' || base.username || base.password || base.pathname !== '/') throw new Error('NAS 관리 주소는 HTTPS 기본 주소여야 합니다.');
    if (!adminToken.value || !adminSite.value || !adminUrl.value) throw new Error('관리 토큰, 사이트, 새 주소를 입력하세요.');
    localStorage.setItem('tokki-admin-api', base.origin);
    adminSubmit.disabled = true;
    const response = await fetch(`${base.origin}/api/manual-candidate`, {
      method: 'POST',
      headers: {'Authorization': `Bearer ${adminToken.value}`, 'Content-Type': 'application/json'},
      body: JSON.stringify({key: adminSite.value, url: adminUrl.value.trim()}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    adminResult.textContent = `${result.url} 검증 요청 완료. NAS 확인 후 통과하면 공개 주소에 반영됩니다.`;
  } catch (error) {
    adminResult.textContent = `요청 실패: ${error.message}`;
  } finally {
    adminSubmit.disabled = false;
  }
});
load();
setInterval(load, 60_000);
