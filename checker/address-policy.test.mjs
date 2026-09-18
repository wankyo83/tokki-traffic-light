import assert from 'node:assert/strict';
import {chooseTrustedAddress, extractGatewayTarget, sameDomainFamily} from './address-policy.mjs';

const blacktoon = {
  base: 'https://blacktoon07.com',
  source: {hostPattern: '^(?:www\\.)?blacktoon\\d+\\.com$'},
};

assert.equal(sameDomainFamily(blacktoon.base, 'https://blacktoon422.com', blacktoon.source.hostPattern), true);
assert.equal(sameDomainFamily(blacktoon.base, 'https://blacktoon422.net', blacktoon.source.hostPattern), false);
assert.equal(sameDomainFamily(blacktoon.base, 'https://newblacktoon422.com', blacktoon.source.hostPattern), false);

const tvwiki = {
  base: 'https://tvwiki50.net',
  source: {hostPattern: '^(?:www\\.)?(?:tvwiki\\d+\\.net|tvwiki\\.store)$'},
};

assert.equal(sameDomainFamily(tvwiki.base, 'https://tvwiki50.net', tvwiki.source.hostPattern), true);
assert.equal(sameDomainFamily(tvwiki.base, 'https://tvwiki50.com', tvwiki.source.hostPattern), false);
assert.equal(sameDomainFamily(tvwiki.base, 'https://tvwiki.store', tvwiki.source.hostPattern), true);
assert.equal(sameDomainFamily(tvwiki.base, 'https://fake-tvwiki.store', tvwiki.source.hostPattern), false);

const tvwikiGatewayRule = {
  cookieName: 'wikimove_tgt',
  hostPattern: '^(?:www\\.)?tvwiki\\d+\\.net$',
};
assert.equal(
  extractGatewayTarget({setCookie: 'wikimove_tgt=tvwiki50.net; path=/; HttpOnly'}, 'https://tvwiki.store', tvwikiGatewayRule),
  'https://tvwiki50.net',
);
assert.equal(
  extractGatewayTarget({setCookie: 'wikimove_tgt=https%3A%2F%2Ftvwiki51.net; path=/'}, 'https://tvwiki.store', tvwikiGatewayRule),
  'https://tvwiki51.net',
);
assert.equal(
  extractGatewayTarget({setCookie: 'wikimove_tgt=evil.example; path=/'}, 'https://tvwiki.store', tvwikiGatewayRule),
  null,
);

assert.deepEqual(
  chooseTrustedAddress(blacktoon, 'https://blacktoon07.com', {ok: true, baseUrl: 'https://blacktoon422.com'}),
  {
    activeBaseUrl: 'https://blacktoon422.com',
    candidateBaseUrl: null,
    candidateConfirmations: 0,
    verifying: false,
    manualReview: false,
  },
);

for (const changedFamily of ['https://blacktoon422.net', 'https://newblacktoon422.com']) {
  const selected = chooseTrustedAddress(blacktoon, 'https://blacktoon07.com', {ok: true, baseUrl: changedFamily});
  assert.equal(selected.activeBaseUrl, 'https://blacktoon07.com');
  assert.equal(selected.candidateBaseUrl, changedFamily);
  assert.equal(selected.verifying, true);
  assert.equal(selected.manualReview, true);
}

console.log('address policy tests: ok');
