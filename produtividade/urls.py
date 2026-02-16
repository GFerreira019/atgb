from django.urls import path
from . import views, apis, relatorios

app_name = 'produtividade'

urlpatterns = [
    # ==========================================================================
    # NAVEGAÇÃO BÁSICA
    # ==========================================================================
    path('', views.home_redirect_view, name='home'),
    path('menu/', views.home_view, name='home_menu'),
    path('configuracoes/', views.configuracoes_view, name='configuracoes'),

    # ==========================================================================
    # CORE: APONTAMENTOS (CRUD)
    # ==========================================================================
    # Formulário de Criação
    path('apontamento/novo/', views.apontamento_atividade_view, name='novo_apontamento'),
    
    # Tela de feedback de sucesso
    path('apontamento/sucesso/', views.apontamento_sucesso_view, name='apontamento_sucesso'),

    # Funcionalidades de Edição e Exclusão (Admin/Gestor)
    path('apontamento/editar/<int:pk>/', views.editar_apontamento_view, name='editar_apontamento'),
    path('apontamento/excluir/<int:pk>/', views.excluir_apontamento_view, name='excluir_apontamento'),

    # ==========================================================================
    # HISTÓRICO, DASHBOARDS E CONFORMIDADE
    # ==========================================================================
    path('historico/', views.historico_apontamentos_view, name='historico_apontamentos'),

    # Solicitar Ajuste (Usuário/Colaborador pede correção em registro passado)
    path('apontamento/<int:pk>/solicitar-ajuste/', views.solicitar_ajuste_view, name='solicitar_ajuste'),

    # Aprovar Ajuste (Gestor aceita a correção)
    path('apontamento/<int:pk>/aprovar-ajuste/', views.aprovar_ajuste_view, name='aprovar_ajuste'),

    # Conformidade de Apontamentos
    path('dashboard/conformidade/', views.dashboard_conformidade_view, name='dashboard_conformidade'),

    # Notificar Pendências de Apontamento (Automático)
    path('dashboard/notificar/', views.notificar_pendencias_view, name='notificar_pendencias'),

    # Notificações do Usuário
    path('notificacoes/ler-todas/', views.marcar_todas_lidas_view, name='marcar_todas_lidas'),

    # Responder Notificação
    path('notificacoes/responder/<int:pk>/', views.responder_notificacao_view, name='responder_notificacao'),

    # Enviar Aviso Personalizado (Manual)
    path('dashboard/enviar-aviso/', views.enviar_aviso_personalizado_view, name='enviar_aviso_personalizado'),

    # Painel Central de Dashboards
    path('painel-administrativo/', views.painel_owner_view, name='painel_owner'),

    # Painel de Auditoria
    path('painel-administrativo/auditoria/', views.dashboard_auditoria_view, name='dashboard_auditoria'),

    # ==========================================================================
    # FLUXO DE APROVAÇÃO (GERENTE)
    # ==========================================================================
    path('aprovacoes/', views.aprovacao_dashboard_view, name='aprovacao_dashboard'),
    path('aprovacoes/<int:pk>/analise/', views.analise_apontamento_view, name='analise_apontamento'),
    path('aprovacoes/<int:pk>/processar/', views.processar_aprovacao_view, name='processar_aprovacao'),

    # ==========================================================================
    # APIs AJAX
    # ==========================================================================
    path('api/get-projeto-info/<int:projeto_id>/', apis.get_projeto_info_ajax, name='get_projeto_info'),
    path('api/get-colaborador-info/<int:colaborador_id>/', apis.get_colaborador_info_ajax, name='get_colaborador_info'),
    path('api/get-auxiliares/', apis.get_auxiliares_ajax, name='get_auxiliares'), 
    path('api/get-centro-custo-info/<int:cc_id>/', apis.get_centro_custo_info_ajax, name='get_centro_custo_info_ajax'),
    path('api/get-calendar-status/', apis.get_calendar_status_ajax, name='get_calendar_status_ajax'),
    path('api/timer/start/', apis.api_iniciar_cronometro, name='api_iniciar_cronometro'),
    path('api/timer/stop/', apis.api_parar_cronometro, name='api_parar_cronometro'),
    path('api/timer/status/', apis.api_status_cronometro, name='api_status_cronometro'),

    # ==========================================================================
    # INTEGRAÇÃO EXTERNA (Dashboard PHP)
    # ==========================================================================
    # 1. Status Online/Offline e Gráficos de hoje
    path('api/dashboard/', apis.api_dashboard_data, name='api_dashboard_data'),
    
    # 2. Sincronização completa de dados (Excel JSON)
    path('api/exportar-completo/', apis.api_exportar_json, name='api_exportar_completo'),

    # ==========================================================================
    # RELATÓRIOS E EXPORTAÇÃO
    # ==========================================================================
    path('exportar/excel/', relatorios.exportar_relatorio_excel, name='exportar_relatorio_excel'),

    path('health/', apis.health_check_view, name='health_check'),
]