"""Ferramentas persistentes de agenda armazenadas no MongoDB."""

import uuid
import threading
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.juiz import agendar_escrita, obter_turno_escrita
from app.memory import get_db

_indice_criado = False
_lock_confirmacao = threading.RLock()


def _get_col_eventos():
    """Obtém a coleção e cria seu índice apenas após conectar ao MongoDB."""
    global _indice_criado
    col_eventos = get_db()["eventos"]
    if not _indice_criado:
        col_eventos.create_index([("user_id", 1), ("inicio", 1)])
        _indice_criado = True
    return col_eventos


def _user_id(config: RunnableConfig) -> str | None:
    configurable = config.get("configurable", {})
    return configurable.get("user_id") or configurable.get("thread_id")


def _instante(texto: str) -> datetime:
    valor = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    return valor if valor.tzinfo else valor.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))


def _validar_intervalo(evento: dict) -> None:
    if _instante(evento["fim"]) <= _instante(evento["inicio"]):
        raise ValueError("O fim deve ser posterior ao início.")


def _conflito(col, evento: dict, turno=None) -> dict | None:
    # Horários antigos são strings com offsets diferentes; comparar os instantes preserva esses dados.
    eventos = {doc["_id"]: doc for doc in col.find({"user_id": evento["user_id"], "status": "ativo"})}
    if turno is not None:
        eventos.update(turno.eventos)
    for outro in eventos.values():
        if outro["_id"] == evento["_id"] or outro["user_id"] != evento["user_id"] or outro["status"] != "ativo":
            continue
        if _instante(outro["inicio"]) < _instante(evento["fim"]) and _instante(outro["fim"]) > _instante(evento["inicio"]):
            return outro
    return None


def _buscar_evento(col, evento_id, user_id, turno):
    evento = turno.eventos.get(evento_id) if turno is not None else None
    if evento is None:
        evento = col.find_one({"_id": evento_id, "user_id": user_id, "status": "ativo"})
    if evento and evento["user_id"] == user_id and evento["status"] == "ativo":
        return dict(evento)
    return None


def _agendar_evento(acao, evento, config):
    agendar_escrita(acao, config)
    turno = obter_turno_escrita(config)
    if turno is not None:
        turno.eventos[evento["_id"]] = dict(evento)


def _efetivar_atualizacao(evento_id, user_id, alteracoes):
    # shortcut: coordena confirmações neste processo; múltiplos workers exigem exclusão no banco.
    with _lock_confirmacao:
        col = _get_col_eventos()
        existente = col.find_one({"_id": evento_id, "user_id": user_id, "status": "ativo"})
        if not existente:
            raise RuntimeError("Evento não está mais ativo.")
        atualizado = {**existente, **alteracoes}
        if atualizado["status"] == "ativo":
            _validar_intervalo(atualizado)
            if _conflito(col, atualizado):
                raise RuntimeError("Existe um compromisso nesse horário.")
        resultado = col.update_one(
            {"_id": evento_id, "user_id": user_id, "status": "ativo"}, {"$set": alteracoes},
        )
        if resultado.matched_count != 1:
            raise RuntimeError("Evento não foi atualizado.")


class CriarEventoArgs(BaseModel):
    titulo: str = Field(..., min_length=1)
    inicio: str = Field(..., description="Data e hora ISO 8601, por exemplo 2026-09-01T14:00:00-03:00.")
    fim: str = Field(..., description="Data e hora ISO 8601 posterior ao início.")
    local: Optional[str] = None
    participantes: list[str] = Field(default_factory=list)
    lembrete: Optional[str] = None


@tool("criar_evento", args_schema=CriarEventoArgs)
def criar_evento(
    titulo: str,
    inicio: str,
    fim: str,
    config: RunnableConfig,
    local: str | None = None,
    participantes: list[str] | None = None,
    lembrete: str | None = None,
) -> dict:
    """Cria um compromisso depois que os dados necessários foram confirmados."""
    user_id = _user_id(config)
    if not user_id:
        return {"status": "error", "message": "Usuário não identificado."}
    evento = {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "titulo": titulo,
        "inicio": inicio,
        "fim": fim,
        "local": local,
        "participantes": participantes or [],
        "lembrete": lembrete,
        "status": "ativo",
        "criado_em": datetime.now(timezone.utc),
    }
    try:
        _validar_intervalo(evento)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    turno = obter_turno_escrita(config)
    with turno.lock if turno is not None else nullcontext():
        conflito = _conflito(_get_col_eventos(), evento, turno)
        if conflito:
            return {"status": "conflict", "message": "Existe um compromisso nesse horário.", "evento": conflito}

        def efetivar():
            with _lock_confirmacao:
                col = _get_col_eventos()
                if _conflito(col, evento):
                    raise RuntimeError("Existe um compromisso nesse horário.")
                col.insert_one(dict(evento))

        _agendar_evento(efetivar, evento, config)
    return {"status": "ok", "evento": evento}


class ListarEventosArgs(BaseModel):
    de: Optional[str] = Field(default=None, description="Inicio ISO 8601 opcional.")
    ate: Optional[str] = Field(default=None, description="Fim ISO 8601 opcional.")
    limite: int = Field(default=20, ge=1, le=100)


@tool("listar_eventos", args_schema=ListarEventosArgs)
def listar_eventos(
    config: RunnableConfig,
    de: str | None = None,
    ate: str | None = None,
    limite: int = 20,
) -> dict:
    """Lista compromissos ativos, podendo filtrar por uma janela de tempo."""
    user_id = _user_id(config)
    if not user_id:
        return {"status": "error", "message": "Usuário não identificado."}
    filtro: dict = {"user_id": user_id, "status": "ativo"}
    if de or ate:
        filtro["inicio"] = {}
        if de:
            filtro["inicio"]["$gte"] = de
        if ate:
            filtro["inicio"]["$lte"] = ate
    eventos = list(_get_col_eventos().find(filtro).sort("inicio", 1).limit(limite))
    return {"status": "ok", "eventos": eventos}


class AtualizarEventoArgs(BaseModel):
    evento_id: str
    titulo: Optional[str] = None
    inicio: Optional[str] = None
    fim: Optional[str] = None
    local: Optional[str] = None
    lembrete: Optional[str] = None


@tool("atualizar_evento", args_schema=AtualizarEventoArgs)
def atualizar_evento(
    evento_id: str,
    config: RunnableConfig,
    titulo: str | None = None,
    inicio: str | None = None,
    fim: str | None = None,
    local: str | None = None,
    lembrete: str | None = None,
) -> dict:
    """Atualiza os campos informados de um compromisso existente."""
    user_id = _user_id(config)
    alteracoes = {
        chave: valor
        for chave, valor in {
            "titulo": titulo, "inicio": inicio, "fim": fim,
            "local": local, "lembrete": lembrete,
        }.items()
        if valor is not None
    }
    if not user_id:
        return {"status": "error", "message": "Usuário não identificado."}
    if not alteracoes:
        return {"status": "error", "message": "Nenhuma alteração informada."}
    turno = obter_turno_escrita(config)
    with turno.lock if turno is not None else nullcontext():
        col_eventos = _get_col_eventos()
        existente = _buscar_evento(col_eventos, evento_id, user_id, turno)
        if not existente:
            return {"status": "error", "message": "Evento não encontrado."}
        evento_atualizado = {**existente, **alteracoes}
        try:
            _validar_intervalo(evento_atualizado)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        if _conflito(col_eventos, evento_atualizado, turno):
            return {"status": "conflict", "message": "Existe um compromisso nesse horário."}
        _agendar_evento(
            lambda: _efetivar_atualizacao(evento_id, user_id, alteracoes), evento_atualizado, config,
        )
    return {"status": "ok", "evento": evento_atualizado}


class CancelarEventoArgs(BaseModel):
    evento_id: str


@tool("cancelar_evento", args_schema=CancelarEventoArgs)
def cancelar_evento(evento_id: str, config: RunnableConfig) -> dict:
    """Cancela um compromisso que o usuário confirmou que deseja cancelar."""
    user_id = _user_id(config)
    if not user_id:
        return {"status": "error", "message": "Usuário não identificado."}
    turno = obter_turno_escrita(config)
    with turno.lock if turno is not None else nullcontext():
        existente = _buscar_evento(_get_col_eventos(), evento_id, user_id, turno)
        if not existente:
            return {"status": "error", "message": "Evento não encontrado."}
        alteracoes = {"status": "cancelado", "cancelado_em": datetime.now(timezone.utc)}
        _agendar_evento(
            lambda: _efetivar_atualizacao(evento_id, user_id, alteracoes),
            {**existente, **alteracoes}, config,
        )
    return {"status": "ok", "evento_id": evento_id}


TOOLS_AGENDA = [criar_evento, listar_eventos, atualizar_evento, cancelar_evento]
