# Maintainer workflow. Installers never run this — they run the skill.
#
#   make template SRC=~/path/to/ae-command-center.html
#       regenerate the shareable template from a personal artifact
#   make check
#       run the gates: PII scan, test build, syntax check
#   make clean

SKILL := plugins/command-center/skills/command-center
TMPL  := $(SKILL)/template/index.html.tmpl
EX    := $(SKILL)/reference/config.example.json
TEST  := build/test-index.html

.PHONY: template check clean

template:
ifndef SRC
	$(error SRC is required: make template SRC=path/to/ae-command-center.html)
endif
	@mkdir -p $(SKILL)/template
	python3 $(SKILL)/scripts/parameterize.py "$(SRC)" -o $(TMPL)
	python3 $(SKILL)/scripts/deidentify.py $(TMPL)
	@echo
	@echo "Template regenerated. Read the diff before committing:"
	@echo "  git diff -- $(TMPL)"
	@echo "Then: make check"

check:
	@echo "== PII gate =="
	@python3 $(SKILL)/scripts/scan_pii.py $(TMPL)
	@echo
	@echo "== test build =="
	@mkdir -p build
	@python3 $(SKILL)/scripts/build.py --template $(TMPL) --config $(EX) --out $(TEST)
	@echo
	@echo "== syntax gate =="
	@$(SKILL)/scripts/check_syntax.sh $(TEST)
	@echo
	@echo "All gates passed. Safe to commit the template."

clean:
	rm -rf build
