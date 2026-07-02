# Root Makefile delegates to each subproject. See docs/design/00-overview.md for layout.
.PHONY: install build test test-system lint typecheck fmt check clean

install:
	$(MAKE) -C backend install
	$(MAKE) -C frontend install
	$(MAKE) -C android install

build: install
	$(MAKE) -C wasm-ascii build
	$(MAKE) -C frontend build

# NOTE(logan): android is NOT wired into CI (.github/workflows/ci.yml has
# no android job -- no runner has the Android SDK set up yet) and CI never
# invokes this root Makefile at all (each subproject job runs its own
# uv/npm/cargo commands directly) -- so including it here only affects
# local `make test` runs, never a CI/CD run. android/Makefile's own
# ANDROID_AAPT2_OVERRIDE is itself conditional (only applied if that exact
# wrapper path exists on disk), so this is also a plain `./gradlew test`
# with no behavior change on any machine that isn't this aarch64 dev host.
test:
	$(MAKE) -C backend test
	$(MAKE) -C frontend test
	$(MAKE) -C wasm-ascii test
	$(MAKE) -C android test

test-system:
	docker compose -f docker-compose.test.yml up -d --build
	$(MAKE) -C backend test-system || ( docker compose -f docker-compose.test.yml down; exit 1 )
	$(MAKE) -C frontend test-system || ( docker compose -f docker-compose.test.yml down; exit 1 )
	docker compose -f docker-compose.test.yml down

lint:
	$(MAKE) -C backend lint
	$(MAKE) -C frontend lint

typecheck:
	$(MAKE) -C backend typecheck
	$(MAKE) -C frontend typecheck

fmt:
	$(MAKE) -C backend fmt
	$(MAKE) -C frontend fmt

check:
	$(MAKE) -C backend check
	$(MAKE) -C frontend check
	$(MAKE) -C wasm-ascii check

clean:
	$(MAKE) -C backend clean
	$(MAKE) -C frontend clean
	$(MAKE) -C wasm-ascii clean
