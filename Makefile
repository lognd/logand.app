# Root Makefile delegates to each subproject. See docs/design/00-overview.md for layout.
.PHONY: install build test test-system lint typecheck fmt check clean

install:
	$(MAKE) -C backend install
	$(MAKE) -C frontend install

build: install
	$(MAKE) -C wasm-ascii build
	$(MAKE) -C frontend build

test:
	$(MAKE) -C backend test
	$(MAKE) -C frontend test
	$(MAKE) -C wasm-ascii test

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
