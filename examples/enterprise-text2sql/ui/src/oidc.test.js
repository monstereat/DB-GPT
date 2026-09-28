import assert from 'node:assert/strict';
import test from 'node:test';
import { webcrypto } from 'node:crypto';
import { exportJWK, generateKeyPair, SignJWT } from 'jose';
import { completeOidcCallback, createOidcAuthorizationUrl } from './oidc.js';

const issuer = 'https://id.example.test/realms/analytics';
const clientId = 'analytics-spa';
const redirectUri = 'https://analytics.example.test/';
const discovery = {
  issuer,
  authorization_endpoint: `${issuer}/protocol/openid-connect/auth`,
  token_endpoint: `${issuer}/protocol/openid-connect/token`,
  jwks_uri: `${issuer}/protocol/openid-connect/certs`,
};

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

function response(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('creates an OIDC authorization request with state, nonce, and S256 PKCE', async () => {
  const storage = memoryStorage();
  const url = new URL(await createOidcAuthorizationUrl({
    issuer,
    clientId,
    redirectUri,
    storage,
    cryptoApi: webcrypto,
    fetcher: async () => response(discovery),
  }));
  const transaction = JSON.parse(storage.getItem('enterprise-text2sql.oidc.transaction'));

  assert.equal(url.origin, issuer.split('/realms/')[0]);
  assert.equal(url.searchParams.get('response_type'), 'code');
  assert.equal(url.searchParams.get('client_id'), clientId);
  assert.equal(url.searchParams.get('redirect_uri'), redirectUri);
  assert.equal(url.searchParams.get('scope'), 'openid profile email');
  assert.equal(url.searchParams.get('state'), transaction.state);
  assert.equal(url.searchParams.get('nonce'), transaction.nonce);
  assert.equal(url.searchParams.get('code_challenge_method'), 'S256');
  assert.notEqual(url.searchParams.get('code_challenge'), transaction.verifier);
  assert.equal(transaction.issuer, issuer);
});

test('exchanges the code and verifies ID Token signature and claims before returning access token', async () => {
  const storage = memoryStorage();
  const keyPair = await generateKeyPair('RS256');
  const jwk = await exportJWK(keyPair.publicKey);
  jwk.kid = 'test-key';
  jwk.alg = 'RS256';
  jwk.use = 'sig';
  const authUrl = await createOidcAuthorizationUrl({
    issuer,
    clientId,
    redirectUri,
    storage,
    cryptoApi: webcrypto,
    fetcher: async () => response(discovery),
  });
  const transaction = JSON.parse(storage.getItem('enterprise-text2sql.oidc.transaction'));
  const idToken = await new SignJWT({ nonce: transaction.nonce })
    .setProtectedHeader({ alg: 'RS256', kid: jwk.kid })
    .setIssuer(issuer)
    .setAudience(clientId)
    .setSubject('user-123')
    .setIssuedAt()
    .setExpirationTime('5m')
    .sign(keyPair.privateKey);
  let tokenRequest;
  const fetcher = async (input, init = {}) => {
    const url = String(input);
    if (url.endsWith('/.well-known/openid-configuration')) return response(discovery);
    if (url === discovery.token_endpoint) {
      tokenRequest = init;
      return response({ access_token: 'short-lived-access-token', token_type: 'Bearer', expires_in: 300, id_token: idToken });
    }
    if (url === discovery.jwks_uri) return response({ keys: [jwk] });
    throw new Error(`Unexpected OIDC request: ${url}`);
  };

  const result = await completeOidcCallback({
    search: `?code=auth-code&state=${encodeURIComponent(transaction.state)}`,
    fetcher,
    storage,
    cryptoApi: webcrypto,
  });
  const body = new URLSearchParams(tokenRequest.body);

  assert.equal(new URL(authUrl).searchParams.get('state'), transaction.state);
  assert.equal(tokenRequest.method, 'POST');
  assert.equal(body.get('grant_type'), 'authorization_code');
  assert.equal(body.get('client_id'), clientId);
  assert.equal(body.get('code'), 'auth-code');
  assert.equal(body.get('redirect_uri'), redirectUri);
  assert.equal(body.get('code_verifier'), transaction.verifier);
  assert.deepEqual(result, {
    accessToken: 'short-lived-access-token',
    expiresIn: 300,
    issuer,
    clientId,
  });
  assert.equal(storage.getItem('enterprise-text2sql.oidc.transaction'), null);
});

test('rejects mismatched OIDC state before sending the token request', async () => {
  const storage = memoryStorage();
  await createOidcAuthorizationUrl({
    issuer,
    clientId,
    redirectUri,
    storage,
    cryptoApi: webcrypto,
    fetcher: async () => response(discovery),
  });
  let tokenRequested = false;
  await assert.rejects(
    completeOidcCallback({
      search: '?code=auth-code&state=attacker-state',
      fetcher: async (url) => {
        if (String(url) === discovery.token_endpoint) tokenRequested = true;
        return response(discovery);
      },
      storage,
      cryptoApi: webcrypto,
    }),
    /state 校验失败/,
  );
  assert.equal(tokenRequested, false);
});

test('rejects an expired login transaction without contacting the token endpoint', async () => {
  const storage = memoryStorage();
  await createOidcAuthorizationUrl({
    issuer,
    clientId,
    redirectUri,
    storage,
    cryptoApi: webcrypto,
    fetcher: async () => response(discovery),
  });
  const transaction = JSON.parse(storage.getItem('enterprise-text2sql.oidc.transaction'));
  transaction.createdAt = Date.now() - 11 * 60 * 1000;
  storage.setItem('enterprise-text2sql.oidc.transaction', JSON.stringify(transaction));
  let tokenRequested = false;
  await assert.rejects(
    completeOidcCallback({
      search: `?code=auth-code&state=${transaction.state}`,
      fetcher: async (url) => {
        if (String(url) === discovery.token_endpoint) tokenRequested = true;
        return response(discovery);
      },
      storage,
      cryptoApi: webcrypto,
    }),
    /登录事务已过期/,
  );
  assert.equal(tokenRequested, false);
});

test('rejects authorization response issuer mismatch before code exchange', async () => {
  const storage = memoryStorage();
  await createOidcAuthorizationUrl({
    issuer,
    clientId,
    redirectUri,
    storage,
    cryptoApi: webcrypto,
    fetcher: async () => response(discovery),
  });
  const transaction = JSON.parse(storage.getItem('enterprise-text2sql.oidc.transaction'));
  let tokenRequested = false;
  await assert.rejects(
    completeOidcCallback({
      search: `?code=auth-code&state=${transaction.state}&iss=https%3A%2F%2Fattacker.example.test`,
      fetcher: async (url) => {
        if (String(url) === discovery.token_endpoint) tokenRequested = true;
        return response(discovery);
      },
      storage,
      cryptoApi: webcrypto,
    }),
    /response issuer 与配置不一致/,
  );
  assert.equal(tokenRequested, false);
});

test('rejects an ID Token with a mismatched nonce', async () => {
  const storage = memoryStorage();
  const keyPair = await generateKeyPair('RS256');
  const jwk = await exportJWK(keyPair.publicKey);
  jwk.kid = 'nonce-test-key';
  jwk.alg = 'RS256';
  jwk.use = 'sig';
  await createOidcAuthorizationUrl({
    issuer,
    clientId,
    redirectUri,
    storage,
    cryptoApi: webcrypto,
    fetcher: async () => response(discovery),
  });
  const transaction = JSON.parse(storage.getItem('enterprise-text2sql.oidc.transaction'));
  const idToken = await new SignJWT({ nonce: 'wrong-nonce' })
    .setProtectedHeader({ alg: 'RS256', kid: jwk.kid })
    .setIssuer(issuer)
    .setAudience(clientId)
    .setSubject('user-123')
    .setIssuedAt()
    .setExpirationTime('5m')
    .sign(keyPair.privateKey);
  const fetcher = async (input) => {
    const url = String(input);
    if (url.endsWith('/.well-known/openid-configuration')) return response(discovery);
    if (url === discovery.token_endpoint) {
      return response({ access_token: 'access-token', token_type: 'Bearer', id_token: idToken });
    }
    if (url === discovery.jwks_uri) return response({ keys: [jwk] });
    throw new Error(`Unexpected OIDC request: ${url}`);
  };

  await assert.rejects(
    completeOidcCallback({
      search: `?code=auth-code&state=${transaction.state}`,
      fetcher,
      storage,
      cryptoApi: webcrypto,
    }),
    /ID Token claim 校验失败/,
  );
});

test('rejects an OIDC discovery issuer mismatch and insecure remote issuer', async () => {
  await assert.rejects(
    createOidcAuthorizationUrl({
      issuer,
      clientId,
      redirectUri,
      storage: memoryStorage(),
      cryptoApi: webcrypto,
      fetcher: async () => response({ ...discovery, issuer: 'https://attacker.example.test' }),
    }),
    /issuer 与配置不一致/,
  );
  await assert.rejects(
    createOidcAuthorizationUrl({
      issuer: 'http://id.example.test/realms/analytics',
      clientId,
      redirectUri,
      storage: memoryStorage(),
      cryptoApi: webcrypto,
      fetcher: async () => response(discovery),
    }),
    /HTTPS 地址/,
  );
});
