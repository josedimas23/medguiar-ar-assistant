"""Webcam reader running in a background thread, so the UI never blocks on read()."""
import threading
import time

import cv2
import numpy as np


class Camera:
    def __init__(self, index=0, size=(640, 480)):
        # 640x480 is the resolution the AR calibration (camara.py) was made for
        self.index = index
        self.size = size
        self._cap = None
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def start(self):
        """Open the camera if it is not open yet. Returns False if it cannot be opened."""
        if self._running:
            return True
        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            cap.release()
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
        self._cap = cap
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _loop(self):
        while self._running:
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._frame = frame
            else:
                time.sleep(0.05)

    def read(self):
        """Latest frame (a copy), or None if there is none yet."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._cap is not None:
            self._cap.release()
        self._cap = self._thread = self._frame = None


class DemoCamera:
    """Simulated camera for `--demo`: the welcome illustration with a gently moving ArUco marker on top."""

    def __init__(self, size=(640, 480), marker_id=0):
        from .ar import MARKER_DICTIONARY
        from .storage import BASE_DIR

        width, height = size
        background = cv2.imread(str(BASE_DIR / "fondo.jpeg"))
        if background is None:
            background = np.full((height, width, 3), 235, np.uint8)
        # cover-crop the illustration to the camera size
        scale = max(width / background.shape[1], height / background.shape[0])
        background = cv2.resize(background, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        y0 = (background.shape[0] - height) // 2
        x0 = (background.shape[1] - width) // 2
        self.background = cv2.GaussianBlur(background[y0:y0 + height, x0:x0 + width], (0, 0), 1.2)

        marker = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(MARKER_DICTIONARY), marker_id, 200)
        marker = cv2.copyMakeBorder(marker, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
        self.marker = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        self.size = size
        self._start = time.time()

    def start(self):
        return True

    def read(self):
        t = time.time() - self._start
        width, height = self.size
        side = self.marker.shape[0]
        cx, cy = width * 0.5 + 18 * np.sin(t * 0.7), height * 0.3 + 8 * np.sin(t * 0.9)  # room below for the 7 boxes
        half = 80
        tilt = 10 * np.sin(t * 0.5)  # slight perspective, like holding a card
        destination = np.float32([
            [cx - half + tilt, cy - half], [cx + half - tilt, cy - half + 6],
            [cx + half + tilt / 2, cy + half], [cx - half - tilt / 2, cy + half - 6],
        ])
        source = np.float32([[0, 0], [side, 0], [side, side], [0, side]])
        warp = cv2.getPerspectiveTransform(source, destination)
        frame = self.background.copy()
        mask = cv2.warpPerspective(np.full(self.marker.shape[:2], 255, np.uint8), warp, (width, height))
        warped = cv2.warpPerspective(self.marker, warp, (width, height))
        frame[mask > 0] = warped[mask > 0]
        return frame

    def stop(self):
        pass
