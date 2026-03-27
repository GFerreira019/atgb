import logging
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from .models import LogAuditoria, Colaborador, Projeto, CentroCusto, Feriado
from .utils import get_client_ip

# Logger para erros internos do sistema de auditoria
logger = logging.getLogger('auditoria')

# ==============================================================================
# SINAIS DE AUDITORIA (LOGIN / LOGOUT)
# ==============================================================================

@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    """Registra logins bem-sucedidos."""
    try:
        ip = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', 'Desconhecido')
        
        LogAuditoria.objects.create(
            usuario=user, 
            acao='LOGIN', 
            modelo_afetado='Sistema', 
            detalhes=f"Acesso realizado via: {user_agent}",
            ip_address=ip
        )
    except Exception as e:
        logger.error(f"FALHA AUDITORIA (LOGIN): {e}")

@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    """Registra logouts."""
    try:
        if user:
            LogAuditoria.objects.create(
                usuario=user, 
                acao='LOGOUT', 
                modelo_afetado='Sistema', 
                detalhes="Logout efetuado com sucesso.",
                ip_address=get_client_ip(request)
            )
    except Exception as e:
        logger.error(f"FALHA AUDITORIA (LOGOUT): {e}")

@receiver(user_login_failed)
def log_login_failed(sender, credentials, request, **kwargs):
    """
    Registra tentativas falhas de login.
    """
    try:
        ip = get_client_ip(request)

        username_tentado = credentials.get('username', 'Desconhecido')
        
        LogAuditoria.objects.create(
            usuario=None,
            acao='LOGIN_FALHA',
            modelo_afetado='Sistema',
            objeto_id=username_tentado,
            detalhes=f"Tentativa de login falhou para o usuário: '{username_tentado}'.",
            ip_address=ip
        )
    except Exception as e:
        logger.error(f"FALHA AUDITORIA (LOGIN FAILED): {e}")


# ==============================================================================
# INVALIDAÇÃO DE CACHE AUTOMÁTICA
# ==============================================================================

@receiver([post_save, post_delete], sender=Colaborador)
def limpar_cache_colaboradores(sender, instance, **kwargs):
    """
    Se um colaborador for adicionado, demitido ou mudar de cargo, 
    limpamos o cache da lista de auxiliares.
    """
    cache.delete('api_lista_auxiliares')

@receiver([post_save, post_delete], sender=Projeto)
def limpar_cache_projetos(sender, instance, **kwargs):
    """Limpa o cache do nome do projeto específico."""
    cache.delete(f'projeto_info_{instance.pk}')

@receiver([post_save, post_delete], sender=CentroCusto)
def limpar_cache_centro_custo(sender, instance, **kwargs):
    """Limpa o cache das regras do centro de custo específico."""
    cache.delete(f'cc_info_{instance.pk}')

@receiver([post_save, post_delete], sender=Feriado)
def limpar_cache_feriados(sender, instance, **kwargs):
    """
    Se um feriado for cadastrado, alterado ou excluído, limpamos o cache 
    exato daquela data e cidade para não impactar o cálculo da jornada.
    """
    if instance.data and instance.cidade and instance.uf:
        data_str = instance.data.strftime('%Y-%m-%d')
        cidade_str = instance.cidade.strip().upper()
        uf_str = instance.uf.strip().upper()
        
        cache_key = f"feriado_{data_str}_{cidade_str}_{uf_str}"
        cache.delete(cache_key)