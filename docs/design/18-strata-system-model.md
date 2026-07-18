# 18 - Strata system model (design/logand-app.strata)

Status: pilot wiring landed (sibling-repos-rollout). Kept green-ish by
hand for now; not yet a required CI gate.

## What this is

`design/logand-app.strata` is a machine-checkable model of this repo's
real deployed topology, written in frob's strata language (see
`~/.claude/refs/frob.md` and the frob repo's own `docs/strata/*.md` for
the language itself -- this doc only covers what OUR model says and how
to keep it honest, not the language).

It models, from the real code and the real `docker-compose.yml`/
`Caddyfile`, not a hypothetical architecture:

- **Nodes**: `browser` (the SPA), `wasm_ascii` (the in-browser Rust/wasm
  compute module), `android` (the native Kotlin client), `edge` (Caddy),
  `backend` (FastAPI), `scheduler` (the recurring-invoice loop, same
  image as backend), `postgres`, `redis_store`, `object_storage`
  (Cloudflare R2), `stripe`, `paypal`, `mail_relay`, `github_api`.
- **Flows**: every real edge between those nodes, including the one that
  is easy to miss -- `GithubRepoCard.tsx` fetches `api.github.com`
  directly from the browser, not proxied through the backend.
- **Capabilities** (`may "..."`) declared per node from an actual grep/
  read of the code each node's `code` glob covers: `fetch_url`,
  `client_storage`, `html_render` on `browser`; `sql`, `net`, `fs`,
  `exec`, `env` on `backend`; etc.
- **Claims**: three `noflow`/`reach` claims about the real trust boundary
  (browser cannot reach postgres directly; stripe cannot reach the object
  store; github_api cannot reach postgres) plus the `assume` claims each
  declared capability drags in (CWE-78/89/918/etc, per
  `docs/strata/threat.md#capabilities-drag-in-obligations` in the frob
  repo).

## Keeping it green

Run `frob sys audit` from the repo root after touching anything that
changes:

- what a node's code does (new `fetch()`/`localStorage`/
  `dangerouslySetInnerHTML`/`subprocess`/`os.environ` call site, in
  either direction -- adding OR removing one),
- a real network/database/third-party edge (new integration, new
  datastore, new outbound call),
- the Caddy routing table or `docker-compose*.yml` service topology.

If the audit reports a new `THREAT003` (an undischarged weakness
obligation), either fix the underlying issue or add an honestly-reasoned
`assume "weakness:CWE-###:<node>" ... owner ... review "..."` claim to
`design/logand-app.strata` citing the specific code you checked -- never
declare a capability away or delete a flow just to force a green run.

## Known gaps (not gamed away)

- **TS/JS and Kotlin capability scanning is incomplete.** `frob sys
  audit`'s effect scanner is written for Python; it does not see
  `fetch()`, `localStorage`, `dangerouslySetInnerHTML` in TypeScript, or
  anything in Kotlin. `browser`'s and `android`'s `may` declarations were
  verified by hand (grep + read), not by the scanner -- expect
  `SYS101 declared but never observed` warnings for those nodes
  indefinitely until frob grows a TS/Kotlin capability scanner.
- **`re.compile(...)` self-matches the `eval` capability pattern** on
  `backend`/`scheduler` (same class of false positive frob's own
  `frob.strata` model hit and partially fixed under T-0151). Not
  declared `may "eval"` to compensate -- that would be gaming the audit.
- **CWE-639 (authz-scoping) on `backend`/`scheduler` is a real open
  item**, tracked as `T-0004` in `tickets.md`, not silently assumed away.

See the strata pilot's own wiring report (frob-side task record) for the
full list filed as upstream frob gaps.
