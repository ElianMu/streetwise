# AI parsing validation — 2026-10-24

## Actual production evidence

Two real HTTPS POSTs to https://streetwise-api.onrender.com/api/interpret with `I want a scenic walk with architecture, parks, and good coffee.` returned 200. Each returned Architecture=85, Nature=85, Food & Retail=80, Scenic & Visual=90; journey=null. No mock was used for these production requests. Status reports llm=true and gpt-4o-mini. This is live backend success consistent with its OpenAI code path, not independent access to OpenAI account usage or billing logs.

The returned preferences were posted to the real /api/routes: HTTP 200, four candidates, ranks 1–4, distances 932.1/931.4/985.5/1007.9 m, durations 11.7/11.6/12.3/12.6 min, personalized utility 73.6/73.4/68.3/68.2. CORS allowed https://elianmu.github.io. Coffee POI preservation FAILS on this production version. Scores do not establish coffee availability.

GitHub main and latest reported GitHub Pages deployment SHA: 02d68f566ee9df54a730fa12639f54707c0f7fba, Pages status built. Render deployment SHA, environment values and historical exception stack are inaccessible. Therefore the historical ValueError's exact production line/cause remains BLOCKED; the error is not currently reproduced.

A synthetic credential containing an internal newline reproduces ValueError in Python http.client.putheader (client.py:1364), before any socket is opened. This proves a possible failure path, not the historical production cause. The upstream main already contains edge trimming and invalid-key-format rejection; those changes were preserved during merge.

## Additional changes and local evidence

- Prompt explicitly requires food/drink requests in journey.food, separately from experience weights. No new dimensions or fabricated places.
- Validate request history type before slicing it.
- Unexpected exceptions log frame file/line/function only, without exception text, locals or headers.
- Frontend timeout 32 seconds exceeds backend's 26-second provider timeout.
- Regression tests cover whitespace normalization, invalid internal characters before HTTP, missing key, provider 401/429/model errors, timeout/network, invalid JSON/schema, structured coffee preservation, and real bundled-network scoring using mocked interpretation.
- Full Python suite: 168 PASS, including geographic tests. Existing ResourceWarnings remain.
- Eight standalone JS scripts PASS. Expanded DOM test PASS: mocked AI success preserves coffee, mocked failure retains visible diagnosis and labelled local mode. Original assertions retained.
- Chromium fixture routing pipeline PASS. These mock/fixture tests are not live AI acceptance or production browser/map verification.

## Release blockers

Git push denied to ym3178-afk (403), although GitHub read API now works. No new PR, merge or Render deployment was completed. New prompt needs live validation after deployment; it cannot yet be reported as a production POI fix. Physical GPS and production map interaction were not retested in this focused task.

Do not rotate a working production key solely on the historical generic error. If logs report invalid_key_format, securely correct Render OPENAI_API_KEY; never paste it into chat. For invalid_api_key, insufficient_quota or model_not_found, correct the indicated authentication/billing/model access in the provider dashboard. This task cannot inspect account billing status.

## Supplied Render logs: dimension validation failure

The supplied 00:58:11 log records HTTP 502, stage model_output_rejected, detail Invalid dimension name, followed by successful interpretation requests at 00:58:36, 00:59:43 and 01:00:41 and routes at 01:00:42. This confirms model output reached validation; it is distinct from the historical generic HTTP 500. The original combined validator could reject unknown weights, unknown directions, or a canonical direction without a matching weight, so the precise offending key cannot be recovered from that log. No raw model output or deploy SHA was supplied.

Validation diagnostics now distinguish these three cases without logging arbitrary output values. The prompt explicitly lists canonical names for UI abbreviations and requires directions keys to exist in weights. Regression tests keep all three malformed cases rejected with HTTP 502; this is not relaxed validation or proof that the new prompt eliminates every model error.
