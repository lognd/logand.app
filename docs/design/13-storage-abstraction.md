# 13 -- File Storage Abstraction

Audience: anyone adding a feature that stores real file bytes (evidence,
receipts, documents/CAD, or anything future). Read
[00-overview.md](00-overview.md) first.

## Why this exists

Budget evidence, receipts, and documents/CAD files all need to persist
real uploaded bytes somewhere. Rather than each feature hard-coding
"write to local disk" (or, worse, "write to whatever cloud bucket we
happen to be using this year"), `domain/storage/` defines one interface
every feature is written against. Swapping where files actually live is
then a config change (`STORAGE_BACKEND`), never a code change in any
caller.

This was also chosen with a specific medium/long-term hosting path in
mind (see "Hosting roadmap" below): local disk today, Cloudflare R2 once
it's worth paying for real object storage, and the door deliberately left
open for a self-hosted NAS if that ever becomes the cheaper or
more-in-control option.

## The interface

```python
class StorageBackend(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...          # raises StorageObjectNotFound
    async def delete(self, key: str) -> None: ...          # idempotent
    async def exists(self, key: str) -> bool: ...
    async def url(self, key: str) -> str | None: ...       # None if no public URL
```

`key` is always a caller-chosen namespaced string (e.g.
`"receipts/{receipt_id}/{filename}"`), never a full URL -- only `url()`
translates a key into something a client can fetch directly, and it
returns `None` for backends (or bucket configs) with no public access,
in which case the caller must proxy bytes through its own authenticated
API route instead (every current caller does this: `GET .../{id}/file`
routes check `url()` first, fall back to streaming `get()`'s bytes).

`domain/storage/factory.py::get_storage_backend(cfg)` is the one place
that knows about every concrete implementation. Callers (`api/budget.py`,
`api/receipts.py`, `api/documents.py`) only ever import the factory and
the `StorageBackend` protocol, never a concrete class.

## Implementations

- **`LocalFilesystemStorage`** (`domain/storage/local.py`) -- default,
  zero external dependency. Writes under `STORAGE_LOCAL_DIR` (default
  `./data/storage`, gitignored). `url()` always returns `None` -- files
  are only ever reachable by proxying through this app's own
  authenticated routes, which is also strictly safer than accidentally
  exposing a public path.
- **`CloudflareR2Storage`** (`domain/storage/r2.py`) -- R2 is
  S3-API-compatible, so this is a thin wrapper around `boto3`'s plain S3
  client pointed at R2's endpoint. No egress fees, 11-nines durability,
  and you're already hosted on Cloudflare (see "Hosting roadmap"). `url()`
  returns a real URL only if `R2_PUBLIC_BASE_URL` is set (a bucket with a
  custom domain opted into public read access); otherwise `None`, same
  proxy-through-the-API fallback as local.

See [secrets.md](../secrets.md) for the full `STORAGE_BACKEND`/`R2_*` env
var reference.

## Public assets and caching

`StorageBackend.put()` takes an optional `cache_control` keyword arg,
plumbed through to R2's `put_object` (`CacheControl=...`) and simply
ignored by `LocalFilesystemStorage` (nothing fetches a local-backend
object directly, so there's no HTTP response to attach a header to).

This exists for a different use case than the private,
authenticated-proxy files above: public, marketing/showcase assets --
Projects-page photos, videos, PDFs -- that need to load on a public page
with no session at all, and that essentially never change once
uploaded. `backend/src/logand_backend/scripts/upload_public_asset.py`
is the CLI for these: it uploads to the configured backend under a
`projects/` key prefix (overridable via `--prefix`) and sets
`Cache-Control: public, max-age=31536000, immutable`.

Because that header is immutable/1-year, **replacing a file's content
means uploading under a new key, never overwriting the old one** --
browsers and any CDN in front of R2 will keep serving the old bytes
from cache for up to a year regardless of what the object now contains
server-side. In practice this means picking a new filename (add a
version suffix, e.g. `torque-arm-diagram-v2.png`) and updating whatever
page references the URL; the old URL is simply left unreferenced and
can be deleted from the bucket later without needing any cache
invalidation step at all.

This is a different caching story than the frontend bundle itself --
Caddy serves `frontend/dist` directly (see [deployment.md](../deployment.md)),
and a normal `npm run build` produces content-hashed filenames for JS/CSS
(cache-bust automatically on every deploy) but an unhashed `index.html`
(must always revalidate, so a deploy is picked up immediately) --
no extra Caddy config needed for either case, it falls out of Vite's
default build output naming.

## Adding a NAS (or any other) backend later

Implement the five `StorageBackend` methods against whatever protocol the
NAS speaks (SFTP, a local network mount, WebDAV, etc.), add one branch to
`get_storage_backend()`, done -- no caller changes. A local-mount NAS
backend in particular could likely just be `LocalFilesystemStorage`
pointed at a mounted path via `STORAGE_LOCAL_DIR`, with no new code at
all, if the NAS is mounted as a regular filesystem path on the host; a
network-protocol NAS (true SFTP, not a local mount) would need a real new
implementation.

## Hosting roadmap (cost/durability tradeoffs, for future reference)

Considered, in the order this project expects to actually need them:

1. **Local disk (now)** -- free, but durability is only as good as the
   host's own disk. Fine while file volume is small and losing a file
   would be an inconvenience, not a real problem (mostly true today: most
   evidence/receipts/documents are also derivable from other records).
2. **Cloudflare R2 (medium term, once it's worth paying for)** -- the
   default next step specifically *because* the site is already hosted
   on Cloudflare: no new vendor relationship, no egress fees (unlike AWS
   S3/GCS, which charge for every byte served out), S3-compatible so the
   `CloudflareR2Storage` implementation already exists and just needs
   real credentials. 11-nines durability (multi-region replication under
   the hood) -- "no hard-drive errors possible" is effectively what R2
   already provides without any additional NAS/RAID engineering on our
   end. Free tier: 10 GB storage + 1M Class A / 10M Class B operations/
   month as of this writing -- verify current pricing before committing,
   but this comfortably covers this app's realistic file volume for a
   long time.
3. **Self-hosted NAS (only if it ever becomes clearly better)** -- cheaper
   per-GB at real scale, and keeps files fully under physical control, but
   shifts durability entirely onto us: a real NAS setup for "infallible"
   durability needs redundant drives (RAID 1/5/6/10, not a single disk),
   a UPS, and a genuine offsite backup (3-2-1 backup rule: 3 copies, 2
   different media, 1 offsite) -- otherwise a fire/theft/flood is a total
   loss regardless of RAID. This is real ongoing operational work, not a
   one-time setup, and is why R2 is the recommended default over this
   even though the direct per-GB cost is higher: R2's durability is
   already handled, a NAS's is a standing responsibility. Revisit if file
   volume/cost genuinely justifies the tradeoff, or if data sovereignty
   (not wanting files on any third party's infrastructure) becomes a hard
   requirement.

Google Cloud Storage / AWS S3 / Backblaze B2 were considered and set
aside for now: B2 is roughly R2-competitive on price but adds a second
vendor relationship for no clear benefit over R2 given the existing
Cloudflare hosting; GCS/S3 both charge real egress fees, which R2
specifically doesn't, making them strictly worse for this app's access
pattern (files get downloaded, not just written once and left alone).

## Testing

`LocalFilesystemStorage` is tested against a real `tmp_path` (no mocked
filesystem). `CloudflareR2Storage` is tested against
[moto](https://github.com/getmoto/moto)'s real in-process S3 API double
-- `boto3`'s actual HTTP client runs against it, not a monkeypatched
method, same "real protocol double" convention as `testing/fake_stripe.py`
/`testing/fake_paypal.py`/`testing/fake_smtp.py`. See
`tests/unit/test_storage.py`.
