import datetime
import time
import os
import os.path
import json
import csv
import msvcrt 
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']
TIMEZONE = "America/Costa_Rica"
TZ_SUFFIX = "-06:00"

# --- CONFIGURACIÓN DE LA JORNADA LABORAL ---
HORA_ENTRADA_H = 7
MINUTO_ENTRADA_M = 35
HORA_SALIDA_H = 17
MINUTO_SALIDA_M = 0

# --- HORAS DE CORTE PARA REPORTES ---
HORA_CORTE_MANANA = 12
MINUTO_CORTE_MANANA = 30
HORA_CORTE_TARDE = 17
MINUTO_CORTE_TARDE = 0

SUELDO_POR_HORA = 15.00 
MONEDA = "$"

ARCHIVO_CONFIG = 'config_eventos.json'
ARCHIVO_REPORTE = 'reporte_tiempos.csv'
ARCHIVO_PENDIENTES = 'resumen_pendiente.json' # NUEVO ARCHIVO DE MEMORIA

# ==========================================
# 1. MODELOS
# ==========================================

class Tarea:
    def __init__(self, id_evento, nombre, inicio_planeado, fin_planeado, es_reagendable=True):
        self.id_evento = id_evento
        self.nombre = nombre
        self.inicio_planeado = inicio_planeado
        self.fin_planeado = fin_planeado
        self.es_reagendable = es_reagendable
        self.inicio_real = None
        self.tiempo_pausado_total = datetime.timedelta(0)
        self.inicio_pausa = None

    def iniciar(self):
        self.inicio_real = datetime.datetime.now()
        print(f"\n▶️ INICIADO: '{self.nombre}' a las {self.inicio_real.strftime('%H:%M:%S')}")

    def pausar(self):
        self.inicio_pausa = datetime.datetime.now()
        print(f"\n⏸️ PAUSADO: '{self.nombre}' a las {self.inicio_pausa.strftime('%H:%M:%S')}.")

    def reanudar_despues_pausa(self):
        if self.inicio_pausa:
            tiempo_pausa = datetime.datetime.now() - self.inicio_pausa
            self.tiempo_pausado_total += tiempo_pausa
            self.inicio_pausa = None
            print(f"\n▶️ REANUDANDO: Pausa de {str(tiempo_pausa).split('.')[0]}")

    def obtener_tiempo_actual(self):
        if not self.inicio_real: return datetime.timedelta(0)
        ahora = datetime.datetime.now()
        duracion = (self.inicio_pausa - self.inicio_real) if self.inicio_pausa else (ahora - self.inicio_real)
        return duracion - self.tiempo_pausado_total


class Empleado:
    def __init__(self, nombre):
        self.nombre = nombre
        self.tarea_actual = None
        self.tareas_terminadas_pendientes = [] 

    def iniciar_tarea(self, tarea):
        self.tarea_actual = tarea
        tarea.iniciar()

    def pausar_tarea_actual(self):
        if self.tarea_actual: self.tarea_actual.pausar()

    def reanudar_tarea_actual(self):
        if self.tarea_actual: self.tarea_actual.reanudar_despues_pausa()


# ==========================================
# 2. GESTOR
# ==========================================

class GestorCalendario:
    def __init__(self):
        self.service = self._autenticar()
        self.memoria_eventos = self._cargar_memoria()
        self._verificar_encabezados_csv()

    def _autenticar(self):
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return build('calendar', 'v3', credentials=creds)

    def _cargar_memoria(self):
        if os.path.exists(ARCHIVO_CONFIG):
            with open(ARCHIVO_CONFIG, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _guardar_memoria(self):
        with open(ARCHIVO_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(self.memoria_eventos, f, indent=4)

    def _verificar_encabezados_csv(self):
        if not os.path.exists(ARCHIVO_REPORTE):
            with open(ARCHIVO_REPORTE, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Fecha", "Hora Inicio", "Tarea", "Empleado", "Tipo", "Tiempo Efectivo", "Tiempo en Pausa", "Horas Extra", "Costo"])

    # --- NUEVAS FUNCIONES PARA GUARDAR/LEER PENDIENTES ---
    def guardar_pendientes(self, empleado):
        datos = []
        for t in empleado.tareas_terminadas_pendientes:
            datos.append({
                'nombre': t['nombre'],
                'duracion_segundos': t['duracion'].total_seconds(),
                'es_reagendable': t['es_reagendable']
            })
        with open(ARCHIVO_PENDIENTES, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=4)

    def cargar_pendientes(self, empleado):
        if os.path.exists(ARCHIVO_PENDIENTES):
            with open(ARCHIVO_PENDIENTES, 'r', encoding='utf-8') as f:
                datos = json.load(f)
                for d in datos:
                    empleado.tareas_terminadas_pendientes.append({
                        'nombre': d['nombre'],
                        'duracion': datetime.timedelta(seconds=d['duracion_segundos']),
                        'es_reagendable': d['es_reagendable']
                    })
            print(f"🔄 Se recuperaron {len(datos)} tareas pendientes de resumen del disco duro.")

    def guardar_en_excel(self, tarea, empleado, duracion_efectiva, horas_extra):
        fecha_str = tarea.inicio_real.strftime('%d/%m/%Y')
        hora_str = tarea.inicio_real.strftime('%H:%M:%S')
        tipo = "Fijo" if not tarea.es_reagendable else "Flexible"
        
        t_efectivo_str = str(duracion_efectiva).split('.')[0]
        t_pausa_str = str(tarea.tiempo_pausado_total).split('.')[0]
        t_extra_str = str(horas_extra).split('.')[0] if horas_extra.total_seconds() > 0 else "0:00:00"
        
        costo = (duracion_efectiva.total_seconds() / 3600) * SUELDO_POR_HORA

        with open(ARCHIVO_REPORTE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([fecha_str, hora_str, tarea.nombre, empleado.nombre, tipo, t_efectivo_str, t_pausa_str, t_extra_str, f"{MONEDA}{costo:.2f}"])

    def crear_bloque_resumen(self, empleado, periodo):
        if not empleado.tareas_terminadas_pendientes:
            print(f"\nNo hay tareas para reportar en el periodo de la {periodo}.")
            return

        ahora = datetime.datetime.now()
        if periodo == "mañana":
            inicio_bloque = ahora.replace(hour=HORA_CORTE_MANANA, minute=MINUTO_CORTE_MANANA, second=0, microsecond=0)
            nombre_bloque = f"[APP] RESUMEN TRABAJO MAÑANA - {empleado.nombre}"
        else:
            inicio_bloque = ahora.replace(hour=HORA_CORTE_TARDE, minute=MINUTO_CORTE_TARDE, second=0, microsecond=0)
            nombre_bloque = f"[APP] RESUMEN TRABAJO TARDE - {empleado.nombre}"

        texto_desc = "Tareas realizadas:\n\n"
        total_tiempo = datetime.timedelta(0)
        total_costo = 0

        for t in empleado.tareas_terminadas_pendientes:
            tiempo_efectivo = t['duracion']
            costo = (tiempo_efectivo.total_seconds() / 3600) * SUELDO_POR_HORA
            total_tiempo += tiempo_efectivo
            total_costo += costo
            texto_desc += f"- {t['nombre']}: {str(tiempo_efectivo).split('.')[0]} | Costo: {MONEDA}{costo:.2f}\n"

        texto_desc += f"\nTOTAL EFECTIVO: {str(total_tiempo).split('.')[0]}\nCOSTO TOTAL: {MONEDA}{total_costo:.2f}"

        evento = {
            'summary': nombre_bloque,
            'description': texto_desc,
            'start': {'dateTime': inicio_bloque.strftime(f"%Y-%m-%dT%H:%M:%S{TZ_SUFFIX}"), 'timeZone': TIMEZONE},
            'end': {'dateTime': (inicio_bloque + datetime.timedelta(minutes=1)).strftime(f"%Y-%m-%dT%H:%M:%S{TZ_SUFFIX}"), 'timeZone': TIMEZONE},
            'colorId': '8' 
        }
        
        try:
            res = self.service.events().insert(calendarId='primary', body=evento).execute()
            self.memoria_eventos[res['id']] = False 
            self._guardar_memoria()
            print(f"\n📅 ¡BLOQUE DE RESUMEN DE LA {periodo.upper()} CREADO EN EL CALENDARIO!")
            
            # Limpiamos la lista y el archivo de pendientes
            empleado.tareas_terminadas_pendientes.clear()
            if os.path.exists(ARCHIVO_PENDIENTES):
                os.remove(ARCHIVO_PENDIENTES) # Borramos el archivo porque ya se usó
        except Exception as e:
            print(f"⚠️ Error al crear el resumen: {e}")

    def _es_evento_ignorado(self, nombre):
        prefijos_ignorados = [
            "[APP] ✅ REAL:", "[APP] ⏸️ PARCIAL:", "[APP] [Evento interrumpido]",
            "[APP] [Evento no terminado]", "[APP] [Cancelado]", "[APP] RESUMEN",
            "✅ REAL:", "⏸️ PARCIAL:", "[Evento interrumpido]", "[Evento no terminado]", "[Cancelado]"
        ]
        if nombre.startswith("[APP] Evento "):
            return False
        for prefijo in prefijos_ignorados:
            if nombre.startswith(prefijo):
                return True
        return False

    def preguntar_si_es_reagendable(self, nombre_evento):
        print(f"\n\n❓ EVENTO NUEVO: '{nombre_evento}'")
        print("¿Reagendable? (s/n): ", end="", flush=True)
        while True:
            if msvcrt.kbhit():
                resp = msvcrt.getch().decode('utf-8').lower()
                if resp == 's': return True
                elif resp == 'n': return False

    def obtener_eventos_hoy(self, preguntar_nuevos=True):
        hoy = datetime.date.today().isoformat()
        start_of_day = f"{hoy}T00:00:00{TZ_SUFFIX}"
        end_of_day = f"{hoy}T23:59:59{TZ_SUFFIX}"
        
        events_result = self.service.events().list(
            calendarId='primary', timeMin=start_of_day, timeMax=end_of_day,
            singleEvents=True, orderBy='startTime').execute()
        
        lista_tareas = []
        for ev in events_result.get('items', []):
            if 'dateTime' not in ev['start']: continue
            nombre = ev.get('summary', 'Sin título')
            
            if self._es_evento_ignorado(nombre): continue
            
            id_ev = ev['id']
            if id_ev not in self.memoria_eventos:
                if preguntar_nuevos:
                    es_reagendable = self.preguntar_si_es_reagendable(nombre)
                    self.memoria_eventos[id_ev] = es_reagendable
                    self._guardar_memoria()
                else:
                    es_reagendable = True 
            else:
                es_reagendable = self.memoria_eventos[id_ev]

            inicio = datetime.datetime.fromisoformat(ev['start']['dateTime'].replace('Z', '+00:00')).replace(tzinfo=None)
            fin = datetime.datetime.fromisoformat(ev['end']['dateTime'].replace('Z', '+00:00')).replace(tzinfo=None)
            lista_tareas.append(Tarea(id_ev, nombre, inicio, fin, es_reagendable))
            
        return lista_tareas

    def reagendar_tiempo_restante(self, tarea, tiempo_restante, tipo_reagende):
        if tiempo_restante.total_seconds() <= 0: return
        fecha_hoy_str = datetime.date.today().strftime('%d/%m/%Y')
        
        if tipo_reagende == "interrupcion":
            nuevo_nombre = f"[APP] Evento {tarea.nombre} interrumpido en el día {fecha_hoy_str}"
        elif tipo_reagende == "falta_tiempo":
            nuevo_nombre = f"[APP] Evento {tarea.nombre} reagendado el {fecha_hoy_str} por falta de tiempo extra"
        
        fecha_busqueda = datetime.date.today()
        for i in range(7):
            dia_str = fecha_busqueda.isoformat()
            events_result = self.service.events().list(
                calendarId='primary', timeMin=f"{dia_str}T00:00:00{TZ_SUFFIX}", timeMax=f"{dia_str}T23:59:59{TZ_SUFFIX}",
                singleEvents=True, orderBy='startTime').execute()
            
            inicio_jornada = datetime.datetime.combine(fecha_busqueda, datetime.time(HORA_ENTRADA_H, MINUTO_ENTRADA_M))
            fin_jornada = datetime.datetime.combine(fecha_busqueda, datetime.time(HORA_SALIDA_H, MINUTO_SALIDA_M))
            if fecha_busqueda == datetime.date.today():
                ahora = datetime.datetime.now()
                if ahora > inicio_jornada: inicio_jornada = ahora

            tiempo_buscado = inicio_jornada
            
            for ev in events_result.get('items', []):
                if 'dateTime' not in ev['start'] or self._es_evento_ignorado(ev.get('summary', '')): continue
                ev_inicio = datetime.datetime.fromisoformat(ev['start']['dateTime'].replace('Z', '+00:00')).replace(tzinfo=None)
                ev_fin = datetime.datetime.fromisoformat(ev['end']['dateTime'].replace('Z', '+00:00')).replace(tzinfo=None)
                
                if tiempo_buscado + tiempo_restante <= ev_inicio:
                    self._crear_evento_reagendado(nuevo_nombre, tiempo_buscado, tiempo_buscado + tiempo_restante)
                    return True
                if ev_fin > tiempo_buscado: tiempo_buscado = ev_fin
                    
            if tiempo_buscado + tiempo_restante <= fin_jornada:
                self._crear_evento_reagendado(nuevo_nombre, tiempo_buscado, tiempo_buscado + tiempo_restante)
                return True
            fecha_busqueda += datetime.timedelta(days=1)
        print("❌ No se encontró espacio para reagendar.")
        return False

    def _crear_evento_reagendado(self, nombre, inicio, fin):
        evento = {
            'summary': nombre,
            'start': {'dateTime': inicio.strftime(f"%Y-%m-%dT%H:%M:%S{TZ_SUFFIX}"), 'timeZone': TIMEZONE},
            'end': {'dateTime': fin.strftime(f"%Y-%m-%dT%H:%M:%S{TZ_SUFFIX}"), 'timeZone': TIMEZONE},
            'colorId': '5'
        }
        res = self.service.events().insert(calendarId='primary', body=evento).execute()
        self.memoria_eventos[res['id']] = True
        self._guardar_memoria()
        print(f"✅ Reagendado el {inicio.strftime('%d/%m')} de {inicio.strftime('%H:%M')} a {fin.strftime('%H:%M')}")


# ==========================================
# 3. INTERFAZ
# ==========================================

class AppAsistente:
    def __init__(self, gestor, empleado):
        self.gestor = gestor
        self.empleado = empleado
        self.tareas_hoy = []
        self.tareas_completadas = []
        self.ultima_actualizacion = 0 
        self.resumen_manana_hecho = False
        self.resumen_tarde_hecho = False
        
        # Al iniciar, cargamos los pendientes del disco duro
        self.gestor.cargar_pendientes(self.empleado)
        self._cargar_tareas()

    def _cargar_tareas(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        print("Cargando eventos del día...")
        self.tareas_hoy = self.gestor.obtener_eventos_hoy(preguntar_nuevos=True)
        self.ultima_actualizacion = time.time()
        print(f"Se encontraron {len(self.tareas_hoy)} tareas planificadas.")

    def _auto_actualizar(self):
        tiempo_actual = time.time()
        if tiempo_actual - self.ultima_actualizacion >= 30:
            ids_actuales = {t.id_evento for t in self.tareas_hoy}
            nuevas_tareas = self.gestor.obtener_eventos_hoy(preguntar_nuevos=False)
            
            for t in nuevas_tareas:
                if t.id_evento not in ids_actuales:
                    if t.nombre.startswith("[APP] Evento "):
                        es_reagendable = True
                    else:
                        es_reagendable = self.gestor.preguntar_si_es_reagendable(t.nombre)
                        self.gestor.memoria_eventos[t.id_evento] = es_reagendable
                        self.gestor._guardar_memoria()
                    t.es_reagendable = es_reagendable
                    self.tareas_hoy.append(t)
            
            self.tareas_hoy.sort(key=lambda x: x.inicio_planeado)
            self.ultima_actualizacion = time.time()

    def buscar_siguiente_tarea(self):
        ahora = datetime.datetime.now()
        for tarea in self.tareas_hoy:
            if tarea not in self.tareas_completadas:
                if not tarea.es_reagendable and ahora >= tarea.inicio_planeado: return tarea
                elif tarea.es_reagendable and ahora >= (tarea.inicio_planeado - datetime.timedelta(minutes=5)): return tarea
        return None

    def finalizar_tarea_actual(self, es_interrupcion=False, motivo=""):
        tarea = self.empleado.tarea_actual
        if not tarea: return

        if not tarea.es_reagendable and es_interrupcion:
            print(f"\n🛡️ '{tarea.nombre}' es un evento FIJO. Presiona [F] cuando termines la reunión.")
            return

        duracion_efectiva = tarea.obtener_tiempo_actual()
        
        if duracion_efectiva.total_seconds() > 60:
            ahora = datetime.datetime.now()
            hora_limite = ahora.replace(hour=HORA_SALIDA_H, minute=MINUTO_SALIDA_M, second=0, microsecond=0)
            horas_extra = max(datetime.timedelta(0), ahora - hora_limite) if ahora > hora_limite else datetime.timedelta(0)

            self.gestor.guardar_en_excel(tarea, self.empleado, duracion_efectiva, horas_extra)
            
            self.empleado.tareas_terminadas_pendientes.append({
                'nombre': tarea.nombre,
                'duracion': duracion_efectiva,
                'es_reagendable': tarea.es_reagendable
            })
            
            # Guardamos los pendientes en el disco duro inmediatamente
            self.gestor.guardar_pendientes(self.empleado)

            if not es_interrupcion:
                print(f"\n⏹️ FINALIZADO: '{tarea.nombre}'. Tiempo: {str(duracion_efectiva).split('.')[0]}")
                self.tareas_completadas.append(tarea)
            else:
                fecha_hoy_str = datetime.date.today().strftime('%d/%m/%Y')
                if motivo == "interrupcion":
                    nombre_original = f"[APP] [Evento interrumpido] {tarea.nombre}"
                else:
                    nombre_original = f"[APP] [Evento no terminado] {tarea.nombre} - {fecha_hoy_str}"
                self.gestor.renombrar_evento(tarea, nombre_original)

                print(f"\n¿Deseas reagendar el tiempo restante de '{tarea.nombre}'? (s/n): ", end="", flush=True)
                while True:
                    if msvcrt.kbhit():
                        resp = msvcrt.getch().decode('utf-8').lower()
                        if resp == 's':
                            duracion_planeada = tarea.fin_planeado - tarea.inicio_planeado
                            tiempo_restante = duracion_planeada - duracion_efectiva
                            if tiempo_restante.total_seconds() > 0:
                                self.gestor.reagendar_tiempo_restante(tarea, tiempo_restante, motivo)
                            break
                        elif resp == 'n': break

        self.empleado.tarea_actual = None
        print("\nPresiona cualquier tecla para volver al menú...")
        while not msvcrt.kbhit(): time.sleep(0.1)
        msvcrt.getch()

    def iniciar_bucle(self):
        print(f"\n=== BIENVENIDO {self.empleado.nombre.upper()} ===")
        print("Comandos: [P] Pausar/Reanudar | [F] Finalizar | [C] Interrumpir\n")
        time.sleep(2)
        
        aviso_hora_extra_mostrado = False
        
        while True:
            ahora = datetime.datetime.now()
            
            hora_corte_m = ahora.replace(hour=HORA_CORTE_MANANA, minute=MINUTO_CORTE_MANANA, second=0, microsecond=0)
            hora_corte_t = ahora.replace(hour=HORA_CORTE_TARDE, minute=MINUTO_CORTE_TARDE, second=0, microsecond=0)

            if ahora >= hora_corte_m and not self.resumen_manana_hecho:
                print("\n\n🕛 ¡Es mediodía! Generando reporte de la mañana...")
                self.gestor.crear_bloque_resumen(self.empleado, "mañana")
                self.resumen_manana_hecho = True
                time.sleep(3)

            if ahora >= hora_corte_t and not self.resumen_tarde_hecho:
                print("\n\n🕔 ¡Es la hora de salida! Generando reporte de la tarde...")
                self.gestor.crear_bloque_resumen(self.empleado, "tarde")
                self.resumen_tarde_hecho = True
                time.sleep(3)

            if self.empleado.tarea_actual:
                tarea = self.empleado.tarea_actual
                tiempo_actual = tarea.obtener_tiempo_actual()
                estado = "PAUSADO" if tarea.inicio_pausa else "TRABAJANDO"
                
                hora_limite_hoy = ahora.replace(hour=HORA_SALIDA_H, minute=MINUTO_SALIDA_M, second=0, microsecond=0)
                
                if ahora >= hora_limite_hoy and not aviso_hora_extra_mostrado:
                    if tarea.es_reagendable:
                        print(f"\n\n⚠️ Ya son las {ahora.strftime('%H:%M')}. ¿Horas extra? (s/n): ", end="", flush=True)
                        while True:
                            if msvcrt.kbhit():
                                resp = msvcrt.getch().decode('utf-8').lower()
                                if resp == 's':
                                    print("\nModo horas extra activado.")
                                    aviso_hora_extra_mostrado = True
                                    break
                                elif resp == 'n':
                                    self.finalizar_tarea_actual(es_interrupcion=True, motivo="falta_tiempo")
                                    aviso_hora_extra_mostrado = False
                                    break
                    else:
                        print(f"\n\n⚠️ Ya son las {ahora.strftime('%H:%M')}. Evento FIJO. Presiona [F] al terminar.")
                        aviso_hora_extra_mostrado = True
                
                print(f"\r[{estado}] {tarea.nombre} | Tiempo: {str(tiempo_actual).split('.')[0]} | (P)ausar (F)inalizar (C)ancelar ", end="", flush=True)
                
                if msvcrt.kbhit():
                    tecla = msvcrt.getch().decode('utf-8').lower()
                    
                    if tecla == 'p':
                        if tarea.inicio_pausa: self.empleado.reanudar_tarea_actual()
                        else: self.empleado.pausar_tarea_actual()
                    
                    elif tecla == 'f':
                        self.finalizar_tarea_actual(es_interrupcion=False)
                        aviso_hora_extra_mostrado = False
                    
                    elif tecla == 'c':
                        self.finalizar_tarea_actual(es_interrupcion=True, motivo="interrupcion")
                        aviso_hora_extra_mostrado = False
                
                time.sleep(1)
                
            else:
                tarea_pendiente = self.buscar_siguiente_tarea()
                if tarea_pendiente:
                    print(f"\n\n🔔 Siguiente evento: [{tarea_pendiente.nombre}]")
                    print(f"   Hora planeada: {tarea_pendiente.inicio_planeado.strftime('%H:%M')}")
                    respuesta = input("¿Iniciar evento? (s/n): ").lower().strip()
                    if respuesta == 's':
                        self.empleado.iniciar_tarea(tarea_pendiente)
                        aviso_hora_extra_mostrado = False
                    else:
                        print("Tarea omitida. Revisando en 10 segundos...")
                        time.sleep(10)
                else:
                    print(f"\r😴 No hay tareas pendientes. Hora actual: {datetime.datetime.now().strftime('%H:%M:%S')}   ", end="", flush=True)
                    self._auto_actualizar()
                    time.sleep(1)

if __name__ == '__main__':
    gestor = GestorCalendario()
    jostin = Empleado("Jostin")
    app = AppAsistente(gestor, jostin)
    
    try:
        app.iniciar_bucle()
    except KeyboardInterrupt:
        print("\n\n👋 App cerrada. ¿Deseas crear el resumen de la tarde antes de salir?")
        if not app.resumen_tarde_hecho:
            gestor.crear_bloque_resumen(jostin, "tarde")
        print("¡Buen trabajo hoy!")