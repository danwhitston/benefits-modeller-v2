.PHONY: build test

# Catala comes from the local opam switch in _opam/, so every call goes through
# `opam exec`.
CATALA = opam exec -- catala
CLERK = opam exec -- clerk

RULES = $(wildcard rules/*.catala_en)

build:
	$(CLERK) start
	@for f in $(RULES); do $(CATALA) typecheck -I rules $$f || exit 1; done

test:
	$(CLERK) test
	uv run pytest
