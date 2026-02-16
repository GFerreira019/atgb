from .models import Colaborador, Notificacao

def notificacoes_globais(request):
    """
    Disponibiliza notificações.
    - Se for Colaborador: Vê os alertas recebidos.
    - Se for Owner (Superuser): Vê as RESPOSTAS dos colaboradores.
    """
    if not request.user.is_authenticated:
        return {}

    # --- LÓGICA DO OWNER (Ver Respostas) ---
    if request.user.is_superuser:
        respostas = Notificacao.objects.filter(
            comentario_colaborador__isnull=False
        ).exclude(
            comentario_colaborador=''
        ).select_related(
            'colaborador').order_by('-data_criacao')[:15]
        
        return {
            'notificacoes_usuario': respostas,
            'notificacoes_nao_lidas_count': len(respostas), 
            'is_owner_view': True
        }

    # --- LÓGICA DO COLABORADOR (Ver Alertas) ---
    try:
        if hasattr(request.user, 'colaborador'):
            colaborador = request.user.colaborador
        else:
            colaborador = Colaborador.objects.get(user_account=request.user)
            
        ultimas = Notificacao.objects.filter(colaborador=colaborador).order_by('-data_criacao')[:10]
        
        count = Notificacao.objects.filter(colaborador=colaborador, lida=False).count()

        return {
            'notificacoes_usuario': ultimas,
            'notificacoes_nao_lidas_count': count,
            'is_owner_view': False
        }
    except Colaborador.DoesNotExist:
        return {
            'notificacoes_usuario': [], 
            'notificacoes_nao_lidas_count': 0,
            'is_owner_view': False
        }