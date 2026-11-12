import os
import unittest
from unittest.mock import patch, MagicMock

# Define variaveis de ambiente ficticias para execucao dos testes
os.environ.setdefault("GEMINI_API_KEY", "mock-gemini-key")
os.environ.setdefault("GROQ_API_KEY", "mock-groq-key")
os.environ.setdefault("DATABASE_URL", "postgres://user:pass@localhost:5432/mockdb")
os.environ.setdefault("MONGODB_URI", "mongodb://user:pass@localhost:27017/")
os.environ.setdefault("QDRANT_URL", "https://mock-qdrant.io")
os.environ.setdefault("QDRANT_API_KEY", "mock-qdrant-key")
os.environ.setdefault("FAQ_PDF_PATH", "data/FAQ_assessor_v1.1.pdf")


class TestAssessorBasics(unittest.TestCase):
    """Suíte de testes de sanidade e contratos para CI/CD."""

    def test_schemas_contracts(self):
        """Valida os esquemas Pydantic centrais da API (ChatRequest, ChatResponse, HealthResponse)."""
        from app.schemas import ChatRequest, ChatResponse, HealthCheck, HealthResponse
        
        req = ChatRequest(session_id="session-123", pergunta="Gastei 50 no mercado")
        self.assertEqual(req.session_id, "session-123")
        self.assertEqual(req.pergunta, "Gastei 50 no mercado")
        self.assertEqual(req.user_id, "usuario_teste")

        resp = ChatResponse(resposta="Registrado com sucesso!", agentes_chamados=["financeiro"])
        self.assertEqual(resp.resposta, "Registrado com sucesso!")
        self.assertEqual(resp.agentes_chamados, ["financeiro"])

    def test_juiz_unit_of_work(self):
        """Valida o mecanismo de escrita diferida (Unit of Work) do Juiz Tardio."""
        from app.juiz import TurnoEscrita, abrir_turno_escrita, agendar_escrita, confirmar_escritas
        
        turno = abrir_turno_escrita()
        self.assertEqual(turno.acoes, [])
        self.assertEqual(turno.transacoes, {})
        self.assertEqual(turno.eventos, {})
        self.assertEqual(turno.status, "preparando")

        config = {"configurable": {"turno_escrita": turno}}
        chamou = []
        agendar_escrita(lambda: chamou.append(True), config=config)

        self.assertEqual(len(turno.acoes), 1)
        self.assertEqual(chamou, [])

        confirmar_escritas(turno)
        self.assertEqual(chamou, [True])
        self.assertEqual(turno.status, "confirmado")

    def test_app_routes_registered(self):
        """Valida se a aplicacao FastAPI monta e registra as rotas essenciais."""
        from app.main import app
        # Filtra rotas com atributo path (ignorando routers intermediarios)
        rotas = [getattr(r, "path", None) for r in app.routes]
        self.assertIn("/health", rotas)


if __name__ == "__main__":
    unittest.main()
