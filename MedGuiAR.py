import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")  # aviso de face_recognition_models

import cv2
import face_recognition
import os
import json
import speech_recognition as sr
from tkinter import Tk, simpledialog, Canvas, Button
import uuid
import unicodedata
import numpy as np
from PIL import Image, ImageTk
import threading


DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# Devuelve el día de la semana tal y como se guarda (con tildes), aceptando "miercoles" o "miércoles"
def normalizar_dia(palabra):
    def sin_tildes(texto):
        return ''.join(c for c in unicodedata.normalize('NFD', texto.lower()) if unicodedata.category(c) != 'Mn')
    return next((dia for dia in DIAS_SEMANA if sin_tildes(dia) == sin_tildes(palabra)), None)


# Función para guardar la imagen del usuario
def save_user_image(frame):
    
    filename = os.path.join('imagenes', f"{uuid.uuid4()}.jpg")
    cv2.imwrite(filename, frame)
    return filename

# Cargar usuarios desde el archivo JSON
def load_users():
    
    if os.path.exists('users.json'):
        try:
            with open('users.json', 'r') as file:
                data = file.read()
                if data.strip():
                    return json.loads(data)['users']
                else:
                    return []
        except json.JSONDecodeError:
            return []
    return []

# Guardar usuarios en el archivo JSON
def save_users(users):
    
    with open('users.json', 'w') as file:
        json.dump({'users': users}, file, indent=4)

# Función para registrar un nuevo usuario
def register_user(frame):
    
    if not os.path.exists('imagenes'):
        os.makedirs('imagenes')
        
    root = Tk()
    root.withdraw()
    user_name = simpledialog.askstring("Autenticación","Introduce tu nombre:")
    root.destroy()

    image_path = save_user_image(frame)
    
    new_user = {
        "name": user_name,
        "photo": image_path,
        'medicamentos': {}  # Aquí irán los medicamentos del usuario
    }
    
    users = load_users()
    users.append(new_user)
    save_users(users)
    
    return new_user

# Función para autenticar al usuario mediante reconocimiento facial
def authenticate_user():
    
    #cargar usuarios y abre un diccionario para los usuarios conocidos
    users = load_users()
    known_encodings = {}
    
    for user in users:
        try:
            
            #cargando para cada usuario su imagen y encoding facial
            image = face_recognition.load_image_file(user['photo'])
            encodings = face_recognition.face_encodings(image)
            
            if encodings:
                known_encodings[user['name']] = encodings[0]
            else:
                print(f"No se detectó ninguna cara en la imagen del usuario {user['name']}.")
                
        except Exception as e:
            print(f"Error al procesar la imagen del usuario {user['name']}: {e}")

    video_capture = cv2.VideoCapture(0)
    frame_counter = 0 #contador de frames
    user_authenticated = None #nombres de usuario

    while True:
        
        ret, frame = video_capture.read() #lee el frame
        
        if not ret:
            break

        resized_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25) #redimensiona el frame para ir mas rapido

        if frame_counter % 10 == 0: #procesa cada 10 frames
            
            face_locations = face_recognition.face_locations(resized_frame) # busca las caras en el frame redimensionado
            face_encodings = face_recognition.face_encodings(resized_frame, face_locations) # obtiene el encoding facial de la cara que detecte
            
            #compara los encoding para almacenar nombre
            for encoding in face_encodings:
                for name, known_encoding in known_encodings.items():
                    
                    match = face_recognition.compare_faces([known_encoding], encoding)
                    
                    if match[0]:
                        user_authenticated = name
                        break
                    
                if user_authenticated:
                    break
        
        #aumenta el contador y muestra el frame
        frame_counter += 1
        cv2.imshow('Video', frame)

        #salir del bucle
        if cv2.waitKey(1) & 0xFF == ord('f'):
            break

    video_capture.release()
    cv2.destroyAllWindows()
    
    authenticated_user = next((u for u in users if u['name'] == user_authenticated), None)
    
    if authenticated_user:
        if 'medicamentos' not in authenticated_user:
            authenticated_user['medicamentos'] = {}

    #si no se autentico ningun usuario, lo registra
    if not user_authenticated:
        if frame is None:  # la cámara no devolvió imagen (p. ej. sin permiso)
            print("No se pudo obtener imagen de la cámara")
            return None
        new_user = register_user(frame)
        print(f"Usuario registrado: {new_user['name']}")
        return new_user
            
    return authenticated_user

#----------------------------------------------------------------------------------------------------------------------------------------------------
# Función para interactuar con el usuario mediante comandos de voz
def voice_control(user):

    def guardar_medicamentos():
        users = load_users()
        for u in users:
            if u['name'] == user['name']:
                u['medicamentos'] = medicamentos
                break
        save_users(users)

    def consulta_medicamentos():
        print("Consulta de medicamentos:")
        for day, meds in medicamentos.items():
            print(f"{day}: {', '.join(meds.keys())}")
        return medicamentos
    
    def añadir_medicamento(command):
        try:
            parts = command.split()
            day = normalizar_dia(parts[1])
            med = parts[2]
            if day:
                if day not in medicamentos:
                    medicamentos[day] = {}
                medicamentos[day][med] = False
                guardar_medicamentos()
                print(f"Medicamento {med} añadido para el {day}.")
            else:
                print("Día inválido. Usa un día de la semana en español.")
        except IndexError:
            print("Formato incorrecto. Usa 'añadir [día] [medicamento]'.")

    def marcar_tomado(command):
        try:
            parts = command.split()
            day = normalizar_dia(parts[1])
            med = parts[2]
            if day:
                if day in medicamentos and med in medicamentos[day]:
                    medicamentos[day][med] = True
                    if all(medicamentos[day].values()):
                        print(f"Todos los medicamentos del {day} han sido tomados.")
                    guardar_medicamentos()
                    print(f"Medicamento {med} marcado como tomado para el {day}.")
                else:
                    print(f"No se encontró el medicamento {med} para el {day}.")
            else:
                print("Día inválido. Usa un día de la semana en español.")
        except IndexError:
            print("Formato incorrecto. Usa 'tomado [día] [medicamento]'.")

    medicamentos = user.get('medicamentos', {})
    
    recognizer = sr.Recognizer()
    MIC_INDEX = None  # micrófono predeterminado del sistema
    
    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        print("Microphone with name \"{1}\" found for `Microphone(device_index={0})`".format(index, name))
        
    with sr.Microphone(device_index=MIC_INDEX) as source:
        recognizer.adjust_for_ambient_noise(source)
        while True:
            print("Esperando comando de voz...")
            audio = recognizer.listen(source)
            try:
                command = recognizer.recognize_google(audio, language='es-ES')
                print(f"Comando recibido: {command}")
                if "salir" in command.lower():
                    break
                elif "consulta" in command:
                    consulta_medicamentos()
                elif "añadir" in command:
                    añadir_medicamento(command)
                elif "tomado" in command:
                    marcar_tomado(command)
            except sr.UnknownValueError:
                print("No se entendió el comando. Intente nuevamente.")
            except sr.RequestError as e:
                print(f"Error en el servicio de reconocimiento de voz: {e}")

#----------------------------------------------------------------------------------------------------------------------------------------------------

# Función para mostrar las letras representativas de los días de la semana encima de los marcadores ArUco

def mostrar_dias(frame, corners, user):
    dias_semana = ["L", "M", "X", "J", "V", "S", "D"]
    base_box_size = 30
    gap = 6
    meds = user.get('medicamentos', {})
    dias_modificados = set(meds.keys())

    for i, corner in enumerate(corners):
        # Obtener las coordenadas del marcador ArUco
        corner = corner[0]
        top_left = corner[0]
        top_right = corner[1]
        bottom_right = corner[2]
        bottom_left = corner[3]

        # Calcular la matriz de transformación de perspectiva
        width = int(np.linalg.norm(top_right - top_left))
        height = int(np.linalg.norm(top_left - bottom_left))
        pts1 = np.array([top_left, top_right, bottom_right, bottom_left], dtype='float32')
        pts2 = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype='float32')
        M = cv2.getPerspectiveTransform(pts2, pts1)

        # Ajustar el tamaño de la caja basado en la distancia del marcador
        scale_factor = width / 100.0  # Ajusta este valor según sea necesario para tu aplicación
        box_size = int(base_box_size * scale_factor)

        for j, day_letter in enumerate(dias_semana):
            # Posicionar cada día de la semana de acuerdo a la posición y tamaño del marcador
            start_x = 5
            start_y = 5 + j * (box_size + gap)
            end_x = start_x + box_size
            end_y = start_y + box_size

            pts_day = np.array([[start_x, start_y], [end_x, start_y], [end_x, end_y], [start_x, end_y]], dtype='float32')
            transformed_pts = cv2.perspectiveTransform(np.array([pts_day]), M)[0].astype(int)

            color = (255, 0, 0)  # Azul por defecto
            day = DIAS_SEMANA[j]
            if day in dias_modificados:
                if all(meds[day].values()):  # Si todos los medicamentos han sido tomados
                    color = (0, 255, 0)  # Verde
                else:
                    color = (0, 0, 255)  # Rojo

            cv2.fillPoly(frame, [transformed_pts], color)
            
            # Dibujar las letras directamente sobre el cuadro transformado
            center_x = (transformed_pts[0][0] + transformed_pts[2][0]) // 2
            center_y = (transformed_pts[0][1] + transformed_pts[2][1]) // 2

            text_size = cv2.getTextSize(day_letter, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            text_x = center_x - text_size[0] // 2
            text_y = center_y + text_size[1] // 2

            cv2.putText(frame, day_letter, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
    return frame

# Función para manejar la realidad aumentada con marcadores Aruco
def augmented_reality_control(user):
    import camara  
    
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_50)
    parametros = cv2.aruco.DetectorParameters()
    cap = cv2.VideoCapture(0)
    
    if cap.isOpened():
        hframe = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        wframe = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

        matrix, roi = cv2.getOptimalNewCameraMatrix(camara.cameraMatrix, camara.distCoeffs, (wframe, hframe), 1, (wframe, hframe))
        roi_x, roi_y, roi_w, roi_h = roi

        while True:
            ret, frame = cap.read()
            if ret:
                framerectificado = cv2.undistort(frame, camara.cameraMatrix, camara.distCoeffs, None, matrix)
                framerecortado = framerectificado[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]

                corners, ids, _ = cv2.aruco.detectMarkers(framerecortado, aruco_dict, parameters=parametros)

                if ids is not None:
                    cv2.aruco.drawDetectedMarkers(frame, corners, ids)
                    frame = mostrar_dias(frame, corners, user)

            cv2.imshow('Realidad Aumentada', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    else:
        print("No se pudo acceder a la cámara")

    cap.release()
    cv2.destroyAllWindows()


#----------------------------------------------------------------------------------------------------------------------------------------------------


# Función principal que ejecuta la aplicación
def main():
    user = authenticate_user()
    if user:
        print(f"Usuario autenticado: {user['name']}")
        voice_thread = threading.Thread(target=voice_control, args=(user,))
        voice_thread.start()
        augmented_reality_control(user)
    else:
        print("Usuario no registrado")


#INTERFAZ GRAFICA

window = Tk()
window.title("MedGuiAR")
window.geometry("800x600")
window.resizable(True, True)

# Crear un Canvas para gestionar el fondo
canvas = Canvas(window, width=800, height=600)
canvas.pack(fill="both", expand=True)

# Fondo
fondo = Image.open('fondo.jpeg')
fondo = fondo.resize((800, 600), Image.LANCZOS)
fondo = ImageTk.PhotoImage(fondo)
canvas.create_image(0, 0, image=fondo, anchor="nw")

# Botón de inicio: cierra la ventana y arranca la app fuera del bucle de Tk
# (en macOS, abrir ventanas de OpenCV dentro de un callback de Tk hace que Python aborte)
iniciar = False

def on_iniciar():
    global iniciar
    iniciar = True
    window.quit()

boton = Button(window, text="Iniciar", command=on_iniciar, bg='black', fg='white', font=("Arial", 14), width=15, height=1)
boton.place(relx=0.5, rely=0.75, anchor='center')

window.mainloop()
window.destroy()

if iniciar:
    main()
