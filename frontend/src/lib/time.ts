// Turns a RateLimitedError's retryAfterSeconds (a duration) into a real
// wall-clock time the user can act on -- "try again at 3:41:12 PM" is more
// useful than "try again in 42s" once you've actually read the message
// and a few seconds have already passed, and the same computation is
// wanted on more than one auth screen (login, forgot-password), so it
// lives here once.
export function formatRetryAt(retryAfterSeconds: number): string {
  const retryAt = new Date(Date.now() + retryAfterSeconds * 1000);
  return retryAt.toLocaleTimeString();
}
