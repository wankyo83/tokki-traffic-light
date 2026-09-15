const owner = 'wankyo83';
const repository = 'tokki-traffic-light';
const workflow = 'pages.yml';
const ref = 'main';
const statusUrl = 'https://wankyo83.github.io/tokki-traffic-light/status.json';
const staleAfterMs = 12 * 60 * 1000;

export default {
  async scheduled(_event, env, context) {
    context.waitUntil(runWatchdog(env));
  },

  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname !== '/health') return new Response('Not found', {status: 404});

    const status = await readPublishedStatus();
    return Response.json({
      ok: status.ok,
      service: 'tokki-traffic-light-scheduler',
      checkedAt: status.checkedAt,
      ageSeconds: status.ageSeconds,
      staleAfterSeconds: staleAfterMs / 1000,
      dispatchRequired: !status.ok || status.ageMs >= staleAfterMs,
    }, {
      headers: {'cache-control': 'no-store'},
    });
  },
};

async function runWatchdog(env) {
  const status = await readPublishedStatus();
  if (status.ok && status.ageMs < staleAfterMs) {
    console.log(`GitHub 검사 결과가 최신입니다. (${status.ageSeconds}초 경과)`);
    return;
  }

  if (!env.GITHUB_ACTIONS_TOKEN) {
    throw new Error('GITHUB_ACTIONS_TOKEN secret is not configured.');
  }

  const response = await fetch(`https://api.github.com/repos/${owner}/${repository}/actions/workflows/${workflow}/dispatches`, {
    method: 'POST',
    headers: {
      accept: 'application/vnd.github+json',
      authorization: `Bearer ${env.GITHUB_ACTIONS_TOKEN}`,
      'content-type': 'application/json',
      'user-agent': 'tokki-traffic-light-scheduler',
      'x-github-api-version': '2022-11-28',
    },
    body: JSON.stringify({ref}),
  });

  if (!response.ok) {
    const detail = (await response.text()).slice(0, 500);
    throw new Error(`GitHub workflow dispatch failed: HTTP ${response.status} ${detail}`);
  }
  console.log(`오래된 GitHub 검사 결과를 감지해 ${workflow} 실행을 요청했습니다.`);
}

async function readPublishedStatus() {
  try {
    const response = await fetch(`${statusUrl}?watchdog=${Date.now()}`, {
      headers: {accept: 'application/json', 'cache-control': 'no-cache'},
      cf: {cacheTtl: 0, cacheEverything: false},
    });
    if (!response.ok) return {ok: false, checkedAt: null, ageMs: Infinity, ageSeconds: null};
    const data = await response.json();
    const checkedAt = String(data.checkedAt || '');
    const checkedAtMs = Date.parse(checkedAt);
    if (!Number.isFinite(checkedAtMs)) return {ok: false, checkedAt, ageMs: Infinity, ageSeconds: null};
    const ageMs = Math.max(0, Date.now() - checkedAtMs);
    return {ok: true, checkedAt, ageMs, ageSeconds: Math.floor(ageMs / 1000)};
  } catch {
    return {ok: false, checkedAt: null, ageMs: Infinity, ageSeconds: null};
  }
}
