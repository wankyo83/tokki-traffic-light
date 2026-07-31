import fs from 'node:fs/promises';

const sites = JSON.parse(await fs.readFile(new URL('./sites.json', import.meta.url), 'utf8'));
const oldStatus = await readOldStatus();
const services = [];

for (const site of sites) {
  const previous = oldStatus.services?.find(s => s.group === site.key && s.ok)?.baseUrl;
  const candidates = candidateUrls(previous || site.base, site.numbered);
  let selected = null;
  let lastFailure = '사이트에 연결할 수 없습니다.';

  for (const candidate of candidates) {
    const probe = await checkUrl(candidate + site.services[0].path);
    if (probe.ok) {
      selected = {baseUrl: candidate, probe};
      break;
    }
    lastFailure = probe.reason;
  }

  for (const service of site.services) {
    if (!selected) {
      services.push({group:site.key,name:service.name,url:site.base + service.path,baseUrl:site.base,ok:false,reason:`기본 주소부터 +10까지 확인 실패 · ${lastFailure}`});
      continue;
    }
    const url = selected.baseUrl + service.path;
    const result = service === site.services[0] ? selected.probe : await checkUrl(url);
    services.push({group:site.key,name:service.name,url,baseUrl:selected.baseUrl,ok:result.ok,reason:result.ok ? '' : result.reason,responseMs:result.responseMs});
  }
}

await fs.writeFile(new URL('../site/status.json', import.meta.url), JSON.stringify({checkedAt:new Date().toISOString(),services}, null, 2) + '\n');
console.log(JSON.stringify(services.map(({name,url,ok,reason}) => ({name,url,ok,reason})), null, 2));

async function readOldStatus() {
  try { return JSON.parse(await fs.readFile(new URL('../site/status.json', import.meta.url), 'utf8')); }
  catch { return {services:[]}; }
}

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

async function checkUrl(url) {
  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(url, {redirect:'follow',signal:controller.signal,headers:{'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36','accept':'text/html,application/xhtml+xml'}});
    const text = (await response.text()).slice(0, 300000);
    const responseMs = Date.now() - started;
    if (!response.ok) return {ok:false,responseMs,reason:`HTTP ${response.status} ${response.statusText}`.trim()};
    if (/cf-chl-|challenge-platform|just a moment|cloudflare ray id/i.test(text)) return {ok:false,responseMs,reason:'Cloudflare 브라우저 인증이 필요합니다.'};
    if (!/<html|<!doctype|<body/i.test(text)) return {ok:false,responseMs,reason:'정상 웹페이지 형식이 아닙니다.'};
    return {ok:true,responseMs};
  } catch (error) {
    const responseMs = Date.now() - started;
    if (error.name === 'AbortError') return {ok:false,responseMs,reason:'응답 시간 초과'};
    return {ok:false,responseMs,reason:error.cause?.code || error.message};
  } finally { clearTimeout(timer); }
}
