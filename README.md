DEPENDECIAS:

    1. Las librerías necesarias para el ejecutable son:

        - cv2 (OpenCV)
        - face_recognition
        - os (incluida en Python)
        - json (incluida en Python)
        - speech_recognition
        - tkinter (incluida en Python)
        - uuid (incluida en Python)
        - numpy
        - Pillow
        - threading (incluida en Python)

        Intalacion necesaria: " pip install opencv-python-headless face-recognition SpeechRecognition numpy Pillow pyinstaller "

    2. Archivo "camara.py" con la camra calibrada
    3. Archivo con el JSON "user.json"
    4. Foto para el fondo llamada "fondo.jpeg"

    5. Por ultimo el ejecutable con todo el codigo fuente "MedGuiAR.py"

        - Para su ejecucion debe poner en terminal en la carpeta:  " /bin/python3 ./MedGuiAR.py " 

ESTRUCTURA FINAL:

    MedGuiAR/
    │
    ├── MedGuiAR.py
    ├── camara.py
    ├── fondo.jpeg
    └── users.json