from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Q, F, Sum
from django.db import transaction
from django.utils import timezone
from django.forms.models import model_to_dict
from datetime import timedelta, datetime, date, time
from collections import defaultdict
import uuid
from .forms import ApontamentoForm
from .models import Apontamento, LogAuditoria, Projeto, Colaborador, Veiculo, CodigoCliente, ApontamentoHistorico, CentroCusto, Notificacao, Feriado
from .utils import (is_owner, is_gerente, pode_fazer_rateio, distribuir_horarios_com_gap, calcular_regras_clt, get_data_contabil, registrar_log)
from .services import ControlePontoService, FeriadoService, WhatsAppService

# ==============================================================================
# 1. VIEWS DE NAVEGAÇÃO E OPERAÇÕES
# ==============================================================================

@login_required
def home_redirect_view(request):
    return redirect('produtividade:home_menu')

@login_required
def home_view(request):
    is_gestor = is_gerente(request.user)
    is_owner_user = is_owner(request.user)

    context = {
        'is_gestor': is_gestor,
        'is_owner': is_owner_user
    }
    return render(request, 'produtividade/home.html', context)

@login_required
def configuracoes_view(request):
    context = {
        'titulo': 'Configurações do Usuário', 
        'change_password_url': '/accounts/password_change/' }
    return render(request, 'produtividade/configuracoes.html', context)

@login_required
def apontamento_atividade_view(request):
    user_kwargs = {'user': request.user}
    
    colaborador_atual = None
    if request.user.is_authenticated:
        try:
            colaborador_atual = getattr(request.user, 'colaborador', None) or Colaborador.objects.get(user_account=request.user)
        except (Colaborador.DoesNotExist, AttributeError):
            pass

    if request.method == 'POST':

        if colaborador_atual and Apontamento.objects.filter(colaborador=colaborador_atual, hora_termino__isnull=True).exists():
            messages.error(request, "Você possui uma atividade em andamento (Check-in). Finalize-a antes de iniciar outra.")
            return redirect('produtividade:novo_apontamento')

        form = ApontamentoForm(request.POST, **user_kwargs)
        if form.is_valid():
            apontamento = form.save(commit=False)
            apontamento.registrado_por = request.user
            apontamento.status_aprovacao = 'EM_ANALISE'
            apontamento.contagem_edicao = 0
            
            # --- Tratamento de Auxiliar/Veículo ---
            if form.cleaned_data.get('registrar_auxiliar'):
                apontamento.auxiliar = form.cleaned_data.get('auxiliar_selecao')
            else:
                apontamento.auxiliar = None

            if form.cleaned_data.get('registrar_veiculo'):
                selection = form.cleaned_data.get('veiculo_selecao')
                if selection == 'OUTRO':
                    apontamento.veiculo = None
                    apontamento.veiculo_manual_modelo = form.cleaned_data.get('veiculo_manual_modelo')
                    apontamento.veiculo_manual_placa = form.cleaned_data.get('veiculo_manual_placa')
                else:
                    try:
                        apontamento.veiculo = Veiculo.objects.get(pk=selection)
                        apontamento.veiculo_manual_modelo = None; apontamento.veiculo_manual_placa = None
                    except Veiculo.DoesNotExist: apontamento.veiculo = None
            else:
                apontamento.veiculo = None; apontamento.veiculo_manual_modelo = None; apontamento.veiculo_manual_placa = None

            # --- RATEIO ---
            extras_obras_str = form.cleaned_data.get('obras_extras_list')
            user_can_rateio = pode_fazer_rateio(request.user)
            
            is_rateio = user_can_rateio and (form.cleaned_data.get('registrar_multiplas_obras') or extras_obras_str)

            if is_rateio:
                agrupamento_uid = str(uuid.uuid4()) 

                principal_str = ""
                if apontamento.projeto: principal_str = f"P_{apontamento.projeto.id}"
                elif apontamento.codigo_cliente: principal_str = f"C_{apontamento.codigo_cliente.id}"
                
                lista_extras = [x.strip() for x in extras_obras_str.split(',') if x.strip()] if extras_obras_str else []
                todas_obras_raw = ([principal_str] + lista_extras) if principal_str else lista_extras

                if not todas_obras_raw:
                    apontamento.status_aprovacao = 'EM_ANALISE'
                    apontamento.save()
                    messages.success(request, "Registro salvo (único).")
                    return redirect('produtividade:novo_apontamento')

                horarios = distribuir_horarios_com_gap(apontamento.hora_inicio, apontamento.hora_termino, len(todas_obras_raw))
                aux_extras_str = form.cleaned_data.get('auxiliares_extras_list')
                ids_aux_list = [int(x) for x in aux_extras_str.split(',') if x.strip().isdigit()] if aux_extras_str else []
                contagem_sucesso = 0

                try:
                    with transaction.atomic():
                        for idx, item_hibrido in enumerate(todas_obras_raw):
                            if '_' not in item_hibrido: continue
                            prefixo, obj_id_str = item_hibrido.split('_')
                            obj_id = int(obj_id_str)

                            novo_registro = Apontamento()
                            novo_registro.colaborador = apontamento.colaborador
                            novo_registro.data_apontamento = apontamento.data_apontamento
                            novo_registro.local_execucao = apontamento.local_execucao
                            novo_registro.veiculo = apontamento.veiculo
                            novo_registro.veiculo_manual_modelo = apontamento.veiculo_manual_modelo
                            novo_registro.veiculo_manual_placa = apontamento.veiculo_manual_placa
                            novo_registro.auxiliar = apontamento.auxiliar
                            novo_registro.ocorrencias = apontamento.ocorrencias
                            novo_registro.em_plantao = apontamento.em_plantao
                            novo_registro.data_plantao = apontamento.data_plantao
                            novo_registro.dorme_fora = apontamento.dorme_fora
                            novo_registro.data_dorme_fora = apontamento.data_dorme_fora
                            novo_registro.latitude = apontamento.latitude
                            novo_registro.longitude = apontamento.longitude
                            novo_registro.registrado_por = request.user
                            novo_registro.status_aprovacao = 'EM_ANALISE'
                            novo_registro.contagem_edicao = 0
                            novo_registro.id_agrupamento = agrupamento_uid 

                            if idx < len(horarios):
                                novo_registro.hora_inicio = horarios[idx][0]
                                novo_registro.hora_termino = horarios[idx][1]
                            
                            if prefixo == 'P':
                                if not Projeto.objects.filter(pk=obj_id).exists(): continue
                                novo_registro.projeto_id = obj_id; novo_registro.codigo_cliente = None
                            elif prefixo == 'C':
                                if not CodigoCliente.objects.filter(pk=obj_id).exists(): continue
                                novo_registro.codigo_cliente_id = obj_id; novo_registro.projeto = None
                            
                            novo_registro.save()

                            try:
                                nome_obra = novo_registro.projeto.nome if novo_registro.projeto else (novo_registro.codigo_cliente.nome if novo_registro.codigo_cliente else "Obra Indefinida")
                                detalhe_log = f"Rateio automático criado: {nome_obra} | Horário: {novo_registro.hora_inicio} - {novo_registro.hora_termino}"
                                registrar_log(request, 'CRIACAO', 'Apontamento', novo_registro.id, detalhe_log)
                            except Exception: pass

                            dt_contabil = get_data_contabil(timezone.make_aware(datetime.combine(novo_registro.data_apontamento, novo_registro.hora_inicio)))
                            calcular_regras_clt(novo_registro.colaborador, dt_contabil)

                            contagem_sucesso += 1
                            if form.cleaned_data.get('registrar_auxiliar') and ids_aux_list:
                                novo_registro.auxiliares_extras.set(ids_aux_list)
                
                    messages.success(request, f"Rateio realizado com sucesso: {contagem_sucesso} registros criados.")
                
                except Exception as e:
                    messages.error(request, f"Erro ao salvar rateio (nenhum registro foi criado): {e}")
                    return redirect('produtividade:novo_apontamento')
                
                return redirect('produtividade:novo_apontamento')

            else:
                apontamento.status_aprovacao = 'EM_ANALISE'
                apontamento.save()

                try:
                    local_ref = apontamento.projeto.nome if apontamento.projeto else (apontamento.codigo_cliente.nome if apontamento.codigo_cliente else (apontamento.centro_custo.nome if apontamento.centro_custo else "Local Manual"))
                    detalhe_log = f"Registro único criado: {local_ref} | Horário: {apontamento.hora_inicio} - {apontamento.hora_termino}"
                    registrar_log(request, 'CRIACAO', 'Apontamento', apontamento.id, detalhe_log)
                except Exception as log_err:
                    print(f"Falha silenciosa ao gravar log: {log_err}")
                    
                dt_contabil = get_data_contabil(timezone.make_aware(datetime.combine(apontamento.data_apontamento, apontamento.hora_inicio)))
                calcular_regras_clt(apontamento.colaborador, dt_contabil)
                if form.cleaned_data.get('registrar_auxiliar'):
                    ids_string = form.cleaned_data.get('auxiliares_extras_list')
                    if ids_string:
                        ids_list = [int(x) for x in ids_string.split(',') if x.strip().isdigit()]
                        apontamento.auxiliares_extras.set(ids_list)
                    else:
                        apontamento.auxiliares_extras.clear()
                else:
                    apontamento.auxiliares_extras.clear()

                messages.success(request, f"Registro de {apontamento.colaborador} salvo com sucesso!")
                return redirect('produtividade:novo_apontamento')
    else:
        apontamento_ativo = None
        if colaborador_atual:
            apontamento_ativo = Apontamento.objects.filter(colaborador=colaborador_atual, hora_termino__isnull=True).order_by('-id').first()

        if apontamento_ativo:
            initial_data = model_to_dict(apontamento_ativo)
            
            initial_data['data_apontamento'] = apontamento_ativo.data_apontamento.strftime('%d/%m/%Y')
            initial_data['hora_inicio'] = apontamento_ativo.hora_inicio.strftime('%H:%M')
            
            if apontamento_ativo.veiculo:
                initial_data['registrar_veiculo'] = True
                initial_data['veiculo_selecao'] = apontamento_ativo.veiculo.id
            elif apontamento_ativo.veiculo_manual_placa:
                initial_data['registrar_veiculo'] = True
                initial_data['veiculo_selecao'] = 'OUTRO'
            
            if apontamento_ativo.auxiliar:
                initial_data['registrar_auxiliar'] = True
                initial_data['auxiliar_selecao'] = apontamento_ativo.auxiliar.id
                
            form = ApontamentoForm(initial=initial_data, **user_kwargs)
            
        else:
            now_local = timezone.localtime(timezone.now())
            initial_data = {
                'data_apontamento': now_local.strftime('%d/%m/%Y'),
                'hora_inicio': now_local.strftime('%H:%M'),
            }
            form = ApontamentoForm(initial=initial_data, **user_kwargs)

    context = {
        'form': form,
        'titulo': 'Timesheet',
        'subtitulo': 'Preencha os dados de horário e local de trabalho.',
        'is_editing': False,
        'atividade_em_andamento': True if (colaborador_atual and Apontamento.objects.filter(colaborador=colaborador_atual, hora_termino__isnull=True).exists()) else False
    }
    return render(request, 'produtividade/apontamento_form.html', context)


# ==============================================================================
# 2. EDIÇÃO E HISTÓRICO DE APONTAMENTOS
# ==============================================================================

@login_required
def historico_apontamentos_view(request):
    """
    View de Listagem com filtros de data e permissões de visualização.
    """
    user = request.user
    
    # --- Definição de Permissões ---
    eh_owner = is_owner(user)
    eh_gestor = is_gerente(user)
    pode_ver_alertas = eh_owner or eh_gestor

    queryset = Apontamento.objects.select_related(
        'projeto', 'codigo_cliente', 'colaborador', 
        'veiculo', 'centro_custo', 'registrado_por'
    ).prefetch_related('auxiliares_extras').all().order_by(
        '-data_apontamento', 'colaborador', '-hora_termino'
    )

    # --- Filtros de Data ---
    period = request.GET.get('period')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=6)
    current_period = '7'

    if period:
        try:
            days = int(period)
            start_date = end_date - timedelta(days=days - 1)
            current_period = period
            start_date_str = None
            end_date_str = None
        except ValueError:
            pass
    elif start_date_str and end_date_str:
        try:
            start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = timezone.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            current_period = 'custom'
        except ValueError:
            pass

    queryset = queryset.filter(data_apontamento__gte=start_date, data_apontamento__lte=end_date)

    bloqueia_data_antiga = False
    
    # --- Regra de Visualização ---
    if eh_gestor and not eh_owner:
        try:
            gerente_profile = Colaborador.objects.get(user_account=user)
            meus_setores = gerente_profile.setores_gerenciados.all()
            
            filtro_proprio = Q(colaborador=gerente_profile)
            filtro_alertas_equipe = Q(colaborador__setor__in=meus_setores, flag_atencao=True)

            queryset = queryset.filter(filtro_proprio | filtro_alertas_equipe)
            
        except Colaborador.DoesNotExist:
            queryset = queryset.filter(registrado_por=user)

        limit_date = timezone.now().date() - timedelta(days=30)
        
        if start_date < limit_date:
            bloqueia_data_antiga = True
        
        queryset = queryset.filter(data_apontamento__gte=limit_date)

    if not pode_ver_alertas:
        try:
            colab = Colaborador.objects.get(user_account=user)
            queryset = queryset.filter(Q(registrado_por=user) | Q(colaborador=colab))
        except:
            queryset = queryset.filter(registrado_por=user)
        
        limit_date = timezone.now().date() - timedelta(days=30)
        if start_date < limit_date:
            bloqueia_data_antiga = True
        queryset = queryset.filter(data_apontamento__gte=limit_date)

    # --- Cálculo de Durações Totais por Dia/Colaborador ---
    mapa_totais_segundos = defaultdict(int)

    for item in queryset:
        if item.hora_inicio and item.hora_termino:
            key = (item.colaborador.id, item.data_apontamento)
            d = date(2000, 1, 1)
            dt_ini = datetime.combine(d, item.hora_inicio)
            dt_fim = datetime.combine(d, item.hora_termino)
            if dt_fim < dt_ini: dt_fim += timedelta(days=1)
            segundos = (dt_fim - dt_ini).total_seconds()
            mapa_totais_segundos[key] += int(segundos)

    historico_lista = []
    chaves_ja_exibidas = set()
    total_segundos_geral = 0

    for item in queryset:
        if item.local_execucao == 'INT':
            local_tipo_display = "DENTRO DA OBRA"
            if item.projeto:
                p_cod = item.projeto.codigo if item.projeto.codigo else ""
                local_ref = f"{p_cod} - {item.projeto.nome}" if p_cod else f"{item.projeto.nome}"
            elif item.codigo_cliente:
                local_ref = f"{item.codigo_cliente.codigo} - {item.codigo_cliente.nome}"
            else:
                local_ref = "Obra/Cliente não informado"
        else:
            local_tipo_display = "FORA DO SETOR"
            local_ref = item.centro_custo.nome if item.centro_custo else "Atividade Externa"
            if item.projeto:
                local_ref += f" (Obra: {item.projeto.codigo})"
            elif item.codigo_cliente:
                local_ref += f" (CLIENTE: {item.codigo_cliente.codigo})"

        if item.veiculo: 
            veiculo_display = str(item.veiculo)
        elif item.veiculo_manual_placa: 
            veiculo_display = f"{item.veiculo_manual_modelo} - {item.veiculo_manual_placa} (Externo)"
        else: 
            veiculo_display = ""

        reg_user = item.registrado_por
        user_display = f"{reg_user.first_name} {reg_user.last_name}" if reg_user and reg_user.first_name else (reg_user.username if reg_user else "Sistema")

        duracao_formatada = item.duracao_total_str

        key = (item.colaborador.id, item.data_apontamento)
        
        if key not in chaves_ja_exibidas:
            should_show_total = True
            chaves_ja_exibidas.add(key)
        else:
            should_show_total = False
        
        texto_total_dia = ""
        cor_total_dia = "text-gray-500"

        if should_show_total:
            secs = mapa_totais_segundos[key]
            horas = secs // 3600
            mins = (secs % 3600) // 60
            texto_total_dia = f"{horas:02d}:{mins:02d}"

            if "JOVEM APRENDIZ" not in item.colaborador.cargo.upper():
                if secs < 31000: cor_total_dia = "text-orange-400 font-bold" # Menos que ~8h36
                elif secs > 32400: cor_total_dia = "text-blue-400 font-bold" # Mais que 9h
                else: cor_total_dia = "text-emerald-400 font-bold" # Na meta
            else:
                cor_total_dia = "text-gray-400 font-bold"

        exibir_alerta = item.flag_atencao and pode_ver_alertas

        base_dict = {
            'id': item.id,
            'data': item.data_apontamento,
            'local_ref': local_ref,
            'local_tipo': local_tipo_display,
            'inicio': item.hora_inicio,
            'termino': item.hora_termino,
            'duracao': duracao_formatada,
            'obs': item.ocorrencias,
            'registrado_em': item.data_registro,
            'registrado_por_str': user_display,
            'registrado_por_id': item.registrado_por.id if item.registrado_por else None,
            'em_plantao': item.em_plantao,
            'dorme_fora': item.dorme_fora,
            'motivo_ajuste': item.motivo_ajuste,
            'status_ajuste': item.status_ajuste,
            'status_aprovacao': item.status_aprovacao,
            'contagem_edicao': item.contagem_edicao,
            'pode_editar': (item.contagem_edicao < 1) or eh_owner,
            'motivo_rejeicao': item.motivo_rejeicao,
            'latitude': item.latitude,
            'longitude': item.longitude,
            'is_last_of_day': should_show_total,
            'total_dia_str': texto_total_dia,
            'total_dia_class': cor_total_dia,
            'flag_atencao': exibir_alerta, 
            'motivo_alerta': item.motivo_alerta if exibir_alerta else None,
        }

        row_main = base_dict.copy()
        row_main.update({
            'nome': item.colaborador.nome_completo, 
            'cargo': item.colaborador.cargo, 
            'veiculo': veiculo_display, 
            'is_auxiliar': False
        })
        historico_lista.append(row_main)

        auxiliares_a_exibir = []
        if item.auxiliar: auxiliares_a_exibir.append(item.auxiliar)
        extras = item.auxiliares_extras.all()
        auxiliares_a_exibir.extend(extras)

        for aux in auxiliares_a_exibir:
            row_aux = base_dict.copy()
            row_aux.update({
                'nome': aux.nome_completo,
                'cargo': aux.cargo,
                'veiculo': "",
                'is_auxiliar': True,
                'is_last_of_day': False,
                'flag_atencao': False,
            })
            historico_lista.append(row_aux)

    context = {
        'titulo': "Histórico",
        'apontamentos_lista': historico_lista,
        'show_user_column': eh_owner, 
        'is_owner': eh_owner,
        'is_gestor': eh_gestor,
        'current_period': current_period,
        'start_date_val': start_date.strftime('%Y-%m-%d'),
        'end_date_val': end_date.strftime('%Y-%m-%d'),
        'bloqueia_data_antiga': bloqueia_data_antiga,
    }
    return render(request, 'produtividade/historico_apontamentos.html', context)

@login_required
def editar_apontamento_view(request, pk):
    """
    Edição com controle de versão e limite de 1x.
    """
    apontamento = get_object_or_404(Apontamento, pk=pk)
    user = request.user

    if not is_owner(user) and apontamento.registrado_por != user:
        messages.error(request, "Acesso Negado: Você só pode editar seus próprios apontamentos.")
        return redirect('produtividade:historico_apontamentos')

    if apontamento.contagem_edicao >= 1 and not is_owner(user):
        messages.error(request, "Limite de edição atingido. Para correções, utilize a opção 'Solicitar Ajuste'.")
        return redirect('produtividade:historico_apontamentos')

    user_kwargs = {'user': request.user, 'instance': apontamento}

    if request.method == 'POST':
        dados_originais = model_to_dict(apontamento, exclude=['auxiliares_extras', 'user_account'])
        
        for k, v in dados_originais.items():
            if isinstance(v, (datetime, date, time)): 
                dados_originais[k] = v.isoformat()
            elif isinstance(v, timedelta): 
                dados_originais[k] = str(v)

        form = ApontamentoForm(request.POST, **user_kwargs)
        if form.is_valid():
            with transaction.atomic():
                ApontamentoHistorico.objects.create(
                    apontamento_original=apontamento,
                    dados_snapshot=dados_originais,
                    editado_por=user,
                    numero_edicao=apontamento.contagem_edicao + 1
                )

                obj = form.save(commit=False)
                obj.contagem_edicao += 1
                obj.status_aprovacao = 'EM_ANALISE'
                obj.motivo_rejeicao = None
                
                if not form.cleaned_data.get('registrar_auxiliar'): obj.auxiliar = None
                if not form.cleaned_data.get('registrar_veiculo'):
                    obj.veiculo = None; obj.veiculo_manual_modelo = None; obj.veiculo_manual_placa = None
                
                obj.save()

                registrar_log(
                    request, 
                    'EDICAO', 
                    'Apontamento', 
                    obj.id, 
                    f"Edição realizada (Versão {obj.contagem_edicao})."
                )

                dt_contabil = get_data_contabil(timezone.make_aware(datetime.combine(obj.data_apontamento, obj.hora_inicio)))
                calcular_regras_clt(obj.colaborador, dt_contabil)

                if form.cleaned_data.get('registrar_auxiliar'):
                    ids_string = form.cleaned_data.get('auxiliares_extras_list')
                    if ids_string:
                        ids_list = [int(x) for x in ids_string.split(',') if x.strip().isdigit()]
                        obj.auxiliares_extras.set(ids_list)
                    else: obj.auxiliares_extras.clear()
                else: obj.auxiliares_extras.clear()

            messages.success(request, "Apontamento editado com sucesso! (Histórico salvo)")
            return redirect('produtividade:historico_apontamentos')
    else:
        initial_data = {}
        if apontamento.veiculo:
            initial_data['registrar_veiculo'] = True
            initial_data['veiculo_selecao'] = apontamento.veiculo.id
        elif apontamento.veiculo_manual_placa:
            initial_data['registrar_veiculo'] = True
            initial_data['veiculo_selecao'] = 'OUTRO'
        if apontamento.auxiliar:
            initial_data['registrar_auxiliar'] = True
            ids_list = list(apontamento.auxiliares_extras.values_list('id', flat=True))
            initial_data['auxiliares_extras_list'] = ",".join(map(str, ids_list))

        form = ApontamentoForm(initial=initial_data, **user_kwargs)

    context = {
        'form': form,
        'titulo': 'Editar Apontamento',
        'subtitulo': f'Editando registro (Versão {apontamento.contagem_edicao + 1})',
        'is_editing': True,
        'apontamento_id': pk
    }
    return render(request, 'produtividade/apontamento_form.html', context)

@login_required
def solicitar_ajuste_view(request, pk):
    """
    Permite que o usuário ou colaborador solicite um ajuste em um registro fechado.
    """
    apontamento = get_object_or_404(Apontamento, pk=pk)
    
    # Segurança: Só permite se o usuário for o dono do registro ou o colaborador vinculado
    is_autor = apontamento.registrado_por == request.user
    is_colaborador = False
    try:
        colab = Colaborador.objects.get(user_account=request.user)
        if apontamento.colaborador == colab:
            is_colaborador = True
    except Colaborador.DoesNotExist:
        pass

    if not (is_autor or is_colaborador or request.user.is_superuser):
         messages.error(request, "Você não tem permissão para solicitar ajuste neste registro.")
         return redirect('produtividade:historico_apontamentos')

    if request.method == 'POST':
        motivo = request.POST.get('motivo_texto')
        if motivo:
            apontamento.motivo_ajuste = motivo
            apontamento.status_aprovacao = 'SOLICITACAO_AJUSTE' 
            apontamento.status_ajuste = 'PENDENTE' 
            apontamento.save()

            registrar_log(request, 'SOLICITACAO', 'Apontamento', pk, f"Solicitou ajuste. Motivo: {motivo}")

            messages.success(request, "Solicitação de ajuste enviada para a administração.")
        else:
            messages.warning(request, "É necessário descrever o motivo do ajuste.")
            
    return redirect('produtividade:historico_apontamentos')

@login_required
@user_passes_test(is_owner)
def excluir_apontamento_view(request, pk):
    """Exclusão de registro (Acesso Admin)."""
    apontamento = get_object_or_404(Apontamento, pk=pk)
    colaborador = apontamento.colaborador
    dt_ref = get_data_contabil(timezone.make_aware(datetime.combine(apontamento.data_apontamento, apontamento.hora_inicio)))

    detalhes = f"Exclusão realizada. Colab: {colaborador.nome_completo} | Data: {apontamento.data_apontamento} | ID Original: {pk}"
    registrar_log(request, 'EXCLUSAO', 'Apontamento', pk, detalhes)

    apontamento.delete()
    calcular_regras_clt(colaborador, dt_ref)
    messages.success(request, "Apontamento excluído com sucesso.")
    return redirect('produtividade:historico_apontamentos')

@login_required
@user_passes_test(is_owner)
def aprovar_ajuste_view(request, pk):
    """Aprovação rápida de ajuste sem necessidade de edição."""
    apontamento = get_object_or_404(Apontamento, pk=pk)
    apontamento.status_ajuste = 'APROVADO'
    apontamento.save()

    registrar_log(request, 'APROVACAO_AJUSTE', 'Apontamento', pk, "Owner aprovou a solicitação de ajuste pendente.")

    messages.success(request, "Solicitação marcada como APROVADA.")
    return redirect('produtividade:historico_apontamentos')

@login_required
def apontamento_sucesso_view(request):
    return render(request, 'produtividade/apontamento_sucesso.html')

# ==============================================================================
# 6. APROVAÇÃO DE AJUSTES (GERENTE)
# ==============================================================================

@login_required
@user_passes_test(is_gerente)
def aprovacao_dashboard_view(request):
    """
    Lista de pendências para o Gerente.
    Se for Owner (Superuser), vê tudo.
    Se for Gestor Comum, vê apenas colaboradores dos seus setores.
    """

    is_owner_user = is_owner(request.user)
    if is_owner_user:
        pendentes = Apontamento.objects.filter(
            status_aprovacao='EM_ANALISE'
        ).select_related('colaborador', 'projeto', 'centro_custo').order_by('-data_apontamento', 'colaborador', '-hora_termino')
        
    else:
        try:
            gerente = Colaborador.objects.get(user_account=request.user)
            meus_setores = gerente.setores_gerenciados.all()
            
            pendentes = Apontamento.objects.filter(
                status_aprovacao='EM_ANALISE',
                colaborador__setor__in=meus_setores
            ).exclude(colaborador=gerente).select_related('colaborador', 'projeto', 'centro_custo').order_by('-data_apontamento', 'colaborador', '-hora_termino')
            
        except Colaborador.DoesNotExist:
            messages.error(request, "Seu usuário não está vinculado a um cadastro de Colaborador/Gestor.")
            return redirect('produtividade:home_menu')

    context = {
        'is_owner': is_owner_user,
        'pendentes': pendentes,
        'titulo': 'Central de Aprovações'
    }
    return render(request, 'produtividade/aprovacao_dashboard.html', context)


@login_required
@user_passes_test(is_gerente)
def analise_apontamento_view(request, pk):
    """
    Tela detalhada para comparar a versão anterior com a atual (Diff Completo).
    """
    apontamento = get_object_or_404(Apontamento, pk=pk)
    
    def item_time_str(t): 
        return t.strftime('%H:%M') if t else ""

    historico = ApontamentoHistorico.objects.filter(apontamento_original=apontamento).order_by('-numero_edicao').first()
    
    diff_data = []
    tem_alteracao = False

    if historico:
        dados_antigos = historico.dados_snapshot
        
        def format_bool(val):
            return "SIM" if val else "NÃO"

        def format_none(val):
            return val if val else "-"

        def get_fk_name(ModelClass, pk):
            if not pk: return "-"
            try:
                return str(ModelClass.objects.get(pk=pk))
            except:
                return f"(ID: {pk} removido)"

        # --- 1. Comparação de Horários ---
        h_ini_old = str(dados_antigos.get('hora_inicio', ''))[:5]
        h_ini_new = item_time_str(apontamento.hora_inicio)
        if h_ini_old != h_ini_new:
            diff_data.append({'campo': 'Hora Início', 'antes': h_ini_old, 'depois': h_ini_new, 'icon': 'clock'})

        h_fim_old = str(dados_antigos.get('hora_termino', ''))[:5]
        h_fim_new = item_time_str(apontamento.hora_termino)
        if h_fim_old != h_fim_new:
            diff_data.append({'campo': 'Hora Término', 'antes': h_fim_old, 'depois': h_fim_new, 'icon': 'clock'})

        # --- 2. Comparação de Local ---
        local_old = dados_antigos.get('local_execucao')
        local_new = apontamento.local_execucao
        if local_old != local_new:
            mapa = {'INT': 'DENTRO DA OBRA', 'EXT': 'FORA DA OBRA'}
            diff_data.append({'campo': 'Local', 'antes': mapa.get(local_old, local_old), 'depois': mapa.get(local_new, local_new), 'icon': 'map'})

        # --- 3. Comparação de Projeto ---
        proj_old_id = dados_antigos.get('projeto')
        proj_new_id = apontamento.projeto.id if apontamento.projeto else None
        if proj_old_id != proj_new_id:
            nome_old = get_fk_name(Projeto, proj_old_id)
            nome_new = str(apontamento.projeto) if apontamento.projeto else "-"
            diff_data.append({'campo': 'Projeto/Obra', 'antes': nome_old, 'depois': nome_new, 'icon': 'briefcase'})

        # --- 4. Comparação de Cliente ---
        cli_old_id = dados_antigos.get('codigo_cliente')
        cli_new_id = apontamento.codigo_cliente.id if apontamento.codigo_cliente else None
        if cli_old_id != cli_new_id:
            nome_old = get_fk_name(CodigoCliente, cli_old_id)
            nome_new = str(apontamento.codigo_cliente) if apontamento.codigo_cliente else "-"
            diff_data.append({'campo': 'Cliente', 'antes': nome_old, 'depois': nome_new, 'icon': 'user'})

        # --- 5. Comparação de Veículos ---
        veic_old_id = dados_antigos.get('veiculo')
        veic_new_id = apontamento.veiculo.id if apontamento.veiculo else None
        
        veic_man_placa_old = dados_antigos.get('veiculo_manual_placa')
        veic_man_placa_new = apontamento.veiculo_manual_placa

        if veic_old_id != veic_new_id:
            nome_old = get_fk_name(Veiculo, veic_old_id)
            nome_new = str(apontamento.veiculo) if apontamento.veiculo else "-"
            diff_data.append({'campo': 'Veículo (Frota)', 'antes': nome_old, 'depois': nome_new, 'icon': 'truck'})
        
        if str(veic_man_placa_old) != str(veic_man_placa_new):
             diff_data.append({'campo': 'Veículo (Externo/Placa)', 'antes': format_none(veic_man_placa_old), 'depois': format_none(veic_man_placa_new), 'icon': 'truck'})

        # --- 6. Comparação de Plantão ---
        if dados_antigos.get('em_plantao') != apontamento.em_plantao:
            diff_data.append({
                'campo': 'Em Plantão?', 
                'antes': format_bool(dados_antigos.get('em_plantao')), 
                'depois': format_bool(apontamento.em_plantao),
                'icon': 'siren'
            })

        # --- 7. Comparação de Dorme-Fora ---
        if dados_antigos.get('dorme_fora') != apontamento.dorme_fora:
            diff_data.append({
                'campo': 'Dorme Fora?', 
                'antes': format_bool(dados_antigos.get('dorme_fora')), 
                'depois': format_bool(apontamento.dorme_fora),
                'icon': 'moon'
            })

        # --- 8. Comparação de Ocorreências
        obs_old = str(dados_antigos.get('ocorrencias', '') or '').strip()
        obs_new = str(apontamento.ocorrencias or '').strip()
        if obs_old != obs_new:
            diff_data.append({'campo': 'Observações', 'antes': obs_old, 'depois': obs_new, 'icon': 'pencil'})

        # --- 9. Comparação de Centro de Custo ---
        cc_old_id = dados_antigos.get('centro_custo')
        cc_new_id = apontamento.centro_custo.id if apontamento.centro_custo else None
        if cc_old_id != cc_new_id:
            nome_old = get_fk_name(CentroCusto, cc_old_id)
            nome_new = str(apontamento.centro_custo) if apontamento.centro_custo else "-"
            diff_data.append({'campo': 'Centro de Custo', 'antes': nome_old, 'depois': nome_new, 'icon': 'map'})

        # --- 10. Comparação de Modelo Veículo ---
        mod_old = str(dados_antigos.get('veiculo_manual_modelo') or '')
        mod_new = str(apontamento.veiculo_manual_modelo or '')
        if mod_old != mod_new:
            diff_data.append({'campo': 'Modelo Veículo (Manual)', 'antes': format_none(mod_old), 'depois': format_none(mod_new), 'icon': 'truck'})

        # --- 11. Comparação de Auxiliar ---
        aux_old_id = dados_antigos.get('auxiliar')
        aux_new_id = apontamento.auxiliar.id if apontamento.auxiliar else None
        if aux_old_id != aux_new_id:
            nome_old = get_fk_name(Colaborador, aux_old_id)
            nome_new = str(apontamento.auxiliar.nome_completo) if apontamento.auxiliar else "-"
            diff_data.append({'campo': 'Auxiliar Principal', 'antes': nome_old, 'depois': nome_new, 'icon': 'user'})

        # --- 12. Comparação de Data de Registro ---
        data_old_str = str(dados_antigos.get('data_apontamento'))
        data_new_str = apontamento.data_apontamento.strftime('%Y-%m-%d')
        if data_old_str != data_new_str:
             d_old_fmt = datetime.strptime(data_old_str, '%Y-%m-%d').strftime('%d/%m/%Y')
             d_new_fmt = apontamento.data_apontamento.strftime('%d/%m/%Y')
             diff_data.append({'campo': 'Data do Registro', 'antes': d_old_fmt, 'depois': d_new_fmt, 'icon': 'calendar'})

        if diff_data: tem_alteracao = True   

    context = {
        'apontamento': apontamento,
        'historico': historico,
        'diffs': diff_data,
        'tem_alteracao': tem_alteracao,
        'duracao_total': apontamento.duracao_total_str if hasattr(apontamento, 'duracao_total_str') else "Calculando...",
        'usuario_editor': historico.editado_por if historico else None
    }
    return render(request, 'produtividade/aprovacao_analise.html', context)


@login_required
@user_passes_test(is_gerente)
def processar_aprovacao_view(request, pk):
    if request.method != 'POST': 
        return redirect('produtividade:aprovacao_dashboard')
    
    apontamento = get_object_or_404(Apontamento, pk=pk)
    acao = request.POST.get('acao')
    motivo = request.POST.get('motivo_rejeicao', '').strip()

    if not motivo:
        messages.error(request, "É obrigatório inserir um comentário/motivo para finalizar a análise.")
        return redirect('produtividade:analise_apontamento', pk=pk)

    if acao == 'APROVAR':
        apontamento.status_aprovacao = 'APROVADO'
        apontamento.motivo_rejeicao = motivo 
        messages.success(request, f"Registro APROVADO com sucesso.")
        registrar_log(request, 'APROVACAO', 'Apontamento', apontamento.id, "Apontamento aprovado pelo Gestor.")
    
    elif acao == 'REJEITAR':
        apontamento.status_aprovacao = 'REJEITADO'
        apontamento.motivo_rejeicao = motivo
        messages.warning(request, f"Registro REJEITADO. O colaborador foi notificado.")
        registrar_log(request, 'REJEICAO', 'Apontamento', apontamento.id, f"Rejeitado. Motivo: {motivo}")

    apontamento.save()
    
    return redirect('produtividade:aprovacao_dashboard')


@login_required
@user_passes_test(is_owner)
def dashboard_conformidade_view(request):
    """
    Dashboard exclusivo para Owner monitorar quem entregou as horas corretamente.
    Busca pela API do Sólides ás horas trabalhadas.
    """
    data_str = request.GET.get('data')
    if data_str:
        try:
            data_ref = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            data_ref = timezone.now().date()
    else:
        data_ref = timezone.now().date()
    
    colaboradores = Colaborador.objects.filter(user_account__is_active=True).order_by('nome_completo')

    mes = data_ref.month
    ano = data_ref.year
    mapa_escalas = ControlePontoService.obter_escalas_do_mes(colaboradores, mes, ano)

    lista_ok = []
    lista_incompleto = []
    lista_ausente = []

    feriado_obj = Feriado.objects.filter(data=data_ref).first()
    nome_feriado_display = feriado_obj.descricao if feriado_obj else None
    is_feriado = bool(feriado_obj)
    is_fim_de_semana = data_ref.weekday() >= 5

    for colab in colaboradores:
        apontamentos = Apontamento.objects.filter(colaborador=colab, data_apontamento=data_ref)
        tem_apontamento = apontamentos.exists()
        
        total_segundos = 0
        qtd_registros = 0

        if tem_apontamento:
            for apt in apontamentos:
                if apt.hora_inicio and apt.hora_termino:
                    dummy = date(2000, 1, 1)
                    dt_ini = datetime.combine(dummy, apt.hora_inicio)
                    dt_fim = datetime.combine(dummy, apt.hora_termino)
                    
                    if dt_fim < dt_ini:
                        dt_fim += timedelta(days=1)
                    
                    total_segundos += (dt_fim - dt_ini).total_seconds()
                    qtd_registros += 1

        dados_ponto = mapa_escalas.get(colab.id, {}).get(data_ref)
        
        if not dados_ponto:
            dados_ponto = {'deve_notificar': True, 'meta_segundos': 31680, 'tolerancia_segundos': 600}
            if is_feriado or is_fim_de_semana:
                 dados_ponto['deve_notificar'] = False
                 dados_ponto['meta_segundos'] = 0

        if not dados_ponto.get('deve_notificar', True):
            meta_segundos = 0
            tolerancia = 0
        else:
            meta_segundos = dados_ponto.get('meta_segundos', 31680)
            tolerancia = dados_ponto.get('tolerancia_segundos', 600)

        if meta_segundos == 0 and total_segundos == 0:
            continue

        horas = int(total_segundos // 3600)
        minutos = int((total_segundos % 3600) // 60)
        tempo_str = f"{horas:02d}:{minutos:02d}"

        dados_colab = {
            'nome': colab.nome_completo,
            'cargo': colab.cargo,
            'total_str': tempo_str,
            'qtd_registros': qtd_registros,
        }

        # 5. DISTRIBUIÇÃO NAS LISTAS
        if total_segundos == 0:
            lista_ausente.append(dados_colab)
            
        elif total_segundos >= (meta_segundos - tolerancia):
            if total_segundos > meta_segundos:
                superavit = total_segundos - meta_segundos
                h_sup = int(superavit // 3600)
                m_sup = int((superavit % 3600) // 60)
                dados_colab['saldo_positivo'] = f"+{h_sup:02d}:{m_sup:02d}"
            
            lista_ok.append(dados_colab)
            
        else:
            deficit = meta_segundos - total_segundos
            h_def = int(deficit // 3600)
            m_def = int((deficit % 3600) // 60)
            dados_colab['saldo_negativo'] = f"-{h_def:02d}:{m_def:02d}"
            
            lista_incompleto.append(dados_colab)

    total_pertinentes = len(lista_ok) + len(lista_incompleto) + len(lista_ausente)
    enviaram_apontamento = len(lista_ok) + len(lista_incompleto)

    percentual_adesao = int((enviaram_apontamento / total_pertinentes) * 100) if total_pertinentes > 0 else 0

    context = {
        'titulo': 'Monitoramento de Conformidade',
        'is_owner': True,
        'data_ref': data_ref,
        'data_ref_str': data_ref.strftime('%Y-%m-%d'),
        'next_date': (data_ref + timedelta(days=1)).strftime('%Y-%m-%d'),
        'prev_date': (data_ref - timedelta(days=1)).strftime('%Y-%m-%d'),
        'lista_ok': lista_ok,
        'lista_incompleto': lista_incompleto,
        'lista_ausente': lista_ausente,
        'total_colaboradores': total_pertinentes,
        'percentual_adesao': percentual_adesao,
        'nome_feriado': nome_feriado_display,
        'is_feriado': is_feriado or is_fim_de_semana
    }

    return render(request, 'produtividade/dashboard_conformidade.html', context)


@login_required
@user_passes_test(is_owner)
def notificar_pendencias_view(request):
    if request.method != 'POST':
        return redirect('produtividade:dashboard_conformidade')

    data_str = request.POST.get('data_ref')
    try:
        data_ref = datetime.strptime(data_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        messages.error(request, "Data inválida para notificação.")
        return redirect('produtividade:dashboard_conformidade')
    
    colaboradores = Colaborador.objects.filter(user_account__is_active=True)
    
    notificacoes_criar = []
    count_criadas = 0

    for colab in colaboradores:
        if not colab.user_account:
            continue

        dados_ponto = ControlePontoService.obter_meta_do_dia(colab, data_ref)

        if not dados_ponto['deve_notificar']:
            continue

        meta_segundos = dados_ponto['meta_segundos']
        tolerancia = dados_ponto['tolerancia_segundos']

        apontamentos = Apontamento.objects.filter(colaborador=colab, data_apontamento=data_ref)
        total_segundos = 0
        
        for apt in apontamentos:
            if apt.hora_inicio and apt.hora_termino:
                dummy = date(2000, 1, 1)
                dt_ini = datetime.combine(dummy, apt.hora_inicio)
                dt_fim = datetime.combine(dummy, apt.hora_termino)
                if dt_fim < dt_ini: dt_fim += timedelta(days=1)
                total_segundos += (dt_fim - dt_ini).total_seconds()

        if total_segundos == 0:
            notificacoes_criar.append(Notificacao(
                colaborador=colab,
                titulo="Ausência de Registro",
                mensagem=f"Olá {colab.nome_completo.split()[0]}, não identificamos apontamentos seus no dia {data_ref.strftime('%d/%m')}. Por favor, verifique.",
                tipo='ALERTA',
                data_referencia=data_ref
            ))
            count_criadas += 1
            
        elif total_segundos < (meta_segundos - tolerancia):
            notificacoes_criar.append(Notificacao(
                colaborador=colab,
                titulo="Horas Incompletas",
                mensagem=f"Olá {colab.nome_completo.split()[0]}, identificamos divergência nos horários registrados entre seu Tangerino e seu apontamento no Timesheet do dia {data_ref.strftime('%d/%m')}. Por favor, verifique seus envios.",
                tipo='ALERTA',
                data_referencia=data_ref
            ))
            count_criadas += 1

    if notificacoes_criar:
        Notificacao.objects.bulk_create(notificacoes_criar)

        wpp_enviados = 0
        for notif in notificacoes_criar:
            if notif.tipo == 'ALERTA':
                
                msg_wpp = (
                    f"*⚠️ Atenção*\n\n"
                    f"Olá {notif.colaborador.nome_completo.split()[0]},\n"
                    f"Há notificações no seu Timesheet referentes ao dia {notif.data_referencia.strftime('%d/%m/%Y')}.\n"
                    f"Por favor, acesse o sistema para verificar."
                )
                
                sucesso = WhatsAppService.enviar_notificacao_pendencia(notif.colaborador, msg_wpp)
                if sucesso:
                    wpp_enviados += 1

        messages.success(request, f"Sucesso! {count_criadas} notificações foram enviadas. WhatsApp enviado para {wpp_enviados} colaboradores.")
    else:
        messages.info(request, "Nenhuma pendência encontrada para notificar neste dia (Dia ok ou folga/feriado).")

    return redirect(f'/produtividade/dashboard/conformidade/?data={data_str}')


@login_required
def marcar_todas_lidas_view(request):
    """
    Marca todas as notificações do usuário como lidas.
    """
    if request.method == 'POST':
        try:
            colab = Colaborador.objects.get(user_account=request.user)
            Notificacao.objects.filter(colaborador=colab, lida=False).update(lida=True)
            messages.success(request, "Notificações marcadas como lidas.")
        except Colaborador.DoesNotExist:
            pass
    
    return redirect(request.META.get('HTTP_REFERER', 'produtividade:home_menu'))


@login_required
def responder_notificacao_view(request, pk):
    """
    Salva a resposta do colaborador na notificação
    """
    if request.method == 'POST':
        notif = get_object_or_404(Notificacao, pk=pk)
        
        try:
            colab = Colaborador.objects.get(user_account=request.user)
            if notif.colaborador != colab:
                messages.error(request, "Acesso negado.")
                return redirect('produtividade:home_menu')
        except:
            pass

        resposta = request.POST.get('resposta_texto')
        if resposta:
            notif.comentario_colaborador = resposta
            notif.lida = True
            notif.save()
            messages.success(request, "Resposta enviada ao gestor.")
        
    return redirect(request.META.get('HTTP_REFERER', 'produtividade:home_menu'))


@login_required
@user_passes_test(is_owner)
def enviar_aviso_personalizado_view(request):
    """
    Owner envia mensagem manual
    """
    if request.method == 'POST':
        colab_id = request.POST.get('colaborador_id')
        titulo = request.POST.get('titulo')
        msg = request.POST.get('mensagem')
        data_ref_str = request.POST.get('data_referencia')
        
        if colab_id and titulo and msg:
            colab = get_object_or_404(Colaborador, pk=colab_id)

            data_final = datetime.now().date()
            
            if data_ref_str:
                try:
                    data_final = datetime.strptime(data_ref_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            data_formatada_msg = data_final.strftime('%d/%m/%Y')

            notificacao = Notificacao.objects.create(
                colaborador=colab,
                titulo=titulo,
                mensagem=msg,
                tipo='INFO',
                data_referencia=data_final
            )

            msg_wpp = (
                    f"*⚠️ Atenção*\n\n"
                    f"Olá {colab.nome_completo.split()[0]},\n"
                    f"Há notificações no seu Timesheet referentes ao dia {data_formatada_msg}.\n"
                    f"Por favor, acesse o sistema para verificar."
                )

            sucesso = WhatsAppService.enviar_notificacao_pendencia(colab, msg_wpp)

            status_envio = "WhatsApp enviado." if sucesso else "Falha ao enviar WhatsApp."

            detalhes_log = (
                f"Aviso manual disparado para: {colab.nome_completo}. "
                f"Título: '{titulo}'. "
                f"Ref: {data_formatada_msg}. "
                f"Status WhatsApp: {status_envio}."
            )
            registrar_log(
                request,
                acao='CRIACAO',
                modelo='Notificacao',
                obj_id=notificacao.id,
                detalhes=detalhes_log
            )
            if sucesso:
                messages.success(request, f"Mensagem enviada para {colab.nome_completo} via WhatsApp. (Ref: {data_formatada_msg})")
            else:
                messages.warning(request, f"Mensagem enviada para {colab.nome_completo} apenas pelo sistema, falha via WhatsApp.")
        else:
            messages.error(request, "Preencha todos os campos.")
            
    return redirect('produtividade:dashboard_conformidade')


@login_required
@user_passes_test(is_owner)
def painel_owner_view(request):
    """
    Hub central de administração (Owner).
    """
    context = {
        'titulo': 'Painel Administrativo'
    }
    return render(request, 'produtividade/owner_dashboard.html', context)


@login_required
@user_passes_test(is_owner)
def dashboard_auditoria_view(request):
    logs = LogAuditoria.objects.select_related('usuario').all().order_by('-data_hora')

    # --- Filtros ---
    user_id = request.GET.get('user')
    acao = request.GET.get('acao')
    data_ini = request.GET.get('data_ini')
    
    if user_id:
        logs = logs.filter(usuario_id=user_id)
    
    if acao:
        logs = logs.filter(acao=acao)
        
    if data_ini:
        logs = logs.filter(data_hora__date=data_ini)

    logs = logs[:200]

    usuarios = User.objects.all().order_by('username')
    
    context = {
        'titulo': 'Trilha de Auditoria',
        'logs': logs,
        'usuarios': usuarios,
        'filtro_user': int(user_id) if user_id else '',
        'filtro_acao': acao,
        'filtro_data': data_ini
    }
    return render(request, 'produtividade/auditoria_dashboard.html', context)