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

SUELDO_POR_HORA = 15.00 
MONEDA = "$"

ARCHIVO_REPORTE = 'reporte_tiempos.csv'

# ==========================================
# LÓGICA DE AUTENTICACIÓN (Adaptada para Cliente Web)
# ==========================================
@st.cache_resource
def get_calendar_service():
    creds = None
    
    # 1. Si ya tenemos el token guardado en secrets (usuario ya autorizó)
    if "google_token" in st.secrets:
        creds = Credentials.from_authorized_user_info(st.secrets["google_token"], SCOPES)
    
    # 2. Si no, usamos el flujo web
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if "google_credentials" in st.secrets:
                creds_info = st.secrets["google_credentials"]
                
                # IMPORTANTE: Forzamos el tipo a 'web' en el diccionario para evitar errores
                if "installed" in creds_info:
                    creds_info["web"] = creds_info.pop("installed")
                
                flow = InstalledAppFlow.from_client_config(creds_info, SCOPES)
                
                # URL de redireccionamiento EXACTA
                REDIRECT_URI = "https://filmmaking-calendar-app.streamlit.app/" 
                flow.redirect_uri = REDIRECT_URI
                
                auth_url, _ = flow.authorization_url(prompt='consent')
                
                st.warning("⚠️ Necesitas autorizar el acceso a tu Google Calendar para continuar.")
                st.markdown(f"👉 **[Haz clic aquí para autorizar con Google]({auth_url})**")
                st.info("Después de autorizar, serás redirigido a la app. Copia el código de la URL (la parte después de '?code=') y pégalo abajo.")
                
                code = st.text_input("Pega el código de autorización aquí:")
                
                if st.button("Conectar cuenta de Google") and code:
                    try:
                        flow.fetch_token(code=code)
                        creds = flow.credentials
                        
                        # Guardamos el token
                        with open('token.json', 'w') as token:
                            token.write(creds.to_json())
                            
                        st.success("¡Autenticación exitosa! Recargando...")
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al autenticar: {e}")
                        return None
            else:
                # Flujo local
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
                
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    if not creds:
        return None
        
    return build('calendar', 'v3', credentials=creds)

# Inicializar servicio
if 'service' not in st.session_state:
    try:
        service = get_calendar_service()
        if service:
            st.session_state.service = service
        else:
            st.stop()
    except Exception as e:
        st.error(f"Error de inicialización: {e}")
        st.stop()

# ==========================================
# ESTADO DE LA SESIÓN
# ==========================================
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
    fecha_str = datetime.date.today().strftime('%d/%m/%Y')
    hora_str = datetime.datetime.now().strftime('%H:%M:%S')
    t_efectivo = str(duracion).split('.')[0]
    t_pausa = str(pausas).split('.')[0]
    
    costo = (duracion.total_seconds() / 3600) * SUELDO_POR_HORA
    
    file_exists = os.path.isfile(ARCHIVO_REPORTE)
    with open(ARCHIVO_REPORTE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Fecha", "Hora", "Tarea", "Empleado", "Tiempo Efectivo", "Tiempo en Pausa", "Costo"])
        writer.writerow([fecha_str, hora_str, nombre_tarea, "Jostin", t_efectivo, t_pausa, f"{MONEDA}{costo:.2f}"])

# ==========================================
# INTERFAZ VISUAL
# ==========================================
st.title("🎬 Filmmaking Calendar")
st.write("Bienvenido, **Jostin**")

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
                        if not nombre.startswith("[APP]"):
                            inicio = datetime.datetime.fromisoformat(ev['start']['dateTime'].replace('Z', '+00:00')).replace(tzinfo=None)
                            st.session_state.tareas_hoy.append({"id": ev['id'], "nombre": nombre, "inicio": inicio})
                st.success(f"Se cargaron {len(st.session_state.tareas_hoy)} tareas.")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Error al cargar eventos: {e}")

st.divider()

if st.session_state.tarea_actual:
    tarea = st.session_state.tarea_actual
    st.info(f"Trabajando en: **{tarea['nombre']}**")
    
    ahora = datetime.datetime.now()
    tiempo_transcurrido = (ahora - st.session_state.inicio_real) - st.session_state.pausas
    
    if st.session_state.inicio_pausa:
        st.warning("⏸️ Tarea en PAUSA. Tómate tu tiempo.")
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
            guardar_en_excel(tarea['nombre'], tiempo_transcurrido, st.session_state.pausas)
            
            st.session_state.historial.append({
                "nombre": tarea['nombre'], 
                "tiempo": str(tiempo_transcurrido).split('.')[0],
                "pausas": str(st.session_state.pausas).split('.')[0]
            })
            
            st.session_state.tarea_actual = None
            st.session_state.inicio_real = None
            st.session_state.pausas = datetime.timedelta(0)
            st.session_state.inicio_pausa = None
            
            st.balloons()
            st.success("¡Tarea guardada exitosamente!")
            time.sleep(1)
            st.rerun()

else:
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
                    st.session_state.tareas_hoy.pop(i)
                    st.rerun()

if st.session_state.historial:
    st.divider()
    st.subheader("📊 Resumen de hoy")
    for h in st.session_state.historial:
        st.write(f"- **{h['nombre']}**: {h['tiempo']} trabajados | {h['pausas']} en pausa")