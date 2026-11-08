from medguiar import schedule


def test_normalize_day_accepts_accents_and_case():
    assert schedule.normalize_day("miercoles") == "Miércoles"
    assert schedule.normalize_day("MIÉRCOLES") == "Miércoles"
    assert schedule.normalize_day("sabado") == "Sábado"
    assert schedule.normalize_day("festivo") is None


def test_add_mark_and_remove():
    meds = {}
    assert schedule.day_status(meds, "Lunes") == schedule.NONE
    schedule.add_medication(meds, "Lunes", "Paracetamol")
    assert schedule.day_status(meds, "Lunes") == schedule.PENDING
    assert schedule.set_taken(meds, "Lunes", "paracetamol") == "Paracetamol"  # case-insensitive
    assert schedule.day_status(meds, "Lunes") == schedule.DONE
    assert schedule.set_taken(meds, "Martes", "paracetamol") is None
    assert schedule.remove_medication(meds, "Lunes", "Paracetamol")
    assert meds == {}


def test_add_is_idempotent_and_pending_is_ordered():
    meds = {}
    schedule.add_medication(meds, "Viernes", "omeprazol")
    schedule.add_medication(meds, "Lunes", "ibuprofeno")
    schedule.add_medication(meds, "Lunes", "Ibuprofeno")
    assert meds["Lunes"] == {"ibuprofeno": False}
    assert schedule.pending(meds) == [("Lunes", "ibuprofeno"), ("Viernes", "omeprazol")]
