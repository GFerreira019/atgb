# Sistema de Apontamento de Horas (Timesheet)

Sistema web desenvolvido em **Python/Django** para gestão de produtividade e controle de horas em atividades operacionais da empresa. O projeto foca na experiência do usuário e na integridade dos dados, substituindo planilhas manuais por um fluxo digital responsivo, com validações de regras de negócio em tempo real.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Django](https://img.shields.io/badge/Django-5.0-green)
![TailwindCSS](https://img.shields.io/badge/Tailwind-CSS-38bdf8)
![GCP](https://img.shields.io/badge/Google_Cloud-Compute_Engine-orange)

## Funcionalidades Principais

### 🚀 Gestão Operacional & Integridade
* **Apontamento Flexível:** Registro de horas vinculado a **Obra Específica** (com adendo) ou **Código de Cliente Geral**, garantindo rastreabilidade de custos.
* **Validação Temporal Inteligente:** Bloqueio robusto de datas e horários futuros para evitar fraudes, com suporte nativo a **jornadas noturnas** (virada de dia, ex: 22h às 02h).
* **Gestão de Veículos:** Seleção de frota cadastrada ou cadastro rápido de veículos externos/alugados durante o apontamento.
* **Equipes Dinâmicas:** Adição de múltiplos auxiliares (Auxiliares/Oficiais) em um único registro de ponto ("explode" visualmente no histórico).

### 📋 Folha e Financeiro
* **Indicadores de Folha Simplificados:** Checkboxes para sinalizar **Plantão** e **Pernoite/Diária**. A data desses eventos é vinculada automaticamente à data do registro principal, eliminando erros de preenchimento.
* **Workflow de Ajustes:** Fluxo de solicitação de correção onde o colaborador justifica o erro e o gestor aprova ou rejeita, mantendo histórico auditável.
* **Exportação Otimizada (Excel):** Geração de relatórios `.xlsx` limpos e consolidados, com cálculo automático de horas (incluindo virada de noite) e separação de custos por centro/obra/veículo.

### 🎨 Experiência do Usuário (UX)
* **Calendário Visual Interativo:** Visualização mensal com indicadores de status e ícones para dias com pernoite. Ao selecionar datas de plantão, o calendário guia o usuário bloqueando dias inválidos.
* **Interface Responsiva:** Design *Mobile-First* com Dark Mode nativo utilizando TailwindCSS.
* **Feedback Imediato:** Validações de conflitos de horário (Overlap) e tentativas de lançamento futuro exibidas instantaneamente via JavaScript antes do envio ao servidor.

## Controle de Acesso e Permissões (RBAC)

O sistema implementa uma hierarquia de acesso robusta para garantir a segurança e organização dos dados:

* **OWNER (Superusuário):** Acesso irrestrito. Visualiza histórico global, gerencia cadastros, aprova ajustes e exporta relatórios financeiros.
* **ADMINISTRATIVO:** Visualiza e gerencia colaboradores pertencentes aos **"Setores sob Gestão"**, além de seus próprios registros.
* **GESTOR:** Envia formulários apenas para si, mas possui visão gerencial (leitura) sobre sua equipe.
* **OPERACIONAL:** Acesso restrito. Pode apenas registrar e visualizar seu próprio histórico.

## Visão de Futuro & Roadmap

Este projeto é o alicerce (MVP) para um ecossistema maior de gestão de obras. Os próximos passos estratégicos incluem:

1.  **Mobile First:** Desenvolvimento de PWA ou App Nativo para uso offline em obras sem sinal.
2.  **Integração com Cronogramas:** Vínculo direto entre as horas apontadas e o cronograma físico da obra (MS Project).
3.  **Dashboard em Tempo Real:** Visualização do avanço físico x financeiro.
4.  **Inteligência de Dados:** Análise de métricas para refinar orçamentos futuros (Orçado vs. Realizado).

## Tecnologias Utilizadas

* **Backend:** Python 3, Django 5
* **Frontend:** HTML5, TailwindCSS (CDN), JavaScript Moderno
* **Infraestrutura:** Google Cloud Platform (Compute Engine), Nginx, Gunicorn
* **Bibliotecas:**
    * `Select2` (Selects pesquisáveis via AJAX)
    * `OpenPyXL` (Geração de relatórios Excel)
* **Banco de Dados:** SQLite (Desenvolvimento) / Configuração pronta para PostgreSQL (Produção)

## Como Executar o Projeto

1. **Clone o repositório:**
   ```bash
   git clone [https://github.com/GFerreira019/sistema-gestao-obras.git](https://github.com/GFerreira019/sistema-gestao-obras.git)
   cd sistema-gestao-obras

2. **Crie e ative um ambiente virtual:**
    ```bash
    python -m venv venv
    # Windows:
    venv\Scripts\activate
    # Linux/Mac:
    source venv/bin/activate

3. **Instale as dependências:**
    ```bash
    pip install -r requirements.txt

4. **Configure o Banco de Dados:**
    ```bash
    python manage.py makemigrations
    python manage.py migrate

5. **Crie um Superusuário (Admin):**
    ```bash
    python manage.py createsuperuser

6. **Inicie o Servidor:**
    ```bash
    python manage.py runserver


Acesse: http://127.0.0.1:8000
