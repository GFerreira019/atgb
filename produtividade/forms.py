from django import forms
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.db.models import Q, F
from datetime import datetime, timedelta, time
from .models import Apontamento, Colaborador, Veiculo, Projeto, Setor, CodigoCliente, CentroCusto

class ApontamentoForm(forms.ModelForm):
    """
    Formulário principal para registro de apontamentos de produtividade.
    Gerencia a entrada de dados, validações de regra de negócio (conflitos, locais)
    e controle de acesso aos campos baseados no nível do usuário (RBAC).
    """

    # ==========================================================================
    # CAMPOS VISUAIS E COMPLEMENTARES
    # ==========================================================================
    
    codigo_cliente = forms.ModelChoiceField(
        queryset=CodigoCliente.objects.filter(ativo=True),
        required=False,
        label="Código do Cliente",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    cargo_colaborador = forms.CharField(
        required=False, 
        disabled=True, 
        label="Cargo", 
        initial="-"
    )

    # --- Gestão de Veículos ---
    registrar_veiculo = forms.BooleanField(
        required=False, 
        label="Adicionar veículo"
    )
    
    veiculo_selecao = forms.ChoiceField(
        required=False, 
        label="Selecione o Veículo",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    veiculo_manual_modelo = forms.CharField(
        required=False, 
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Ex: Fiat Strada'
        })
    )
    veiculo_manual_placa = forms.CharField(
        required=False, 
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'ABC1234', 
            'maxlength': '7', 
            'style': 'text-transform:uppercase'
        })
    )

    # --- Gestão de Auxiliares ---
    registrar_auxiliar = forms.BooleanField(
        required=False, 
        label="Adicionar Auxiliares?"
    )
    
    auxiliar_selecao = forms.ModelChoiceField(
        queryset=Colaborador.objects.filter(
            cargo__in=['AUXILIAR TECNICO', 'OFICIAL DE SISTEMAS']
        ), 
        required=False, 
        label="Auxiliar Principal"
    )
    
    auxiliares_extras_list = forms.CharField(
        required=False, 
        widget=forms.HiddenInput()
    )

    # --- Gestão de Múltiplas Obras (Rateio) ---
    registrar_multiplas_obras = forms.BooleanField(
        required=False, 
        label="Ratear em múltiplas obras?"
    )
    obras_extras_list = forms.CharField(
        required=False, 
        widget=forms.HiddenInput()
    )

    # --- Adicionais de Folha ---
    em_plantao = forms.BooleanField(
        required=False,
        label="Atividade em Plantão?"
    )
    data_plantao = forms.DateField(
        required=False,
        widget=forms.HiddenInput(),
        input_formats=['%d/%m/%Y', '%Y-%m-%d']
    )
    dorme_fora = forms.BooleanField(
        required=False,
        label="Dorme Fora Nesta Data?"
    )
    data_dorme_fora = forms.DateField(
        required=False,
        widget=forms.HiddenInput(),
        input_formats=['%d/%m/%Y', '%Y-%m-%d']
    )

    # --- Geolocalização ---
    latitude = forms.DecimalField(widget=forms.HiddenInput(), required=False)
    longitude = forms.DecimalField(widget=forms.HiddenInput(), required=False)

    # ==========================================================================
    # CONFIGURAÇÕES DE META (MODELO)
    # ==========================================================================

    class Meta:
        model = Apontamento
        fields = [
            'colaborador', 'data_apontamento', 'local_execucao',
            'projeto', 'codigo_cliente', 'obras_extras_list',
            'centro_custo', 'hora_inicio', 'hora_termino', 'ocorrencias',
            'veiculo_manual_modelo', 'veiculo_manual_placa',
            'em_plantao', 'data_plantao', 'dorme_fora', 'data_dorme_fora',
            'latitude', 'longitude'
        ]
        widgets = {
            'data_apontamento': forms.TextInput(attrs={
                'class': 'form-control cursor-pointer bg-slate-800 text-left font-bold text-emerald-400 border-emerald-500/50 pl-3',
                'readonly': 'readonly', 
                'placeholder': 'DD/MM/AAAA'
            }),
            'hora_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'hora_termino': forms.TimeInput(attrs={'type': 'time'}),
            'ocorrencias': forms.Textarea(attrs={'rows': 3}),
            'local_execucao': forms.Select(attrs={'class': 'form-select'}),
            'centro_custo': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'centro_custo': 'Setor / Justificativa (Custo)'
        }

    # ==========================================================================
    # INICIALIZAÇÃO E CONTROLE DE ACESSO (RBAC)
    # ==========================================================================

    def __init__(self, *args, **kwargs):
        """
        Inicializa o formulário aplicando filtros de permissão baseados no usuário logado.
        Define quais colaboradores podem ser selecionados e popula selects dinâmicos.
        """
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.instance.data_apontamento:
            self.initial['data_apontamento'] = self.instance.data_apontamento.strftime('%d/%m/%Y')

        self.fields['data_apontamento'].input_formats = ['%d/%m/%Y', '%Y-%m-%d']
        self.fields['projeto'].queryset = Projeto.objects.filter(ativo=True)
        self.fields['centro_custo'].queryset = CentroCusto.objects.filter(ativo=True)
        self.fields['codigo_cliente'].queryset = CodigoCliente.objects.filter(ativo=True)
        
        veiculos_db = Veiculo.objects.all()
        choices = [('', '-- Escolha o Veículo --')]
        choices += [(v.id, str(v)) for v in veiculos_db]
        choices.append(('OUTRO', 'OUTRO (Cadastrar Novo)'))
        self.fields['veiculo_selecao'].choices = choices

        if self.user:
            is_owner = self.user.is_superuser
            groups = list(self.user.groups.values_list('name', flat=True))
            is_gestor = 'GESTOR' in groups
            is_admin = 'ADMINISTRATIVO' in groups
            is_coord = 'COORDENADOR' in groups
            
            pode_ratear = is_owner or is_coord or is_admin
            
            if not pode_ratear:
                if 'registrar_multiplas_obras' in self.fields:
                    del self.fields['registrar_multiplas_obras']
                if 'obras_extras_list' in self.fields:
                    del self.fields['obras_extras_list']

            if is_owner:
                self.fields['colaborador'].queryset = Colaborador.objects.all()
            
            elif is_admin:
                try:
                    colaborador_logado = Colaborador.objects.get(user_account=self.user)
                    setores_permitidos = colaborador_logado.setores_gerenciados.all()
                    
                    if setores_permitidos.exists():
                        qs = Colaborador.objects.filter(setor__in=setores_permitidos)
                        qs = qs | Colaborador.objects.filter(pk=colaborador_logado.pk)
                        self.fields['colaborador'].queryset = qs.distinct()
                    else:
                        self.fields['colaborador'].queryset = Colaborador.objects.filter(pk=colaborador_logado.pk)
                    
                    self.initial['cargo_colaborador'] = colaborador_logado.cargo
                except Colaborador.DoesNotExist:
                    self.fields['colaborador'].queryset = Colaborador.objects.none()
            
            elif is_gestor or is_coord:
                try:
                    colaborador_logado = Colaborador.objects.get(user_account=self.user)
                    self.initial['colaborador'] = colaborador_logado
                    self.initial['cargo_colaborador'] = colaborador_logado.cargo
                    self._lock_colaborador_field(colaborador_logado)
                except Colaborador.DoesNotExist:
                    self.fields['colaborador'].queryset = Colaborador.objects.none()
            
            else: 
                try:
                    colaborador_logado = Colaborador.objects.get(user_account=self.user)
                    self.initial['colaborador'] = colaborador_logado
                    self.initial['cargo_colaborador'] = colaborador_logado.cargo
                    self._lock_colaborador_field(colaborador_logado)
                except Colaborador.DoesNotExist:
                    self.fields['colaborador'].queryset = Colaborador.objects.none()

        self.fields['colaborador'].required = True
        self.fields['hora_inicio'].required = True
        self.fields['hora_termino'].required = True

        for name, field in self.fields.items():
            if name not in ['registrar_veiculo', 'registrar_auxiliar', 'em_plantao', 'dorme_fora']:
                if 'class' not in field.widget.attrs:
                    field.widget.attrs.update({'class': 'form-control'})
                elif 'form-control' not in field.widget.attrs['class']:
                     field.widget.attrs['class'] += ' form-control'
    
    def _lock_colaborador_field(self, colaborador_logado):
        """Bloqueia visualmente o campo colaborador."""
        self.fields['colaborador'].widget.attrs.update({
            'class': 'form-control pointer-events-none bg-slate-700 text-gray-400 cursor-not-allowed',
            'tabindex': '-1'
        })
        self.fields['colaborador'].queryset = Colaborador.objects.filter(pk=colaborador_logado.pk)
        self.fields['colaborador'].empty_label = None

    tipo_acao = forms.CharField(required=False, widget=forms.HiddenInput())

    def clean(self):
        """
        Validação centralizada:
        - Lógica robusta para Turnos Noturnos (Overnight).
        - Higienização de dados (strip/upper).
        - Interface de erro visual (HTML/SVG).
        """
        cleaned_data = super().clean()

        # --- 0. Lógica de Reset (Botão START) ---
        acao = cleaned_data.get('tipo_acao')
        if acao == 'START':
            if 'hora_termino' in self.errors:
                del self.errors['hora_termino']
            cleaned_data['hora_termino'] = None
            return cleaned_data

        # --- 1. Permissões e Rateio (RBAC) ---
        if self.user:
            is_owner = self.user.is_superuser
            groups = list(self.user.groups.values_list('name', flat=True))
            pode_ratear = is_owner or 'COORDENADOR' in groups or 'ADMINISTRATIVO' in groups
            
            if not pode_ratear:
                cleaned_data['registrar_multiplas_obras'] = False
                cleaned_data['obras_extras_list'] = ''
        
        colaborador = cleaned_data.get('colaborador')
        data_apontamento = cleaned_data.get('data_apontamento')
        inicio = cleaned_data.get('hora_inicio')
        termino = cleaned_data.get('hora_termino')

        # --- 2. Bloqueio de Datas Futuras ---
        if data_apontamento and inicio and termino:
            agora = timezone.localtime(timezone.now())
            
            dt_inicio = timezone.make_aware(datetime.combine(data_apontamento, inicio))
            dt_termino = timezone.make_aware(datetime.combine(data_apontamento, termino))
            
            if dt_termino < dt_inicio:
                dt_termino += timedelta(days=1)

            if dt_inicio > agora:
                self.add_error('hora_inicio', "O horário de início não pode ser no futuro.")
            
            if dt_termino > agora:
                self.add_error('hora_termino', "O horário de término não pode ser no futuro.")

        if self.errors:
            return cleaned_data

        # --- 3. Detecção de Conflitos ---
        if colaborador and data_apontamento and inicio and termino:
            
            conflito = None
            tipo_conflito_msg = "Conflito de horário detectado!"

            base_query = Apontamento.objects.filter(colaborador=colaborador, data_apontamento=data_apontamento)
            if self.instance and self.instance.pk:
                base_query = base_query.exclude(pk=self.instance.pk)

            is_overnight = inicio > termino

            if not is_overnight:
                colisao = base_query.filter(
                    Q(hora_inicio__lt=termino, hora_termino__gt=inicio) | 
                    Q(hora_inicio__gt=F('hora_termino'), hora_inicio__lt=termino)
                )
            else:
                q1 = Q(hora_inicio__gte=inicio) | Q(hora_termino__gt=inicio)
                q2 = Q(hora_inicio__lt=termino) | Q(hora_termino__gt=time(0,0), hora_termino__lt=termino)
                colisao = base_query.filter(q1 | q2)

            if colisao.exists():
                conflito = colisao.first()
                tipo_conflito_msg = "Conflito de horário (Mesmo dia)"

            if not conflito:
                yesterday = data_apontamento - timedelta(days=1)
                
                conflito_ontem = Apontamento.objects.filter(
                    colaborador=colaborador,
                    data_apontamento=yesterday,
                    hora_inicio__gt=F('hora_termino'),
                    hora_termino__gt=inicio
                )
                
                if self.instance and self.instance.pk:
                    conflito_ontem = conflito_ontem.exclude(pk=self.instance.pk)

                if conflito_ontem.exists():
                    conflito = conflito_ontem.first()
                    tipo_conflito_msg = "Conflito Interjornada (Dia Anterior)"

            if conflito:
                if conflito.local_execucao == 'INT':
                    referencia = f"{str(conflito.projeto)}" if conflito.projeto else f"{str(conflito.codigo_cliente)}"
                else: 
                    referencia = f"{str(conflito.centro_custo)}" if conflito.centro_custo else "Local Externo"
                    
                inicio_str = conflito.hora_inicio.strftime('%H:%M')
                termino_str = conflito.hora_termino.strftime('%H:%M') if conflito.hora_termino else "..."
                data_fmt = conflito.data_apontamento.strftime('%d/%m/%Y')
                
                icon_user = '<svg class="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>'
                icon_place = '<svg class="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" /></svg>'
                icon_date = '<svg class="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>'
                icon_clock = '<svg class="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>'

                error_message = mark_safe(f"""
                    <div class="text-left">
                        <p class="font-bold text-base text-red-300 mb-2">{tipo_conflito_msg}</p>
                        <div class="bg-slate-800/80 p-3 rounded border border-red-500/30 text-sm space-y-2 mb-3 shadow-inner">
                            <div class="flex items-start gap-3">
                                <div class="mt-0.5">{icon_user}</div>
                                <span class="font-bold text-white tracking-wide">{colaborador.nome_completo.upper()}</span>
                            </div>
                            <div class="flex items-start gap-3">
                                <div class="mt-0.5">{icon_place}</div>
                                <span class="text-gray-300">{referencia}</span>
                            </div>
                            <div class="flex items-start gap-3">
                                <div class="mt-0.5">{icon_date}</div>
                                <span class="text-gray-300">{data_fmt}</span>
                            </div>
                            <div class="flex items-center gap-3">
                                <div>{icon_clock}</div>
                                <span class="font-mono text-white font-bold bg-red-900/40 px-2 rounded border border-red-900/50">{inicio_str} - {termino_str}</span>
                            </div>
                        </div>
                        <p class="text-xs text-red-300 italic">Ajuste os horários. Não é permitido sobrepor apontamentos.</p>
                    </div>
                """)
                raise ValidationError(error_message)

        # --- 4. Regras de Local e Contexto ---
        local = cleaned_data.get('local_execucao')
        projeto = cleaned_data.get('projeto')
        cod_cliente = cleaned_data.get('codigo_cliente')
        centro_custo = cleaned_data.get('centro_custo')

        if local == 'INT':
            if projeto and cod_cliente:
                self.add_error('projeto', "Selecione apenas a Obra ou o Cliente, não ambos.")
            if not projeto and not cod_cliente:
                self.add_error('projeto', "Informe a Obra Específica ou o Código do Cliente.")
            cleaned_data['centro_custo'] = None
                
        elif local == 'EXT':
            if not centro_custo:
                self.add_error('centro_custo', "Selecione o Setor / Justificativa (Custo).")
            
            if centro_custo and centro_custo.permite_alocacao:
                if not projeto and not cod_cliente:
                     self.add_error('projeto', "Para esta Justificativa, é OBRIGATÓRIO informar Obra/Cliente.")
                if projeto and cod_cliente:
                    self.add_error('projeto', "Selecione apenas a Obra ou o Cliente, não ambos.")
            else:
                cleaned_data['projeto'] = None
                cleaned_data['codigo_cliente'] = None
                self.instance.projeto = None
                self.instance.codigo_cliente = None
            
        # --- 5. Validação de Veículos ---
        if cleaned_data.get('registrar_veiculo'):
            selection = cleaned_data.get('veiculo_selecao')
            if not selection:
                self.add_error('veiculo_selecao', "Selecione um veículo.")
            elif selection == 'OUTRO':
                mod = cleaned_data.get('veiculo_manual_modelo')
                pla = cleaned_data.get('veiculo_manual_placa')
                
                if mod: cleaned_data['veiculo_manual_modelo'] = mod.strip().upper()
                else: self.add_error('veiculo_manual_modelo', "Informe o Modelo.")
                
                if pla: 
                    pla_limpa = pla.upper().replace('-', '').replace(' ', '').strip()
                    cleaned_data['veiculo_manual_placa'] = pla_limpa
                    if len(pla_limpa) != 7:
                        self.add_error('veiculo_manual_placa', f"A placa deve ter 7 caracteres (Digitado: {len(pla_limpa)}).")
                else:
                    self.add_error('veiculo_manual_placa', "Informe a Placa.")
            else:
                cleaned_data['veiculo_manual_modelo'] = None
                cleaned_data['veiculo_manual_placa'] = None
        else:
            self.instance.veiculo = None
            cleaned_data['veiculo_manual_modelo'] = None
            cleaned_data['veiculo_manual_placa'] = None

        # --- 6. Validação de Auxiliares ---
        if cleaned_data.get('registrar_auxiliar'):
            if not cleaned_data.get('auxiliar_selecao'):
                self.add_error('auxiliar_selecao', "Selecione o Auxiliar.")
            
            self.instance.auxiliar = cleaned_data.get('auxiliar_selecao')
            self.instance.auxiliares_extras_ids = cleaned_data.get('auxiliares_extras_list', '')
        else:
            self.instance.auxiliar = None
            self.instance.auxiliares_extras_ids = ''

        # --- 7. Validação de Plantão ---
        if cleaned_data.get('em_plantao'):
            dt_plantao = cleaned_data.get('data_plantao')
            if not dt_plantao:
                self.add_error(None, "Selecione a Data do Plantão no calendário.")
            elif dt_plantao != data_apontamento:
                self.add_error(None, "A Data do Plantão deve ser a mesma do registro principal.")

        # --- 8. Validação de Múltiplas Obras (Rateio) ---
        if cleaned_data.get('registrar_multiplas_obras'):
            extras = cleaned_data.get('obras_extras_list')
            if not extras or len(str(extras).strip()) == 0:
                self.add_error('registrar_multiplas_obras', "Erro de processamento: Nenhuma obra adicional foi detectada para o rateio.")

        return cleaned_data