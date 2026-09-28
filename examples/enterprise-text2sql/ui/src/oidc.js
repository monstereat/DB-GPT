import { createRemoteJWKSet, customFetch, jwtVerify } from 'jose';

const TRANSACTION_KEY = 'enterprise-text2sql.oidc.transaction';
const TRANSACTION_MAX_AGE_MS = 10 * 60 * 1000;
const ALLOWED_ID_TOKEN_ALGORITHMS = [
  'RS256',
  'RS384',
  'RS512',
  'PS256',
  'PS384',
  'PS512',
  'ES256',
  'ES384',
  'ES512',
  'EdDSA',
];

function base64Url(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
}

function randomValue(cryptoApi) {
  return base64Url(cryptoApi.getRandomValues(new Uint8Array(32)));
}

function normalizeIssuer(value) {
  const issuer = new URL(value.trim());
  if (
    !['https:', 'http:'].includes(issuer.protocol)
    || issuer.username
    || issuer.password
    || issuer.search
    || issuer.hash
    || (issuer.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(issuer.hostname))
  ) {
    throw new Error('OIDC issuer 必须是 HTTPS 地址；仅 localhost 可使用 HTTP。');
  }
  return issuer.href;
}

function requireHttpsEndpoint(value, issuer) {
  const endpoint = new URL(value);
  const issuerUrl = new URL(issuer);
  const loopbackHosts = ['localhost', '127.0.0.1', '[::1]'];
  const localIssuer = issuerUrl.protocol === 'http:' && loopbackHosts.includes(issuerUrl.hostname);
  if (
    !['https:', 'http:'].includes(endpoint.protocol)
    || endpoint.username
    || endpoint.password
    || (endpoint.protocol === 'http:' && (!localIssuer || !loopbackHosts.includes(endpoint.hostname)))
  ) {
    throw new Error('OIDC discovery 返回了不安全的 endpoint。');
  }
  return endpoint.href;
}

async function discover(issuer, fetcher) {
  const discoveryUrl = `${issuer.replace(/\/$/, '')}/.well-known/openid-configuration`;
  const response = await fetcher(discoveryUrl, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error('无法读取 OIDC provider discovery 配置。');
  const metadata = await response.json();
  if (metadata.issuer !== issuer) throw new Error('OIDC discovery issuer 与配置不一致。');
  if (!metadata.authorization_endpoint || !metadata.token_endpoint || !metadata.jwks_uri) {
    throw new Error('OIDC discovery 缺少授权、令牌或 JWKS endpoint。');
  }
  return {
    authorizationEndpoint: requireHttpsEndpoint(metadata.authorization_endpoint, issuer),
    tokenEndpoint: requireHttpsEndpoint(metadata.token_endpoint, issuer),
    jwksUri: requireHttpsEndpoint(metadata.jwks_uri, issuer),
  };
}

export async function createOidcAuthorizationUrl({
  issuer: issuerValue,
  clientId,
  redirectUri,
  fetcher = fetch,
  storage = sessionStorage,
  cryptoApi = crypto,
}) {
  const issuer = normalizeIssuer(issuerValue);
  const normalizedClientId = clientId.trim();
  if (!normalizedClientId) throw new Error('请填写 OIDC public client ID。');
  const redirect = new URL(redirectUri);
  if (
    (redirect.protocol !== 'https:'
      && !(redirect.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(redirect.hostname)))
    || redirect.search
    || redirect.hash
  ) {
    throw new Error('OIDC redirect URI 必须使用 HTTPS；本地开发可使用 localhost。');
  }

  const metadata = await discover(issuer, fetcher);
  const verifier = randomValue(cryptoApi);
  const challenge = base64Url(
    new Uint8Array(await cryptoApi.subtle.digest('SHA-256', new TextEncoder().encode(verifier))),
  );
  const state = randomValue(cryptoApi);
  const nonce = randomValue(cryptoApi);
  storage.setItem(
    TRANSACTION_KEY,
    JSON.stringify({
      issuer,
      clientId: normalizedClientId,
      redirectUri: redirect.href,
      verifier,
      state,
      nonce,
      createdAt: Date.now(),
    }),
  );

  const authorizationUrl = new URL(metadata.authorizationEndpoint);
  authorizationUrl.searchParams.set('response_type', 'code');
  authorizationUrl.searchParams.set('client_id', normalizedClientId);
  authorizationUrl.searchParams.set('redirect_uri', redirect.href);
  authorizationUrl.searchParams.set('scope', 'openid profile email');
  authorizationUrl.searchParams.set('state', state);
  authorizationUrl.searchParams.set('nonce', nonce);
  authorizationUrl.searchParams.set('code_challenge', challenge);
  authorizationUrl.searchParams.set('code_challenge_method', 'S256');
  return authorizationUrl.href;
}

export async function completeOidcCallback({
  search = location.search,
  fetcher = fetch,
  storage = sessionStorage,
  cryptoApi = crypto,
}) {
  const params = new URLSearchParams(search);
  const code = params.get('code');
  const state = params.get('state');
  const transactionText = storage.getItem(TRANSACTION_KEY);
  storage.removeItem(TRANSACTION_KEY);
  if (!transactionText) throw new Error('OIDC 登录状态已失效，请重新登录。');

  let transaction;
  try {
    transaction = JSON.parse(transactionText);
  } catch {
    throw new Error('OIDC 登录状态无效，请重新登录。');
  }
  if (
    !Number.isFinite(transaction.createdAt)
    || Date.now() - transaction.createdAt > TRANSACTION_MAX_AGE_MS
    || transaction.createdAt > Date.now() + 60_000
  ) {
    throw new Error('OIDC 登录事务已过期，请重新登录。');
  }
  if (!state || state !== transaction.state) {
    throw new Error('OIDC state 校验失败，请重新登录。');
  }
  const responseIssuer = params.get('iss');
  if (responseIssuer && responseIssuer !== transaction.issuer) {
    throw new Error('OIDC authorization response issuer 与配置不一致。');
  }
  if (params.has('error')) throw new Error(params.get('error_description') || 'OIDC 登录失败。');
  if (!code) throw new Error('OIDC authorization response 缺少授权码。');

  const metadata = await discover(transaction.issuer, fetcher);
  const tokenResponse = await fetcher(metadata.tokenEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: transaction.clientId,
      code,
      redirect_uri: transaction.redirectUri,
      code_verifier: transaction.verifier,
    }),
  });
  if (!tokenResponse.ok) throw new Error('OIDC authorization code 兑换失败。');
  const tokens = await tokenResponse.json();
  if (!tokens.access_token || tokens.token_type?.toLowerCase() !== 'bearer' || !tokens.id_token) {
    throw new Error('OIDC token response 缺少 Bearer access token 或 ID Token。');
  }

  const jwks = createRemoteJWKSet(new URL(metadata.jwksUri), { [customFetch]: fetcher });
  const { payload } = await jwtVerify(tokens.id_token, jwks, {
    issuer: transaction.issuer,
    audience: transaction.clientId,
    algorithms: ALLOWED_ID_TOKEN_ALGORITHMS,
  });
  if (
    typeof payload.sub !== 'string'
    || !payload.sub
    || typeof payload.exp !== 'number'
    || typeof payload.iat !== 'number'
    || payload.nonce !== transaction.nonce
    || (payload.azp && payload.azp !== transaction.clientId)
    || (Array.isArray(payload.aud) && payload.aud.length > 1 && payload.azp !== transaction.clientId)
  ) {
    throw new Error('OIDC ID Token claim 校验失败。');
  }
  return {
    accessToken: tokens.access_token,
    expiresIn: Number.isFinite(tokens.expires_in) ? tokens.expires_in : null,
    issuer: transaction.issuer,
    clientId: transaction.clientId,
  };
}
