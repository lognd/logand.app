# logand.app -- Android

Native Android (Kotlin, Jetpack Compose) client for the mileage-tracking
and quick-capture-receipts features -- see
[`docs/design/14-mileage-receipts-documents.md`](../docs/design/14-mileage-receipts-documents.md)
for the product/API design this was built against.

## Structure

```
android/
  core/    plain Kotlin/JVM module -- API client, models, rotating
           file logger, no Android dependency at all. Builds and tests
           with a bare JDK+Gradle, no Android SDK required.
  app/     the real Android application -- Jetpack Compose UI,
           ViewModels, AndroidManifest, resources, crash handler.
           Depends on :core.
```

`core/.../logging/FileLogger.kt` is a size-capped, generational rotating
file logger (pure `java.io.File`, no Android imports -- testable as a
plain JVM unit test). `app/.../logging/CrashHandler.kt` installs it as
the process's default uncaught-exception handler, and
`ShareLogsAction.kt` opens the system share sheet with every log file
concatenated ("Share app logs" on the login screen) so a crash or bug
report can be handed to the developer without needing `adb logcat`.

`:core` is the stable API contract the "abstraction layer" requirement
from the product ask actually is (see design doc 14's "API stability"
section) -- every screen in `:app` only ever talks to the backend
through `app.logand.core.ApiClient`.

## Third-party assets

`app/src/main/res/font/jetbrains_mono.ttf` is the real JetBrains Mono
variable-weight font (SIL Open Font License 1.1, full license text at
`app/licenses/JETBRAINS_MONO_OFL.txt`), matching the web frontend's own
`fontFamily.mono` (see `frontend/tailwind.config.ts`) -- not a generic
system-monospace substitute.

## Requirements

- JDK 17
- Android SDK: `platform-tools`, `platforms;android-34`,
  `build-tools;34.0.0`
- A `local.properties` file (gitignored, machine-specific) pointing
  `sdk.dir` at your Android SDK install

## Building

```
./gradlew :app:assembleDebug
```

Produces `app/build/outputs/apk/debug/app-debug.apk`. Install on a
device/emulator with `adb install app/build/outputs/apk/debug/app-debug.apk`,
or open the `android/` directory in Android Studio and run normally.

`make install`/`make test` (this directory's own `Makefile`, also what
the repo root's `make install`/`make test` delegate to) wrap the same
`./gradlew` commands below, adding the aarch64-Linux `aapt2` override
automatically when it's needed -- see "Building on aarch64 Linux" below.
Prefer them unless you need a specific Gradle task directly.

## Installing on a real device (e.g. Pixel 7a)

Every push of a `vX.Y.Z` tag builds a debug-signed APK and attaches it
to a GitHub Release automatically (`.github/workflows/release-android.yml`)
-- **that's the easiest path**: grab `app-debug.apk` from
[the latest release](../../releases/latest) instead of building it
yourself. It's debug-signed (this project has no Play-Store-grade
release keystore), which just means Android will label it as coming
from an unverified developer during install -- expected, not a warning
to work around.

Steps on a Pixel 7a (stock Android 14, but this is the same on any
modern Android device -- menu wording may vary slightly by OS version):

1. **Download the APK directly on the phone.** Open the release page's
   `app-debug.apk` link in Chrome (or transfer the file over any other
   way -- `adb push`, a cable, a cloud drive -- and open it from Files).
2. **Allow installs from this source, when prompted.** The first time
   you open a downloaded APK, Android blocks it and offers a link to
   **Settings**. Enable "Allow from this source" for whichever app you
   opened it with (Chrome, Files, etc.) -- this is scoped to that one
   app, not a global "allow anything" toggle.
3. **Tap Install**, then **Open**.

To reinstall a newer version later, repeat with the new release's APK
-- Android treats a debug-signed APK with a matching `applicationId`
(`app.logand.mobile`) as an update over the previous install as long as
it's signed with the exact same debug key, which it always will be
here (AGP's own generated debug keystore, not a per-machine one, since
every build in this repo's CI runs through the same checked-in Gradle
config).

### Installing over USB (`adb`) instead

If you'd rather build locally and push straight to the device:

1. On the phone: **Settings > About phone**, tap **Build number** 7
   times to unlock Developer options, then **Settings > System >
   Developer options > USB debugging**, enable it.
2. Connect the phone via USB, accept the "Allow USB debugging?" prompt
   on the phone.
3. `adb devices` should list it. Then:
   ```
   ./gradlew :app:installDebug
   ```
   (equivalent to `assembleDebug` + `adb install` in one step -- see
   "Building" above for the plain `assembleDebug` + manual `adb
   install` path if you'd rather build once and install more than
   once without a live USB connection each time.)

## Testing

```
./gradlew :core:test              # 36 tests, pure JVM, real MockWebServer
./gradlew :app:testDebugUnitTest  # 17 tests, ViewModels + data layer
```

`:core`'s tests exercise `ApiClient` against a real local HTTP server
(OkHttp MockWebServer) -- the same "real infra over mocks" convention
the backend's `testing/fake_stripe.py`/`fake_paypal.py`/`fake_smtp.py`
use, so these tests catch real request-shape bugs (and did: see git
history for the bodyless-POST and `List<String>` query-param bugs these
tests caught before this was ever run on a device).

`:app`'s ViewModel tests do the same against real `ApiClient` instances;
`ServerSettingsRepositoryTest` and `ReceiptCaptureControllerTest` use
Robolectric for the two places that genuinely need a simulated Android
`Context` (DataStore, `FileProvider`).

**Compose UI screens (`ui/*/​*Screen.kt`) are not covered by these unit
tests** -- verifying an actual rendered UI needs either a connected
device/emulator (`./gradlew :app:connectedAndroidTest`, using the
`androidTest` dependencies already wired into `app/build.gradle.kts`)
or a real device in Android Studio. No emulator was available in the
environment this was built in (see "Building on aarch64 Linux" below),
so screen-level UI tests were not added -- the business logic under
every screen (ViewModel state transitions, the actual HTTP calls) is
fully covered instead, which is where the real risk of a silent bug
lives (the UI layer is thin, declarative, and mostly just renders that
state).

### Coverage

```
./gradlew :core:jacocoTestReport   # core/build/reports/jacoco/test/html/index.html
./gradlew :app:jacocoTestReport    # app/build/reports/jacoco/jacocoTestReport/html/index.html
```

Last measured: `:core` 95.1% line coverage. `:app`'s business logic
(ViewModels, data layer, `ReceiptCaptureController`) is at 71.3%;
Compose screens are at 0% for the reason above (not tested, not that
they failed) and dominate `:app`'s raw total (601 of 831 measured
lines) -- read the split, not the blended number, for an honest
picture.

## Running against a local backend

By default the app talks to `https://logand.app`
(`ServerSettingsRepository.DEFAULT_BASE_URL`). To point it at a local
backend instead:

1. Run the backend locally (see `../docs/deployment.md`).
2. In the app, change the server URL in-app (persisted via DataStore --
   see `data/ServerSettingsRepository.kt`). From an emulator, use
   `http://10.0.2.2:8000` (the emulator's alias for the host machine's
   `localhost`) -- from a physical device on the same network, use the
   host machine's real LAN IP.
3. `res/xml/network_security_config.xml` allow-lists cleartext HTTP
   ONLY for `10.0.2.2` and `localhost` -- every other host requires
   real HTTPS. A physical device pointed at a LAN IP over plain HTTP
   will be blocked by this on purpose; use a real cert (e.g. via a
   reverse proxy) or add that specific IP to the allow-list locally
   (do not commit a broadened allow-list).

Login uses the same `/api/auth/login` session-cookie flow as the web
frontend -- CORS and `SameSite` don't apply to a native HTTP client at
all (those are browser-only enforcement mechanisms), so no backend
changes were needed to support this client; see design doc 14.

## Known limitations (honest, not hidden)

- **Session does not survive process death.** Only the server URL
  setting is persisted (DataStore); the session cookie lives in
  `SessionCookieJar`, in memory, for the app process's lifetime. A
  killed app requires logging in again. This was a deliberate scope
  tradeoff (see `data/ServerSettingsRepository.kt`'s doc comment) --
  encrypted-at-rest credential storage was judged not worth the added
  complexity for what's meant to be a small personal data-entry tool.
- **No offline queueing.** A mileage/receipt submission made with no
  connectivity fails immediately with a "check your connection" message
  rather than queueing for later sync. Worth adding if this app is used
  somewhere connectivity is routinely spotty (see design doc 14 for
  where this would slot in).
- **No instrumented/UI tests** -- see the Testing section above.

## Building on aarch64 Linux

This project (and this README's own setup) was originally built and
verified on an aarch64 (ARM64) Linux host, which Google's Android SDK
does not officially support for the build-tools toolchain (`aapt2`,
`d8`, etc. are only published as native `x86_64` binaries for Linux).
If you're on a normal x86_64 dev machine or macOS/Windows, none of this
section applies -- just install Android Studio and open the project.

If you ARE on aarch64 Linux, here's what made a real build work,
recorded so it doesn't have to be rediscovered:

1. **`qemu-user` binary emulation** lets an aarch64 kernel transparently
   run `x86_64` ELF binaries. Requires `qemu-x86_64` and, since the SDK's
   `aapt2` is dynamically linked, a minimal `x86_64` sysroot with
   `libc.so.6`/`libstdc++.so.6`/`ld-linux-x86-64.so.2` (these can be
   extracted from Debian/Ubuntu `.deb` packages with `dpkg-deb -x`,
   entirely in user space, no root required -- fix any absolute symlinks
   the extraction leaves behind to point back inside the sysroot).
2. **`android.aapt2FromMavenOverride`** (a Gradle project property) lets
   you point AGP at a wrapper script instead of the real `aapt2` binary
   it would otherwise resolve from Maven. AGP's own validation requires
   the override path's filename to literally end in `aapt2` (case-
   sensitive, no extension) -- name the wrapper file exactly `aapt2`
   inside its own directory, not `aapt2-wrapper.sh` or similar (a real
   error this project's own history includes: "Custom AAPT2 location
   does not point to an AAPT2 executable").
   ```
   ./gradlew :app:assembleDebug -Pandroid.aapt2FromMavenOverride=/path/to/wrapper-dir/aapt2
   ```
   where that wrapper is a shell script: `exec qemu-x86_64 -L <sysroot> <real-x86_64-aapt2-binary> "$@"`.
   This directory's `Makefile` applies this flag automatically (only
   when `ANDROID_AAPT2_OVERRIDE`'s path actually exists on disk, so
   `make test` is a no-op-different plain `./gradlew test` on any
   machine that doesn't need it -- override the variable if your
   wrapper lives somewhere else).
3. **Robolectric's Android sandbox loads `conscrypt` (for TLS) at
   startup**, unconditionally, even for tests that never touch
   networking. `conscrypt-openjdk-uber` only started shipping a
   `linux-aarch64` native build in the `2.6-alpha` series -- every
   stable `2.x` release is `x86_64`/`osx`/`windows` only. Add
   `testImplementation("org.conscrypt:conscrypt-openjdk-uber:2.6-alpha5")`
   (or newer) explicitly; `app/build.gradle.kts` already does this.
4. **Robolectric's remote-artifact fetcher** wants either real network
   access (with its own conscrypt-backed TLS client) or an offline flat
   directory of pre-fetched jars. Set both
   `-Drobolectric.offline=true` and `-Drobolectric.dependency.dir=<dir>`
   (already wired into `app/build.gradle.kts`'s `tasks.withType<Test>`)
   with the needed `android-all-instrumented-*.jar` copied (flat, not a
   Maven-layout path) into that directory once.

None of this is committed as a portable, one-command setup script (it's
genuinely machine-specific -- exact `.deb` package versions, exact SDK
build-tools version, local paths) -- it's recorded here as a map for
whoever needs to redo it, not as something `./gradlew` does
automatically.
