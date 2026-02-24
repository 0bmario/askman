.PHONY: db release clean install build

# Default target
all: build

# Generate the commands database (semantic index)
db:
	cargo run --bin import_tldr --features="dev"

# Build the release binary
build:
	cargo build --release

# Clean up local askman data (models, cache, db)
clean:
	cargo run -- --clean

# Standard cargo installation
install:
	cargo install --path .

# Helper to tag and push a new release
# Usage: make release VERSION=0.3.0
release:
	@if [ -z "$(VERSION)" ]; then echo "Error: VERSION is required (e.g. make release VERSION=0.3.0)"; exit 1; fi
	sed -i '' 's/^version = ".*"/version = "$(VERSION)"/' Cargo.toml
	git add Cargo.toml
	git commit -m "chore: bump version to $(VERSION)"
	git tag -a v$(VERSION) -m "Release v$(VERSION)"
	git push origin main
	git push origin v$(VERSION)
	@echo "\nRelease v$(VERSION) tagged and pushed. CI will build binaries."
	@echo "Don't forget to manually upload the 'commands.db' to the GitHub release page after 'make db' finishes!"
