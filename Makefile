# MedGuiAR · arranque en un comando (macOS con Homebrew)
VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: setup run test calibrate clean

## setup: instala dependencias del sistema, crea el entorno virtual e instala las librerías
setup:
	brew install uv cmake portaudio flac
	uv venv --python 3.12 --managed-python $(VENV)
	uv pip install --python $(VENV) -r requirements.txt

## run: lanza la aplicación (prepara el entorno si no existe)
run: $(PY)
	$(PY) MedGuiAR.py

$(PY):
	$(MAKE) setup

## test: ejecuta los tests unitarios (no necesitan cámara ni micrófono)
test: $(PY)
	uv pip install --python $(VENV) -r requirements-dev.txt
	$(PY) -m pytest -q

## calibrate: recalibra la cámara con un tablero ChArUco y regenera camara.py
calibrate: $(PY)
	$(PY) calibrar.py

## clean: borra el entorno virtual
clean:
	rm -rf $(VENV)
