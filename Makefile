# Convenience delegation — the Python project lives in backend/.
.PHONY: demo test lint dev install
demo test lint dev install:
	$(MAKE) -C backend $@
