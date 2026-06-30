.PHONY: build check test clean

build:
	wasm-pack build --target web --out-dir ../frontend/src/ascii/pkg

check:
	cargo check
	cargo clippy -- -D warnings
	cargo fmt --check
	cargo test

test:
	cargo test

clean:
	rm -rf target ../frontend/src/ascii/pkg
