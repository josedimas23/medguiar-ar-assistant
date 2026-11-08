"""Spanish voice commands: push-to-talk recording, transcription (Google Web Speech API) and parsing."""
import threading
from dataclasses import dataclass

import speech_recognition as sr

from .schedule import normalize_day

ADD_WORDS = {"añadir", "añade", "agregar", "agrega"}
TAKEN_WORDS = {"tomado", "tomada"}
REMOVE_WORDS = {"quitar", "quita", "borrar", "borra"}
QUERY_WORDS = {"consulta", "consultar"}
EXIT_WORDS = {"salir"}

# (example, description) shown on screen
COMMANDS = [
    ("añadir lunes paracetamol", "Apunta una pastilla"),
    ("tomado lunes paracetamol", "La marca como tomada"),
    ("quitar lunes paracetamol", "La borra"),
    ("consulta", "Te dice lo que te falta"),
    ("salir", "Cierra la sesión"),
]


class VoiceError(Exception):
    """Error with a message that can be shown to the user as-is."""


@dataclass
class Command:
    action: str  # "add" | "taken" | "remove" | "query" | "exit" | "invalid" | "unknown"
    day: str | None = None
    medication: str | None = None
    error: str | None = None


def parse_command(text):
    """Turn a transcription like "añadir miércoles ibuprofeno" into a Command."""
    words = text.lower().split()
    if EXIT_WORDS & set(words):
        return Command("exit")
    if QUERY_WORDS & set(words):
        return Command("query")
    for keywords, action, example in (
        (ADD_WORDS, "add", "añadir lunes paracetamol"),
        (TAKEN_WORDS, "taken", "tomado lunes paracetamol"),
        (REMOVE_WORDS, "remove", "quitar lunes paracetamol"),
    ):
        index = next((i for i, w in enumerate(words) if w in keywords), None)
        if index is None:
            continue
        rest = words[index + 1:]
        if len(rest) < 2:
            return Command("invalid", error=f"Falta el día o la pastilla. Di, por ejemplo: «{example}».")
        day = normalize_day(rest[0])
        if day is None:
            return Command("invalid", error=f"«{rest[0]}» no es un día de la semana.")
        return Command(action, day=day, medication=" ".join(rest[1:]))
    return Command("unknown")


def transcribe(audio):
    try:
        return sr.Recognizer().recognize_google(audio, language="es-ES")
    except sr.UnknownValueError:
        raise VoiceError("No te he entendido. Inténtalo otra vez.") from None
    except sr.RequestError:
        raise VoiceError("No hay conexión con el servicio de voz. Revisa internet.") from None


class PushToTalk:
    """Records from the default microphone between start() and stop(), then transcribes.

    Callbacks run on the recording thread: on_ready() once the microphone is open,
    on_processing() after stop(), and finally on_text(text) or on_error(VoiceError).
    """

    MIN_SECONDS = 0.4
    MAX_SECONDS = 15

    def __init__(self, on_ready, on_processing, on_text, on_error):
        self.on_ready, self.on_processing = on_ready, on_processing
        self.on_text, self.on_error = on_text, on_error
        self._stop = threading.Event()
        self.active = False

    def start(self):
        if self.active:
            return
        self.active = True
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            try:
                with sr.Microphone() as source:
                    self.on_ready()
                    rate, width = source.SAMPLE_RATE, source.SAMPLE_WIDTH
                    max_chunks = int(self.MAX_SECONDS * rate / source.CHUNK)
                    chunks = []
                    while not self._stop.is_set() and len(chunks) < max_chunks:
                        chunks.append(source.stream.read(source.CHUNK))
            except OSError:
                raise VoiceError("No puedo usar el micrófono. Revisa el permiso en Ajustes del Sistema.") from None
            data = b"".join(chunks)
            if len(data) < self.MIN_SECONDS * rate * width:
                raise VoiceError("Mantén pulsado mientras hablas y suelta al terminar.")
            self.on_processing()
            self.on_text(transcribe(sr.AudioData(data, rate, width)))
        except VoiceError as error:
            self.on_error(error)
        finally:
            self.active = False
