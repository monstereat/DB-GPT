# Enterprise Text-to-SQL UI

This directory is a standalone Vue 3 + Vite demo client for the sibling
`../api.py` service.

## Directory rules

- Keep the Vue page in `src/App.vue` and its entry point in `src/main.js`.
- Keep metric API requests in `src/api.js` and time-series calculations in
  `src/analytics.js`, with Node tests beside those helpers.
- Keep ReAct session and transcript state in `src/agent-conversation.js`, with
  Node tests beside the helper.
- Keep the dashboard's page-specific styles in `src/style.css`.
- Keep local build configuration at this directory's root.
- Do not store access tokens in browser storage or commit environment files.
- Add only dependencies used by this demo; do not change the repository-level
  `web/` application.

## Run

Start the demo API as described in `../README.md`, then run:

```bash
npm install
npm run dev
```

Open the Vite URL printed in the terminal. The browser sends requests through
the local Vite proxy to `http://127.0.0.1:8000`. For OIDC login, enter the exact
provider issuer and public client ID. Register the page URL as an allowed
redirect URI and web origin; configure a public client with Authorization Code
flow and PKCE S256. The UI discovers the provider endpoints, checks the ID Token
signature and issuer/audience/expiry/nonce, then sends only the Bearer access
token to the API. No client secret is used in the browser. The access token
stays in memory and is cleared when the page is refreshed; the state, nonce,
and PKCE verifier are kept in the current tab's session storage for at most ten
minutes while completing the redirect. If needed, a short-lived access token can
still be pasted manually. The provider must allow browser CORS for its discovery,
JWKS, and token endpoints. The table panel can export the registered metrics
as an XLSX report; the API applies the same tenant and region scope as the
dashboard queries. When viewing paid refunds, choose between refund-date
version 1.0.0 and original-order-date cohort version 2.0.0; the selected
version is used for the query, SQL preview, metric card, and matching report
metric. “下载 PDF” requests a server-generated report using the same authenticated
tenant/region scope as the XLSX export; “打印报告” opens a printable page for
browser printing. The
natural-language panel calls DB-GPT's `/api/v1/chat/react-agent`
and streams the final answer and SQL action through a separate Vite proxy.
Follow-up questions reuse the same conversation ID and remain visible in the
current-page transcript; changing the access token or datasource clears the
transcript and starts a new conversation. No transcript is stored locally. Set
`DBGPT_AGENT_ORIGIN` when the DB-GPT app is not listening on `127.0.0.1:5670`,
then enter a DB-GPT datasource name visible to the authenticated user.

Use `npm run build` to create the static production bundle in `dist/`. Production
hosting, redirect URI registration, API reverse proxy, and the identity provider's
issuer/client settings must be configured for the deployment origin.
The ReAct Agent uses DB-GPT's configured datasource directly; configure its
database account as read-only and enforce tenant/region scope with database
policies or a tenant-specific datasource. The demo metrics API's SQLite tenant
executor does not wrap the separate ReAct datasource.
