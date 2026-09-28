# Plan: App-Agent daily token quota

1. Build quota context only from the verified OIDC request identity.
2. Pass the wrapper explicitly through v1/v2 App-Agent controller calls; do not put identity or quota data in request `ext_info`.
3. Reject flow-backed App-Agent requests when quota is active.
4. Keep a private Core wrapper context as unintegrated groundwork; fail closed on `/flow/debug` and all dynamic HTTP triggers while quota is enabled because custom nodes may invoke an LLM.
5. Add focused tests, run App/Core regressions, then update the roadmap and verification record.
