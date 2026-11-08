"""Webcam reader running in a background thread, so the UI never blocks on read()."""
import threading
import time

import cv2


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
