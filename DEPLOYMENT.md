# Deployment note: the Agent Runtime's dependencies

This is the **first** `requirements.txt` this repository has had. `server.py`/`routing/*` remain intentionally
stdlib-only and need nothing from it — if `AGENT_ENABLED` is never set to `1`, these packages are never
imported and the server runs exactly as it did before this change.

If you want the real Agent Runtime live in production (`AGENT_ENABLED=1` + a real `OPENAI_API_KEY` in
Render's environment settings, alongside the existing `GOOGLE_PLACES_API_KEY` etc. per `PROVIDER_ACCESS.md`),
Render's build command needs to install `requirements.txt`:

```
pip install -r requirements.txt
```

No Dockerfile, no container runtime, no new infrastructure — this is one extra `pip install` line, consistent
with the rest of this app's zero-framework deployment. Not adding CI/CD changes beyond this note: no new
GitHub Actions workflow was added, since the 4 existing ones (`production-acceptance.yml`,
`indexed-urban-refresh.yml`, `tourism-data-audit.yml`, `urban-intelligence.yml`) don't exercise this new,
flag-gated endpoint and nothing in the request asked for a new pipeline to be built for it.

## Street photos (Mapillary)

Optional. To show street-level photos along a walk, set one environment variable on the API host (Render → the
service → Environment → Add Environment Variable), then redeploy:

    MAPILLARY_TOKEN = <the "Access Token" shown for the app in the Mapillary developer dashboard, starting with MLY|>

- Use the **Access Token**, not the **Client secret**. The client secret is only for OAuth sign-in, is not used by this
  project, and should never be pasted into code, a commit, or the environment.
- The token stays on the API host: the browser calls `POST /api/street-photos` and never sees it.
- Check: `POST /api/street-photos` with a route's coordinates answers `"configured": true` once the variable is set.
  `"failed_points"` above 0 means Mapillary did not answer (bad token, rate limit or outage).
- Without the variable the endpoint answers `"configured": false` and the page shows no street photos.

