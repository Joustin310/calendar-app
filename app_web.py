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
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURACIÓN BÁSICA ---
st.set_page_config(page_title="Tezeline Studios", page_icon="🎬", layout="centered")

# Refrescar la página cada 1000 milisegundos (1 segundo) si hay una tarea activa
if 'tarea_actual' in st.session_state and st.session_state.tarea_actual is not None:
    st_autorefresh(interval=1000, limit=None, key="reloj")

SCOPES = ['https://www.googleapis.com/auth/calendar']
TIMEZONE = "America/Costa_Rica"
TZ_SUFFIX = "-06:00"

SUELDO_POR_HORA = 15.00 
MONEDA = "$"

ARCHIVO_REPORTE = 'reporte_tiempos.csv'
ARCHIVO_ESTADO = 'estado_actual.json' # Archivo para no perder el progreso

# ==========================================
# CONFIGURACIÓN DE CALENDARIOS
# ==========================================
CALENDARIO_PRINCIPAL = 'primary'
CALENDARIO_CREATIVO = '7ec5c5ed4ea023b1fdb672dfd360b9065e696d873e737f289b594aebebfc6915@group.calendar.google.com'
CALENDARIO_COMERCIO = '98669128df62f69a9b30417192dd2fc78f480913a55f7a5f01d9725daf0a528e@group.calendar.google.com'

CALENDARIOS_A_LEER = [CALENDARIO_PRINCIPAL, CALENDARIO_CREATIVO, CALENDARIO_COMERCIO]

COLORES_GOOGLE = {
    "1": "🔵", "2": "🟢", "3": "🟣", "4": "🔴",
    "5": "🟡", "6": "🟠", "7": "🩵", "8": "⚪",
    "9": "🔷", "10": "🟩", "11": "🟥"
}

# ==========================================
# LÓGICA DE AUTENTICACIÓN
# ==========================================
def get_calendar_service():
    creds = None
    if "google_token" in st.secrets:
        token_raw = st.secrets["google_token"]
        if isinstance(token_raw, str):
            token_raw = json.loads(token_raw)
        creds = Credentials.from_authorized_user_info(token_raw, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if "google_credentials" in st.secrets:
                creds_info_raw = st.secrets["google_credentials"]
                if isinstance(creds_info_raw, str):
                    creds_info = json.loads(creds_info_raw)
                else:
                    creds_info = creds_info_raw
                
                if "installed" in creds_info:
                    creds_info["web"] = creds_info.pop("installed")
                
                flow = InstalledAppFlow.from_client_config(creds_info, SCOPES)
                REDIRECT_URI = "https://filmmaking-calendar-app.streamlit.app/" 
                flow.redirect_uri = REDIRECT_URI
                
                auth_url, _ = flow.authorization_url(prompt='consent')
                
                st.warning("⚠️ Necesitas autorizar el acceso a tu Google Calendar para continuar.")
                st.markdown(f"👉 **[Haz clic aquí para autorizar con Google]({auth_url})**")
                
                code = st.text_input("Pega el código de autorización aquí:")
                
                if st.button("Conectar cuenta de Google") and code:
                    try:
                        flow.fetch_token(code=code)
                        creds = flow.credentials
                        with open('token.json', 'w') as token:
                            token.write(creds.to_json())
                        st.success("¡Autenticación exitosa! Recargando...")
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al autenticar: {e}")
                        return None
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
                
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    if not creds:
        return None
        
    return build('calendar', 'v3', credentials=creds)

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
# GESTIÓN DE ESTADO PERSISTENTE
# ==========================================
def guardar_estado():
    """Guarda la tarea actual en un archivo JSON para que no se pierda al recargar."""
    estado = {
        "tarea_actual": st.session_state.tarea_actual,
        "inicio_real": st.session_state.inicio_real.isoformat() if st.session_state.inicio_real else None,
        "pausas_segundos": st.session_state.pausas.total_seconds(),
        "inicio_pausa": st.session_state.inicio_pausa.isoformat() if st.session_state.inicio_pausa else None
    }
    with open(ARCHIVO_ESTADO, 'w') as f:
        json.dump(estado, f)

def cargar_estado():
    """Intenta recuperar el estado si la app se cerró por accidente."""
    if os.path.exists(ARCHIVO_ESTADO):
        with open(ARCHIVO_ESTADO, 'r') as f:
            try:
                estado = json.load(f)
                if estado.get('tarea_actual'):
                    st.session_state.tarea_actual = estado['tarea_actual']
                    st.session_state.inicio_real = datetime.datetime.fromisoformat(estado['inicio_real']) if estado['inicio_real'] else None
                    st.session_state.pausas = datetime.timedelta(seconds=estado['pausas_segundos'])
                    st.session_state.inicio_pausa = datetime.datetime.fromisoformat(estado['inicio_pausa']) if estado['inicio_pausa'] else None
                    return True
            except Exception:
                pass
    return False

def limpiar_estado():
    """Limpia el estado cuando se termina una tarea."""
    if os.path.exists(ARCHIVO_ESTADO):
        os.remove(ARCHIVO_ESTADO)

# Inicializar variables en session_state
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

# Al arrancar la app por primera vez, intentamos cargar el estado anterior
if 'estado_cargado' not in st.session_state:
    cargar_estado()
    st.session_state.estado_cargado = True

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

def iniciar_tarea(t):
    st.session_state.tarea_actual = t
    st.session_state.inicio_real = datetime.datetime.now()
    st.session_state.pausas = datetime.timedelta(0)
    st.session_state.inicio_pausa = None
    guardar_estado()
    st.rerun()

# ==========================================
# INTERFAZ VISUAL
# ==========================================
st.title("🎬 Tezeline Studios")
st.write("Bienvenidos a **Tezeline Studios**")

hoy_inicio = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
hoy_fin = hoy_inicio + datetime.timedelta(days=1)

if not st.session_state.tareas_hoy and not st.session_state.tarea_actual:
    if st.button("📅 Cargar Eventos de Hoy", use_container_width=True, type="primary"):
        with st.spinner("Conectando con todos los calendarios..."):
            try:
                todos_los_eventos = []
                for cal_id in CALENDARIOS_A_LEER:
                    if "PEGA_AQUI" in cal_id: continue
                    try:
                        events_result = st.session_state.service.events().list(
                            calendarId=cal_id, 
                            timeMin=hoy_inicio.isoformat() + TZ_SUFFIX, 
                            timeMax=hoy_fin.isoformat() + TZ_SUFFIX,
                            singleEvents=True, 
                            orderBy='startTime'
                        ).execute()
                        
                        for ev in events_result.get('items', []):
                            if 'dateTime' in ev['start']:
                                nombre = ev.get('summary', 'Sin título')
                                if not nombre.startswith("[APP]"):
                                    inicio = datetime.datetime.fromisoformat(ev['start']['dateTime'].replace('Z', '+00:00')).replace(tzinfo=None)
                                    color_id = ev.get('colorId', '1') 
                                    todos_los_eventos.append({
                                        "id": ev['id'], "nombre": nombre, "inicio": inicio, "color": color_id
                                    })
                    except Exception as e:
                        pass
                
                todos_los_eventos.sort(key=lambda x: x['inicio'])
                st.session_state.tareas_hoy = todos_los_eventos
                st.rerun()
            except Exception as e:
                st.error(f"Error general: {e}")

st.divider()

if st.session_state.tarea_actual:
    tarea = st.session_state.tarea_actual
    color_emoji = COLORES_GOOGLE.get(tarea.get('color', '1'), "⚪")
    
    st.info(f"Trabajando en: {color_emoji} **{tarea['nombre']}**")
    
    ahora = datetime.datetime.now()
    
    # Lógica de tiempo
    if st.session_state.inicio_pausa:
        tiempo_transcurrido = (st.session_state.inicio_pausa - st.session_state.inicio_real) - st.session_state.pausas
        st.warning("⏸️ Tarea en PAUSA. Tómate tu tiempo.")
    else:
        tiempo_transcurrido = (ahora - st.session_state.inicio_real) - st.session_state.pausas
    
    st.metric(label="⏱️ Tiempo Efectivo", value=str(tiempo_transcurrido).split('.')[0])
    
    # Sección para ajustar/borrar tiempo (por si se olvidaron marcar)
    with st.expander("🛠️ Ajustar tiempo manualmente (Error de registro)"):
        st.write("Si te olvidaste de marcar el inicio, puedes ajustar el reloj aquí.")
        mins_ajuste = st.number_input("Minutos a sumar/restar (usa negativos para restar):", value=0, step=1)
        if st.button("Aplicar ajuste"):
            if st.session_state.inicio_pausa:
                st.session_state.inicio_pausa -= datetime.timedelta(minutes=mins_ajuste)
            else:
                st.session_state.inicio_real -= datetime.timedelta(minutes=mins_ajuste)
            guardar_estado()
            st.success(f"Se ajustaron {mins_ajuste} minutos.")
            time.sleep(1)
            st.rerun()

    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("⏸️ Pausar", use_container_width=True, disabled=st.session_state.inicio_pausa is not None):
            st.session_state.inicio_pausa = datetime.datetime.now()
            guardar_estado()
            st.rerun()
    
    with col2:
        if st.button("▶️ Reanudar", use_container_width=True, disabled=st.session_state.inicio_pausa is None):
            if st.session_state.inicio_pausa:
                duracion_pausa = datetime.datetime.now() - st.session_state.inicio_pausa
                st.session_state.pausas += duracion_pausa
                st.session_state.inicio_pausa = None
            guardar_estado()
            st.rerun()
    
    with col3:
        if st.button("⏹️ Finalizar", type="primary", use_container_width=True):
            guardar_en_excel(tarea['nombre'], tiempo_transcurrido, st.session_state.pausas)
            st.session_state.historial.append({"nombre": tarea['nombre'], "tiempo": str(tiempo_transcurrido).split('.')[0]})
            
            # Limpiar todo
            st.session_state.tarea_actual = None
            st.session_state.inicio_real = None
            st.session_state.pausas = datetime.timedelta(0)
            st.session_state.inicio_pausa = None
            limpiar_estado() # Borramos el archivo de guardado
            
            st.balloons()
            st.success("¡Tarea guardada exitosamente!")
            time.sleep(1)
            st.rerun()

else:
    if st.session_state.tareas_hoy:
        ahora = datetime.datetime.now()
        
        # --- LÓGICA DEL SIGUIENTE EVENTO Y ATRASADOS ---
        proximos_eventos = [t for t in st.session_state.tareas_hoy if t['inicio'] >= ahora]
        
        if proximos_eventos:
            siguiente_evento = proximos_eventos[0]
            color_emoji = COLORES_GOOGLE.get(siguiente_evento.get('color', '1'), "⚪")
            
            st.subheader("🔔 Siguiente evento planeado:")
            with st.container(border=True):
                st.markdown(f"### {color_emoji} {siguiente_evento['nombre']}")
                st.write(f"⏰ Programado para las: **{siguiente_evento['inicio'].strftime('%H:%M')}**")
                if st.button(f"▶️ Iniciar Ahora", type="primary", use_container_width=True):
                    iniciar_tarea(siguiente_evento)
        else:
            st.info("🎉 No hay más eventos próximos para hoy.")

        st.divider()

        st.subheader("📋 Todas tus tareas de hoy:")
        
        for i, t in enumerate(st.session_state.tareas_hoy):
            color_emoji = COLORES_GOOGLE.get(t.get('color', '1'), "⚪")
            
            # Comprobar si está atrasado (si su hora de inicio ya pasó)
            esta_atrasado = ahora > t['inicio']
            
            with st.container(border=True):
                if esta_atrasado:
                    st.error(f"⚠️ ATRASADO - {color_emoji} **{t['nombre']}**")
                else:
                    st.markdown(f"**{color_emoji} {t['nombre']}**")
                    
                st.caption(f"Planeado para: {t['inicio'].strftime('%H:%M')}")
                
                # Botón de iniciar
                if st.button(f"▶️ Iniciar", key=f"btn_{i}", use_container_width=True):
                    iniciar_tarea(t)
    else:
        st.warning("No hay tareas cargadas. Presiona 'Cargar Eventos de Hoy'.")

if st.session_state.historial:
    st.divider()
    st.subheader("📊 Resumen de hoy")
    for h in st.session_state.historial:
        st.write(f"- **{h['nombre']}**: {h['tiempo']} trabajados")