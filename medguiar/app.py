"""Single-window interface: welcome -> face login -> weekly panel with live AR camera."""
import datetime
import queue
import threading
import time
import tkinter

import customtkinter as ctk
import cv2
from PIL import Image

from . import schedule, storage, voice
from .ar import STATUS_HEX, ARRenderer, load_calibration
from .camera import Camera, DemoCamera
from .face_auth import FaceAuthenticator, count_faces

CAMERA_SIZE = (640, 480)
MUTED = "#6B7280"
TEXT = "#111827"
CARD = "#FFFFFF"
BACKGROUND = "#F3F4F6"
PLACEHOLDER = "#E5E7EB"
ACCENT = "#1F6AA5"
TOAST_STYLES = {  # (background, text)
    "ok": ("#E7F6EC", "#1E6B3A"),
    "error": ("#FDECEC", "#A12C2C"),
    "info": ("#E8F0FB", "#1F4E8C"),
}
STATUS_TEXT = {schedule.NONE: "Sin pastillas", schedule.PENDING: "Pendiente", schedule.DONE: "Tomado"}
TALK_KEY = "space"
TALK_IDLE = "Mantén pulsado para hablar"


def demo_user():
    """Example user for --demo: a mix of taken, pending and empty days. Nothing is saved to disk."""
    return {"name": "demo", "photo": "", "medicamentos": {
        "Lunes": {"paracetamol": True},
        "Martes": {"ibuprofeno": False, "vitamina D": True},
        "Jueves": {"omeprazol": True},
        "Viernes": {"paracetamol": False},
    }}


def today():
    return schedule.DAYS[datetime.date.today().weekday()]


def fit(size, box):
    """Largest size with the aspect ratio of `size` that fits inside `box`."""
    scale = min(box[0] / size[0], box[1] / size[1])
    return max(1, int(size[0] * scale)), max(1, int(size[1] * scale))


def to_ctk_image(frame_bgr, box):
    h, w = frame_bgr.shape[:2]
    size = fit((w, h), box)
    frame_bgr = cv2.resize(frame_bgr, size, interpolation=cv2.INTER_AREA)
    image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    return ctk.CTkImage(light_image=image, size=size)


class App(ctk.CTk):
    def __init__(self, demo=False):
        super().__init__(fg_color=BACKGROUND)
        self.demo = demo
        self.title("MedGuiAR")
        self.geometry("1240x800")
        self.minsize(960, 660)
        self.fonts = {
            "title": ctk.CTkFont(size=36, weight="bold"),
            "h1": ctk.CTkFont(size=26, weight="bold"),
            "h2": ctk.CTkFont(size=19, weight="bold"),
            "body": ctk.CTkFont(size=16),
            "bold": ctk.CTkFont(size=16, weight="bold"),
            "small": ctk.CTkFont(size=13),
            "code": ctk.CTkFont(family="Menlo", size=13),
            "button": ctk.CTkFont(size=17, weight="bold"),
        }
        self.camera = DemoCamera(size=CAMERA_SIZE) if demo else Camera(size=CAMERA_SIZE)
        self._events = queue.Queue()
        self.screen = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(50, self._drain_events)
        self.show(WelcomeScreen)

    def call_in_ui(self, fn, *args):
        """Schedule `fn(*args)` on the Tk thread (safe to call from worker threads)."""
        self._events.put((fn, args))

    def _drain_events(self):
        try:
            while not self._events.empty():
                fn, args = self._events.get_nowait()
                fn(*args)
        finally:
            self.after(50, self._drain_events)

    def show(self, screen_cls, **kwargs):
        if self.screen is not None:
            self.screen.close()
            self.screen.destroy()
        self.screen = screen_cls(self, **kwargs)
        self.screen.pack(fill="both", expand=True, padx=28, pady=24)

    def close(self):
        if self.screen is not None:
            self.screen.close()
        self.camera.stop()
        self.destroy()


# ----------------------------------------------------------------------------- base screens

class Screen(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app, fg_color="transparent")
        self.app = app
        self.fonts = app.fonts
        self.alive = True
        self._global_bindings = []

    def post(self, fn, *args):
        """From a worker thread: run fn on the UI thread, only if this screen is still shown."""
        self.app.call_in_ui(lambda: fn(*args) if self.alive else None)

    def bind_global(self, sequence, handler):
        """bind_all that is removed when the screen closes."""
        self.app.bind_all(sequence, handler)
        self._global_bindings.append(sequence)

    def close(self):
        self.alive = False
        for sequence in self._global_bindings:
            self.app.unbind_all(sequence)

    def card(self, parent, **kwargs):
        return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16, **kwargs)

    def secondary_button(self, parent, text, command, **kwargs):
        return ctk.CTkButton(parent, text=text, command=command, height=40, font=self.fonts["bold"],
                             fg_color="transparent", border_width=2, border_color="#D1D5DB",
                             text_color="#374151", hover_color=PLACEHOLDER, **kwargs)

    def enable_trackpad_scroll(self, scrollable):
        """customtkinter only listens to <MouseWheel>; Tk 9 on macOS sends trackpad gestures as <TouchpadScroll>."""
        container = str(scrollable._parent_frame)
        canvas = scrollable._parent_canvas

        def on_scroll(event):
            pointer = self.app.winfo_containing(*self.app.winfo_pointerxy())
            if pointer is None or not str(pointer).startswith(container):
                return
            _dx, dy = (int(v) for v in self.app.tk.splitlist(self.app.tk.call("tk::PreciseScrollDeltas", event.delta)))
            region = canvas.bbox("all")
            if not dy or region is None:
                return
            content_height = region[3] - region[1]
            if content_height <= canvas.winfo_height():
                return
            top, _bottom = canvas.yview()
            canvas.yview_moveto(top - dy / content_height)

        self.bind_global("<TouchpadScroll>", on_scroll)


class CameraScreen(Screen):
    """Screen with a live camera view that fills its area and refreshes ~30 times per second."""

    def build_video(self, parent):
        self.video_area = ctk.CTkFrame(parent, fg_color=PLACEHOLDER, corner_radius=12)
        self.video = ctk.CTkLabel(self.video_area, text="Abriendo la cámara…", font=self.fonts["body"],
                                  text_color=MUTED, fg_color="transparent")
        self.video.place(relx=0.5, rely=0.5, anchor="center")
        self.video_box = CAMERA_SIZE
        self.video_area.bind("<Configure>", self._on_video_resize)
        return self.video_area

    def _on_video_resize(self, event):
        scaling = ctk.ScalingTracker.get_widget_scaling(self)
        self.video_box = (max(160, event.width / scaling - 12), max(120, event.height / scaling - 12))
        self.video.configure(wraplength=int(self.video_box[0] * 0.8))

    def start_video(self):
        if not self.alive:
            return
        if not self.app.camera.start():
            self.video.configure(text="No puedo abrir la cámara.\n\nSi macOS te ha pedido permiso, acéptalo.\n"
                                      "Ajustes del Sistema › Privacidad y seguridad › Cámara.\n\nReintentando…")
            self.after(2000, self.start_video)
            return
        self._tick()

    def _tick(self):
        if not self.alive:
            return
        frame = self.app.camera.read()
        if frame is not None:
            self._image = to_ctk_image(self.render_frame(frame), self.video_box)
            self.video.configure(image=self._image, text="")
        self.after(33, self._tick)

    def render_frame(self, frame):
        return frame


# ----------------------------------------------------------------------------- welcome

class WelcomeScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        app.camera.stop()
        self.grid_columnconfigure(0, weight=5, uniform="cols")
        self.grid_columnconfigure(1, weight=6, uniform="cols")
        self.grid_rowconfigure(0, weight=1)

        text = ctk.CTkFrame(self, fg_color="transparent")
        text.grid(row=0, column=0, sticky="ew", padx=(16, 32))
        ctk.CTkLabel(text, text="MedGuiAR", font=self.fonts["title"]).pack(anchor="w")
        self.intro = ctk.CTkLabel(text, text="Tu pastillero, más fácil: entra con tu cara, apunta tus pastillas "
                                             "y míralas sobre el pastillero con realidad aumentada.",
                                  font=self.fonts["body"], text_color=MUTED, justify="left", wraplength=440)
        self.intro.pack(anchor="w", pady=(6, 28))

        steps = [
            ("1", "Entra mirando a la cámara", "La primera vez te registras en un momento."),
            ("2", "Apunta tus pastillas", "Con botones o manteniendo pulsada la barra espaciadora para hablar."),
            ("3", "Enseña el marcador del pastillero", "Verás cada día en azul, rojo o verde."),
        ]
        self.step_labels = []
        for number, title, subtitle in steps:
            row = ctk.CTkFrame(text, fg_color="transparent")
            row.pack(anchor="w", fill="x", pady=8)
            ctk.CTkLabel(row, text=number, width=40, height=40, corner_radius=20, fg_color=ACCENT,
                         text_color="white", font=self.fonts["bold"]).pack(side="left", anchor="n", padx=(0, 14))
            labels = ctk.CTkFrame(row, fg_color="transparent")
            labels.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(labels, text=title, font=self.fonts["bold"]).pack(anchor="w")
            label = ctk.CTkLabel(labels, text=subtitle, font=self.fonts["small"], text_color=MUTED,
                                 justify="left", wraplength=380)
            label.pack(anchor="w")
            self.step_labels.append(label)

        if app.demo:
            button_text, note = "Entrar en la demo", "Modo demo: cámara simulada y usuario de ejemplo; no se guarda nada."
            enter = lambda: app.show(MainScreen, user=demo_user())  # noqa: E731
        else:
            button_text, note = "Entrar con mi cara", "Necesita cámara, micrófono e internet (para la voz)."
            enter = lambda: app.show(LoginScreen)  # noqa: E731
        ctk.CTkButton(text, text=button_text, height=56, width=300, corner_radius=14,
                      font=self.fonts["button"], command=enter).pack(anchor="w", pady=(32, 8))
        ctk.CTkLabel(text, text=note, font=self.fonts["small"], text_color=MUTED).pack(anchor="w")
        text.bind("<Configure>", self._on_text_resize)

        self.hero_source = None
        background = storage.BASE_DIR / "fondo.jpeg"
        if background.exists():
            self.hero_source = Image.open(background)
            self.hero = ctk.CTkLabel(self, text="", corner_radius=16)
            self.hero.grid(row=0, column=1, sticky="nsew", padx=(0, 16))
            self.hero.bind("<Configure>", self._on_hero_resize)
            self._hero_width = 0

    def _on_text_resize(self, event):
        width = event.width / ctk.ScalingTracker.get_widget_scaling(self)
        self.intro.configure(wraplength=max(260, width - 10))
        for label in self.step_labels:
            label.configure(wraplength=max(200, width - 70))

    def _on_hero_resize(self, event):
        scaling = ctk.ScalingTracker.get_widget_scaling(self)
        box = (event.width / scaling, event.height / scaling)
        size = fit(self.hero_source.size, box)
        if abs(size[0] - self._hero_width) > 8:  # avoid resize loops on tiny changes
            self._hero_width = size[0]
            self._hero_image = ctk.CTkImage(light_image=self.hero_source, size=size)
            self.hero.configure(image=self._hero_image)


# ----------------------------------------------------------------------------- login

class LoginScreen(CameraScreen):
    def __init__(self, app):
        super().__init__(app)
        self.auth = None
        self.faces = []
        self.hits = {}
        self.logging_in = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        video_card = self.card(self)
        video_card.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        self.build_video(video_card).pack(fill="both", expand=True, padx=16, pady=16)

        panel = ctk.CTkScrollableFrame(self, width=360, fg_color=CARD, corner_radius=16)
        panel.grid(row=0, column=1, sticky="ns")
        self.enable_trackpad_scroll(panel)
        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(inner, text="Identificación", font=self.fonts["h1"]).pack(anchor="w")
        self.status = ctk.CTkLabel(inner, text="Preparando el reconocimiento…", font=self.fonts["h2"],
                                   wraplength=320, justify="left")
        self.status.pack(anchor="w", pady=(16, 4))
        self.hint = ctk.CTkLabel(inner, text="", font=self.fonts["body"], text_color=MUTED,
                                 wraplength=320, justify="left")
        self.hint.pack(anchor="w")

        ctk.CTkFrame(inner, height=2, fg_color=PLACEHOLDER).pack(fill="x", pady=24)
        ctk.CTkLabel(inner, text="¿Es tu primera vez?", font=self.fonts["h2"]).pack(anchor="w")
        ctk.CTkLabel(inner, text="Escribe tu nombre, mira a la cámara y pulsa el botón.",
                     font=self.fonts["small"], text_color=MUTED, wraplength=320, justify="left").pack(anchor="w")
        self.name_entry = ctk.CTkEntry(inner, placeholder_text="Tu nombre", height=44, font=self.fonts["body"])
        self.name_entry.pack(fill="x", pady=(12, 8))
        self.name_entry.bind("<Return>", lambda _e: self.register())
        ctk.CTkButton(inner, text="Hacer foto y registrarme", height=44, font=self.fonts["bold"],
                      command=self.register).pack(fill="x")
        self.register_error = ctk.CTkLabel(inner, text="", font=self.fonts["small"],
                                           text_color=TOAST_STYLES["error"][1], wraplength=320, justify="left")
        self.register_error.pack(anchor="w", pady=(6, 0))

        self.secondary_button(inner, "Volver", lambda: app.show(WelcomeScreen)).pack(fill="x", pady=(24, 0))

        self.start_video()
        threading.Thread(target=self._load_users, daemon=True).start()

    # --- background work
    def _load_users(self):
        users = storage.load_users()
        self.post(self._on_users_loaded, FaceAuthenticator(users))

    def _on_users_loaded(self, auth):
        self.auth = auth
        self.status.configure(text="Mírame a la cámara")
        if not auth.names:
            self.hint.configure(text="Todavía no hay nadie registrado. Regístrate aquí abajo.")
        threading.Thread(target=self._recognition_loop, daemon=True).start()

    def _recognition_loop(self):
        while self.alive and not self.logging_in:
            frame = self.app.camera.read()
            if frame is None:
                time.sleep(0.1)
                continue
            self.post(self._on_faces, self.auth.identify(frame))
            time.sleep(0.1)

    def _on_faces(self, faces):
        self.faces = faces
        if self.logging_in:
            return
        known = [name for _box, name in faces if name]
        for name in known:
            self.hits[name] = self.hits.get(name, 0) + 1
            if self.hits[name] >= 2:  # two consecutive matches to avoid false positives
                user = storage.find_user(storage.load_users(), name)
                if user:
                    self.login(user)
                return
        self.hits = {name: n for name, n in self.hits.items() if name in known}
        if not faces:
            self.status.configure(text="Mírame a la cámara")
            if self.auth.names:
                self.hint.configure(text="Colócate de frente y con buena luz.")
        elif not known and self.auth.names:
            self.status.configure(text="No te reconozco")
            self.hint.configure(text="Si es tu primera vez, regístrate aquí abajo.")

    # --- drawing
    def render_frame(self, frame):
        frame = cv2.flip(frame, 1)  # mirror view, like a selfie camera
        width = frame.shape[1]
        for (top, right, bottom, left), name in self.faces:
            left, right = width - right, width - left
            color = (91, 158, 46) if name else (160, 160, 160)
            cv2.rectangle(frame, (left, top), (right, bottom), color, 3)
            label = name or "?"
            (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            cv2.rectangle(frame, (left, bottom), (left + text_w + 16, bottom + text_h + 16), color, -1)
            cv2.putText(frame, label, (left + 8, bottom + text_h + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (255, 255, 255), 2, cv2.LINE_AA)
        return frame

    # --- actions
    def login(self, user):
        self.logging_in = True
        self.status.configure(text=f"¡Hola, {user['name'].capitalize()}!", text_color=TOAST_STYLES["ok"][1])
        self.hint.configure(text="Entrando…")
        self.after(900, lambda: self.app.show(MainScreen, user=user) if self.alive else None)

    def register(self):
        name = self.name_entry.get().strip()
        frame = self.app.camera.read()
        if not name:
            error = "Escribe tu nombre."
        elif storage.find_user(storage.load_users(), name):
            error = f"Ya hay alguien llamado «{name}». Usa otro nombre."
        elif frame is None:
            error = "La cámara todavía no está lista."
        else:
            faces = count_faces(frame)
            error = ("No veo ninguna cara. Mira a la cámara." if faces == 0
                     else "Hay más de una cara. Ponte solo delante de la cámara." if faces > 1 else None)
        if error:
            self.register_error.configure(text=error)
            return
        self.register_error.configure(text="")
        self.login(storage.register_user(name, frame))


# ----------------------------------------------------------------------------- main panel

class MainScreen(CameraScreen):
    def __init__(self, app, user):
        super().__init__(app)
        self.user = user
        self.user.setdefault("medicamentos", {})
        self.meds = self.user["medicamentos"]
        self.ar = ARRenderer(*load_calibration())
        self.marker_found = None
        self._toast_job = None
        self._release_job = None
        self.recorder = voice.PushToTalk(
            on_ready=lambda: self.post(self._on_recording),
            on_processing=lambda: self.post(self._on_processing),
            on_text=lambda text: self.post(self._on_heard, text),
            on_error=lambda error: self.post(self._on_voice_error, str(error)),
        )

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(header, text=f"Hola, {user['name'].capitalize()}", font=self.fonts["h1"]).pack(side="left")
        ctk.CTkLabel(header, text=f"   Hoy es {today().lower()}", font=self.fonts["body"],
                     text_color=MUTED).pack(side="left", pady=(6, 0))
        self.secondary_button(header, "Cerrar sesión", self.logout, width=150).pack(side="right")
        if app.demo:
            ctk.CTkLabel(header, text="Modo demo", font=self.fonts["small"], fg_color="#FEF3C7", text_color="#92400E",
                         corner_radius=8, height=28).pack(side="right", padx=12, ipadx=8)

        # left: AR camera (grows with the window)
        video_card = self.card(self)
        video_card.grid(row=1, column=0, sticky="nsew", padx=(0, 20))
        ctk.CTkLabel(video_card, text="Tu pastillero", font=self.fonts["h2"]).pack(anchor="w", padx=20, pady=(18, 0))
        self.ar_hint = ctk.CTkLabel(video_card, text="", font=self.fonts["body"], text_color=MUTED)
        self.ar_hint.pack(anchor="w", padx=20)
        legend = ctk.CTkFrame(video_card, fg_color="transparent")
        legend.pack(side="bottom", anchor="w", padx=20, pady=(0, 16))
        for status in (schedule.NONE, schedule.PENDING, schedule.DONE):
            ctk.CTkLabel(legend, text="", width=16, height=16, corner_radius=4,
                         fg_color=STATUS_HEX[status]).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(legend, text=STATUS_TEXT[status], font=self.fonts["small"]).pack(side="left", padx=(0, 18))
        self.build_video(video_card).pack(fill="both", expand=True, padx=20, pady=12)

        # right: week, add, voice (scrolls when the window is short)
        self._side_width = 400
        self.side = ctk.CTkScrollableFrame(self, width=self._side_width, fg_color="transparent")
        self.side.grid(row=1, column=1, sticky="ns")
        self.enable_trackpad_scroll(self.side)
        self.app.bind("<Configure>", self._on_window_resize, add="+")

        week_card = self.card(self.side)
        week_card.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(week_card, text="Tu semana", font=self.fonts["h2"]).pack(anchor="w", padx=18, pady=(16, 6))
        self.week = ctk.CTkFrame(week_card, fg_color="transparent")
        self.week.pack(fill="x", padx=18, pady=(0, 14))

        add_card = self.card(self.side)
        add_card.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(add_card, text="Añadir pastilla", font=self.fonts["h2"]).pack(anchor="w", padx=18, pady=(16, 8))
        row = ctk.CTkFrame(add_card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(0, 16))
        self.day_menu = ctk.CTkOptionMenu(row, values=schedule.DAYS, width=124, height=40, font=self.fonts["body"])
        self.day_menu.set(today())
        self.day_menu.pack(side="left")
        self.med_entry = ctk.CTkEntry(row, placeholder_text="Nombre", height=40, font=self.fonts["body"])
        self.med_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.med_entry.bind("<Return>", lambda _e: self.add_from_form())
        ctk.CTkButton(row, text="Añadir", width=76, height=40, font=self.fonts["bold"],
                      command=self.add_from_form).pack(side="left")

        self._build_voice_card(self.side)

        # bottom: feedback
        self.toast = ctk.CTkLabel(self, text="", height=44, corner_radius=12, font=self.fonts["bold"],
                                  fg_color="transparent")
        self.toast.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        self.bind_global(f"<KeyPress-{TALK_KEY}>", self._key_down)
        self.bind_global(f"<KeyRelease-{TALK_KEY}>", self._key_up)

        self.refresh_week()
        self.start_video()

    def _build_voice_card(self, parent):
        card = self.card(parent)
        card.pack(fill="x")
        ctk.CTkLabel(card, text="Hablar con MedGuiAR", font=self.fonts["h2"]).pack(anchor="w", padx=18, pady=(16, 8))
        self.talk_button = ctk.CTkButton(card, text=TALK_IDLE, height=56, corner_radius=28,
                                         font=self.fonts["button"], command=None)
        self.talk_button.pack(fill="x", padx=18)
        self.talk_button.bind("<ButtonPress-1>", lambda _e: self.start_talking())
        self.talk_button.bind("<ButtonRelease-1>", lambda _e: self.stop_talking())
        ctk.CTkLabel(card, text="o mantén pulsada la barra espaciadora", font=self.fonts["small"],
                     text_color=MUTED).pack(pady=(6, 0))
        self.heard = ctk.CTkLabel(card, text="", font=self.fonts["body"], text_color=TEXT,
                                  justify="left", wraplength=340)
        self.heard.pack(anchor="w", padx=18, pady=(8, 0))

        ctk.CTkLabel(card, text="Qué puedes decir", font=self.fonts["bold"]).pack(anchor="w", padx=18, pady=(10, 6))
        commands = ctk.CTkFrame(card, fg_color="transparent")
        commands.pack(fill="x", padx=18, pady=(0, 16))
        commands.grid_columnconfigure(1, weight=1)
        for i, (example, description) in enumerate(voice.COMMANDS):
            ctk.CTkLabel(commands, text=f"«{example}»", font=self.fonts["code"], fg_color=BACKGROUND,
                         corner_radius=6, text_color=TEXT).grid(row=i, column=0, sticky="w", pady=3, ipadx=6)
            ctk.CTkLabel(commands, text=description, font=self.fonts["small"], text_color=MUTED,
                         anchor="w").grid(row=i, column=1, sticky="w", padx=(10, 0))

    def _on_window_resize(self, event):
        if event.widget is not self.app or not self.alive:
            return
        width = event.width / ctk.ScalingTracker.get_window_scaling(self.app)
        side_width = int(min(460, max(340, width * 0.33)))
        if side_width != self._side_width:
            self._side_width = side_width
            self.side.configure(width=side_width)

    # --- camera
    def render_frame(self, frame):
        frame, found = self.ar.render(frame, self.meds)
        if found != self.marker_found:
            self.marker_found = found
            self.ar_hint.configure(text="Marcador detectado: así va tu semana." if found
                                   else "Enseña a la cámara el marcador de tu pastillero.")
        return frame

    # --- week view
    def refresh_week(self):
        for child in self.week.winfo_children():
            child.destroy()
        for day, letter in zip(schedule.DAYS, schedule.DAY_LETTERS):
            status = schedule.day_status(self.meds, day)
            row = ctk.CTkFrame(self.week, fg_color="#EEF4FB" if day == today() else "transparent", corner_radius=10)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=letter, width=34, height=34, corner_radius=8, fg_color=STATUS_HEX[status],
                         text_color="white", font=self.fonts["bold"]).pack(side="left", anchor="n", padx=8, pady=6)
            body = ctk.CTkFrame(row, fg_color="transparent")
            body.pack(side="left", fill="x", expand=True, pady=6)
            title = day + ("  · hoy" if day == today() else "")
            ctk.CTkLabel(body, text=title, font=self.fonts["bold"]).pack(anchor="w")
            meds = self.meds.get(day, {})
            if not meds:
                ctk.CTkLabel(body, text="Sin pastillas", font=self.fonts["small"], text_color=MUTED).pack(anchor="w")
            for med, taken in meds.items():
                med_row = ctk.CTkFrame(body, fg_color="transparent")
                med_row.pack(fill="x")
                box = ctk.CTkCheckBox(med_row, text=med, font=self.fonts["body"], checkbox_width=22,
                                      checkbox_height=22, fg_color=STATUS_HEX[schedule.DONE])
                if taken:
                    box.select()
                box.configure(command=lambda d=day, m=med, b=box: self.toggle(d, m, bool(b.get())))
                box.pack(side="left", pady=2)
                ctk.CTkButton(med_row, text="✕", width=30, height=26, fg_color="transparent", text_color=MUTED,
                              hover_color="#F3D6D6", command=lambda d=day, m=med: self.remove(d, m)
                              ).pack(side="right", padx=6)

    def save(self):
        if not self.app.demo:
            storage.save_medications(self.user)
        self.refresh_week()

    # --- actions (buttons and voice share them)
    def add(self, day, name):
        name = schedule.add_medication(self.meds, day, name)
        self.save()
        self.notify(f"Añadido: {name} el {day.lower()}.", "ok")

    def add_from_form(self):
        name = self.med_entry.get().strip()
        if not name:
            self.notify("Escribe el nombre de la pastilla.", "error")
            return
        self.add(self.day_menu.get(), name)
        self.med_entry.delete(0, "end")

    def toggle(self, day, name, taken):
        schedule.set_taken(self.meds, day, name, taken)
        self.save()
        self.notify(f"{name} ({day.lower()}): {'tomada' if taken else 'pendiente'}.", "ok" if taken else "info")

    def mark_taken(self, day, name):
        stored = schedule.set_taken(self.meds, day, name)
        if stored is None:
            self.notify(f"No tienes «{name}» el {day.lower()}.", "error")
            return
        self.save()
        message = f"Tomada: {stored} el {day.lower()}."
        if schedule.day_status(self.meds, day) == schedule.DONE:
            message += f" ¡Todo listo el {day.lower()}!"
        self.notify(message, "ok")

    def remove(self, day, name):
        if not schedule.remove_medication(self.meds, day, name):
            self.notify(f"No tienes «{name}» el {day.lower()}.", "error")
            return
        self.save()
        self.notify(f"Quitado: {name} del {day.lower()}.", "info")

    def summary(self):
        if not any(self.meds.values()):
            return "No tienes pastillas apuntadas esta semana."
        todo = schedule.pending(self.meds)
        if not todo:
            return "¡Lo has tomado todo esta semana!"
        return "Te falta: " + ", ".join(f"{med} ({day.lower()})" for day, med in todo) + "."

    def logout(self):
        self.app.show(WelcomeScreen)

    # --- push-to-talk
    def _typing(self):
        try:
            return isinstance(self.app.focus_get(), tkinter.Entry)
        except KeyError:  # focus inside a popup menu
            return False

    def _key_down(self, _event):
        if self._typing():
            return None
        self.start_talking()
        return "break"

    def _key_up(self, _event):
        if self._typing():
            return None
        self.stop_talking()
        return "break"

    def start_talking(self):
        if self._release_job:  # key auto-repeat sends release+press pairs while held
            self.after_cancel(self._release_job)
            self._release_job = None
            return
        if self.recorder.active:
            return
        self.talk_button.configure(text="Abriendo el micrófono…", fg_color="#9CA3AF")
        self.heard.configure(text="")
        self.recorder.start()

    def stop_talking(self):
        if self._release_job:
            self.after_cancel(self._release_job)
        self._release_job = self.after(120, self._really_stop)

    def _really_stop(self):
        self._release_job = None
        self.recorder.stop()

    def _on_recording(self):
        if self.recorder.active and not self.recorder._stop.is_set():
            self.talk_button.configure(text="Te escucho… suelta al terminar", fg_color=STATUS_HEX[schedule.PENDING])

    def _on_processing(self):
        self.talk_button.configure(text="Un momento…", fg_color="#9CA3AF")

    def _voice_ready(self):
        self.talk_button.configure(text=TALK_IDLE, fg_color=ACCENT)

    def _on_voice_error(self, message):
        self._voice_ready()
        self.notify(message, "error")

    def _on_heard(self, text):
        self._voice_ready()
        self.heard.configure(text=f"Has dicho: «{text}»")
        command = voice.parse_command(text)
        if command.action == "add":
            self.add(command.day, command.medication)
        elif command.action == "taken":
            self.mark_taken(command.day, command.medication)
        elif command.action == "remove":
            self.remove(command.day, command.medication)
        elif command.action == "query":
            self.notify(self.summary(), "info", seconds=12)
        elif command.action == "exit":
            self.logout()
        elif command.action == "invalid":
            self.notify(command.error, "error")
        else:
            self.notify("No conozco esa orden. Mira la lista «Qué puedes decir».", "error")

    # --- feedback
    def notify(self, message, kind="info", seconds=6):
        background, text = TOAST_STYLES[kind]
        self.toast.configure(text=message, fg_color=background, text_color=text)
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(seconds * 1000, self._clear_toast)

    def _clear_toast(self):
        self._toast_job = None
        if self.alive:
            self.toast.configure(text="", fg_color="transparent")

    def close(self):
        self.recorder.stop()
        super().close()


def main(demo=False):
    ctk.set_appearance_mode("light")
    App(demo=demo).mainloop()
