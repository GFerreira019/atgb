from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.db import connection
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from datetime import datetime, date, timedelta
import calendar
import os
import requests

from .services import ControlePontoService, FeriadoService
from .models import Projeto, Colaborador, Veiculo, CentroCusto, Apontamento, Notificacao
from .utils import is_owner, registrar_log, calcular_regras_clt, get_data_contabil
from .forms import ApontamentoForm

# ==============================================================================
# APIS DE CONSULTA
# ==============================================================================

@login_required
def get_projeto_info_ajax(request, projeto_id):
    cache_key = f'projeto_info_{projeto_id}'
    nome_projeto = cache.get(cache_key)
    
    if not nome_projeto:
        projeto = get_object_or_404(Projeto, pk=projeto_id)
        nome_projeto = projeto.nome
        cache.set(cache_key, nome_projeto, 43200)
        
    return JsonResponse({'nome_projeto': nome_projeto})

@login_required
def get_colaborador_info_ajax(request, colaborador_id):
    colaborador = get_object_or_404(Colaborador, pk=colaborador_id)
    return JsonResponse({'cargo': colaborador.cargo})

@login_required
def get_auxiliares_ajax(request):
    cache_key = 'api_lista_auxiliares'
    auxs = cache.get(cache_key)
    
    if not auxs:
        auxs = list(Colaborador.objects.filter(
            cargo__in=['AUXILIAR TECNICO', 'OFICIAL DE SISTEMAS']
        ).values('id', 'nome_completo'))
        
        cache.set(cache_key, auxs, 43200)
        
    return JsonResponse({'auxiliares': auxs})

@login_required
def get_centro_custo_info_ajax(request, cc_id):
    cache_key = f'cc_info_{cc_id}'
    permite = cache.get(cache_key)
    
    if permite is None:
        cc = get_object_or_404(CentroCusto, pk=cc_id)
        permite = cc.permite_alocacao
        cache.set(cache_key, permite, 43200)
        
    return JsonResponse({'permite_alocacao': permite})

# ==============================================================================
# APIS DO CRONÔMETRO
# ==============================================================================

@login_required
@require_POST
def api_iniciar_cronometro(request):
    """
    Inicia o timer (Check-in)
    """
    try:
        colaborador = Colaborador.objects.get(user_account=request.user)
    except Colaborador.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Usuário sem perfil de colaborador vinculado.'})

    if Apontamento.objects.filter(colaborador=colaborador, hora_termino__isnull=True).exists():
        return JsonResponse({'success': False, 'error': 'Você já possui uma atividade em andamento.'})

    dados = request.POST.copy()
    dados['tipo_acao'] = 'START'
    
    agora = timezone.localtime(timezone.now())
    dados['hora_inicio'] = agora.strftime('%H:%M')
    
    form = ApontamentoForm(dados, user=request.user)

    if form.is_valid():
        apontamento = form.save(commit=False)
        apontamento.registrado_por = request.user
        apontamento.hora_inicio = agora.time()
        apontamento.hora_termino = None
        apontamento.status_aprovacao = 'EM_ANALISE'

        if form.cleaned_data.get('registrar_veiculo'):
            selection = form.cleaned_data.get('veiculo_selecao')         
            if str(selection) == 'OUTRO' or request.POST.get('veiculo_selecao') == 'OUTRO':
                apontamento.veiculo = None
                apontamento.veiculo_manual_modelo = form.cleaned_data.get('veiculo_manual_modelo')
                apontamento.veiculo_manual_placa = form.cleaned_data.get('veiculo_manual_placa')
            else:
                if hasattr(selection, 'id'):
                    apontamento.veiculo = selection
                elif selection:
                     try:
                        apontamento.veiculo = Veiculo.objects.get(pk=selection)
                     except (Veiculo.DoesNotExist, ValueError):
                        apontamento.veiculo = None
                apontamento.veiculo_manual_modelo = None
                apontamento.veiculo_manual_placa = None
        else:
            apontamento.veiculo = None
            apontamento.veiculo_manual_modelo = None
            apontamento.veiculo_manual_placa = None

        if form.cleaned_data.get('registrar_auxiliar'):
            aux_principal = form.cleaned_data.get('auxiliar_selecao')
            if aux_principal:
                apontamento.auxiliar = aux_principal 
            else:
                 apontamento.auxiliar = None
        else:
            apontamento.auxiliar = None

        apontamento.save()

        if form.cleaned_data.get('registrar_auxiliar'):
            ids_string = form.cleaned_data.get('auxiliares_extras_list')
            if ids_string:
                ids_list = [int(x) for x in ids_string.split(',') if x.strip().isdigit()]
                apontamento.auxiliares_extras.set(ids_list)

        return JsonResponse({
            'success': True, 
            'message': 'Atividade iniciada!', 
            'inicio': agora.strftime('%H:%M'),
            'id': apontamento.id
        })
    else:
        print("Erro Form API Start:", form.errors)
        primeiro_erro = list(form.errors.values())[0][0] if form.errors else "Erro desconhecido"
        return JsonResponse({'success': False, 'error': primeiro_erro})

def api_parar_cronometro(request):
    """
    Para o timer (Check-out)
    """
    target_id = request.POST.get('colaborador_id')

    try:
        if request.user.is_superuser and target_id:
            colaborador = Colaborador.objects.get(id=target_id)
        else:
            colaborador = Colaborador.objects.get(user_account=request.user)

    except Colaborador.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Colaborador não encontrado.'})
    except ValueError:
        return JsonResponse({'success': False, 'error': 'ID de colaborador inválido.'})

    apontamento = Apontamento.objects.filter(
        colaborador=colaborador,
        hora_termino__isnull=True
    ).order_by('-id').first()

    if not apontamento:
        nome = colaborador.user_account.first_name if colaborador.user_account else "Colaborador"
        return JsonResponse({'success': False, 'error': f'Nenhuma atividade em andamento encontrada para {nome}.'})

    agora = timezone.localtime(timezone.now())
    apontamento.hora_termino = agora.time()
    apontamento.save()

    try:
        dt_contabil = get_data_contabil(timezone.make_aware(datetime.combine(apontamento.data_apontamento, apontamento.hora_inicio)))
        calcular_regras_clt(colaborador, dt_contabil)
    except Exception as e:
        print(f"Erro ao calcular regras CLT no stop timer: {e}")

    return JsonResponse({
        'success': True, 
        'message': 'Atividade finalizada!',
        'termino': agora.strftime('%H:%M'),
        'duracao': getattr(apontamento, 'duracao_total_str', 'Calculando...')
    })

@login_required
def api_status_cronometro(request):
    """
     status ao carregar a página.
    """
    try:
        colaborador = Colaborador.objects.get(user_account=request.user)
        apontamento = Apontamento.objects.filter(
            colaborador=colaborador,
            hora_termino__isnull=True
        ).order_by('-id').first()

        if apontamento:
            dt_inicio = datetime.combine(apontamento.data_apontamento, apontamento.hora_inicio)
            dt_inicio_aware = timezone.make_aware(dt_inicio)

            veiculo_id = None
            if apontamento.veiculo:
                veiculo_id = apontamento.veiculo.id
            elif apontamento.veiculo_manual_modelo or apontamento.veiculo_manual_placa:
                veiculo_id = 'OUTRO'
            
            return JsonResponse({
                'ativo': True,
                'inicio_timestamp': dt_inicio_aware.timestamp(),
                'inicio_str': apontamento.hora_inicio.strftime('%H:%M'),
                'data_registro': apontamento.data_apontamento.strftime('%d/%m/%Y'),
                'colaborador_id': apontamento.colaborador.id,
                'colaborador_nome': str(apontamento.colaborador),
                'veiculo_id': veiculo_id,
                'veiculo_nome': str(apontamento.veiculo) if apontamento.veiculo else 'Veículo Manual',
                'projeto_nome': str(apontamento.projeto) if apontamento.projeto else None,
                'projeto_id': apontamento.projeto_id,
                'cliente_nome': str(apontamento.codigo_cliente) if apontamento.codigo_cliente else None,
                'cliente_id': apontamento.codigo_cliente_id,
                'cc_nome': str(apontamento.centro_custo) if apontamento.centro_custo else None,
                'cc_id': apontamento.centro_custo_id,
                'local': apontamento.local_execucao
            })
        
        return JsonResponse({'ativo': False})

    except Exception as e:
        return JsonResponse({'ativo': False, 'error': str(e)})
    
# ==============================================================================
# DASHBOARDS E CALENDÁRIOS
# ==============================================================================

@login_required
def get_calendar_status_ajax(request):
    try:
        month = int(request.GET.get('month'))
        year = int(request.GET.get('year'))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Parâmetros inválidos'}, status=400)
    
    user = request.user
    _, num_days = calendar.monthrange(year, month)
    today = timezone.now().date()
    days_data = []

    # ==============================================================================
    # 1. LÓGICA DE GESTÃO (Owner/Gestor) - Visão Global da Empresa
    # ==============================================================================
    if is_owner(user):
        dias_notificados = set(Notificacao.objects.filter(
            data_referencia__year=year,
            data_referencia__month=month,
            tipo='ALERTA'
        ).values_list('data_referencia', flat=True))

        start_date = date(year, month, 1)
        end_date = date(year, month, num_days)
        
        apontamentos = Apontamento.objects.filter(
            data_apontamento__gte=start_date, 
            data_apontamento__lte=end_date
        ).select_related('colaborador')

        todos_colaboradores = list(Colaborador.objects.filter(user_account__is_active=True))
        mapa_escalas_mes = ControlePontoService.obter_escalas_do_mes(todos_colaboradores, month, year)

        for day in range(1, num_days + 1):
            current_date = date(year, month, day)
            
            if current_date > today:
                days_data.append({'day': day, 'date': current_date.strftime('%Y-%m-%d'), 'status': 'future'})
                continue

            is_feriado = FeriadoService.eh_feriado(current_date)
            is_weekend = current_date.weekday() >= 5
            
            status_dia = 'day_off' if (is_feriado or is_weekend) else 'missing'
            apts_dia = [a for a in apontamentos if a.data_apontamento == current_date]
            if apts_dia:
                status_dia = 'filled'
                
                mapa_horas = {}
                colabs_map = {}

                dummy = date(2000, 1, 1)
                for a in apts_dia:
                    if a.hora_inicio and a.hora_termino:
                        dt_i = datetime.combine(dummy, a.hora_inicio)
                        dt_f = datetime.combine(dummy, a.hora_termino)
                        if dt_f < dt_i: dt_f += timedelta(days=1)
                        secs = (dt_f - dt_i).total_seconds()
                        
                        cid = a.colaborador.id
                        mapa_horas[cid] = mapa_horas.get(cid, 0) + secs
                        colabs_map[cid] = a.colaborador

                for cid, total_segundos in mapa_horas.items():
                    dados_ponto = mapa_escalas_mes.get(cid, {}).get(current_date)
                    
                    if not dados_ponto:
                        dados_ponto = {'meta_segundos': 31680, 'tolerancia_segundos': 600}

                    meta = dados_ponto['meta_segundos']
                    tol = dados_ponto['tolerancia_segundos']
                    if meta > 0 and total_segundos < (meta - tol):
                        status_dia = 'incomplete'
                        break
            
            ja_notificado = current_date in dias_notificados
            if ja_notificado and status_dia == 'missing':
                 status_dia = 'missing'

            days_data.append({
                'day': day,
                'date': current_date.strftime('%Y-%m-%d'),
                'status': status_dia, 
                'is_owner': True,
                'ja_notificado': ja_notificado
            })

        return JsonResponse({'is_owner': True, 'days': days_data})

    # ==============================================================================
    # 2. LÓGICA PESSOAL (Colaborador)
    # ==============================================================================
    try:
        colaborador = Colaborador.objects.get(user_account=user)
    except Colaborador.DoesNotExist:
        return JsonResponse({'error': 'Colaborador não encontrado'}, status=400)

    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)

    mapa_escalas_mes = ControlePontoService.obter_escalas_do_mes([colaborador], month, year)

    queryset = Apontamento.objects.filter(
        colaborador=colaborador, data_apontamento__gte=start_date, data_apontamento__lte=end_date
    ).values('data_apontamento', 'hora_inicio', 'hora_termino', 'dorme_fora', 'em_plantao')
    
    dados_dias = {}
    dummy_date = date(2000, 1, 1)

    for entry in queryset:
        d_str = entry['data_apontamento'].strftime('%Y-%m-%d')
        if d_str not in dados_dias:
            dados_dias[d_str] = {'total_segundos': 0, 'dorme_fora': False, 'em_plantao': False}
        
        if entry['dorme_fora']: dados_dias[d_str]['dorme_fora'] = True
        if entry['em_plantao']: dados_dias[d_str]['em_plantao'] = True

        if entry['hora_inicio'] and entry['hora_termino']:
            dt_ini = datetime.combine(dummy_date, entry['hora_inicio'])
            dt_fim = datetime.combine(dummy_date, entry['hora_termino'])
            if dt_fim < dt_ini: dt_fim += timedelta(days=1)
            dados_dias[d_str]['total_segundos'] += (dt_fim - dt_ini).total_seconds()

    for day in range(1, num_days + 1):
        current_date = date(year, month, day)
        date_str = current_date.strftime('%Y-%m-%d')
        
        status = 'missing'
        has_dorme_fora = False
        has_em_plantao = False
        
        if current_date > today:
            status = 'future'
        else:
            dados_ponto = mapa_escalas_mes.get(colaborador.id, {}).get(current_date)
            
            if not dados_ponto:
                dados_ponto = {'meta_segundos': 31680, 'tolerancia_segundos': 600}
            
            meta = dados_ponto['meta_segundos']
            tol = dados_ponto['tolerancia_segundos']
            
            realizado = 0
            if date_str in dados_dias:
                realizado = dados_dias[date_str]['total_segundos']
                has_dorme_fora = dados_dias[date_str]['dorme_fora']
                has_em_plantao = dados_dias[date_str]['em_plantao']

            if meta == 0:
                status = 'filled' if realizado > 0 else 'day_off'
            else:
                if realizado == 0: status = 'missing'
                elif realizado < (meta - tol): status = 'incomplete'
                else: status = 'filled'
        
        days_data.append({
            'date': date_str, 'day': day, 'status': status,
            'has_dorme_fora': has_dorme_fora, 'has_em_plantao': has_em_plantao,
            'is_owner': False
        })

    return JsonResponse({'is_owner': False, 'days': days_data})

@csrf_exempt
def api_dashboard_data(request):
    """
    API JSON para alimentar o Dashboard
    """
    api_key_esperada = getattr(settings, 'DJANGO_API_KEY', None)

    if not api_key_esperada:
        return JsonResponse({'erro': 'Erro de Configuração: API Key não definida no servidor.'}, status=500)

    token_recebido = request.headers.get('X-API-KEY')

    if token_recebido != api_key_esperada and not request.user.is_authenticated:
         return JsonResponse({'erro': 'Acesso Negado'}, status=403)

    hoje = timezone.now().date()
    
    qs = Apontamento.objects.filter(data_apontamento=hoje).select_related('projeto', 'colaborador')

    total_registros = qs.count()
    total_segundos = 0
    projetos_ativos = {}
    colaboradores_ids = set()

    for a in qs:
        if a.hora_inicio and a.hora_termino:
            dummy_date = date(2000, 1, 1)
            dt_inicio = datetime.combine(dummy_date, a.hora_inicio)
            dt_termino = datetime.combine(dummy_date, a.hora_termino)
            
            if dt_termino < dt_inicio:
                dt_termino += timedelta(days=1)
            
            diff = dt_termino - dt_inicio
            total_segundos += diff.total_seconds()

        nome_proj = "Outros"
        if a.local_execucao == 'INT':
             if a.projeto: nome_proj = a.projeto.nome
             elif a.codigo_cliente: nome_proj = f"Cliente {a.codigo_cliente.codigo}"
        else:
             if a.centro_custo: nome_proj = a.centro_custo.nome

        projetos_ativos[nome_proj] = projetos_ativos.get(nome_proj, 0) + 1
        
        if a.colaborador:
            colaboradores_ids.add(a.colaborador.nome_completo)

    total_horas = round(total_segundos / 3600, 2)

    data = {
        'data_referencia': hoje.strftime('%d/%m/%Y'),
        'kpis': {
            'total_apontamentos': total_registros,
            'total_horas': total_horas,
            'colaboradores_ativos': len(colaboradores_ids),
        },
        'grafico_projetos': {
            'labels': list(projetos_ativos.keys()),
            'valores': list(projetos_ativos.values())
        },
        'lista_colaboradores': list(colaboradores_ids)
    }

    return JsonResponse(data)

@csrf_exempt
def api_exportar_json(request):
    api_key_esperada = getattr(settings, 'DJANGO_API_KEY', None)

    if not api_key_esperada:
        return JsonResponse({'erro': 'Erro de Configuração: API Key não definida no servidor.'}, status=500)
    
    token_recebido = request.headers.get('X-API-KEY')

    if token_recebido != api_key_esperada: 
        return JsonResponse({'erro': 'Acesso Negado'}, status=403)

    days = int(request.GET.get('days', 45))
    start_date = timezone.now().date() - timedelta(days=days)
    
    queryset = Apontamento.objects.select_related(
        'projeto', 'colaborador', 'veiculo', 'centro_custo', 'codigo_cliente'
    ).prefetch_related('auxiliares_extras').filter(
        data_apontamento__gte=start_date
    ).order_by('data_apontamento')

    dados_saida = []

    def fmt_hora(h): return h.strftime('%H:%M:%S') if h else None
    def fmt_data(d): return d.strftime('%Y-%m-%d') if d else None

    for item in queryset:
        local_nome = ""
        codigo_obra = None
        codigo_cliente = None
        
        if item.local_execucao == 'INT':
            tipo_str = "OBRA"
            if item.projeto:
                local_nome = item.projeto.nome
                codigo_obra = item.projeto.codigo
            elif item.codigo_cliente:
                local_nome = item.codigo_cliente.nome
                codigo_cliente = item.codigo_cliente.codigo
        else:
            tipo_str = "FORA DO SETOR"
            local_nome = item.centro_custo.nome if item.centro_custo else "Atividade Externa"
            if item.projeto: codigo_obra = item.projeto.codigo
            elif item.codigo_cliente: codigo_cliente = item.codigo_cliente.codigo

        if codigo_obra and len(str(codigo_obra)) >= 5:
             if not codigo_cliente: codigo_cliente = str(codigo_obra)[1:5]
        elif codigo_obra and not codigo_cliente:
             codigo_cliente = codigo_obra

        veiculo_nome = ""
        placa = ""
        if item.veiculo:
            veiculo_nome = item.veiculo.descricao
            placa = item.veiculo.placa
        elif item.veiculo_manual_modelo:
            veiculo_nome = item.veiculo_manual_modelo
            placa = item.veiculo_manual_placa

        base_obj = {
            'data': fmt_data(item.data_apontamento),
            'dia_semana': item.data_apontamento.weekday(), 
            'tipo': tipo_str,
            'local': local_nome,
            'codigo_obra': codigo_obra,
            'codigo_cliente': codigo_cliente,
            'hora_inicio': fmt_hora(item.hora_inicio),
            'hora_fim': fmt_hora(item.hora_termino), 
            'observacoes': item.ocorrencias,
            'registrado_por': item.registrado_por.username if item.registrado_por else 'Sistema',
            'dorme_fora': item.dorme_fora,
            'em_plantao': item.em_plantao,
            'status': item.status_ajuste or 'OK'
        }

        row_main = base_obj.copy()
        row_main.update({
            'colaborador': item.colaborador.nome_completo,
            'cargo': item.colaborador.cargo,
            'veiculo': veiculo_nome,
            'placa': placa,
            'is_auxiliar': False
        })
        dados_saida.append(row_main)

        auxiliares = []
        if item.auxiliar: auxiliares.append(item.auxiliar)
        auxiliares.extend(list(item.auxiliares_extras.all()))

        for aux in auxiliares:
            row_aux = base_obj.copy()
            row_aux.update({
                'colaborador': aux.nome_completo,
                'cargo': aux.cargo,
                'veiculo': 'Passageiro', 
                'placa': None,
                'is_auxiliar': True,
                'dorme_fora': True if item.dorme_fora else False, 
                'em_plantao': True if item.em_plantao else False, 
            })
            dados_saida.append(row_aux)

    return JsonResponse(dados_saida, safe=False)

# ==============================================================================
# HEALTH CHECK
# ==============================================================================

def health_check_view(request):
    """
    Verifica a saúde de todas as dependências do sistema.
    """
    health_status = {
        "status": "healthy",
        "timestamp": timezone.now().isoformat(),
        "dependencies": {
            "database": "offline",
            "wppconnect": "offline",
            "feriados_api": "offline",
            "solides_api": "pending_integration" # Futuro
        }
    }
    
    status_code = 200

    # 1. Banco de Dados
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        health_status["dependencies"]["database"] = "online"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["dependencies"]["database"] = f"error: {str(e)}"
        status_code = 503

    # 2. WPPConnect (Node.js)
    wpp_url = os.getenv('WPP_BASE_URL', 'http://localhost:3000')
    try:
        resp_wpp = requests.get(f"{wpp_url}/health", timeout=3)
        if resp_wpp.status_code == 200:
            fila = resp_wpp.json().get('queueSize', 0)
            health_status["dependencies"]["wppconnect"] = f"online (Fila: {fila})"
        else:
            health_status["dependencies"]["wppconnect"] = "disconnected_or_starting"
            health_status["status"] = "degraded"
    except requests.exceptions.RequestException:
        health_status["status"] = "degraded"
        health_status["dependencies"]["wppconnect"] = "unreachable"

    # 3. Checar API de Feriados (FeriadosAPI)
    try:
        token_feriados = os.getenv('FERIADOS_API_TOKEN')
        headers_feriados = {}
        if token_feriados:
            headers_feriados['Authorization'] = f'Bearer {token_feriados}'
            
        ano_atual = timezone.now().year
        url_ping_feriados = f"https://www.feriadosapi.com/api/v1/feriados/cidade/3550308?ano={ano_atual}"
        
        resp_feriados = requests.get(url_ping_feriados, headers=headers_feriados, timeout=3)
        
        if resp_feriados.status_code == 200:
            health_status["dependencies"]["feriados_api"] = "online"
        else:
            health_status["dependencies"]["feriados_api"] = f"api_error (Status {resp_feriados.status_code})"
            health_status["status"] = "degraded"
            
    except requests.exceptions.RequestException:
        health_status["dependencies"]["feriados_api"] = "unreachable"
        health_status["status"] = "degraded"

    # 4. Checar Sólides (Futuro)
    # url_solides = "https://api.solides.com.br/health" (Exemplo)
    # Fazer o mesmo request e atualizar health_status["dependencies"]["solides_api"]

    return JsonResponse(health_status, status=status_code)