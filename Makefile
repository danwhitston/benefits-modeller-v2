.PHONY: build test export

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

test:
	$(CLERK) test
	$(DUNE) test --root exporter
	uv run pytest

# Writes the UniversalCredit scope as bm-ir JSON (see docs/bm-ir.md).
export: build
	$(DUNE) build --root exporter
	mkdir -p build
	$(CATALA) bm-export --plugin-dir $(PLUGIN_DIR) -I rules \
	  -s UniversalCredit rules/uc.catala_en -o build/uc.bm-ir.json
