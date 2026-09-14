export function normalizeOrigin(value, sourceUrl) {
  try {
    const candidate = new URL(value, sourceUrl);
    if (!/^https?:$/i.test(candidate.protocol)) return null;
    candidate.protocol = 'https:';
    candidate.pathname = '/';
    candidate.search = '';
    candidate.hash = '';
    return candidate.origin;
  } catch {
    return null;
  }
}

export function matchesAllowedHost(value, hostPattern) {
  try {
    return Boolean(hostPattern && new RegExp(hostPattern, 'i').test(new URL(value).hostname));
  } catch {
    return false;
  }
}

export function sameDomainFamily(configuredBase, candidateBase, hostPattern) {
  try {
    const configuredHost = new URL(configuredBase).hostname.replace(/^www\./i, '');
    const candidateHost = new URL(candidateBase).hostname.replace(/^www\./i, '');
    if (hostPattern && new RegExp(hostPattern, 'i').test(candidateHost)) return true;
    const configuredNumbered = configuredHost.match(/^(.*?)(\d+)(\.[a-z.]+)$/i);
    if (!configuredNumbered) return configuredHost === candidateHost;
    const candidateNumbered = candidateHost.match(/^(.*?)(\d+)(\.[a-z.]+)$/i);
    return Boolean(candidateNumbered
      && configuredNumbered[1] === candidateNumbered[1]
      && configuredNumbered[3] === candidateNumbered[3]);
  } catch {
    return false;
  }
}

export function chooseTrustedAddress(site, activeBaseUrl, result, previousGroup) {
  if (!result.ok) {
    return {
      activeBaseUrl,
      candidateBaseUrl: previousGroup?.candidateBaseUrl ?? null,
      candidateConfirmations: 0,
      verifying: false,
      manualReview: Boolean(previousGroup?.candidateRequiresManualApproval),
    };
  }

  const discovered = result.baseUrl;
  if (discovered === activeBaseUrl) {
    return {
      activeBaseUrl,
      candidateBaseUrl: null,
      candidateConfirmations: 0,
      verifying: false,
      manualReview: false,
    };
  }

  if (sameDomainFamily(site.base, discovered, site.source?.hostPattern)) {
    return {
      activeBaseUrl: discovered,
      candidateBaseUrl: null,
      candidateConfirmations: 0,
      verifying: false,
      manualReview: false,
    };
  }

  return {
    activeBaseUrl,
    candidateBaseUrl: discovered,
    candidateConfirmations: 0,
    verifying: true,
    manualReview: true,
  };
}
