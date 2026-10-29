.PHONY: build test export check

# Catala comes from the local opam switch in _opam/, so every call goes through
# `opam exec`. The exporter plugin needs no opam packages beyond those Catala
# 1.3.0 already depends on (yojson and zarith among them).
CATALA = opam exec -- catala
CLERK = opam exec -- clerk
DUNE = opam exec -- dune

RULES = $(wildcard rules/*.catala_en)

# The bm-export plugin, built by dune into a directory of its own.
PLUGIN_DIR = exporter/_build/default/plugin

build:
	$(CLERK) start
	@for f in $(RULES); do $(CATALA) typecheck -I rules $$f || exit 1; done

# The Python tests read build/uc.bm-ir.json, which `export` writes.
test: export
	$(CLERK) test
	$(DUNE) test --root exporter
	uv run pytest

# Writes the UniversalCredit scope as bm-ir JSON (see docs/bm-ir.md).
export: build
	$(DUNE) build --root exporter
	mkdir -p build
	$(CATALA) bm-export --plugin-dir $(PLUGIN_DIR) -I rules \
	  -s UniversalCredit rules/uc.catala_en -o build/uc.bm-ir.json

# The differential check: Catala, Z3 and PolicyEngine UK on generated households.
# Exits 1 on a mismatch that docs/mismatches.md does not explain.
check: export
	uv run bm check build/uc.bm-ir.json --bounds rules/uc.inputs.toml
