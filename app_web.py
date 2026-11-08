import streamlit as st
import datetime
import time
import os
import os.path
import json
import csv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# --- CONFIGURACIÓN BÁSICA ---
st.set_page_config(page_title="Filmmaking Calendar", page_icon="🎬", layout="centered")

SCOPES = ['https://www.googleapis.com/auth/calendar']
TIMEZONE = "America/Costa_Rica"
TZ_SUFFIX = "-06:00"

# --- CONFIGURACIÓN FINANCIERA ---
SUELDO_POR_HORA = 15.00 
MONEDA = "$"

ARCHIVO_REPORTE = 'reporte_tiempos.csv'

# ==========================================
# LÓGICA DE AUTENTICACIÓN CON SECRETS
# ==========================================
@st.cache_resource
def get_calendar_service():
    creds = None
    
    # 1. Intentar cargar credenciales desde los Secrets de Streamlit (Nube)
    if "google_token" in st.secrets:
        creds = Credentials.from_authorized_user_info(st.secrets["google_token"], SCOPES)
        
    # 2. Si no hay secrets, intentar cargar desde el archivo local (Desarrollo)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    # 3. Si las credenciales no son válidas o no existen, iniciar flujo de autorización
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if "google_credentials" in st.secrets:
                creds_info = st.secrets["google_credentials"]
                flow = InstalledAppFlow.from_client_config(creds_info, SCOPES)
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                
            # Usamos run_console porque estamos en la nube y no hay navegador
            creds = flow.run_console()
            
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    return build('calendar', 'v3', credentials=creds)


# ==========================================
# ESTADO DE LA SESIÓN (Memoria de Streamlit)
# ==========================================
if 'service' not in st.session_state:
    try:
        st.session_state.service = get_calendar_service()
    except Exception as e:
        st.error(f"Error de autenticación: {e}")
        st.stop()

if 'tareas_hoy' not in st.session_state:
    st.session_state.tareas_hoy = []
if 'tarea_actual' not in st.session_state:
    st.session_state.tarea_actual = None
if 'inicio_real' not in st.session_state:
    st.session_state.inicio_real = None
if 'pausas' not in st.session_state:
    st.session_state.pausas = datetime.timedelta(0)
if 'inicio_pausa' not in st.session_state:
    st.session_state.inicio_pausa = None
if 'historial' not in st.session_state:
    st.session_state.historial = []

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================
def guardar_en_excel(nombre_tarea, duracion, pausas):
    """Guarda el registro en el archivo CSV."""
    fecha_str = datetime.date.today().strftime('%d/%m/%Y')
    hora_str = datetime.datetime.now().strftime('%H:%M:%S')
    t_efectivo = str(duracion).split('.')[0]
    t_pausa = str(pausas).split('.')[0]
    
    costo = (duracion.total_seconds() / 3600) * SUELDO_POR_HORA
    
    # Verificar si el archivo existe para poner encabezados
    file_exists = os.path.isfile(ARCHIVO_REPORTE)
    with open(ARCHIVO_REPORTE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Fecha", "Hora", "Tarea", "Empleado", "Tiempo Efectivo", "Tiempo en Pausa", "Costo"])
        writer.writerow([fecha_str, hora_str, nombre_tarea, "Jostin", t_efectivo, t_pausa, f"{MONEDA}{costo:.2f}"])

# ==========================================
# INTERFAZ VISUAL (Streamlit)
# ==========================================
st.title("🎬 Filmmaking Calendar")
st.write("Bienvenido, **Jostin**")

# 1. Cargar eventos si no hay
if not st.session_state.tareas_hoy and not st.session_state.tarea_actual:
    if st.button("📅 Cargar Eventos de Hoy", use_container_width=True, type="primary"):
        with st.spinner("Conectando con Google Calendar..."):
            try:
                hoy = datetime.date.today().isoformat()
                events_result = st.session_state.service.events().list(
                    calendarId='primary', timeMin=f"{hoy}T00:00:00{TZ_SUFFIX}", timeMax=f"{hoy}T23:59:59{TZ_SUFFIX}",
                    singleEvents=True, orderBy='startTime').execute()
                
                for ev in events_result.get('items', []):
                    if 'dateTime' in ev['start']:
                        nombre = ev.get('summary', 'Sin título')
                        # Ignorar eventos creados por la app
                        if not nombre.startswith("[APP]"):
                            inicio = datetime.datetime.fromisoformat(ev['start']['dateTime'].replace('Z', '+00:00')).replace(tzinfo=None)
                            st.session_state.tareas_hoy.append({"id": ev['id'], "nombre": nombre, "inicio": inicio})
                st.success(f"Se cargaron {len(st.session_state.tareas_hoy)} tareas.")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Error al cargar eventos: {e}")

st.divider()

# 2. Panel de Control (Trabajando o Seleccionando)
if st.session_state.tarea_actual:
    tarea = st.session_state.tarea_actual
    st.info(f"Trabajando en: **{tarea['nombre']}**")
    
    # Calcular tiempo en vivo
    ahora = datetime.datetime.now()
    tiempo_transcurrido = (ahora - st.session_state.inicio_real) - st.session_state.pausas
    
    # Si está en pausa, mostramos el estado
    if st.session_state.inicio_pausa:
        st.warning("⏸️ Tarea en PAUSA. Tómate tu tiempo.")
        # El tiempo se congela en la pausa
        tiempo_transcurrido = (st.session_state.inicio_pausa - st.session_state.inicio_real) - st.session_state.pausas
    
    st.metric(label="⏱️ Tiempo Efectivo", value=str(tiempo_transcurrido).split('.')[0])
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("⏸️ Pausar", use_container_width=True, disabled=st.session_state.inicio_pausa is not None):
            st.session_state.inicio_pausa = datetime.datetime.now()
            st.rerun()
    
    with col2:
        if st.button("▶️ Reanudar", use_container_width=True, disabled=st.session_state.inicio_pausa is None):
            if st.session_state.inicio_pausa:
                duracion_pausa = datetime.datetime.now() - st.session_state.inicio_pausa
                st.session_state.pausas += duracion_pausa
                st.session_state.inicio_pausa = None
            st.rerun()
    
    with col3:
        if st.button("⏹️ Finalizar", type="primary", use_container_width=True):
            # Guardar datos
            guardar_en_excel(tarea['nombre'], tiempo_transcurrido, st.session_state.pausas)
            
            st.session_state.historial.append({
                "nombre": tarea['nombre'], 
                "tiempo": str(tiempo_transcurrido).split('.')[0],
                "pausas": str(st.session_state.pausas).split('.')[0]
            })
            
            # Limpiar estado
            st.session_state.tarea_actual = None
            st.session_state.inicio_real = None
            st.session_state.pausas = datetime.timedelta(0)
            st.session_state.inicio_pausa = None
            
            st.balloons()
            st.success("¡Tarea guardada exitosamente!")
            time.sleep(1)
            st.rerun()

else:
    # MODO SELECCIÓN DE TAREAS
    st.subheader("Tus tareas pendientes:")
    
    if not st.session_state.tareas_hoy:
        st.warning("No hay tareas cargadas. Presiona 'Cargar Eventos de Hoy'.")
    else:
        for i, t in enumerate(st.session_state.tareas_hoy):
            with st.container(border=True):
                st.write(f"**{t['nombre']}**")
                st.caption(f"Planeado para: {t['inicio'].strftime('%H:%M')}")
                if st.button(f"▶️ Iniciar", key=f"btn_{i}", use_container_width=True):
                    st.session_state.tarea_actual = t
                    st.session_state.inicio_real = datetime.datetime.now()
                    st.session_state.pausas = datetime.timedelta(0)
                    st.session_state.tareas_hoy.pop(i) # Quitarlo de pendientes
                    st.rerun()

# 3. Resumen del día
if st.session_state.historial:
    st.divider()
    st.subheader("📊 Resumen de hoy")
    for h in st.session_state.historial:
        st.write(f"- **{h['nombre']}**: {h['tiempo']} trabajados | {h['pausas']} en pausa")