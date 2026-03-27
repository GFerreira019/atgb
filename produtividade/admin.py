from django.contrib import admin
from django.utils.html import format_html
from .models import Projeto, Colaborador, Veiculo, Apontamento, Setor, CodigoCliente, CentroCusto, Feriado, LogAuditoria

# ==============================================================================
# CADASTROS AUXILIARES
# ==============================================================================

@admin.register(Setor)
class SetorAdmin(admin.ModelAdmin):
    """Gerenciamento de Setores/Departamentos (ex: Manutenção, E&O)."""
    list_display = ('nome', 'ativo')
    search_fields = ('nome',)


@admin.register(CentroCusto)
class CentroCustoAdmin(admin.ModelAdmin):
    """Gerenciamento de Centros de Custo / Justificativas para alocação externa."""
    list_display = ('nome', 'permite_alocacao', 'ativo')
    search_fields = ('nome',)
    list_filter = ('ativo', 'permite_alocacao')


@admin.register(Projeto)
class ProjetoAdmin(admin.ModelAdmin):
    """Gerenciamento de Obras e Projetos."""
    list_display = ('codigo', 'nome', 'ativo')
    search_fields = ('codigo', 'nome')
    list_filter = ('ativo',)


@admin.register(CodigoCliente)
class CodigoClienteAdmin(admin.ModelAdmin):
    """Gerenciamento de Códigos de Cliente (4 dígitos)."""
    list_display = ('codigo', 'nome', 'ativo')
    search_fields = ('codigo', 'nome')
    list_filter = ('ativo',)


@admin.register(Colaborador)
class ColaboradorAdmin(admin.ModelAdmin):
    """
    Cadastro de funcionários e prestadores de serviço. 
    Permite vincular o colaborador à conta de usuário e definir setores gerenciados.
    """
    list_display = ('id_colaborador', 'nome_completo', 'cargo', 'setor', 'cidade', 'uf', 'telefone', 'user_account')
    search_fields = ('nome_completo', 'id_colaborador', 'cidade', 'user_account__username')
    list_filter = ('cargo', 'setor', 'uf', 'cidade')
    fields = ('id_colaborador', 'nome_completo', 'cargo', 'setor', 'cidade', 'uf', 'telefone', 'setores_gerenciados', 'user_account')
    filter_horizontal = ('setores_gerenciados',)


@admin.register(Veiculo)
class VeiculoAdmin(admin.ModelAdmin):
    """Cadastro da frota de veículos oficiais ou alugados."""
    list_display = ('placa', 'descricao')
    search_fields = ('placa', 'descricao')

@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    """Gerenciamento de feriados cadastrados no sistema."""
    list_display = ('data', 'cidade', 'uf', 'descricao')
    search_fields = ('cidade', 'descricao')
    list_filter = ('uf', 'cidade', 'data')

# ==============================================================================
# REGISTRO PRINCIPAL (CORE)
# ==============================================================================

@admin.register(Apontamento)
class ApontamentoAdmin(admin.ModelAdmin):
    """
    Visão geral dos apontamentos de produtividade.
    Configurado para alta performance com muitos registros e facilidade de auditoria.
    """
    date_hierarchy = 'data_apontamento'
    
    list_display = (
        'data_apontamento',
        'colaborador',
        'get_tipo_local',
        'get_detalhe_local',
        'hora_inicio',
        'hora_termino',
        'em_plantao',
        'dorme_fora',
        'registrado_por'
    )

    list_filter = (
        'local_execucao',
        'status_ajuste',
        'em_plantao',
        'dorme_fora',
        'centro_custo',
        'projeto'
    )

    search_fields = (
        'colaborador__nome_completo',
        'projeto__nome',
        'projeto__codigo',
        'codigo_cliente__nome',
        'ocorrencias'    
    )

    autocomplete_fields = ['colaborador', 'projeto', 'codigo_cliente', 'centro_custo', 'veiculo']
    readonly_fields = ('data_registro', 'registrado_por')

    fieldsets = (
        ('Identificação e Tempo', {
            'fields': (
                ('colaborador', 'data_apontamento'),
                ('hora_inicio', 'hora_termino'),
            )
        }),
        ('Localização', {
            'fields': (
                'local_execucao',
                ('projeto', 'codigo_cliente'),
                'centro_custo',
            )
        }),
        ('Recursos e Equipe', {
            'fields': (
                ('veiculo', 'veiculo_manual_modelo', 'veiculo_manual_placa'),
                'auxiliar',
                'auxiliares_extras'
            )
        }),
        ('Adicionais e Detalhes', {
            'fields': (
                ('em_plantao', 'data_plantao'), 
                ('dorme_fora', 'data_dorme_fora'),
                'ocorrencias'
            )
        }),
        ('Auditoria e Ajustes', {
            'fields': (
                ('motivo_ajuste', 'status_ajuste'),
                ('registrado_por', 'data_registro')
            ),
            'classes': ('collapse',)
        }),
    )

    def get_tipo_local(self, obj):
        """Retorna a descrição legível do local de execução."""
        return obj.get_local_execucao_display()
    get_tipo_local.short_description = "Tipo"

    def get_detalhe_local(self, obj):
        """Lógica dinâmica para exibir o local específico ou Centro de Custo com alocação."""
        if obj.local_execucao == 'INT':
            if obj.projeto:
                return f"Obra: {obj.projeto}"
            elif obj.codigo_cliente:
                return f"Cli: {obj.codigo_cliente}"
            return "—"
        elif obj.local_execucao == 'EXT':
            base = str(obj.centro_custo) if obj.centro_custo else "—"
            if obj.projeto:
                return f"{base} -> Obra: {obj.projeto.codigo}"
            elif obj.codigo_cliente:
                return f"{base} -> Cli: {obj.codigo_cliente.codigo}"
            return base
        return "—"
    get_detalhe_local.short_description = "Local / Detalhe"


# ==============================================================================
# LOG DE AUDITORIA
# ==============================================================================

@admin.register(LogAuditoria)
class LogAuditoriaAdmin(admin.ModelAdmin):
    list_display = ('data_hora', 'usuario', 'acao', 'modelo_afetado', 'ip_address')
    list_filter = ('acao', 'data_hora', 'modelo_afetado')
    search_fields = ('detalhes', 'usuario__username', 'usuario__first_name', 'objeto_id')
    readonly_fields = [field.name for field in LogAuditoria._meta.fields]

    def get_acao_colorida(self, obj):
        colors = {
            'LOGIN': 'green',
            'LOGOUT': 'gray',
            'LOGIN_FALHA': 'red',
            'CRIACAO': 'blue',
            'EDICAO': 'orange',
            'EXCLUSAO': 'darkred',
        }
        color = colors.get(obj.acao, 'black')
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.get_acao_display())
    get_acao_colorida.short_description = 'Ação'
    
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False