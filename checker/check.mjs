import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chooseTrustedAddress, matchesAllowedHost, normalizeOrigin, sameDomainFamily} from './address-policy.mjs';

const checkerDir = path.dirname(fileURLToPath(import.meta.url));
const outputDir = path.resolve(checkerDir, '../site');
const configuredSites = JSON.parse(await fs.readFile(path.join(checkerDir, 'sites.json'), 'utf8'));
const requestedSiteKeys = new Set((process.env.CHECK_SITE_KEYS || '').split(',').map(value => value.trim()).filter(Boolean));
const sites = requestedSiteKeys.size
  ? configuredSites.filter(site => requestedSiteKeys.has(site.key))
  : configuredSites;
const previous = await readPreviousStatus();
const previousGroups = new Map((previous.groups ?? []).map(group => [group.key, group]));
const intervalMinutes = numberFromEnv('CHECK_INTERVAL_MINUTES', 10);
const groups = [];
const cycleStarted = Date.now();

for (const site of sites) {
  const previousGroup = previousGroups.get(site.key);
  const activeBaseUrl = previousActiveBase(site, previousGroup);
  const result = site.manual
    ? {ok: true, manual: true, baseUrl: site.base, responseMs: 0, reason: '', errorCode: ''}
    : site.source
      ? await discoverFromSource(site)
      : await checkFixedAddress(site);
  const selected = chooseTrustedAddress(site, activeBaseUrl, result, previousGroup);
  const checkedAt = new Date().toISOString();

  groups.push({
    key: site.key,
    name: site.name,
    category: site.category ?? 'manga',
    activeBaseUrl: selected.activeBaseUrl,
    state: result.manual ? 'manual' : result.ok ? (selected.verifying ? 'verifying' : 'healthy') : (selected.activeBaseUrl ? 'stale' : 'unavailable'),
    checkedAt,
    lastSuccessfulAt: result.ok ? checkedAt : previousGroup?.lastSuccessfulAt ?? null,
    candidateBaseUrl: selected.candidateBaseUrl,
    candidateConfirmations: selected.candidateConfirmations,
    candidateConfirmationsRequired: 0,
    candidateRequiresManualApproval: selected.manualReview,
    sourceName: site.manual?.name ?? site.source?.name ?? site.check?.name ?? '주소 확인',
    sourceUrl: site.manual?.url ?? site.source?.url ?? site.check?.url ?? site.base,
    sourceType: site.manual ? 'manual' : site.source?.type ?? 'direct',
    errorCode: result.ok ? '' : result.errorCode,
    reason: selected.verifying ? '도메인 형식이 변경되어 직접 확인이 필요합니다.' : result.reason,
  });
}

const checkedAt = new Date().toISOString();
const status = {
  schemaVersion: 3,
  checkedAt,
  durationMs: Date.now() - cycleStarted,
  policy: {
    intervalMinutes,
    candidateConfirmationsRequired: 0,
    preservesLastKnownGood: true,
    addressSourcesOnly: true,
    sequentialNumberSearch: false,
    sameFamilyAutoPromotion: true,
    crossFamilyRequiresManualApproval: true,
  },
  groups,
  services: [],
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

async function discoverFromSource(site) {
  const started = Date.now();
  const source = site.source;
  const fetched = await fetchSource(source);
  if (!fetched.ok) return {...fetched, responseMs: Date.now() - started};

  const normalized = fetched.text.toLowerCase();
  const missingMarker = (source.markers ?? []).find(marker => !normalized.includes(marker.toLowerCase()));
  if (missingMarker) {
    return {
      ok: false,
      errorCode: 'SOURCE_FORMAT',
      reason: `주소 안내 페이지 형식이 달라졌습니다. (${missingMarker})`,
      responseMs: Date.now() - started,
    };
  }

  const redirectedBaseUrl = source.useFinalUrl
    ? normalizeCandidate(fetched.finalUrl, source.url, source.hostPattern)
    : null;
  const baseUrl = redirectedBaseUrl ?? (source.type === 'telegram'
    ? extractLatestTelegramAddress(fetched.text, source)
    : extractGuideAddress(fetched.text, source));
  if (!baseUrl) {
    return {
      ok: false,
      errorCode: 'ADDRESS_NOT_FOUND',
      reason: '안내 페이지에서 허용된 최신 주소 링크를 찾지 못했습니다.',
      responseMs: Date.now() - started,
    };
  }
  return {ok: true, baseUrl, responseMs: Date.now() - started, reason: '', errorCode: ''};
}

async function checkFixedAddress(site) {
  const started = Date.now();
  const target = site.check?.url ?? site.base;
  const fetched = await fetchHtml(target);
  if (!fetched.ok) return {...fetched, responseMs: Date.now() - started};
  const normalized = fetched.text.toLowerCase();
  const missingMarker = (site.check?.markers ?? []).find(marker => !normalized.includes(marker.toLowerCase()));
  if (missingMarker) {
    return {
      ok: false,
      errorCode: 'CONTENT_MISMATCH',
      reason: `고정 주소는 열렸지만 예상한 사이트 내용이 없습니다. (${missingMarker})`,
      responseMs: Date.now() - started,
    };
  }
  return {ok: true, baseUrl: site.base, responseMs: Date.now() - started, reason: '', errorCode: ''};
}

async function fetchSource(source) {
  const urls = source.fetchUrls ?? [source.url, ...(source.fallbackUrls ?? [])];
  let lastResult;
  for (const url of urls) {
    const allowPlainText = url.startsWith('https://r.jina.ai/');
    lastResult = await fetchHtml(url, {allowPlainText});
    if (lastResult.ok) return lastResult;
  }
  return lastResult;
}

async function fetchHtml(url, {allowPlainText = false} = {}) {
  let lastResult;
  for (const delayMs of [0, 3_000]) {
    if (delayMs) await delay(delayMs);
    lastResult = await fetchHtmlOnce(url, {allowPlainText});
    if (lastResult.ok || !isRetryable(lastResult)) return lastResult;
  }
  return lastResult;
}

async function fetchHtmlOnce(url, {allowPlainText = false} = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(url, {
      redirect: 'follow',
      signal: controller.signal,
      cache: 'no-store',
      headers: {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36',
        accept: 'text/html,application/xhtml+xml',
      },
    });
    if (!response.ok) {
      return {
        ok: false,
        errorCode: `HTTP_${response.status}`,
        reason: `HTTP ${response.status} ${response.statusText}`.trim(),
      };
    }
    const bytes = await response.arrayBuffer();
    const charset = response.headers.get('content-type')?.match(/charset\s*=\s*["']?([^;"'\s]+)/i)?.[1] || 'utf-8';
    let text;
    try { text = new TextDecoder(charset).decode(bytes); }
    catch { text = new TextDecoder('utf-8').decode(bytes); }
    if (!allowPlainText && !/<html|<!doctype|<body/i.test(text)) {
      return {ok: false, errorCode: 'INVALID_HTML', reason: '정상 HTML 페이지 형식이 아닙니다.'};
    }
    return {ok: true, text: text.slice(0, 1_000_000), finalUrl: response.url};
  } catch (error) {
    if (error.name === 'AbortError') return {ok: false, errorCode: 'TIMEOUT', reason: '응답 시간 초과'};
    const code = error.cause?.code || 'NETWORK';
    return {ok: false, errorCode: code, reason: readableNetworkReason(code, error.message)};
  } finally {
    clearTimeout(timer);
  }
}

function extractGuideAddress(html, source) {
  const sourceOrigin = new URL(source.url).origin;
  const candidates = uniqueOrigins([...extractHrefs(html), ...extractMarkdownLinkTargets(html), ...extractAbsoluteUrls(html)], source)
    .filter(baseUrl => baseUrl !== sourceOrigin);
  for (const preferredHost of source.preferredHosts ?? []) {
    const preferred = candidates.find(baseUrl => new URL(baseUrl).hostname.replace(/^www\./i, '') === preferredHost.replace(/^www\./i, ''));
    if (preferred) return preferred;
  }
  return candidates.find(baseUrl => matchesAllowedHost(baseUrl, source.hostPattern))
    ?? candidates.find(baseUrl => isReviewableExternalAddress(baseUrl, source))
    ?? null;
}

function extractLatestTelegramAddress(html, source) {
  const postPattern = new RegExp(`data-post=["']${escapeRegExp(source.channel)}/(\\d+)["']`, 'gi');
  const posts = [...html.matchAll(postPattern)];
  const candidates = [];
  for (let index = 0; index < posts.length; index++) {
    const start = posts[index].index;
    const end = posts[index + 1]?.index ?? html.length;
    const chunk = html.slice(start, end);
    const candidateChunk = selectTelegramAddressSection(chunk, source);
    const postNumber = Number(posts[index][1]);
    for (const baseUrl of uniqueOrigins([...extractHrefs(candidateChunk), ...extractMarkdownLinkTargets(candidateChunk), ...extractAbsoluteUrls(candidateChunk)], source)) {
      if (isReviewableExternalAddress(baseUrl, source)) candidates.push({postNumber, baseUrl, allowed: matchesAllowedHost(baseUrl, source.hostPattern)});
    }
  }
  candidates.sort((a, b) => b.postNumber - a.postNumber || Number(b.allowed) - Number(a.allowed));
  const latestPost = candidates[0]?.postNumber;
  const latest = candidates.filter(value => value.postNumber === latestPost);
  return latest.find(value => value.allowed)?.baseUrl ?? latest[0]?.baseUrl ?? null;
}

function selectTelegramAddressSection(chunk, source) {
  if (!source.preferredLabel) return chunk;

  const normalized = chunk.toLowerCase();
  const label = source.preferredLabel.toLowerCase();
  const start = normalized.indexOf(label);
  if (start < 0) return '';

  let end = chunk.length;
  for (const stopLabel of source.stopLabels ?? []) {
    const stop = normalized.indexOf(stopLabel.toLowerCase(), start + label.length);
    if (stop >= 0 && stop < end) end = stop;
  }
  return chunk.slice(start, end);
}

function extractHrefs(html) {
  return [...html.matchAll(/href\s*=\s*["']([^"']+)["']/gi)].map(match => decodeHtmlUrl(match[1]));
}

function extractMarkdownLinkTargets(text) {
  return [...text.matchAll(/\]\((https?:\/\/[^)\s]+)\)/gi)].map(match => decodeHtmlUrl(match[1]));
}

function extractAbsoluteUrls(html) {
  return [...html.matchAll(/https?:\/\/[^\s"'<>]+/gi)].map(match => decodeHtmlUrl(match[0]));
}

function decodeHtmlUrl(value) {
  return value
    .replace(/&amp;/gi, '&')
    .replace(/&#x2F;/gi, '/')
    .replace(/&#47;/gi, '/')
    .replace(/[),.;]+$/g, '');
}

function normalizeCandidate(value, sourceUrl, hostPattern) {
  const candidate = normalizeOrigin(value, sourceUrl);
  return candidate && matchesAllowedHost(candidate, hostPattern) ? candidate : null;
}

function uniqueOrigins(values, source) {
  const seen = new Set();
  const result = [];
  for (const value of values) {
    const origin = normalizeOrigin(value, source.url);
    if (!origin || seen.has(origin)) continue;
    seen.add(origin);
    result.push(origin);
  }
  return result;
}

function isReviewableExternalAddress(baseUrl, source) {
  try {
    const host = new URL(baseUrl).hostname.replace(/^www\./i, '').toLowerCase();
    const sourceHost = new URL(source.url).hostname.replace(/^www\./i, '').toLowerCase();
    if (host === sourceHost) return false;
    return !/(^|\.)(twitter\.com|x\.com|t\.me|telegram\.(?:me|org)|telesco\.pe|telegra\.ph|facebook\.com|instagram\.com|youtube\.com|youtu\.be|naver\.com|kakao\.com|github\.com)$/i.test(host);
  } catch {
    return false;
  }
}

async function readPreviousStatus() {
  const remoteUrl = process.env.PREVIOUS_STATUS_URL;
  if (remoteUrl) {
    try {
      const separator = remoteUrl.includes('?') ? '&' : '?';
      const response = await fetch(`${remoteUrl}${separator}t=${Date.now()}`, {headers: {accept: 'application/json'}});
      if (response.ok) return await response.json();
    } catch (error) {
      console.warn(`이전 공개 상태를 읽지 못해 저장소 상태를 사용합니다: ${error.message}`);
    }
  }
  try {
    return JSON.parse(await fs.readFile(path.join(outputDir, 'status.json'), 'utf8'));
  } catch {
    return {groups: []};
  }
}

function previousActiveBase(site, previousGroup) {
  const configuredSourceUrl = site.source?.url ?? site.check?.url ?? site.base;
  if (previousGroup?.sourceUrl && previousGroup.sourceUrl !== configuredSourceUrl) return site.base;
  const previousBase = previousGroup?.activeBaseUrl;
  if (!previousBase || !sameDomainFamily(site.base, previousBase, site.source?.hostPattern)) return site.base;
  return previousBase;
}

function isRetryable(result) {
  return ['TIMEOUT', 'NETWORK', 'EAI_AGAIN', 'ECONNRESET', 'ETIMEDOUT', 'UND_ERR_CONNECT_TIMEOUT', 'HTTP_500', 'HTTP_502', 'HTTP_503', 'HTTP_504'].includes(result.errorCode);
}

function readableNetworkReason(code, fallback) {
  const messages = {
    ENOTFOUND: 'DNS에서 주소를 찾지 못했습니다.',
    EAI_AGAIN: 'DNS 조회가 일시적으로 지연됐습니다.',
    ECONNRESET: '연결이 일시적으로 끊어졌습니다.',
    ETIMEDOUT: '연결 시간이 초과됐습니다.',
    UND_ERR_CONNECT_TIMEOUT: '연결 시간이 초과됐습니다.',
  };
  return messages[code] ?? fallback ?? '주소 확인 중 네트워크 오류가 발생했습니다.';
}

function numberFromEnv(name, fallback) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function delay(milliseconds) {
  return milliseconds > 0 ? new Promise(resolve => setTimeout(resolve, milliseconds)) : Promise.resolve();
}
