from datetime import timedelta, date
from .models import Colaborador, Feriado
from django.core.cache import cache
from django.db.models import Q
import os
import logging
import requests
import calendar

logger = logging.getLogger('services')

class FeriadoService:
    """
    Serviço responsável por verificar os feriados.
    """
    @staticmethod
    def eh_feriado(data_ref, cidade=None, uf=None):
        cidade_busca = cidade.strip().upper() if cidade else ""
        uf_busca = uf.strip().upper() if uf else ""

        cidade_cache = cidade_busca.replace(" ", "_")
        uf_cache = uf_busca.replace(" ", "_")

        cache_key = f"feriado_{data_ref}_{cidade_cache}_{uf_cache}"
        
        resultado = cache.get(cache_key)
        
        if resultado is None:
            resultado = Feriado.objects.filter(
                data=data_ref,
                cidade__iexact=cidade_busca,
                uf__iexact=uf_busca
            ).exists()
            cache.set(cache_key, resultado, 86400)
            
        return resultado

class ControlePontoService:
    """
    Serviço responsável por consultar a fonte oficial de ponto (Futuramente API Sólides).
    """
    cargos_isentos = ['JOVEM APRENDIZ', 'GERENTE', 'CONTROLLER', 'DIRETOR', 'SÓCIO']
    
    # Movidos para o escopo da classe para serem reaproveitados
    META_PADRAO = 31680      # 08:48h em segundos
    TOLERANCIA_PADRAO = 900  # 15 minutos em segundos

    @staticmethod
    def _calcular_meta_padrao(data_ref: date, cidade: str, uf: str) -> dict:
        """
        Método privado que centraliza a regra de negócio local (Fallback) para definir 
        a meta diária com base em dias úteis, finais de semana e feriados.
        """
        dia_semana = data_ref.weekday()
        is_fim_de_semana = dia_semana >= 5
        is_feriado = FeriadoService.eh_feriado(data_ref, cidade, uf)
        
        is_dia_folga = is_fim_de_semana or is_feriado

        if not is_dia_folga:
            meta = ControlePontoService.META_PADRAO
            tol = ControlePontoService.TOLERANCIA_PADRAO
            motivo = None
        else:
            meta = 0
            tol = 0
            if is_feriado:
                motivo = 'Feriado'
            elif is_fim_de_semana:
                motivo = 'Fim de Semana'
            else:
                motivo = 'Folga / API'

        return {
            'meta_segundos': meta,
            'tolerancia_segundos': tol,
            'deve_notificar': meta > 0,
            'motivo_ausencia': motivo
        }

    @staticmethod
    def obter_meta_do_dia(colaborador, data_ref: date) -> dict:
        """
        Retorna um dicionário com a expectativa de trabalho para aquele dia específico.
        """
        cargo_atual = colaborador.cargo.upper() if colaborador.cargo else ''
        
        colaborador_isento = any(cargo in cargo_atual for cargo in ControlePontoService.cargos_isentos)

        if colaborador_isento:
            return {
                'meta_segundos': 0,
                'tolerancia_segundos': 0,
                'deve_notificar': False,
                'motivo_ausencia': 'Cargo Isento'
            }

        # Quando a API for integrada, a checagem extra (ex: plantões no fim de semana) pode 
        # sobreescrever o retorno desse método base.
        return ControlePontoService._calcular_meta_padrao(data_ref, colaborador.cidade, colaborador.uf)

    @staticmethod
    def obter_escalas_do_mes(colaboradores: list, mes: int, ano: int) -> dict:
        """
        Busca em lote (batch) a escala de múltiplos colaboradores para um mês inteiro.
        """
        mapa_escalas = {}
        _, num_dias = calendar.monthrange(ano, mes)
        
        ids_para_consultar = []
        for colab in colaboradores:
            mapa_escalas[colab.id] = {}
            cargo_atual = colab.cargo.upper() if colab.cargo else ''
            
            if any(c in cargo_atual for c in ControlePontoService.cargos_isentos):
                for dia in range(1, num_dias + 1):
                    mapa_escalas[colab.id][date(ano, mes, dia)] = {
                        'meta_segundos': 0,
                        'tolerancia_segundos': 0,
                        'deve_notificar': False,
                        'motivo_ausencia': 'Cargo Isento'
                    }
            else:
                ids_para_consultar.append(colab.id)

        if not ids_para_consultar:
            return mapa_escalas

        # ---------------------------------------------------------
        # 2. INTEGRAÇÃO FUTURA COM A API SÓLIDES (Exemplo)
        # ---------------------------------------------------------
        # payload = {"mes": mes, "ano": ano, "colaboradores": ids_para_consultar}
        # dados_api = requests.post(".../escalas/lote", json=payload).json()
        dados_api = None

        # ---------------------------------------------------------
        # 3. PROCESSAMENTO E FALLBACK
        # ---------------------------------------------------------
        for colab in colaboradores:
            if colab.id not in ids_para_consultar:
                continue 
                
            for dia in range(1, num_dias + 1):
                data_atual = date(ano, mes, dia)
                
                if dados_api and str(colab.id) in dados_api:
                    # [Extrair dados do json da API aqui futuramente]
                    pass 
                
                else:
                    mapa_escalas[colab.id][data_atual] = ControlePontoService._calcular_meta_padrao(
                        data_atual, 
                        colab.cidade, 
                        colab.uf
                    )

        return mapa_escalas
    
class WhatsAppService:
    """
    Integração com Script Node.js Local (WPPConnect)
    """
    @staticmethod
    def enviar_notificacao_pendencia(colaborador, mensagem_texto):
        base_url = os.getenv('WPP_BASE_URL', 'http://localhost:3000')
        api_token = os.getenv('WPP_API_TOKEN')

        if not api_token:
            logger.error("WPP_API_TOKEN não configurado. Mensagem não enviada.")
            return False

        if not colaborador.telefone:
            logger.warning(f"Colaborador {colaborador} sem telefone cadastrado.")
            return False

        numero_limpo = "".join(filter(str.isdigit, colaborador.telefone))

        numero_final = numero_limpo

        if 10 <= len(numero_limpo) <= 11:
            numero_final = f"55{numero_limpo}"
            
        if len(numero_final) < 12:
            logger.warning(f"Número inválido detectado para {colaborador}: {numero_final}")
            return False
        
        url = f"{base_url}/send-message"

        payload = {
            "number": numero_final,
            "message": mensagem_texto
        }
        
        headers = {
            'Content-Type': 'application/json',
            'x-api-token': api_token
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return True
            else:
                logger.error(f"Erro Node API (Status {response.status_code}): {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error("Timeout ao conectar com o serviço de WhatsApp (Node.js).")
            return False
        except Exception as e:
            logger.error(f"Falha de conexão com WhatsApp Service: {e}")
            return False