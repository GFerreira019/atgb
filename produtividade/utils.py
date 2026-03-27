from datetime import datetime, time, date, timedelta
from django.utils import timezone
from django.db.models import Sum, Q
from .models import LogAuditoria
import logging

# ==============================================================================
# LÓGICA DE CONTROLE DE ACESSO (RBAC)
# ==============================================================================

def is_owner(user):
    return user.is_superuser

def check_group(user, group_name):
    return user.groups.filter(name=group_name).exists()

def is_coordenador(user):
    return check_group(user, 'COORDENADOR') or is_owner(user)

def is_administrativo(user):
    return check_group(user, 'ADMINISTRATIVO') or is_owner(user)

def is_gerente(user):
    return check_group(user, 'GESTOR') or is_owner(user)

def pode_fazer_rateio(user):
    return is_coordenador(user) or is_administrativo(user) or is_owner(user)

# ==============================================================================
# HELPERS DE CÁLCULO
# ==============================================================================

def distribuir_horarios_com_gap(inicio, fim, qtd_obras):
    """Calcula horários sequenciais SEM INTERVALOS (Gap Zero)."""
    if qtd_obras <= 0: return []
    d = date(2000, 1, 1)
    
    dt_ini = datetime.combine(d, inicio)
    dt_fim = datetime.combine(d, fim)
    
    if dt_fim < dt_ini: 
        dt_fim += timedelta(days=1)
    total_minutos = int((dt_fim - dt_ini).total_seconds() / 60)
    minutos_base = total_minutos // qtd_obras
    resto = total_minutos % qtd_obras
    intervalos = []
    tempo_atual = dt_ini
    for i in range(qtd_obras):
        duracao = minutos_base + (1 if i < resto else 0)
        if duracao < 1 and total_minutos > 0: duracao = 1 
        fim_obra = tempo_atual + timedelta(minutes=duracao)
        intervalos.append((tempo_atual.time(), fim_obra.time()))
        tempo_atual = fim_obra
    return intervalos

# ==============================================================================
# REGRAS DE CONFORMIDADE DA JORNADA DE TRABALHO (CLT)
# ==============================================================================

def get_data_contabil(dt_referencia):
    """
    Define a qual 'Dia de Trabalho' um datetime pertence.
    Regra: O dia começa às 06:00 e termina às 05:59 do dia seguinte.
    Se for antes das 06:00, pertence contabilmente ao dia anterior.
    """
    if dt_referencia.hour < 6:
        return dt_referencia.date() - timedelta(days=1)
    return dt_referencia.date()

def calcular_regras_clt(colaborador, data_contabil_ref):
    """
    Processa as regras para um colaborador em uma data específica.
    Chamado ao Salvar, Editar ou Excluir um apontamento.
    Processa Dia Anterior, Dia Atual e Dia Seguinte, para garantir Interjornada.
    """
    from .models import Apontamento

    datas_para_processar = [
        data_contabil_ref - timedelta(days=1),
        data_contabil_ref,
        data_contabil_ref + timedelta(days=1)
    ]

    for data_contabil in datas_para_processar:
        inicio_janela = timezone.make_aware(datetime.combine(data_contabil, time(6, 0)))
        fim_janela = timezone.make_aware(datetime.combine(data_contabil + timedelta(days=1), time(5, 59, 59)))

        apontamentos = list(Apontamento.objects.filter(
            colaborador=colaborador,
            data_apontamento__range=(data_contabil, data_contabil + timedelta(days=1))
        ).order_by('data_apontamento', 'hora_inicio'))

        apontamentos_validos = []
        for apt in apontamentos:
            dt_ini = timezone.make_aware(datetime.combine(apt.data_apontamento, apt.hora_inicio))
            if inicio_janela <= dt_ini <= fim_janela:
                apontamentos_validos.append(apt)

        alerts_map = {apt.id: [] for apt in apontamentos_validos}
        
        # --- Regra Limite Diário (10:48h) ---
        total_segundos = 0
        for apt in apontamentos_validos:
            total_segundos += _calcular_segundos(apt)
        
        limite_diario_segundos = (10 * 3600) + (48 * 60)
        
        if total_segundos > limite_diario_segundos:
            msg = f"Jornada total ({_fmt_duracao(total_segundos)}) excedeu as 02:00h adicionais diária"
            for apt in apontamentos_validos:
                alerts_map[apt.id].append(msg)

        # --- Regra Intervalo Intrajornada (Max 6h contínuas) ---
        tempo_continuo = 0
        last_end = None
        
        for i, apt in enumerate(apontamentos_validos):
            duracao = _calcular_segundos(apt)
            dt_ini = _to_dt(apt.data_apontamento, apt.hora_inicio)
            
            if last_end and dt_ini == last_end:
                tempo_continuo += duracao
            else:
                tempo_continuo = duracao
            
            last_end = _to_dt(apt.data_apontamento, apt.hora_termino)
            if last_end < dt_ini: last_end += timedelta(days=1)

            if tempo_continuo > (6 * 3600):
                alerts_map[apt.id].append("Trabalho contínuo superior a 06:00h sem intervalo.")

        # --- Regra Descanso Interjornada (11h) ---
        dia_anterior_contabil = data_contabil - timedelta(days=1)
        ini_prev = timezone.make_aware(datetime.combine(dia_anterior_contabil, time(6, 0)))
        fim_prev = timezone.make_aware(datetime.combine(data_contabil, time(5, 59, 59)))
        
        last_apt_prev = Apontamento.objects.filter(
            colaborador=colaborador,
            data_apontamento__range=(dia_anterior_contabil, data_contabil)
        ).order_by('-data_apontamento', '-hora_termino')
        
        ultimo_dia_anterior = None
        for cand in last_apt_prev:
            dt_end_cand = _to_dt_full(cand)
            if ini_prev <= dt_end_cand <= fim_prev:
                ultimo_dia_anterior = cand
                break
        
        if ultimo_dia_anterior and apontamentos_validos:
            primeiro_dia_atual = apontamentos_validos[0]
            
            if ultimo_dia_anterior.hora_termino:
                dt_fim_ant = _to_dt_full(ultimo_dia_anterior)
                
                d_atual = primeiro_dia_atual.data_apontamento
                h_atual = primeiro_dia_atual.hora_inicio
                dt_ini_atual_naive = datetime.combine(d_atual, h_atual)
                dt_ini_atual = timezone.make_aware(dt_ini_atual_naive) if timezone.is_naive(dt_ini_atual_naive) else dt_ini_atual_naive
                
                diff = dt_ini_atual - dt_fim_ant
                
                if diff.total_seconds() > 0 and diff.total_seconds() < (11 * 3600):
                    msg = f"Descanso Interjornada de {_fmt_duracao(diff.total_seconds())} (Mínimo 11h)."
                    alerts_map[primeiro_dia_atual.id].append(msg)

        updates = []
        for apt in apontamentos_validos:
            msgs = alerts_map[apt.id]
            novo_flag = len(msgs) > 0
            novo_motivo = " | ".join(msgs) if msgs else None
            
            if apt.flag_atencao != novo_flag or apt.motivo_alerta != novo_motivo:
                apt.flag_atencao = novo_flag
                apt.motivo_alerta = novo_motivo
                updates.append(apt)
        
        if updates:
            Apontamento.objects.bulk_update(updates, ['flag_atencao', 'motivo_alerta'])

# --- Helpers Privados para Engine ---
def _calcular_segundos(apt):
    if not apt.hora_inicio or not apt.hora_termino:
        return 0
    dummy = datetime(2000,1,1)
    ini = datetime.combine(dummy, apt.hora_inicio)
    fim = datetime.combine(dummy, apt.hora_termino)
    if fim < ini: fim += timedelta(days=1)
    return (fim - ini).total_seconds()

def _to_dt(data, hora):
    return datetime.combine(data, hora)

def _to_dt_full(apt):
    d = apt.data_apontamento
    h = apt.hora_termino
    
    if not h:
        h = apt.hora_inicio 

    dt = datetime.combine(d, h)
    
    if apt.hora_inicio and h < apt.hora_inicio:
        dt += timedelta(days=1)
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt

def _fmt_duracao(segundos):
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    return f"{h:02d}:{m:02d}h"


# ==============================================================================
# LOG DE AUDITORIA
# ==============================================================================

logger = logging.getLogger('auditoria')

def get_client_ip(request):
    """
    Captura o IP real do usuário.
    Considera proxies reversos via HTTP_X_FORWARDED_FOR.
    """
    if not request:
        return None

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def registrar_log(request, acao, modelo, obj_id, detalhes):
    """
    Função helper para salvar logs de qualquer lugar do sistema.
    """
    try:
        ip = get_client_ip(request)
        
        user = None
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            user = request.user
        
        LogAuditoria.objects.create(
            usuario=user,
            acao=acao,
            modelo_afetado=modelo,
            objeto_id=str(obj_id) if obj_id else None,
            detalhes=detalhes,
            ip_address=ip
        )
    except Exception as e:
        logger.error(f"FALHA CRÍTICA DE AUDITORIA: Não foi possível salvar o log. Detalhes: {e}", exc_info=True)