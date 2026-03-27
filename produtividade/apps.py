from django.apps import AppConfig


class ProdutividadeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'produtividade'

    def ready(self):
        import produtividade.signals
