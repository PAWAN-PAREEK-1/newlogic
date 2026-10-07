PYTHON := python3
VENV_DIR := env
VENV_PY := $(VENV_DIR)/bin/python
TEST_NAMES = 0_0_gridlines

ifeq ($(OS),Windows_NT)
	VENV_PY := $(VENV_DIR)\Scripts\python.exe
	ACTIVATE := $(VENV_DIR)\Scripts\activate.bat
else
	ACTIVATE := source $(VENV_DIR)/bin/activate
endif

makeVirtual:
	$(PYTHON) -m venv $(VENV_DIR)

pipInstall: makeVirtual
	$(VENV_PY) -m pip install --upgrade pip

pipPackages: pipInstall
	$(VENV_PY) -m pip install -r requirements.txt

packInstall: pipPackages
	$(VENV_PY) -m pip install -e .

setup: packInstall
	@echo "Virtual environment ready."
	@echo "To activate it, run:"
	@echo "$(ACTIVATE)"


# Games use relative imports, so they are run as modules: make run GAME=0_0_gridlines
run:
	$(VENV_PY) -m games.$(GAME).run

# Replay every published book against the game rules: make verify GAME=0_0_gridlines
verify:
	$(VENV_PY) -m games.$(GAME).verify_books

test:
	$(VENV_PY) -m pytest tests/

test_run:
	@for f in $(TEST_NAMES); do \
		echo "processing $$f"; \
		$(VENV_PY) -m games.$$f.run --sims 2000; \
	done


clean:
	rm -rf env __pycache__ *.pyc
