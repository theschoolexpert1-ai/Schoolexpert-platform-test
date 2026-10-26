# REST API v1 (mobile app & integrations)

Base: `https://www.schoolexpert.in/api/v1`. JSON in/out. Authentication with bearer tokens only (cookies are ignored, so the API has no CSRF surface). Organisation users can pass `X-Org-Id` to pick the active organisation. Tokens last `API_TOKEN_DAYS` (default 90) and are stored hashed.

| Method & path | Auth | Purpose |
|---|---|---|
| `POST /auth/token` `{email, password, device}` | — | Get a token (rate-limited) |
| `DELETE /auth/token` | ✓ | Sign out this device |
| `GET /me` | ✓ | Profile, organisations, active plan & features |
| `GET /listings?group=schools&city=&board=&q=&page=&per=` | — | Search the directory |
| `GET /listings/<slug>` | optional | Public profile; `detailed` only when entitled (same rules as the website) |
| `POST /school-match` | optional | Run AI School Match (same body fields as the web form) |
| `GET /jobs?city=` | — | Open teaching jobs |
| `GET /plans?family=school|vendor|addon|parent|teacher` | — | Plans & prices |
| `GET /notifications` | ✓ | Latest notifications |
| `GET /dashboard` | ✓ org | 30-day stats, leads (if plan allows), upgrade quote; `402` if no active plan |

Payments stay on the website checkout (Razorpay) — the app opens it in the web view.
