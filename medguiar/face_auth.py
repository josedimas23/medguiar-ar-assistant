"""Face login built on face_recognition (dlib)."""
import threading
import warnings

import cv2

warnings.filterwarnings("ignore", message="pkg_resources is deprecated")  # from face_recognition_models
import face_recognition  # noqa: E402
import numpy as np  # noqa: E402

from . import storage  # noqa: E402

TOLERANCE = 0.6  # face_recognition's default distance threshold
_dlib_lock = threading.Lock()  # dlib models are shared between the UI and the recognition thread


def _small_rgb(frame, scale):
    small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
    return cv2.cvtColor(small, cv2.COLOR_BGR2RGB)


def count_faces(frame):
    with _dlib_lock:
        return len(face_recognition.face_locations(_small_rgb(frame, 0.5)))


class FaceAuthenticator:
    def __init__(self, users):
        self.names, self.encodings = [], []
        for user in users:
            try:
                image = face_recognition.load_image_file(storage.photo_path(user))
                with _dlib_lock:
                    encodings = face_recognition.face_encodings(image)
            except (OSError, ValueError):
                continue
            if encodings:
                self.names.append(user["name"])
                self.encodings.append(encodings[0])

    def identify(self, frame, scale=0.5):
        """Faces in the frame as [((top, right, bottom, left), name or None)], in full-frame pixels."""
        rgb = _small_rgb(frame, scale)
        with _dlib_lock:
            locations = face_recognition.face_locations(rgb)
            encodings = face_recognition.face_encodings(rgb, locations)
        results = []
        for location, encoding in zip(locations, encodings):
            name = None
            if self.encodings:
                distances = face_recognition.face_distance(self.encodings, encoding)
                best = int(np.argmin(distances))
                if distances[best] <= TOLERANCE:
                    name = self.names[best]
            box = tuple(int(v / scale) for v in location)
            results.append((box, name))
        return results
