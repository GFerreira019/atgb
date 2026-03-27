import requests
import os
import unicodedata
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from produtividade.models import Feriado

class Command(BaseCommand):
    help = 'Importa feriados da API externa e salva no banco'

    def normalizar_texto(self, texto):
        """
        Remove acentos e coloca em caixa alta.
        Ex: 'São Paulo' -> 'SAO PAULO'
        """
        if not texto: return ""
        try:
            texto_normalizado = unicodedata.normalize('NFD', texto)
            texto_sem_acento = ''.join(c for c in texto_normalizado if unicodedata.category(c) != 'Mn')
            return texto_sem_acento.upper()
        except Exception:
            return texto.upper()
        

    def handle(self, *args, **kwargs):
        TOKEN = os.getenv('FERIADOS_API_TOKEN')
        HEADERS = {}
        if TOKEN:
            HEADERS['Authorization'] = f'Bearer {TOKEN}'
        
        ano_atual = datetime.now().year
        ANOS = [ano_atual, ano_atual + 1]

        # LISTA DE CIDADES
        cidades_alvo = [
            {'nome': 'Porto Seguro', 'uf': 'BA', 'ibge': '2925303'},
            {'nome': 'Guarapari', 'uf': 'ES', 'ibge': '3202405'},
            {'nome': 'Conceição do Mato Dentro', 'uf': 'MG', 'ibge': '3117504'},
            {'nome': 'Congonhas', 'uf': 'MG', 'ibge': '3118007'},
            {'nome': 'Conselheiro Lafaiete', 'uf': 'MG', 'ibge': '3118304'},
            {'nome': 'Sete Lagoas', 'uf': 'MG', 'ibge': '3167202'},
            {'nome': 'Duque de Caxias', 'uf': 'RJ', 'ibge': '3301702'},
            {'nome': 'Resende', 'uf': 'RJ', 'ibge': '3304201'},
            {'nome': 'Rio de Janeiro', 'uf': 'RJ', 'ibge': '3304557'},
            {'nome': 'Cajamar', 'uf': 'SP', 'ibge': '3509205'},
            {'nome': 'Campinas', 'uf': 'SP', 'ibge': '3509502'},
            {'nome': 'Jundiaí', 'uf': 'SP', 'ibge': '3525904'},
            {'nome': 'Piracicaba', 'uf': 'SP', 'ibge': '3538709'},
            {'nome': 'Porto Feliz', 'uf': 'SP', 'ibge': '3540606'},
            {'nome': 'Ribeirão Preto', 'uf': 'SP', 'ibge': '3543402'},
            {'nome': 'São Paulo', 'uf': 'SP', 'ibge': '3550308'},
            {'nome': 'Sorocaba', 'uf': 'SP', 'ibge': '3552205'},
        ]

        self.stdout.write("--- INICIANDO IMPORTAÇÃO ---")

        for ano in ANOS:
            self.stdout.write(f"\n> Processando ano {ano}...")
            
            for cidade in cidades_alvo:
                ibge = cidade['ibge']
                nome_cidade_banco = self.normalizar_texto(cidade['nome'])
                uf_banco = self.normalizar_texto(cidade['uf'])
                
                url = f"https://www.feriadosapi.com/api/v1/feriados/cidade/{ibge}?ano={ano}"

                try:
                    response = requests.get(url, headers=HEADERS, timeout=10)
                    
                    if response.status_code == 200:
                        retorno_api = response.json()
                        
                        if isinstance(retorno_api, list):
                            lista_feriados = retorno_api
                        elif isinstance(retorno_api, dict):
                            lista_feriados = retorno_api.get('feriados', [])
                        else:
                            self.stdout.write(self.style.WARNING(f"Formato inesperado API em {nome_cidade_banco}"))
                            continue
                        
                        count_novos = 0
                        count_atualizados = 0

                        with transaction.atomic():
                            for item in lista_feriados:
                                raw_date = item.get('data') or item.get('date')
                                nome_feriado = item.get('nome') or item.get('name')
                                
                                if not raw_date: continue

                                try:
                                    if '-' in raw_date:
                                        data_formatada = datetime.strptime(raw_date, '%Y-%m-%d').date()
                                    else:
                                        data_formatada = datetime.strptime(raw_date, '%d/%m/%Y').date()
                                except ValueError:
                                    continue

                                obj, created = Feriado.objects.update_or_create(
                                    data=data_formatada,
                                    cidade__iexact=nome_cidade_banco, 
                                    uf__iexact=uf_banco,
                                    defaults={
                                        'cidade': nome_cidade_banco,
                                        'uf': uf_banco,
                                        'descricao': nome_feriado
                                    }
                                )

                                if created:
                                    count_novos += 1
                                else:
                                    count_atualizados += 1
                        
                        self.stdout.write(self.style.SUCCESS(
                            f"  ✔ {nome_cidade_banco}: {count_novos} novos, {count_atualizados} atualizados."
                        ))

                    else:
                        self.stdout.write(self.style.ERROR(f"  ✖ Erro {response.status_code} em {nome_cidade_banco}"))
                
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  ✖ Falha de conexão em {nome_cidade_banco}: {str(e)}"))

        self.stdout.write(self.style.SUCCESS("\n--- IMPORTAÇÃO CONCLUÍDA ---"))