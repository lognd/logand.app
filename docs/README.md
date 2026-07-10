# Documentation index -- logand.app

Two kinds of docs live here, for two different audiences:

| Directory/file | For | Read when you're... |
|---|---|---|
| [design/](design/README.md) | Engineers/agents building or modifying a feature | Implementing something, or trying to understand *why* it's built the way it is |
| [deployment.md](deployment.md) | Whoever is standing up or redeploying the site | Setting up a fresh VPS, or redeploying after a gap |
| [secrets.md](secrets.md) | Same as above | Generating, rotating, or figuring out where a secret lives |
| [usage.md](usage.md) | Anyone using the deployed site | Using it as a customer or as the admin |
| [OPERATIONS.md](OPERATIONS.md) | Whoever is operating the site day-to-day | Deploying, running a migration, chasing a mail/payment/Android issue, or working the pre-push checklist |
| [runbooks/restore.md](runbooks/restore.md) | Whoever is operating the site | Something's actually broken and you need to restore from backup |

Start at the root [README.md](../README.md) if you haven't already --
it's the shortest path to "how do I even run this locally."

## Status

`design/` is intentionally kept close to a pre-implementation spec, but
each doc gets updated in the same change as the code whenever real
implementation diverges from what it originally said (see
[design/README.md](design/README.md)'s own "Status" section) -- it is
not a historical artifact frozen at design time. The other docs here
(`deployment.md`, `secrets.md`, `usage.md`, `runbooks/`) describe the
system as actually built and deployed, not a plan for it.
