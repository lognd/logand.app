.PHONY: install build dev test test-system lint fmt typecheck check types clean

install:
	npm ci

dev:
	npm run dev

build:
	npm run build

test:
	npm run test

test-system:
	npm run test:system

lint:
	npm run lint

fmt:
	npm run fmt

typecheck:
	npm run typecheck

check: lint typecheck test

types:
	npm run types

clean:
	rm -rf dist node_modules
