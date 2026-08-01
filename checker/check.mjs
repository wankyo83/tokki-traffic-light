import fs from 'node:fs/promises';

const sites = JSON.parse(await fs.readFile(new URL('./sites.json', import.meta.url), 'utf8'));
const services = [];

for (const site of sites) {
  for (const service of site.services) {
    const candidates = candidateUrls(site.base, site.numbered);
    let selected = null;
    let lastFailure = '사이트에 연결할 수 없습니다.';
    let defaultProbe = null;

    for (let index = 0; index < candidates.length; index++) {
      const candidate = candidates[index];
      const probe = await checkUrl(candidate + service.path, site, service);
      if (index === 0) defaultProbe = probe;
      if (probe.ok) {
        selected = {baseUrl: candidate, probe};
        break;
      }
      lastFailure = probe.reason;
    }

    // GitHub 서버에서만 차단된 기본 주소는 DNS가 살아 있으면 유지한다.
    // 번호 후보 주소는 반드시 사이트 고유 문구와 콘텐츠 구조가 확인돼야 채택한다.
    if (!selected && defaultProbe && isRunnerLimited(defaultProbe) && await dnsExists(new URL(site.base).hostname)) {
      selected = {baseUrl: site.base, probe: {...defaultProbe, ok:true, limited:true}};
    }

    if (!selected) {
      services.push({group:site.key,name:service.name,url:site.base + service.path,baseUrl:site.base,ok:false,reason:`기본 주소부터 +10까지 확인 실패 · ${lastFailure}`});
      continue;
    }
    const url = selected.baseUrl + service.path;
    const result = selected.probe;
    services.push({group:site.key,name:service.name,url,baseUrl:selected.baseUrl,ok:result.ok,reason:result.ok ? '' : result.reason,responseMs:result.responseMs});
  }
}

await fs.writeFile(new URL('../site/status.json', import.meta.url), JSON.stringify({checkedAt:new Date().toISOString(),services}, null, 2) + '\n');
console.log(JSON.stringify(services.map(({name,url,ok,reason}) => ({name,url,ok,reason})), null, 2));

function candidateUrls(base, numbered) {
  if (!numbered) return [base];
  const url = new URL(base);
  const match = url.hostname.match(/^(.*?)(\d+)(\.[a-z.]+)$/i);
  if (!match) return [base];
  const [,prefix,digits,suffix] = match;
  const start = Number(digits);
  return Array.from({length:11}, (_,i) => {
    const n = String(start + i).padStart(digits.length, '0');
    const next = new URL(base); next.hostname = `${prefix}${n}${suffix}`;
    return next.origin;
  });
}

async function checkUrl(url, site, service) {
  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(url, {redirect:'follow',signal:controller.signal,headers:{'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36','accept':'text/html,application/xhtml+xml'}});
    const bytes = await response.arrayBuffer();
    const charset = response.headers.get('content-type')?.match(/charset\s*=\s*["']?([^;"'\s]+)/i)?.[1] || 'utf-8';
    let text;
    try { text = new TextDecoder(charset).decode(bytes).slice(0, 300000); }
    catch { text = new TextDecoder('utf-8').decode(bytes).slice(0, 300000); }
    const responseMs = Date.now() - started;
    if (!response.ok) return {ok:false,responseMs,reason:`HTTP ${response.status} ${response.statusText}`.trim()};
    if (/cf-chl-|challenge-platform|just a moment|cloudflare ray id/i.test(text)) return {ok:false,responseMs,reason:'Cloudflare 브라우저 인증이 필요합니다.'};
    if (!/<html|<!doctype|<body/i.test(text)) return {ok:false,responseMs,reason:'정상 웹페이지 형식이 아닙니다.'};
    const normalized = text.toLowerCase();
    const siteMatch = site.markers.some(marker => normalized.includes(marker.toLowerCase()));
    const sectionMatch = service.markers.some(marker => normalized.includes(marker.toLowerCase()));
    if (!siteMatch || !sectionMatch) return {ok:false,responseMs,identityMismatch:true,reason:'사이트 또는 콘텐츠 종류가 일치하지 않습니다.'};
    return {ok:true,responseMs};
  } catch (error) {
    const responseMs = Date.now() - started;
    if (error.name === 'AbortError') return {ok:false,responseMs,reason:'응답 시간 초과'};
    return {ok:false,responseMs,reason:error.cause?.code || error.message};
  } finally { clearTimeout(timer); }
}

async function dnsExists(hostname) {
  try {
    const response = await fetch(`https://dns.google/resolve?name=${encodeURIComponent(hostname)}&type=A`, {headers:{accept:'application/dns-json'}});
    if (!response.ok) return false;
    const data = await response.json();
    return data.Status === 0 && Array.isArray(data.Answer) && data.Answer.some(answer => answer.type === 1);
  } catch { return false; }
}

function isRunnerLimited(probe) {
  return !probe.identityMismatch && (
    /^HTTP (403|429)\b/.test(probe.reason) ||
    /^(ENOTFOUND|EAI_AGAIN|ECONNRESET|ETIMEDOUT|UND_ERR_CONNECT_TIMEOUT|검사 시간 초과)$/.test(probe.reason)
  );
}
