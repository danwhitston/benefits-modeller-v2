.PHONY: build test test-fast export check probe

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

# As `test`, but skips the tests marked slow (the PolicyEngine UK ones).
test-fast: export
	$(CLERK) test
	$(DUNE) test --root exporter
	uv run pytest -m "not slow"

# Writes the UniversalCredit scope, the ClaimWindow scope and the longer
# windows used to measure solver time as bm-ir JSON (see docs/bm-ir.md).
export: build
	$(DUNE) build --root exporter
	mkdir -p build
	$(CATALA) bm-export --plugin-dir $(PLUGIN_DIR) -I rules \
	  -s UniversalCredit rules/uc.catala_en -o build/uc.bm-ir.json
	$(CATALA) bm-export --plugin-dir $(PLUGIN_DIR) -I rules \
	  -s ClaimWindow rules/uc.catala_en -o build/claim_window.bm-ir.json
	$(CATALA) bm-export --plugin-dir $(PLUGIN_DIR) -I rules \
	  -s ClaimWindow4 rules/uc.catala_en -o build/claim_window4.bm-ir.json
	$(CATALA) bm-export --plugin-dir $(PLUGIN_DIR) -I rules \
	  -s ClaimWindow5 rules/uc.catala_en -o build/claim_window5.bm-ir.json
	$(CATALA) bm-export --plugin-dir $(PLUGIN_DIR) -I rules \
	  -s ClaimWindow6 rules/uc.catala_en -o build/claim_window6.bm-ir.json

# The differential check: Catala, Z3 and PolicyEngine UK on generated households.
# Exits 1 on a mismatch that docs/mismatches.md does not explain.
check: export
	uv run bm check build/uc.bm-ir.json --inputs rules/uc.inputs.toml

# The scaling probe for the claim window (docs/spike-window-scaling.md). Slow:
# it times 80 optimisations and writes build/probe-window.json, which git ignores.
probe: export
	uv run python scripts/probe_window.py
