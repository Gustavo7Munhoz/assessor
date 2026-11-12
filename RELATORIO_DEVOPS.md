# Relatório de Atividade — Pipeline CI/CD com IA Generativa

**Curso / Disciplina:** LAB – DevOps  
**Instituição:** Instituto J&F – Centro de Educação para os Negócios  
**Aluno:** Gustavo Munhoz  
**Repositório do Projeto:** [https://github.com/Gustavo7Munhoz/assessor](https://github.com/Gustavo7Munhoz/assessor)  
**Data:** Novembro de 2026  

---

## 1. Descrição do Projeto

O projeto **Assessor** é uma aplicação backend orientada a microsserviços desenvolvida em **FastAPI** e orquestrada por grafos de execução com **LangGraph**. A aplicação oferece um assistente inteligente com arquitetura multiagente especializada (agentes financeiro, agenda, institucional com RAG vetorial e geral) e emprega o padrão de **Juiz Tardio (Deferred Write / Unit of Work)** para garantir que nenhuma transação ou compromisso seja persistido antes da avaliação de fidelidade semântica da resposta.

A persistência do sistema é híbrida, integrando:
* **PostgreSQL (Aiven Cloud)**: Transações financeiras relacionais;
* **MongoDB Atlas**: Documentos de agenda e compromissos;
* **Qdrant Cloud**: Base vetorial com embeddings do FAQ corporativo para RAG.

---

## 2. Estratégia de CI/CD Adotada

### Integração Contínua (CI)
* **Gatilhos**: Executado a cada `push` na branch `main` e em qualquer `pull_request` direcionado para `main`.
* **Ambiente**: Runner `ubuntu-latest` configurado com runtime **Python 3.12**.
* **Etapas**:
  1. **Checkout**: Clonagem do código-fonte via `actions/checkout@v4`.
  2. **Configuração de Ambiente**: Setup do Python com cache de dependências do `pip` (`actions/setup-python@v5`).
  3. **Instalação**: Instalação das bibliotecas e requisitos (`pip install -r requirements.txt`).
  4. **Compilação e Verificação Estática**: Execução de `python -m py_compile` em todos os módulos Python do diretório `app/` para garantir ausência de erros de sintaxe ou referências corrompidas.
  5. **Análise de Código (Linting)**: Execução de `flake8` focado na detecção de erros críticos (erros de sintaxe `E9` e variáveis indefinidas `F82`).
  6. **Testes Automatizados**: Execução de suíte de testes com isolamento de dependências e mocks, cobrindo validação de esquemas Pydantic (`ChatRequest`, `ChatResponse`), rotas do FastAPI (`/health`) e a lógica central de escrita diferida (*Unit of Work*) do `TurnoEscrita`.

### Entrega e Deployment Contínuo (CD)
* **Gatilhos**: Disparado **estritamente após a conclusão com sucesso de todos os passos de CI** (`needs: ci`) e apenas em eventos de `push` na branch `main`.
* **Estratégia Escolhida**: **Containerização Docker e Publicação Automatizada no GitHub Container Registry (GHCR)**.
* **Justificativa da Estratégia**:
  > *"Por se tratar de um ecossistema com múltiplos bancos de dados externos (PostgreSQL, MongoDB e Qdrant) e APIs de inferência LLM (Gemini e Groq), a estratégia corporativa mais adequada e segura é o empacotamento contínuo em container Docker padronizado (`ghcr.io/gustavo7munhoz/assessor:latest`). Essa abordagem assegura imutabilidade do artefato, portabilidade imediata para qualquer orquestrador (Kubernetes, AWS ECS ou GCP Cloud Run) e elimina riscos de segurança derivados da exposição indevida de chaves de produção durante testes de homologação."*
* **Etapas do CD**:
  1. Setup do Docker Buildx (`docker/setup-buildx-action@v3`).
  2. Autenticação no registro de containers do GitHub (`ghcr.io`) via token nativo (`secrets.GITHUB_TOKEN`).
  3. Extração automática de metadados e tags semânticas (`docker/metadata-action@v5`).
  4. Build e publicação (*Push*) da imagem com cache otimizado (`docker/build-push-action@v5`).
  5. Confirmação do deployment e versionamento da imagem vinculada ao SHA do commit.

---

## 3. Arquivo da Pipeline (`.github/workflows/ci-cd.yml`)

```yaml
name: CI/CD Pipeline - Assessor Inteligente

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  # ============================================================================
  # ETAPA 1: CI (Continuous Integration)
  # Executa checkout, setup Python, instalacao, analise de sintaxe e testes
  # ============================================================================
  ci:
    name: CI - Validacao, Lint & Testes Automatizados
    runs-on: ubuntu-latest

    steps:
      - name: 1. Checkout do Repositorio
        uses: actions/checkout@v4

      - name: 2. Configurar Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: 3. Instalar Dependencias
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: 4. Verificacao de Sintaxe e Compilacao dos Modulos
        run: |
          python -m py_compile $(find app -name "*.py")
          python -c "import app.main; print('App module successfully loaded!')"

      - name: 5. Analise Estatica (Flake8 / Lint)
        run: |
          flake8 app --count --select=E9,F63,F7,F82 --show-source --statistics

      - name: 6. Execucao dos Testes Automatizados (Pytest)
        run: |
          pytest tests/ -v --disable-warnings

  # ============================================================================
  # ETAPA 2: CD (Continuous Deployment)
  # Executa SOMENTE apos a CI passar com sucesso e APENAS em push na branch main
  # ============================================================================
  cd:
    name: CD - Build & Deploy de Container (GitHub Packages / GHCR)
    needs: ci
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: 1. Checkout do Repositorio
        uses: actions/checkout@v4

      - name: 2. Setup do Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: 3. Autenticacao no GitHub Container Registry (GHCR)
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: 4. Extrair Metadados e Tags para o Container
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=raw,value=latest
            type=sha,format=short

      - name: 5. Build e Publicacao (Deploy) da Imagem Docker
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: 6. Confirmacao do Deploy Automatizado
        run: |
          echo "=============================================================="
          echo " Deployment concluido com sucesso no GitHub Packages!"
          echo " Imagem disponibilizada: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest"
          echo " Commit SHA: ${{ github.sha }}"
          echo "=============================================================="
```

---

## 4. Registro de Interação com a IA Generativa

Durante o ciclo de engenharia do pipeline, foram realizadas interações direcionadas com a IA para concepção, depuração e refinamento dos artefatos:

| # | Prompt Utilizado | Resultado Obtido | Problema / Desafio Encontrado | Alteração / Solução Adotada |
|---|---|---|---|---|
| **1** | *"Crie um planejamento para a gente fazer essa atividade nesse novo repositório nosso"* | Plano detalhado mapeando os requisitos de CI, CD e testes. | O projeto original não possuía suíte de testes unitários automatizados para o CI executar. | Planejada a criação da pasta `tests/` e inclusão de dependências (`pytest`, `flake8`) no `requirements.txt`. |
| **2** | *"O que eu preciso fazer? Você consegue fazer tudo sozinho? Quero a explicação completa"* | Mapeamento das opções de deployment para FastAPI (Render vs Docker/GHCR). | A sugestão inicial de hospedar no Render exigiria cadastro manual externo e chaves de banco de produção. | Analisadas as alternativas do enunciado e selecionado o GitHub Container Registry como solução completa e autônoma. |
| **3** | *"Mas eu preciso rodar no Render? Não pode ser só o link do repositório? Porque o Render só vai subir o front, mas não vai funcionar efetivamente porque a API não vai estar rodando, não é??"* | Validação técnica da crítica do desenvolvedor e confirmação do modelo em Docker. | Constatou-se que tentar rodar a API completa no Render sem os 3 bancos configurados resultaria em falhas de timeout e exposição de segredos. | Adoção formal da estratégia de container Docker (`ghcr.io`) conforme previsto explicitamente no enunciado da atividade. |
| **4** | *"Pode implementar sim"* | Criação dos arquivos `Dockerfile`, `.dockerignore`, `tests/test_basic.py` e `.github/workflows/ci-cd.yml`. | Divergência de atributos no teste do `TurnoEscrita` e routers do FastAPI durante a validação local. | Ajustados os testes para refletir exatamente os métodos `abrir_turno_escrita` e `confirmar_escritas` de `app/juiz.py`. |

---

## 5. Respostas às Questões Conclusivas

### 1. Quantos prompts foram necessários para chegar à versão final?
Foram necessários **4 prompts** principais com a IA para:
1. Elaboração do plano técnico de arquitetura;
2. Esclarecimento sobre o papel do desenvolvedor e escopo das ferramentas;
3. Refinamento crítico da estratégia de deploy (substituição do Render pelo GitHub Container Registry);
4. Instrução de implementação e consolidação dos artefatos.

### 2. Quais foram os principais problemas encontrados?
* **Ausência de suíte de testes prévia**: O projeto continha apenas código de aplicação e não possuía rotinas de teste para alimentar o step de testes do CI.
* **Complexidade de credenciais no deploy remoto**: A aplicação depende de 3 bancos (PostgreSQL, MongoDB Atlas e Qdrant) e chaves de IA (Gemini e Groq). Um deploy em PaaS convencional falharia sem a sincronização manual de todas as variáveis de ambiente.
* **Ajuste de contratos de teste**: A primeira versão do teste unitário tentou instanciar contratos fictícios de uma versão anterior do `TurnoEscrita`, necessitando alinhamento com a implementação real de `app/juiz.py`.

### 3. Quais alterações foram necessárias?
* Adição de pacotes de qualidade no `requirements.txt` (`pytest`, `pytest-mock`, `httpx`, `flake8`).
* Criação de um `Dockerfile` otimizado em múltiplas camadas baseado em `python:3.12-slim`.
* Criação do `.dockerignore` para impedir o empacotamento de segredos (`.env`), ambientes virtuais e caches.
* Desenvolvimento de testes automatizados modulares com variáveis de ambiente mockadas em `tests/test_basic.py`.
* Criação do fluxo `.github/workflows/ci-cd.yml` separando explicitamente os jobs de CI e CD.

### 4. Quais alterações foram realizadas manualmente?
* A definição do repositório no GitHub (`https://github.com/Gustavo7Munhoz/assessor`) e a sincronização inicial da licença.
* A análise crítica pelo desenvolvedor quanto à inviabilidade de deploy no Render sem credenciais de banco, orientando a IA para a solução via Docker.
* A coleta e inserção das evidências gráficas da execução da pipeline no GitHub Actions.

### 5. Como você verificou que a pipeline estava funcionando corretamente?
* **Verificação Local**: Execução prévia da compilação com `py_compile` e execução da suíte `tests/test_basic.py` aprovando 100% dos testes de esquemas, rotas e `TurnoEscrita`.
* **Verificação Remota (GitHub Actions)**: Acompanhamento da execução na aba **Actions** do repositório após o `git push` na branch `main`, constatando o status de sucesso (verde ✅) em ambas as etapas:
  * Job `CI - Validacao, Lint & Testes Automatizados`: OK;
  * Job `CD - Build & Deploy de Container (GitHub Packages / GHCR)`: Imagem `latest` construída e publicada com sucesso no GitHub Container Registry.

---

## 6. Evidências de Execução da Pipeline CI/CD

*(Espaço reservado para inserção dos screenshots da tela do GitHub Actions exibindo o fluxo verde e o pacote gerado)*

* **Evidência 1: Visão geral da execução da Pipeline (CI → CD)**
> *(Inserir print da tela de Actions do GitHub com os dois jobs concluídos com sucesso)*

* **Evidência 2: Detalhe do Job de CI (Testes e Validação)**
> *(Inserir print dos logs do job `ci` exibindo a aprovação dos testes)*

* **Evidência 3: Detalhe do Job de CD (Deploy da Imagem no GHCR)**
> *(Inserir print do job `cd` e/ou da aba Packages do repositório com o container publicado)*
