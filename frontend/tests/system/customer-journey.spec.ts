import { test, expect, type Page, type APIRequestContext } from "@playwright/test";

// Drives the whole customer lifecycle through the REAL browser UI against
// the real running backend (see docs/design/12-testing-strategy.md's
// "Customer" system flow) -- register, confirm the session is live, log
// out, confirm the nav reflects a logged-out visitor again, log back into
// the SAME account, get sent an invoice, and pay it. Each step already has
// its own focused coverage (see backend/tests/system/test_customer_journey.py
// for the same chain at the HTTP level); this test's value is specifically
// that the handoffs between steps work through the real UI -- form
// submission, client-side routing, session-cookie persistence across
// navigations -- not any single step in isolation.
//
// Requires the full stack (frontend dev server + real backend + real
// Postgres/Redis) -- see docker-compose.test.yml and this project's
// vite.config.ts VITE_API_PROXY_TARGET, which is what lets a relative
// "/api/..." fetch from the browser actually reach the backend rather than
// 404ing against the plain vite dev server.

function uniqueEmail(label: string): string {
  return `${label}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

async function registerViaUi(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/register");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /create account/i }).click();
  // Registration logs the account in immediately and navigates home --
  // the nav's "log out" link is the real signal that a session exists,
  // not just that the form submission didn't error.
  await expect(page.getByRole("button", { name: "log out" })).toBeVisible();
}

async function loginViaUi(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("button", { name: "log out" })).toBeVisible();
}

async function logoutViaUi(page: Page): Promise<void> {
  await page.getByRole("button", { name: "log out" }).click();
  // The logged-out nav shows "log in"/"register" again -- this is the UI
  // reflecting that the session is genuinely over, not just that the
  // logout request returned 200.
  await expect(page.getByRole("link", { name: "log in" })).toBeVisible();
}

// The customer-facing UI has no admin invoice-creation screen (see
// Projects.tsx-adjacent admin routes) -- seeding an invoice for the new
// customer to pay goes straight through the real API instead, exactly as
// a real admin's own browser session would, just without a UI for it in
// this test. request context shares nothing with the page's cookie jar,
// so this logs an admin in and out entirely on its own.
async function seedSentInvoice(
  request: APIRequestContext,
  customerId: string,
): Promise<string> {
  const adminEmail = uniqueEmail("journey-admin");
  const registerResp = await request.post("/api/auth/register", {
    data: { email: adminEmail, password: "admin-seed-password" },
  });
  expect(registerResp.ok()).toBeTruthy();

  // Self-registration always creates a customer-role account (see
  // Register.tsx's doc comment) -- there is no API path to become an
  // admin from the outside, by design. Promoting this seed account
  // directly is out of scope for a browser-driven system test; instead
  // this assumes a seeded admin fixture (SEED_ADMIN_EMAIL/PASSWORD, see
  // docs/design/12's "seeded test customer/admin" system-test fixtures)
  // already exists in the test stack's database.
  const adminEmailEnv = process.env.SEED_ADMIN_EMAIL;
  const adminPasswordEnv = process.env.SEED_ADMIN_PASSWORD;
  test.skip(
    !adminEmailEnv || !adminPasswordEnv,
    "SEED_ADMIN_EMAIL/SEED_ADMIN_PASSWORD not set -- needs a pre-seeded admin fixture in the test stack",
  );

  const adminLogin = await request.post("/api/auth/login", {
    data: { email: adminEmailEnv, password: adminPasswordEnv },
  });
  expect(adminLogin.ok()).toBeTruthy();
  const csrfCookie = (await request.storageState()).cookies.find(
    (c) => c.name === "csrf_token",
  );
  const csrfHeaders: Record<string, string> = csrfCookie
    ? { "X-CSRF-Token": csrfCookie.value }
    : {};

  const createResp = await request.post("/api/admin/invoices", {
    params: { customer_id: customerId },
    data: [{ description: "e2e journey widget", quantity: "1", unit_price: "42.00" }],
    headers: csrfHeaders,
  });
  expect(createResp.ok()).toBeTruthy();
  const invoiceId = (await createResp.json()).id as string;

  const sendResp = await request.post(`/api/admin/invoices/${invoiceId}/send`, {
    headers: csrfHeaders,
  });
  expect(sendResp.ok()).toBeTruthy();

  await request.post("/api/auth/logout", { headers: csrfHeaders });
  return invoiceId;
}

test.describe("customer journey", () => {
  test("register, log out, confirm session over, log back in", async ({ page }) => {
    const email = uniqueEmail("journey");
    const password = "a-real-password-123";

    await registerViaUi(page, email, password);

    // Session reload persistence, not just the in-memory nav state --
    // reload the page and confirm /api/me still reports logged in from
    // the real cookie, matching docs/design/12's "session persists
    // across reload" required flow.
    await page.reload();
    await expect(page.getByRole("button", { name: "log out" })).toBeVisible();

    await logoutViaUi(page);
    // Reload again after logout to rule out an in-memory-only nav state
    // change without the underlying session actually being gone.
    await page.reload();
    await expect(page.getByRole("link", { name: "log in" })).toBeVisible();

    // Log back into the SAME account (not a fresh one) -- proves the
    // credentials survived the logout rather than only ever being
    // exercised against a brand new registration.
    await loginViaUi(page, email, password);
  });

  test("customer can pay an invoice sent to their account", async ({ page, request }) => {
    const email = uniqueEmail("journey-payer");
    const password = "another-real-password";

    await registerViaUi(page, email, password);

    // page.request (NOT the standalone `request` fixture) for THIS read --
    // the standalone fixture is its own isolated APIRequestContext with no
    // cookies at all, so a plain `/api/me` through it always 401s
    // regardless of what the page itself just registered. page.request
    // shares the browser context's real cookie jar, which is what actually
    // carries the customer session this specific read needs.
    const meResp = await page.request.get("/api/me");
    expect(meResp.ok()).toBeTruthy();
    const customerId = (await meResp.json()).user_id as string;

    // The standalone `request` fixture again (isolated, NOT page.request)
    // for the actual admin seeding below -- seedSentInvoice logs an admin
    // account in and back out. Doing that through page.request would log
    // the admin in and out on the SAME cookie jar the page itself is using
    // for the customer's own session, overwriting/clearing it before the
    // test gets to actually use it to view/pay the invoice as the customer.
    const invoiceId = await seedSentInvoice(request, customerId);

    await page.goto("/invoices");
    await expect(page.getByRole("link", { name: `Pay invoice ${invoiceId}` })).toBeVisible();
    await page.getByRole("link", { name: `Pay invoice ${invoiceId}` }).click();

    await expect(page).toHaveURL(new RegExp(`/invoices/${invoiceId}/pay$`));

    // Waits registered BEFORE the click so a fast response can't slip
    // past them.
    const payResponse = page.waitForResponse(
      (resp) =>
        resp.url().endsWith(`/api/invoices/${invoiceId}/pay`) &&
        resp.request().method() === "POST",
    );
    await page.getByRole("button", { name: /pay with card/i }).click();

    // The real assertions: POST /pay minted an intent against the
    // fake-stripe double (a real client_secret round trip), and the page
    // swapped the pay buttons for the card form. The Payment Element
    // iframe INSIDE that form talks to Stripe's actual servers, so with
    // pk_test_fake (see docker-compose.test.yml) it can never finish
    // loading -- entering a card number and charging it is deliberately
    // out of scope here; Pay.test.tsx covers everything past this
    // boundary with the stripe-js layer mocked.
    expect((await payResponse).status()).toBe(200);
    await expect(page.getByRole("form", { name: "Card payment" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("button", { name: "Pay now" })).toBeVisible();
  });
});
