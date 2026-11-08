import datetime
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']

# --- CONFIGURACIÓN ---
WORK_HOURS_START = 9   # 9 AM
WORK_HOURS_END = 17    # 5 PM
IMMOVABLE_KEYWORDS = ["Meet", "Reunión", "Llamada", "Cita", "Personal", "Almuerzo", "Podcast", "Grabar", "Curso"]
FLEXIBLE_KEYWORDS = ["Editar", "Filmar", "Preparar", "Desarrollo"]

def get_calendar_service():
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

def is_immovable(event):
    summary = event.get('summary', '').lower()
    return any(keyword.lower() in summary for keyword in IMMOVABLE_KEYWORDS)

def parse_dt(dt_string):
    return datetime.datetime.fromisoformat(dt_string.replace('Z', '+00:00')).replace(tzinfo=None)

# --- NUEVA FUNCIÓN: Buscar el próximo día disponible ---
def get_next_available_day(service, start_date):
    check_date = start_date + datetime.timedelta(days=1)
    # Buscar hasta 7 días en el futuro
    for _ in range(7): 
        start_of_day = f"{check_date.strftime('%Y-%m-%d')}T00:00:00-06:00" 
        end_of_day = f"{check_date.strftime('%Y-%m-%d')}T23:59:59-06:00"
        
        events_result = service.events().list(
            calendarId='primary', timeMin=start_of_day, timeMax=end_of_day,
            singleEvents=True, orderBy='startTime').execute()
        
        events = events_result.get('items', [])
        
        # Si no hay eventos, o si los que hay no ocupan el día entero (ignoramos los de todo el día 'date')
        timed_events = [e for e in events if 'dateTime' in e['start']]
        
        # Si hay menos de 3 eventos (una suposición de que no está lleno), o si no hay eventos, lo usamos.
        # Puedes cambiar este número si quieres ser más estricto.
        if len(timed_events) < 3: 
            return check_date
            
        check_date += datetime.timedelta(days=1)
    return check_date # Si todo está lleno, devuelve el día 7

def reschedule_flexible_tasks(service, date_str):
    start_of_day = f"{date_str}T00:00:00-06:00" 
    end_of_day = f"{date_str}T23:59:59-06:00"
    
    events_result = service.events().list(
        calendarId='primary', timeMin=start_of_day, timeMax=end_of_day,
        singleEvents=True, orderBy='startTime').execute()
    events = events_result.get('items', [])

    if not events:
        print("No hay eventos para este día.")
        return

    fixed_events = []
    flexible_events = []

    for event in events:
        if 'dateTime' not in event['start']:
            continue
            
        if is_immovable(event):
            fixed_events.append(event)
        else:
            flexible_events.append(event)

    current_time = datetime.datetime.fromisoformat(f"{date_str}T{WORK_HOURS_START:02d}:00:00")
    hora_fin_dt = datetime.datetime.fromisoformat(f"{date_str}T{WORK_HOURS_END:02d}:00:00")

    for flex_event in flexible_events:
        start_str = flex_event['start']['dateTime']
        end_str = flex_event['end']['dateTime']
        
        start_dt = parse_dt(start_str)
        end_dt = parse_dt(end_str)
        duration = end_dt - start_dt

        print(f"Revisando: '{flex_event.get('summary')}' (Hora original: {start_dt.strftime('%H:%M')})")

        if current_time > start_dt:
            start_dt = current_time
            end_dt = start_dt + duration

        # Comprobar choques con eventos fijos
        overlap = True
        while overlap:
            overlap = False
            for fixed in fixed_events:
                f_start = parse_dt(fixed['start']['dateTime'])
                f_end = parse_dt(fixed['end']['dateTime'])
                
                if start_dt < f_end and end_dt > f_start:
                    start_dt = f_end
                    end_dt = start_dt + duration
                    overlap = True
                    print(f"  -> Choca con '{fixed.get('summary')}'. Moviendo a {start_dt.strftime('%H:%M')}")

        # --- LÓGICA DE CORTE (Splitting) ---
        if end_dt > hora_fin_dt:
            print(f"  [CORTE] '{flex_event.get('summary')}' se pasa de las {WORK_HOURS_END}:00.")
            
            # ¡NUEVO! Si el final se pasa de las 5, verificamos si el bloque (hasta las 5) choca con algo fijo
            # y lo empujamos antes de cortar.
            overlap_al_cortar = True
            while overlap_al_cortar:
                overlap_al_cortar = False
                for fixed in fixed_events:
                    f_start = parse_dt(fixed['start']['dateTime'])
                    f_end = parse_dt(fixed['end']['dateTime'])
                    
                    # Si el inicio del bloque choca con la reunión
                    if start_dt < f_end and hora_fin_dt > f_start:
                        start_dt = f_end
                        print(f"  -> Al cortar chocaba con '{fixed.get('summary')}'. Empujando el inicio a {start_dt.strftime('%H:%M')}")
                        overlap_al_cortar = True

            # Recalculamos cuánto tiempo nos queda hoy
            tiempo_disponible_hoy = hora_fin_dt - start_dt
            tiempo_sobrante = duration - tiempo_disponible_hoy

            if tiempo_disponible_hoy.total_seconds() > 0:
                # A. Acortar el evento original para que termine justo a las 5 PM
                flex_event['start']['dateTime'] = start_dt.strftime("%Y-%m-%dT%H:%M:%S-06:00")
                flex_event['end']['dateTime'] = hora_fin_dt.strftime("%Y-%m-%dT%H:%M:%S-06:00")
                service.events().update(calendarId='primary', eventId=flex_event['id'], body=flex_event).execute()
                print(f"  [CORTADO] El bloque de hoy irá de {start_dt.strftime('%H:%M')} a las 17:00.")

                # 2. Buscar el próximo día disponible
                fecha_actual_dt = datetime.datetime.fromisoformat(date_str)
                proximo_dia = get_next_available_day(service, fecha_actual_dt)
                
                # B. Crear el nuevo evento para el sobrante
                nuevo_inicio = proximo_dia.replace(hour=WORK_HOURS_START, minute=0, second=0)
                nuevo_fin = nuevo_inicio + tiempo_sobrante

                evento_continuacion = {
                    'summary': f"{flex_event.get('summary')} (Continuación)",
                    'description': f"Parte 2 del evento original. Duración restante: {tiempo_sobrante}",
                    'start': {
                        'dateTime': nuevo_inicio.strftime("%Y-%m-%dT%H:%M:%S-06:00"),
                        'timeZone': 'America/Costa_Rica',
                    },
                    'end': {
                        'dateTime': nuevo_fin.strftime("%Y-%m-%dT%H:%M:%S-06:00"),
                        'timeZone': 'America/Costa_Rica',
                    },
                }
                service.events().insert(calendarId='primary', body=evento_continuacion).execute()
                print(f"  [AGENDADO MAÑANA] '{flex_event.get('summary')} (Continuación)' el {proximo_dia.strftime('%Y-%m-%d')} a las 09:00.")

            else:
                # Si no nos queda nada de tiempo hoy (porque chocamos hasta las 5pm), movemos todo al siguiente día
                fecha_actual_dt = datetime.datetime.fromisoformat(date_str)
                proximo_dia = get_next_available_day(service, fecha_actual_dt)
                nuevo_inicio = proximo_dia.replace(hour=WORK_HOURS_START, minute=0, second=0)
                nuevo_fin = nuevo_inicio + duration
                
                flex_event['start']['dateTime'] = nuevo_inicio.strftime("%Y-%m-%dT%H:%M:%S-06:00")
                flex_event['end']['dateTime'] = nuevo_fin.strftime("%Y-%m-%dT%H:%M:%S-06:00")
                service.events().update(calendarId='primary', eventId=flex_event['id'], body=flex_event).execute()
                print(f"  [MOVIDO COMPLETO] al {proximo_dia.strftime('%Y-%m-%d')} a las 09:00 (No había espacio hoy).")

            continue

        # Si no se pasa de las 5 PM, actualizar normalmente
        original_start_dt = parse_dt(start_str)
        if start_dt != original_start_dt:
            flex_event['start']['dateTime'] = start_dt.strftime("%Y-%m-%dT%H:%M:%S-06:00")
            flex_event['end']['dateTime'] = end_dt.strftime("%Y-%m-%dT%H:%M:%S-06:00")
            service.events().update(calendarId='primary', eventId=flex_event['id'], body=flex_event).execute()
            print(f"  [MOVIDO] a las {start_dt.strftime('%H:%M')}")

        current_time = end_dt + datetime.timedelta(minutes=15)

if __name__ == '__main__':
    service = get_calendar_service()
    
    # Usar la fecha real de tu computadora
    fecha_inicio = datetime.date.today()
    
    print(f"--- Iniciando organización desde {fecha_inicio} ---")
    
    # Revisar hoy + los próximos 7 días
    for i in range(7):
        dia_a_revisar = fecha_inicio + datetime.timedelta(days=i)
        fecha_str = dia_a_revisar.isoformat()
        
        print(f"\n>>> Revisando el día: {fecha_str} <<<")
        reschedule_flexible_tasks(service, fecha_str)
        
    print("\n--- Proceso terminado para toda la semana ---")