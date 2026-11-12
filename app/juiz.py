"""
Juiz de fidelidade. Na ordem desta aula ele fala por último.
Quem decide é o JEV: choice e noul, sem redação.
A frase fixa, quando entra, é deste arquivo.
"""
import json
import math
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from app.config import TYPESAFE_API_KEY

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODELO = "jev-latest"
LIMIAR = 0.70
FRASE_SEGURA = "Não tenho evidência para afirmar isso."
FRASE_ERRO_ESCRITA = (
    "Não foi possível confirmar todas as gravações. Algumas podem ter sido salvas. "
    "Consulte os registros antes de repetir o pedido."
)

@dataclass
class TurnoEscrita:
    """Unidade em memória, passada pelo estado/config do grafo, nunca pela thread."""
    acoes: list[Callable[[], None]] = field(default_factory=list, repr=False)
    eventos: dict[str, dict] = field(default_factory=dict, repr=False)
    transacoes: dict[int, dict] = field(default_factory=dict, repr=False)
    lock: object = field(default_factory=threading.RLock, repr=False)
    status: str = "preparando"


def abrir_turno_escrita() -> TurnoEscrita:
    """Inicializa a fila de escritas pendentes para o turno atual."""
    return TurnoEscrita()


def obter_turno_escrita(config: dict | None) -> TurnoEscrita | None:
    turno = (config or {}).get("configurable", {}).get("turno_escrita")
    if turno is not None and not isinstance(turno, TurnoEscrita):
        raise RuntimeError("Contexto de escrita inválido.")
    if turno is None and (config or {}).get("metadata", {}).get("langgraph_node"):
        raise RuntimeError("Escrita no grafo sem um turno identificado.")
    return turno


def agendar_escrita(acao: Callable[[], None], config: dict | None = None) -> None:
    """Registra uma escrita para execução após aprovação do juiz, ou executa se fora de turno."""
    turno = obter_turno_escrita(config)
    if turno is not None:
        with turno.lock:
            if turno.status != "preparando":
                raise RuntimeError("O turno de escrita já foi encerrado.")
            turno.acoes.append(acao)
    else:
        acao()


def confirmar_escritas(turno: TurnoEscrita | None) -> None:
    """Efetiva todas as escritas agendadas no turno aprovado."""
    if turno is None:
        return
    with turno.lock:
        if turno.status == "confirmado":
            return
        if turno.status != "preparando":
            raise RuntimeError("O turno não pode ser confirmado novamente.")
        turno.status = "confirmando"
        pendentes = tuple(turno.acoes)
        turno.acoes.clear()
        try:
            for acao in pendentes:
                acao()
        except Exception:
            turno.status = "erro"
            raise
        else:
            turno.status = "confirmado"
        finally:
            turno.eventos.clear()
            turno.transacoes.clear()


def descartar_escritas(turno: TurnoEscrita | None) -> None:
    """Descarta todas as escritas pendentes do turno sem tocar no banco."""
    if turno is not None:
        with turno.lock:
            turno.acoes.clear()
            turno.eventos.clear()
            turno.transacoes.clear()
            if turno.status == "preparando":
                turno.status = "descartado"


REGRAS = (
    "A pergunta do usuário também é evidência do que ele disse que fez. "
    "Somas, contagens, datas convertidas para o horário de Brasília e "
    "reformatação de valores tirados da evidência contam como apoiada. "
    "Esclarecimento, saudação, oferta de ajuda, sugestão de próximo passo "
    "e ausência de registro contam como apoiada. "
    "Opinião do usuário pode ser citada como fala dele. "
    "A moeda de cada valor é a que aparece no source_text ou na fala do usuário. "
    "Moeda trocada, valores de moedas diferentes somados num total só, "
    "opinião dita como fato do sistema, número, data, telefone ou regra "
    "que não saiam da evidência contam como sem_apoio."
)


def _texto(mensagem) -> str:
    conteudo = getattr(mensagem, "content", "")
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        pedacos = []
        for parte in conteudo:
            if isinstance(parte, str):
                pedacos.append(parte)
            elif isinstance(parte, dict):
                pedacos.append(str(parte.get("text") or ""))
        return "\n".join(p for p in pedacos if p)
    return str(conteudo or "")


def _coleta(estado):
    pergunta = ""
    resposta = ""
    evidencias = []
    for mensagem in estado["messages"]:
        tipo = getattr(mensagem, "type", "")
        texto = _texto(mensagem).strip()
        if tipo == "human" and texto:
            pergunta = texto
            evidencias = []
        elif tipo == "tool" and texto:
            nome = getattr(mensagem, "name", "") or "tool"
            evidencias.append(f"[{nome}]\n{texto}")
        elif tipo == "ai":
            for chamada in getattr(mensagem, "tool_calls", None) or []:
                argumentos = json.dumps(chamada.get("args", {}), ensure_ascii=False)
                evidencias.append(f"[chamada {chamada.get('name')}]\n{argumentos}")
            if texto:
                resposta = texto
    evidencia = "\n\n".join(evidencias).strip()
    if not evidencia:
        evidencia = "(nenhuma tool devolveu conteúdo neste turno)"
    return pergunta, resposta, evidencia[-6000:]


def _publicar(texto, rotulo, resposta_original, erro=False):
    print(f"[juiz] {rotulo}")
    resultado = {"agentes_chamados": [f"juiz:{rotulo}"], "erro_operacional": erro}
    if texto.strip() == (resposta_original or "").strip():
        return resultado
    return {**resultado, "messages": [{"role": "assistant", "content": texto.strip()}]}


def _julgar_jev(pergunta, resposta, evidencia, turno=None):
    if not TYPESAFE_API_KEY:
        descartar_escritas(turno)
        return _publicar(FRASE_SEGURA, "sem_chave", resposta, erro=True)
    corpo = json.dumps({
        "model": JEV_MODELO,
        "state": {
            "pergunta": pergunta,
            "resposta": resposta,
            "evidencia": evidencia,
            "regras": REGRAS,
        },
        "questions": {
            "veredito": {
                "type": "choice",
                "instructions": "Seguindo as regras, a resposta só afirma o que a evidência sustenta?",
                "criteria": {
                    "apoiada": "toda afirmação factual aparece na evidência",
                    "parcial": "parte aparece e parte não",
                    "sem_apoio": "há fato, número, regra ou opinião sem evidência",
                },
            },
            "apoiada": {
                "type": "noul",
                "instructions": (
                    "Seguindo as regras, a resposta é fiel à evidência: todo valor, moeda, "
                    "data e fato dela sai da evidência, da fala do usuário ou de contas sobre elas?"
                ),
            },
        },
    }).encode()
    pedido = urllib.request.Request(
        JEV_URL,
        data=corpo,
        headers={
            "Authorization": f"Bearer {TYPESAFE_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as resp:
            dados = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        descartar_escritas(turno)
        return _publicar(FRASE_SEGURA, f"erro http {exc.code}", resposta, erro=True)
    respostas = dados["answers"]
    choice = respostas["veredito"]["choice"]
    noul = float(respostas["apoiada"]["noul"])
    if choice not in {"apoiada", "parcial", "sem_apoio"} or not math.isfinite(noul) or not 0 <= noul <= 1:
        raise ValueError("Veredito inválido do juiz.")
    if choice == "apoiada" and noul >= LIMIAR:
        try:
            confirmar_escritas(turno)
        except Exception as exc:
            print(f"[juiz] falha de gravação: {type(exc).__name__}")
            return _publicar(FRASE_ERRO_ESCRITA, "erro_gravacao", resposta, erro=True)
        return _publicar(resposta, f"apoiada noul={noul:.2f}", resposta)
    descartar_escritas(turno)
    rotulo = "apoiada:abaixo_do_limiar" if choice == "apoiada" else choice
    return _publicar(FRASE_SEGURA, f"{rotulo} noul={noul:.2f}", resposta)


def no_juiz(estado: dict) -> dict:
    turno = estado.get("turno_escrita")
    resposta = ""
    try:
        pergunta, resposta, evidencia = _coleta(estado)
        if not resposta:
            descartar_escritas(turno)
            return _publicar(FRASE_SEGURA, "sem_resposta", resposta, erro=True)
        return _julgar_jev(pergunta, resposta, evidencia, turno)
    except Exception as exc:
        descartar_escritas(turno)
        print(f"[juiz] erro {type(exc).__name__}")
        return _publicar(FRASE_SEGURA, "erro", resposta, erro=True)
