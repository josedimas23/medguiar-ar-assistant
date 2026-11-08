import pytest

from medguiar.voice import parse_command


@pytest.mark.parametrize("text, action, day, medication", [
    ("añadir miércoles ibuprofeno", "add", "Miércoles", "ibuprofeno"),
    ("Añade sabado vitamina d", "add", "Sábado", "vitamina d"),
    ("tomado lunes paracetamol", "taken", "Lunes", "paracetamol"),
    ("quitar viernes omeprazol", "remove", "Viernes", "omeprazol"),
    ("consulta", "query", None, None),
    ("quiero salir", "exit", None, None),
    ("hola qué tal", "unknown", None, None),
])
def test_parse_command(text, action, day, medication):
    command = parse_command(text)
    assert (command.action, command.day, command.medication) == (action, day, medication)


@pytest.mark.parametrize("text", ["añadir lunes", "tomado festivo aspirina"])
def test_invalid_commands_explain_the_problem(text):
    command = parse_command(text)
    assert command.action == "invalid"
    assert command.error
