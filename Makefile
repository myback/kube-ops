.PHONY: build
build: clean
	@hatch build -t wheel

.PHONY: upload
upload: build
	@hatch publish

.PHONY: clean
clean:
	@rm -rf .pytest_cache/ build/ dist/
	@find . -not -path './.venv*' -path '*/__pycache__*' -delete
	@find . -not -path './.venv*' -path '*/*.egg-info*' -delete
