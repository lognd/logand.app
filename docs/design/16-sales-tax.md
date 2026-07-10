# 16 - Taxes (sales, use, import duty, ...)

Status: Phase 1 built; Phase 3/4 engine scaffolding built and KEY-READY
(inert until a Claude key + rate data are supplied). The model is normalized
to support ARBITRARY tax types per line (not just sales tax), because the
business also owes import duty/customs on parts (e.g. PCBs) and use tax, and
"extensibility is the key idea."

## What is built vs. what needs data (be honest)

Built and tested: the per-line charge model + computation + PDF/exports/API
(Phase 1); the `tax_rules` knowledge base + deterministic rate lookup; the
Claude categorizer (pydantic-enforced, DB-vocabulary-constrained, TTL-cached
and persisted for audit in `tax_categorization_cache`); the
`scripts/fetch_tax_rules.py` loader; and the admin tax-filing report
(`build_tax_report` + GET /api/admin/invoices/tax-report).

Not built, and NOT fakeable in code: authoritative rate/duty DATA. Correct US
sales/use tax needs a live per-jurisdiction feed (thousands of jurisdictions,
constantly changing) and import duty needs HTS classification. Point
`fetch_tax_rules.py` at a real source (commercial API, government tables, or a
curated file) before trusting any number. Tax filings still need professional
review -- the report is an aid, not advice.

## Why

The app records what was sold (`invoice_line_items`), for how much
(`amount_total`), when, to whom, and -- since migration 0021 -- the payer's
billing ZIP (`payments.zip_code`). That is enough to reconstruct revenue,
but not sales tax: there was no record of how much tax was charged, at what
rate, on which line, under which jurisdiction. This design adds an
auditable, extensible sales-tax model.

Two hard requirements shape it:

- **Auditable.** Every figure that determined a customer's total must be
  reconstructable years later from the invoice itself, never recomputed
  from *current* config. So the rate applied to each line, the tax amount,
  and the origin jurisdiction in effect at issue time are all snapshotted
  onto the row when the invoice is created. Moving the business's tax state
  (see below) or changing a rate never rewrites a historical invoice.
- **Extensible.** The business is an LLC registered in **TN** today and may
  move to **FL**; different items are taxed at different rates; tax may
  apply to a finished product *and* independently to its BOM subcomponents;
  and item taxability is intended to be categorized by a Claude call. The
  model must absorb all of that without another schema break.

## Model

### The line item classifies; a child table charges

Tax lives per-line, because different items are taxed differently and a
BOM's components and its finished product are each their own line, taxed
independently. But a single line can owe MORE THAN ONE tax (a PCB owes both
import duty AND sales/use tax), so the actual charges are rows in a child
table, not a single rate column.

`invoice_line_items` (classification, snapshotted):

- `taxable: bool` (default `true`) -- master gate: whether this line is
  subject to ANY tax. False = exempt, no charges apply regardless of rows.
  The Phase 4 categorizer flips it per item.
- `tax_category: str | null` -- optional classification (e.g.
  `tangible-goods`, `imported-component`, `service`, `exempt-resale`) the
  categorizer writes; drives which charges get attached. Null today.

`invoice_line_item_taxes` (the charges, one row per tax applied to a line):

- `line_item_id` -> `invoice_line_items.id` (CASCADE).
- `tax_type: str` -- `sales`, `use`, `import_duty`, ... open vocabulary so a
  new tax type is data, not a migration.
- `jurisdiction: str | null` -- who levies it (e.g. `US-TN`, `US-FL`,
  `US-customs`), for reporting/remittance and audit.
- `rate: Numeric(8,5)` (`>= 0`, check-constrained) -- the rate actually
  charged, snapshotted (not a pointer to a rate table that could change).
  8,5 not 6,4 so a small/precise duty rate fits.

A charge's `amount` is DERIVED (`quantize(line_total * rate)`), not stored,
so it can never desync from the snapshotted inputs (`line_total`, `rate`,
the line's `taxable`). Everything auditable -- which taxes, at what rate,
from which jurisdiction, on which line -- is persisted; the money is always
recomputed the same way wherever shown.

This one model covers every requirement: multiple tax types per line
(multiple rows), per-line rates (rate lives on the row), origin x
destination sourcing (Phase 3 chooses which rows/rates to attach), BOM
independent taxation (each line has its own rows), and import duty
(`tax_type=import_duty`) exactly like sales tax.

### Sales-tax sourcing (single-source, destination-preferred)

A line can owe several DIFFERENT taxes at once (import duty AND use tax AND
sales tax), and those stack. But it must never carry TWO `sales` charges: the
origin state's sales tax AND the destination state's sales tax summed on one
line would over-collect (e.g. origin TN 7% + destination FL 6% on a $100 line
= $13.00 of "sales" tax on a single sale). So `sales` tax is **single-source**:
a line carries at most ONE charge of `tax_type = sales`. Every other tax type
(`import_duty`, `use`, ...) still stacks normally across jurisdictions.

The one sales jurisdiction is chosen **destination-preferred**:

1. If the customer's DESTINATION jurisdiction (their `address_state`) has a
   configured `sales` rule for the line's category, use the DESTINATION rate.
2. Otherwise, if the ORIGIN jurisdiction (`tax_origin_state`) has a `sales`
   rule, use the ORIGIN rate.
3. Otherwise, no sales charge.

Presence of a configured rule -- not its rate -- decides the source: a
destination with an explicit 0% rule sources the (zero) charge and does not
fall through to origin.

**This is a deliberate simplification of US tax law, not a model of it.**
Real sales-tax sourcing (origin- vs destination-based) genuinely varies by
state and by whether the seller has nexus in the destination state. This app
encodes ONE rule -- single jurisdiction per line, destination-preferred -- and
does NOT attempt to encode per-state origin/destination rules. The operator
MUST confirm this rule matches their own nexus and registration obligations
with an accountant before relying on the charged amounts or the filing report.

### Per-invoice (denormalized rollups + jurisdiction snapshot)

- `tax_amount: Numeric(14,3)` (default `0`) -- sum of the per-line tax
  amounts, denormalized for query speed exactly like `amount_total`, and
  recomputed server-side on every write by `recompute_amount_total`. Never
  trusted from client input.
- `amount_total` -- now `subtotal + tax_amount`, where `subtotal` is the sum
  of the (quantized) line totals. Existing column; its meaning is unchanged
  for a zero-tax invoice.
- `tax_origin_state: str | null` -- the seller's tax jurisdiction (US state
  code, e.g. `TN`) in effect WHEN THE INVOICE WAS CREATED, snapshotted from
  `AppConfig.invoice_tax_origin_state`. This is what makes the TN->FL move
  clean: flip the config, and only invoices created afterward carry `FL`;
  every historical invoice keeps the `TN` it was actually filed under.

### Config

- `INVOICE_TAX_ORIGIN_STATE` (default `TN`) -- the current seller state,
  snapshotted onto each new invoice. Changing it is the entire TN->FL
  migration on the seller side.

## Computation

`recompute_amount_total` (the single server-side chokepoint, called on
every write path) now computes, in the invoice's own currency precision:

```
subtotal        = sum(quantize(qty * unit_price))            over all lines
charge_amount   = quantize(line_total * charge.rate)         per tax charge row
line_tax        = sum(charge_amount) if line.taxable else 0  over that line's charges
tax_amount      = sum(line_tax)                              over all lines
amount_total    = subtotal + tax_amount
```

Each line total and each line tax is quantized to the currency BEFORE
summing, matching the existing `InvoiceLineItemView.line_total` rule so the
per-line figures shown on the PDF/email always sum to the stored rollups
(the FINDINGS.md M1/L1 invariant, extended to tax).

## Phases

- **Phase 1 (foundation):** the normalized model above -- line
  `taxable`/`tax_category`, `invoice_line_item_taxes` charge rows, invoice
  `tax_amount`/`tax_origin_state`, computation, and surfacing through the
  PDF (Subtotal / Tax / Total), the plaintext and for-robots.json exports,
  and the admin create/read API. Charges are supplied explicitly per line
  via the API.
- **Phase 2 - admin UI:** add/edit tax charges + taxable toggle per line on
  the admin invoice form; Subtotal/Tax/Total (and per-type) breakdown on the
  admin and customer (Pay page) views.
- **Phase 3 - automatic sourcing + freshness:** stop entering rates by hand.
  Attach charges automatically from origin (`tax_origin_state`) x destination
  (customer location) x `tax_category`: a rate provider/table for US sales/
  use tax and an HTS-based duty lookup for imports. "Keep tax amounts up to
  date" = a scheduled refresh of the rate tables (scheduler.py) and a check
  that DRAFT invoices reprice against current rates, while SENT/PAID invoices
  keep their snapshot. Needs a customer address (today only the payer billing
  ZIP on `payments` exists, captured only AFTER payment).
- **Phase 4 - two bifurcated components** (distinct responsibilities):
  1. **Tax knowledge base (deterministic).** Maintains every applicable tax
     for the SELLER (county/state/federal) and for the BUYER (their
     county/state/federal), across item categories -- conceptually the
     cartesian product of seller-jurisdictions x buyer-jurisdictions x
     item-category, though stored/queried as rules, not a literal exploded
     table. The RESULT it serves is deterministic (a lookup returns exact
     rates), but BUILDING/refreshing it may itself use an LLM to fetch and
     normalize published tax codes across every state/county/federal source
     into that structured table -- an ingestion step, kept separate from and
     upstream of the deterministic lookup so a model hiccup can never perturb
     a rate already in the table. Refreshed on a schedule (the "keep up to
     date" job).
- **Phase 5 - do-as-we-go per-item classification (built):** rather than a
  batch job, items are classified lazily as they're invoiced. The first time
  an item appears it is classified (Claude, or by hand) and cached in
  `item_tax_classifications` by a normalized key; every later invoice reuses
  it, so only genuinely-new items cost a model call (still one batched call
  per invoice for all new lines). A Claude result is `pending` until an admin
  confirms or overrides it (GET/POST /api/admin/tax/classifications); a human
  decision is authoritative and never re-asked. Claude rate limits and errors
  degrade gracefully -- the new item is deferred (no charges, retried next
  time), never failing invoice creation. Claude also proposes an HTS code for
  imported items, which the USITC duty adapter (a fetch_tax_rules source, to
  be added) prices.

  2. **Claude matcher (categorizer).** Matches each item AND the assembly
     against the BoM, and emits the concrete taxes/duties for each line by
     querying component (1). Its output is CACHED WITH A TTL keyed on the
     item/assembly + jurisdictions, so repeated invoices for the same parts
     don't re-call the model; the TTL is what lets a rate change in (1)
     eventually flow through. LLM-shaped -- build with the `claude-api`
     skill and a current model (e.g. Sonnet 5); own pass, own review. The
     charge rows it produces are exactly the `invoice_line_item_taxes` rows
     Phase 1 defines, so this bolts on with no schema change.

## Review gating: unconfirmed tax never auto-charges (M2/M3)

`apply_auto_tax` only ever auto-charges a line whose classification is
human-`confirmed` or `overridden`. A `pending` (model-classified, not yet
confirmed) line -- or a line the categorizer never resolved because Claude
rate-limited/errored while a key IS configured -- is charged NOTHING and the
invoice is flagged via `flag_invoice_needs_review` ("N line item(s) need tax
review"). This makes the human review workflow actually hold back money and
makes a categorizer outage fail CLOSED-with-a-signal instead of silently
under-collecting. A genuinely tax-free CONFIRMED line (`taxable=false`,
confirmed) does not raise the flag -- only an unresolved/unconfirmed line
does. The charge writes run inside a savepoint (`db.begin_nested`) so a
mid-loop failure can never leave partial charge rows against a stale
`tax_amount`/`amount_total` (L2). An UNCONFIGURED deployment (no Claude key)
stays a pure no-op: auto-tax is not expected there, so no review flag is
raised and admins enter charges by hand as before.

## BOM interaction (open, Phase 3+)

The BOM feature will emit line items for a finished product AND its
subcomponents. Per the decision recorded here, components and the finished
product are **taxed independently**: each is its own line with its own
`taxable`/`tax_rate`, and `tax_amount` sums across all of them. The model
already supports this (tax is per line). The open question deferred to
Phase 3+ is whether some BOM configurations should instead roll component
value into the finished line to avoid taxing the same value twice; if so it
becomes a categorizer/BOM policy on top of this same per-line model, not a
schema change.

## Keeping figures in sync

The set of places that render the tax breakdown -- the PDF template, the
plaintext/JSON exports, the admin read API, and (Phase 2) the admin form and
Pay page -- must stay consistent. All read the one `InvoiceExportData`
(loaded once by `load_invoice_export_data`); new formats must derive from it
rather than re-deriving tax independently.
