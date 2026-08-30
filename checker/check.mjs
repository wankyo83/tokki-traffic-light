import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const checkerDir = path.dirname(fileURLToPath(import.meta.url));
const outputDir = path.resolve(checkerDir, '../site');
const configuredSites = JSON.parse(await fs.readFile(path.join(checkerDir, 'sites.json'), 'utf8'));
const requestedSiteKeys = new Set((process.env.CHECK_SITE_KEYS || '').split(',').map(value => value.trim()).filter(Boolean));
const sites = requestedSiteKeys.size
  ? configuredSites.filter(site => requestedSiteKeys.has(site.key))
  : configuredSites;
const previous = await readPreviousStatus();
const previousServices = Array.isArray(previous.services) ? previous.services : [];
const previousGroups = new Map((previous.groups ?? []).map(group => [group.key, group]));
const services = [];
const groups = [];
const cycleStarted = Date.now();

const serviceDelayMs = numberFromEnv('SERVICE_DELAY_MS', 20_000);
const siteDelayMs = numberFromEnv('SITE_DELAY_MS', 3_000);
const candidateConfirmationsRequired = numberFromEnv('CANDIDATE_CONFIRMATIONS', 2);
const intervalMinutes = numberFromEnv('CHECK_INTERVAL_MINUTES', 10);

for (let siteIndex = 0; siteIndex < sites.length; siteIndex++) {
  const site = sites[siteIndex];
  const previousGroup = previousGroups.get(site.key);
  const activeBaseUrl = previousActiveBase(site, previousGroup);
  const primary = site.services[0];
  const discovery = await discoverBase(site, primary, activeBaseUrl);
  const candidateState = chooseActiveBase(activeBaseUrl, discovery, previousGroup);
  const probeBaseUrl = candidateState.probeBaseUrl;
  const groupServices = [];

  for (let serviceIndex = 0; serviceIndex < site.services.length; serviceIndex++) {
    const service = site.services[serviceIndex];
    if (serviceIndex > 0) await delay(serviceDelayMs);

    const probe = serviceIndex === 0 && discovery.probeBaseUrl === probeBaseUrl
      ? discovery.probe
      : await checkUrl(`${probeBaseUrl}${service.path}`, site, service);

    const priorService = previousServices.find(item => item.group === site.key && item.name === service.name);
    const transient = !probe.ok && isTransientFailure(probe.reason);
    const lastSuccessfulAt = probe.ok
      ? new Date().toISOString()
      : priorService?.lastSuccessfulAt ?? (priorService?.ok ? previous.checkedAt : null);

    const item = {
      group: site.key,
      name: service.name,
      url: `${candidateState.activeBaseUrl}${service.path}`,
      probeUrl: `${probeBaseUrl}${service.path}`,
      baseUrl: candidateState.activeBaseUrl,
      ok: probe.ok || Boolean(transient && priorService?.ok),
      state: probe.ok ? (candidateState.verifying ? 'verifying' : 'healthy') : (transient && priorService?.ok ? 'stale' : 'unavailable'),
      reason: probe.ok ? '' : readableReason(probe.reason),
      responseMs: probe.responseMs,
      lastSuccessfulAt,
      checkedAt: new Date().toISOString(),
    };

    groupServices.push(item);
    services.push(item);
  }

  const allHealthy = groupServices.every(item => item.state === 'healthy');
  const hasUsableAddress = Boolean(candidateState.activeBaseUrl);
  const state = candidateState.verifying
    ? 'verifying'
    : allHealthy
      ? 'healthy'
      : hasUsableAddress
        ? 'stale'
        : 'unavailable';

  groups.push({
    key: site.key,
    name: site.name,
    activeBaseUrl: candidateState.activeBaseUrl,
    state,
    checkedAt: new Date().toISOString(),
    lastSuccessfulAt: allHealthy
      ? new Date().toISOString()
      : latestTimestamp(groupServices.map(item => item.lastSuccessfulAt)) ?? previousGroup?.lastSuccessfulAt ?? null,
    candidateBaseUrl: candidateState.candidateBaseUrl,
    candidateConfirmations: candidateState.candidateConfirmations,
    candidateConfirmationsRequired,
    reason: candidateState.reason,
  });

  if (siteIndex < sites.length - 1) await delay(siteDelayMs);
}

const checkedAt = new Date().toISOString();
const status = {
  schemaVersion: 2,
  checkedAt,
  durationMs: Date.now() - cycleStarted,
  policy: {
    intervalMinutes,
    serviceDelaySeconds: serviceDelayMs / 1000,
    candidateConfirmationsRequired,
    preservesLastKnownGood: true,
  },
  groups,
  services,
};

const domains = {
  schemaVersion: 1,
  updatedAt: checkedAt,
  domains: Object.fromEntries(groups
    .filter(group => group.activeBaseUrl)
    .map(group => [group.key, {
      baseUrl: group.activeBaseUrl,
      status: group.state,
      lastConfirmedAt: group.lastSuccessfulAt,
    }])),
};

if (process.env.DRY_RUN !== 'true') {
  await fs.writeFile(path.join(outputDir, 'status.json'), `${JSON.stringify(status, null, 2)}\n`);
  await fs.writeFile(path.join(outputDir, 'domains.json'), `${JSON.stringify(domains, null, 2)}\n`);
}
console.log(JSON.stringify({checkedAt, durationMs: status.durationMs, groups}, null, 2));

async function discoverBase(site, service, activeBaseUrl) {
  const candidates = candidateUrls(activeBaseUrl, site.numbered);
  const first = candidates[0];
  const firstProbe = await checkUrl(`${first}${service.path}`, site, service);
  debug('현재 주소 검사', {site: site.key, url: `${first}${service.path}`, probe: firstProbe});
  if (firstProbe.ok) {
    const resolved = firstProbe.resolvedBaseUrl ?? first;
    return {probeBaseUrl: resolved, probe: firstProbe, reason: ''};
  }

  // 일부 사이트는 이전 번호에 실제 콘텐츠를 두고, 다음 번호에는 최신 주소만
  // 안내한다. 안내된 주소를 그대로 믿지 않고 실제 콘텐츠 구조까지 다시 검증한다.
  if (firstProbe.announcement) {
    const announcedBaseUrl = firstProbe.announcedBaseUrl ?? await fetchAnnouncedBaseUrl(first, site);
    debug('안내 주소 확인', {site: site.key, announcedBaseUrl});
    const announcedProbe = announcedBaseUrl
      ? await checkUrl(`${announcedBaseUrl}${service.path}`, site, service)
      : null;
    debug('안내된 실제 주소 검사', {site: site.key, announcedBaseUrl, probe: announcedProbe});
    if (announcedProbe?.ok) {
      return {
        probeBaseUrl: announcedProbe.resolvedBaseUrl ?? announcedBaseUrl,
        probe: announcedProbe,
        reason: '',
      };
    }
  }

  if (isTransientFailure(firstProbe.reason) && await dnsExists(new URL(first).hostname)) {
    return {probeBaseUrl: first, probe: firstProbe, reason: readableReason(firstProbe.reason), transient: true};
  }

  if (!site.numbered) {
    return {probeBaseUrl: first, probe: firstProbe, reason: readableReason(firstProbe.reason)};
  }

  let lastProbe = firstProbe;
  for (const candidate of candidates.slice(1)) {
    const probe = await checkUrl(`${candidate}${service.path}`, site, service, {quick: true});
    lastProbe = probe;
    if (probe.ok) {
      return {probeBaseUrl: probe.resolvedBaseUrl ?? candidate, probe, reason: ''};
    }
  }

  return {
    probeBaseUrl: first,
    probe: lastProbe,
    reason: `현재 주소부터 +10까지 확인 실패 · ${readableReason(lastProbe.reason)}`,
  };
}

function chooseActiveBase(activeBaseUrl, discovery, previousGroup) {
  const discovered = discovery.probe.ok ? discovery.probeBaseUrl : null;
  if (!discovered || discovered === activeBaseUrl) {
    return {
      activeBaseUrl,
      probeBaseUrl: activeBaseUrl,
      candidateBaseUrl: null,
      candidateConfirmations: 0,
      verifying: false,
      reason: discovery.reason,
    };
  }

  const previousCount = previousGroup?.candidateBaseUrl === discovered
    ? Number(previousGroup.candidateConfirmations || 0)
    : 0;
  const confirmations = previousCount + 1;
  if (confirmations >= candidateConfirmationsRequired) {
    return {
      activeBaseUrl: discovered,
      probeBaseUrl: discovered,
      candidateBaseUrl: null,
      candidateConfirmations: 0,
      verifying: false,
      reason: '',
    };
  }

  return {
    activeBaseUrl,
    probeBaseUrl: discovered,
    candidateBaseUrl: discovered,
    candidateConfirmations: confirmations,
    verifying: true,
    reason: `새 주소 확인 중 (${confirmations}/${candidateConfirmationsRequired})`,
  };
}

async function checkUrl(url, site, service, {quick = false} = {}) {
  const retryDelays = quick ? [0] : [0, 5_000, 15_000];
  let result;
  for (const retryDelay of retryDelays) {
    if (retryDelay) await delay(retryDelay);
    result = await checkUrlOnce(url, site, service);
    if (result.ok || result.identityMismatch || !isTransientFailure(result.reason)) return result;
  }
  return result;
}

async function checkUrlOnce(url, site, service) {
  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12_000);
  try {
    const response = await fetch(url, {
      redirect: 'follow',
      signal: controller.signal,
      headers: {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36',
        accept: 'text/html,application/xhtml+xml',
      },
    });
    const bytes = await response.arrayBuffer();
    const charset = response.headers.get('content-type')?.match(/charset\s*=\s*["']?([^;"'\s]+)/i)?.[1] || 'utf-8';
    let text;
    try { text = new TextDecoder(charset).decode(bytes).slice(0, 300_000); }
    catch { text = new TextDecoder('utf-8').decode(bytes).slice(0, 300_000); }
    const responseMs = Date.now() - started;
    if (!response.ok) return {ok: false, responseMs, reason: `HTTP ${response.status} ${response.statusText}`.trim()};
    if (!/<html|<!doctype|<body/i.test(text)) return {ok: false, responseMs, reason: '정상 웹페이지 형식이 아닙니다.'};
    const normalized = text.toLowerCase();
    const challengeDetected = /cf-chl-|challenge-platform|just a moment|cloudflare ray id/i.test(text);
    if (site.announcementMarkers?.some(marker => normalized.includes(marker.toLowerCase()))) {
      const announcedBaseUrl = extractAnnouncedBaseUrl(text, site);
      return {
        ok: false,
        responseMs,
        announcement: true,
        announcedBaseUrl,
        reason: announcedBaseUrl ? `최신 주소 안내 페이지 · ${announcedBaseUrl}` : '최신 주소 안내 페이지',
      };
    }
    const siteMatch = site.markers.some(marker => normalized.includes(marker.toLowerCase()));
    const sectionMatch = service.markers.some(marker => normalized.includes(marker.toLowerCase()));
    if (!siteMatch || !sectionMatch) {
      if (challengeDetected) return {ok: false, responseMs, reason: 'Cloudflare 브라우저 인증이 필요합니다.'};
      return {ok: false, responseMs, identityMismatch: true, reason: '사이트 또는 콘텐츠 종류가 일치하지 않습니다.'};
    }
    if (service.requiredPatterns?.length) {
      const patternMatches = service.requiredPatterns.reduce(
        (total, pattern) => total + countOccurrences(normalized, pattern.toLowerCase()),
        0,
      );
      const minimumPatternMatches = Number(service.minimumPatternMatches || 1);
      if (patternMatches < minimumPatternMatches) {
        if (challengeDetected) return {ok: false, responseMs, reason: 'Cloudflare 브라우저 인증이 필요합니다.'};
        return {
          ok: false,
          responseMs,
          identityMismatch: true,
          reason: `카테고리·작품 목록 구조가 부족합니다. (${patternMatches}/${minimumPatternMatches})`,
        };
      }
    }
    const resolvedBaseUrl = resolvedBase(response.url, site);
    if (!resolvedBaseUrl) return {ok: false, responseMs, identityMismatch: true, reason: '허용되지 않은 다른 도메인으로 이동했습니다.'};
    return {ok: true, responseMs, resolvedBaseUrl};
  } catch (error) {
    const responseMs = Date.now() - started;
    if (error.name === 'AbortError') return {ok: false, responseMs, reason: '응답 시간 초과'};
    return {ok: false, responseMs, reason: error.cause?.code || error.message};
  } finally {
    clearTimeout(timer);
  }
}

async function readPreviousStatus() {
  const remoteUrl = process.env.PREVIOUS_STATUS_URL;
  if (remoteUrl) {
    try {
      const response = await fetch(`${remoteUrl}${remoteUrl.includes('?') ? '&' : '?'}t=${Date.now()}`, {headers: {accept: 'application/json'}});
      if (response.ok) return await response.json();
    } catch (error) {
      console.warn(`이전 공개 상태를 읽지 못해 저장소 상태를 사용합니다: ${error.message}`);
    }
  }
  try {
    return JSON.parse(await fs.readFile(path.join(outputDir, 'status.json'), 'utf8'));
  } catch {
    return {groups: [], services: []};
  }
}

function previousActiveBase(site, previousGroup) {
  const previousBase = previousGroup?.activeBaseUrl
    ?? previousServices.find(service => service.group === site.key && service.baseUrl)?.baseUrl;
  if (!previousBase || !sameDomainFamily(site.base, previousBase)) return site.base;
  const configuredNumber = domainNumber(site.base);
  const previousNumber = domainNumber(previousBase);
  if (configuredNumber !== null && previousNumber !== null && previousNumber < configuredNumber) return site.base;
  return previousBase;
}

function candidateUrls(base, numbered) {
  if (!numbered) return [base];
  const url = new URL(base);
  const match = url.hostname.match(/^(.*?)(\d+)(\.[a-z.]+)$/i);
  if (!match) return [base];
  const [, prefix, digits, suffix] = match;
  const start = Number(digits);
  return Array.from({length: 11}, (_, index) => {
    const number = String(start + index).padStart(digits.length, '0');
    const candidate = new URL(base);
    candidate.hostname = `${prefix}${number}${suffix}`;
    return candidate.origin;
  });
}

function resolvedBase(responseUrl, site) {
  try {
    const base = new URL(responseUrl).origin;
    return sameDomainFamily(site.base, base) ? base : null;
  } catch {
    return null;
  }
}

function extractAnnouncedBaseUrl(text, site) {
  if (!site.announcedHostPattern) return null;
  const match = text.match(new RegExp(site.announcedHostPattern, 'i'));
  if (!match) return null;
  try {
    const candidate = `https://${match[0]}`;
    return sameDomainFamily(site.base, candidate) ? new URL(candidate).origin : null;
  } catch {
    return null;
  }
}

async function fetchAnnouncedBaseUrl(baseUrl, site) {
  if (!site.announcementDataPath || !site.announcementDataField) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8_000);
  try {
    const response = await fetch(new URL(site.announcementDataPath, baseUrl), {
      signal: controller.signal,
      cache: 'no-store',
      headers: {accept: 'application/json'},
    });
    if (!response.ok) return null;
    const data = await response.json();
    const raw = data?.[site.announcementDataField];
    if (typeof raw !== 'string') return null;
    const candidate = new URL(raw).origin;
    return sameDomainFamily(site.base, candidate) ? candidate : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function sameDomainFamily(configuredBase, candidateBase) {
  const configured = new URL(configuredBase);
  const candidate = new URL(candidateBase);
  if (candidate.protocol !== 'https:') return false;
  const configuredHost = configured.hostname.replace(/^www\./i, '');
  const candidateHost = candidate.hostname.replace(/^www\./i, '');
  const numbered = configuredHost.match(/^(.*?)(\d+)(\.[a-z.]+)$/i);
  if (!numbered) return configuredHost === candidateHost;
  const candidateNumbered = candidateHost.match(/^(.*?)(\d+)(\.[a-z.]+)$/i);
  return Boolean(candidateNumbered && numbered[1] === candidateNumbered[1] && numbered[3] === candidateNumbered[3]);
}

function domainNumber(base) {
  const host = new URL(base).hostname.replace(/^www\./i, '');
  const match = host.match(/^(.*?)(\d+)(\.[a-z.]+)$/i);
  return match ? Number(match[2]) : null;
}

async function dnsExists(hostname) {
  try {
    const response = await fetch(`https://dns.google/resolve?name=${encodeURIComponent(hostname)}&type=A`, {headers: {accept: 'application/dns-json'}});
    if (!response.ok) return false;
    const data = await response.json();
    return data.Status === 0 && Array.isArray(data.Answer) && data.Answer.some(answer => answer.type === 1);
  } catch {
    return true;
  }
}

function isTransientFailure(reason) {
  return /^(ENOTFOUND|EAI_AGAIN|ECONNRESET|ETIMEDOUT|UND_ERR_CONNECT_TIMEOUT|응답 시간 초과|fetch failed)$/i.test(reason);
}

function readableReason(reason) {
  const messages = {
    ENOTFOUND: '검사 서버의 순간적인 DNS 조회 실패',
    EAI_AGAIN: '검사 서버의 순간적인 DNS 조회 지연',
    ECONNRESET: '연결이 일시적으로 끊어짐',
    ETIMEDOUT: '연결 시간 초과',
    UND_ERR_CONNECT_TIMEOUT: '연결 시간 초과',
    'fetch failed': '검사 서버의 일시적인 연결 실패',
  };
  return messages[reason] ?? reason ?? '사이트에 연결할 수 없습니다.';
}

function numberFromEnv(name, fallback) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function latestTimestamp(values) {
  return values.filter(Boolean).sort().at(-1) ?? null;
}

function countOccurrences(text, search) {
  if (!search) return 0;
  let count = 0;
  let position = 0;
  while ((position = text.indexOf(search, position)) !== -1) {
    count++;
    position += search.length;
  }
  return count;
}

function delay(milliseconds) {
  return milliseconds > 0 ? new Promise(resolve => setTimeout(resolve, milliseconds)) : Promise.resolve();
}

function debug(label, value) {
  if (process.env.DEBUG_CHECKS === 'true') console.log(`[debug] ${label}`, JSON.stringify(value));
}
