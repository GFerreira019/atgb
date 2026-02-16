from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import time, date, datetime, timedelta
from .models import Colaborador, Projeto, Apontamento, CentroCusto

class CalculoHorasModelTest(TestCase):
    """
    Testes focados na lógica matemática do sistema.
    Garante que não vamos pagar horas erradas.
    """

    def setUp(self):
        # Cria dados básicos para teste
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.colab = Colaborador.objects.create(
            nome_completo='João Teste', 
            user_account=self.user,
            cargo='Analista'
        )
        self.projeto = Projeto.objects.create(nome='Obra Teste', codigo='OBRA-01')

    def test_calculo_horas_simples(self):
        """Teste básico: 08:00 às 12:00 deve dar 04:00"""
        apt = Apontamento.objects.create(
            colaborador=self.colab,
            projeto=self.projeto,
            data_apontamento=date.today(),
            hora_inicio=time(8, 0),
            hora_termino=time(12, 0),
            local_execucao='INT'
        )
        self.assertEqual(apt.duracao_total_str, "04:00")

    def test_calculo_virada_de_noite(self):
        """
        Teste de turno noturno.
        Entrou às 22:00 e saiu às 05:00 do dia seguinte.
        O sistema NÃO pode calcular negativo ou erro. Deve dar 7 horas.
        """
        apt = Apontamento.objects.create(
            colaborador=self.colab,
            projeto=self.projeto,
            data_apontamento=date.today(),
            hora_inicio=time(22, 0),
            hora_termino=time(5, 0),
            local_execucao='INT'
        )
        # 22h -> 24h = 2h
        # 00h -> 05h = 5h
        # Total = 7h
        self.assertEqual(apt.duracao_total_str, "07:00")

    def test_calculo_meia_noite_exata(self):
        """Teste de borda: Término exatamente à meia-noite"""
        apt = Apontamento.objects.create(
            colaborador=self.colab,
            projeto=self.projeto,
            data_apontamento=date.today(),
            hora_inicio=time(20, 0),
            hora_termino=time(0, 0),
            local_execucao='INT'
        )
        self.assertEqual(apt.duracao_total_str, "04:00")


class ApiSegurancaTest(TestCase):
    """
    Testes de Segurança para garantir que ninguém baixe o banco de dados
    sem a senha correta configurada no servidor.
    """

    def setUp(self):
        self.client = Client()
        self.url_exportacao = '/produtividade/api/exportar-completo/'

    @override_settings(DJANGO_API_KEY='senha_super_forte_teste')
    def test_acesso_api_com_senha_correta(self):
        """Deve permitir acesso se o Header bater com o Settings"""
        response = self.client.get(
            self.url_exportacao,
            headers={'X-API-KEY': 'senha_super_forte_teste'} # Header Correto
        )
        # Esperamos 200 OK (ou JSON vazio válido)
        self.assertEqual(response.status_code, 200)

    @override_settings(DJANGO_API_KEY='senha_super_forte_teste')
    def test_acesso_api_com_senha_errada(self):
        """Deve BLOQUEAR (403) se a senha estiver errada"""
        response = self.client.get(
            self.url_exportacao,
            headers={'X-API-KEY': 'senha_fraca_hacker'}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Acesso Negado', response.content)

    @override_settings(DJANGO_API_KEY='senha_super_forte_teste')
    def test_acesso_api_sem_header(self):
        """Deve BLOQUEAR (403) se tentar acessar pelo navegador sem header"""
        response = self.client.get(self.url_exportacao)
        self.assertEqual(response.status_code, 403)

    @override_settings(DJANGO_API_KEY=None)
    def test_servidor_sem_configuracao_seguranca(self):
        """
        Se o servidor não tiver senha configurada (None),
        o sistema deve travar (Erro 500) por segurança, jamais abrir.
        """
        # Tenta acessar mesmo com qualquer senha
        response = self.client.get(
            self.url_exportacao,
            headers={'X-API-KEY': 'tentativa_acesso'}
        )
        # O sistema deve retornar 500 (Erro de Configuração)
        self.assertEqual(response.status_code, 500)


class FluxoPrincipalTest(TestCase):
    """
    Teste rápido de integração para ver se a View de criação não está quebrada.
    """
    def setUp(self):
        self.user = User.objects.create_user(username='operador', password='123')
        self.colab = Colaborador.objects.create(nome_completo='Operador Silva', user_account=self.user)
        self.projeto = Projeto.objects.create(nome='Obra 01', codigo='OB01')
        self.client.login(username='operador', password='123')

    def test_acesso_pagina_novo_apontamento(self):
        """Verifica se a página de lançamento carrega (status 200)"""
        response = self.client.get('/produtividade/apontamento/novo/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'produtividade/apontamento_form.html')

    def test_criar_apontamento_simples(self):
        """Tenta postar um formulário válido"""
        data_iso = date.today().strftime('%Y-%m-%d')
        dados = {
            'data_apontamento': data_iso,
            'hora_inicio': '08:00',
            'hora_termino': '12:00',
            'local_execucao': 'INT',
            'projeto': self.projeto.id,
            'colaborador': self.colab.id,
            'veiculo_selecao': '', 
            'auxiliar_selecao': '',
        }
        
        response = self.client.post('/produtividade/apontamento/novo/', dados)
        
        # Se falhar (retornar 200), imprime o erro do form para saber o que é
        if response.status_code == 200:
            print("\nERROS DO FORMULÁRIO:", response.context['form'].errors)
        
        # Se der certo, redireciona para a mesma página (PRG pattern) com mensagem de sucesso
        self.assertRedirects(response, '/produtividade/apontamento/novo/')
        
        # Verifica se salvou no banco
        self.assertEqual(Apontamento.objects.count(), 1)
        apt = Apontamento.objects.first()
        self.assertEqual(apt.colaborador, self.colab)