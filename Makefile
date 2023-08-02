.PHONY: build
build:
	python -m build -w

.PHONY: upload
upload:
	python -m twine upload dist/*

.PHONY: clean
clean:
	@rm -rf .pytest_cache/ build/ dist/
	@find . -not -path './.venv*' -path '*/__pycache__*' -delete
	@find . -not -path './.venv*' -path '*/*.egg-info*' -delete
