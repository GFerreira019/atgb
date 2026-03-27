import logging
from datetime import datetime, time, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from produtividade.models import Apontamento, LogAuditoria

class Command(BaseCommand):
    help = 'Aprova automaticamente apontamentos originais (sem edição) e sem pendências de CLT.'

    def handle(self, *args, **options):
        self.stdout.write("Iniciando rotina de aprovação automática...")
        
        # 1. Busca apenas pendentes e que ESTÃO EM CONFORMIDADE (flag_atencao=False)
        pendentes = Apontamento.objects.filter(
            status_aprovacao='EM_ANALISE',
            flag_atencao=False,
            contagem_edicao=0
        )

        agora = timezone.localtime(timezone.now())
        total_aprovados = 0

        self.stdout.write(f"Encontrados {pendentes.count()} candidatos à aprovação.")

        for apt in pendentes:
            # Data/Hora exata que o registro foi criado no banco
            data_registro_local = timezone.localtime(apt.data_registro)
            hora_envio = data_registro_local.time()
            
            # Data de referência para calcular o gatilho
            data_base = data_registro_local.date()
            
            gatilho_aprovacao = None

            # --- REGRA 1: Enviados entre 06:00 e 18:00 ---
            # Aprovam à 00:00 do dia seguinte
            if time(6, 0) <= hora_envio <= time(18, 0):
                # Gatilho: Dia seguinte às 00:00
                data_alvo = data_base + timedelta(days=1)
                gatilho_aprovacao = timezone.make_aware(datetime.combine(data_alvo, time(0, 0)))

            # --- REGRA 2: Enviados entre 18:01 e 05:59 ---
            # Aprovam às 08:00 da manhã
            else:
                # Se foi enviado após as 18h (ex: 20h), aprova às 08h de amanhã
                if hora_envio > time(18, 0):
                    data_alvo = data_base + timedelta(days=1)
                # Se foi enviado de madrugada (ex: 02h), aprova às 08h de hoje mesmo
                else:
                    data_alvo = data_base
                
                gatilho_aprovacao = timezone.make_aware(datetime.combine(data_alvo, time(8, 0)))

            # --- VERIFICAÇÃO FINAL ---
            if gatilho_aprovacao and agora >= gatilho_aprovacao:
                try:
                    with transaction.atomic():
                        apt.status_aprovacao = 'APROVADO'
                        apt.save()

                        # Gera Log de Auditoria (Sistema)
                        LogAuditoria.objects.create(
                            usuario=None, # None indica Sistema
                            acao='APROVACAO',
                            modelo_afetado='Apontamento',
                            objeto_id=str(apt.id),
                            detalhes=f"Aprovação Automática (Robô). Envio: {data_registro_local.strftime('%d/%m %H:%M')} | Gatilho: {gatilho_aprovacao.strftime('%d/%m %H:%M')}",
                            ip_address='127.0.0.1'
                        )
                        
                        total_aprovados += 1
                        self.stdout.write(self.style.SUCCESS(f"Apontamento {apt.id} aprovado."))
                        
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Erro ao aprovar {apt.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Rotina finalizada. Total aprovados: {total_aprovados}"))