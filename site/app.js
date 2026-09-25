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
    stale: {icon: '⚠️', label: '확인 실패 · 기존 주소 유지', badge: 'stale'},
    unavailable: {icon: '❌', label: '확정 주소 없음', badge: 'unavailable'},
  }[group.state] ?? {icon: '⚠️', label: '확인 필요', badge: 'stale'};
  const activeAddress = group.activeBaseUrl
    ? `<a class="url address-link" href="${escapeHtml(group.activeBaseUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(group.activeBaseUrl)}</a>`
    : '<div class="url">확정 주소 없음</div>';
  const candidate = group.candidateBaseUrl
    ? `<div class="candidate">새 주소 후보: <a href="${escapeHtml(group.candidateBaseUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(group.candidateBaseUrl)}</a> · 직접 확인 필요</div>`
    : '';
  const checks = group.checks;
  const stageMessages = [];
  if (checks?.current?.state === 'failed') {
    stageMessages.push(`등록 주소 확인 실패: ${checks.current.detail || '사이트 검증 실패'}`);
  }
  if (checks?.source?.state === 'failed') {
    stageMessages.push(`참조처 확인 실패: ${checks.source.detail || '유효한 주소를 찾지 못함'}`);
  }
  if (checks?.source?.state === 'healthy') {
    stageMessages.push('참조처 주소 검증 성공');
  }
  if (checks?.numeric?.state === 'failed') {
    stageMessages.push(`다음 번호 +1~+10 확인 실패 (${checks.numeric.checked || 0}개) · 기존 주소 유지`);
  }
  if (checks?.numeric?.state === 'healthy') {
    stageMessages.push(`다음 번호 검증 성공 (${checks.numeric.checked || 0}번째 후보)`);
  }
  if (checks?.numeric?.state === 'unavailable') {
    stageMessages.push('다음 번호 후보가 없어 기존 주소 유지');
  }
  const error = checks
    ? stageMessages.map(message => `<div class="reason ${group.state === 'healthy' ? 'warning' : ''}">${escapeHtml(message)}</div>`).join('')
    : group.reason && group.state !== 'healthy'
      ? `<div class="reason">${group.errorCode ? `${escapeHtml(group.errorCode)} · ` : ''}${escapeHtml(group.reason)}</div>`
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
load();
setInterval(load, 60_000);
