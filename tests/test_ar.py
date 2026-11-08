import cv2
import numpy as np

from medguiar import schedule
from medguiar.ar import MARKER_DICTIONARY, STATUS_BGR, ARRenderer


def synthetic_marker_frame():
    dictionary = cv2.aruco.getPredefinedDictionary(MARKER_DICTIONARY)
    frame = np.full((480, 640, 3), 255, np.uint8)
    frame[140:340, 220:420] = cv2.cvtColor(cv2.aruco.generateImageMarker(dictionary, 0, 200), cv2.COLOR_GRAY2BGR)
    return frame


def test_no_marker_returns_frame_untouched():
    blank = np.full((480, 640, 3), 255, np.uint8)
    out, found = ARRenderer().render(blank.copy(), {})
    assert not found
    assert np.array_equal(out, blank)


def test_marker_gets_one_coloured_box_per_status():
    meds = {"Lunes": {"paracetamol": True}, "Martes": {"ibuprofeno": False}}
    out, found = ARRenderer().render(synthetic_marker_frame(), meds)
    assert found
    # Boxes are 60 px tall (30 * 200/100) with a 6 px gap, starting 5 px inside the marker's top-left corner
    def colour_of_box(index):
        return tuple(int(c) for c in out[140 + 5 + index * 66 + 8, 220 + 5 + 8])
    assert colour_of_box(0) == STATUS_BGR[schedule.DONE]
    assert colour_of_box(1) == STATUS_BGR[schedule.PENDING]
    assert colour_of_box(2) == STATUS_BGR[schedule.NONE]
