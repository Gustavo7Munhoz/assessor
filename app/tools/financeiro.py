import re
import math

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from typing import List, Optional
from pydantic import BaseModel, Field

from app.juiz import agendar_escrita, obter_turno_escrita
from app.tools.db import get_conn
from app.tools.perfil import consultar_perfil_financeiro


# Essa classe garante que o objeto de Python passe todos esses campos
class AddTransactionArgs(BaseModel):
    amount: float = Field(..., description="Valor da transação (use positivo).")
    source_text: str = Field(..., description="Texto original do usuário.")
    occurred_at: Optional[str] = Field(
        default=None,
        description="Timestamp ISO 8601; se ausente, usa NOW() no banco."
    )
    type_id: Optional[int] = Field(default=None, description="ID em transaction_types (1=INCOME, 2=EXPENSES, 3=TRANSFER).")
    type_name: Optional[str] = Field(default=None, description="Nome do tipo: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="FK de categories (opcional).")
    category_name: Optional[str] = Field(default=None, description="Nome da categoria (ex: comida, transporte, etc.)")
    description: Optional[str] = Field(default=None, description="Descrição (opcional).")
    payment_method: Optional[str] = Field(default=None, description="Forma de pagamento (opcional).")

TYPE_ALIASES = {
    "INCOME": "INCOME", "ENTRADA": "INCOME", "RECEITA": "INCOME", "SALÁRIO": "INCOME",
    "EXPENSE": "EXPENSES", "EXPENSES": "EXPENSES", "DESPESA": "EXPENSES", "GASTO": "EXPENSES",
    "TRANSFER": "TRANSFER", "TRANSFERÊNCIA": "TRANSFER", "TRANSFERENCIA": "TRANSFER"
}

TYPE_CATEGORIES = {
    # COMIDA
    "COMIDA": "comida", "ALMOÇO": "comida", "JANTAR": "comida",
    "CAFÉ": "comida", "CAFE": "comida", "RESTAURANTE": "comida",
    "LANCHONETE": "comida", "MERCADO": "comida", "SUPERMERCADO": "comida",
    "IFOOD": "comida", "UBER EATS": "comida", "DELIVERY": "comida",
    "PADARIA": "comida",

    # BESTEIRA
    "BESTEIRA": "besteira", "DOCE": "besteira", "DOCES": "besteira",
    "CHOCOLATE": "besteira", "BALAS": "besteira", "SALGADINHO": "besteira",
    "REFRIGERANTE": "besteira", "SNACK": "besteira", "FAST FOOD": "besteira",

    # ESTUDO
    "ESTUDO": "estudo", "ESCOLA": "estudo", "FACULDADE": "estudo",
    "CURSO": "estudo", "CURSOS": "estudo", "LIVRO": "estudo",
    "LIVROS": "estudo", "MATERIAL": "estudo", "CADERNO": "estudo",
    "CANETA": "estudo", "APOSTILA": "estudo", "EDUCAÇÃO": "estudo",

    # FÉRIAS
    "FÉRIAS": "férias", "FERIAS": "férias", "VIAGEM": "férias",
    "HOTEL": "férias", "POUSADA": "férias", "TURISMO": "férias", "RESORT": "férias",

    # TRANSPORTE
    "TRANSPORTE": "transporte", "UBER": "transporte", "99": "transporte",
    "TAXI": "transporte", "ÔNIBUS": "transporte", "ONIBUS": "transporte",
    "METRÔ": "transporte", "METRO": "transporte", "COMBUSTÍVEL": "transporte",
    "GASOLINA": "transporte", "ETANOL": "transporte", "DIESEL": "transporte",
    "PASSAGEM": "transporte",

    # MORADIA
    "MORADIA": "moradia", "ALUGUEL": "moradia", "CONDOMÍNIO": "moradia",
    "CONDOMINIO": "moradia", "LUZ": "moradia", "ÁGUA": "moradia",
    "AGUA": "moradia", "INTERNET": "moradia", "GÁS": "moradia",
    "GAS": "moradia", "IPTU": "moradia",

    # SAÚDE
    "SAÚDE": "saúde", "SAUDE": "saúde", "FARMÁCIA": "saúde",
    "FARMACIA": "saúde", "REMÉDIO": "saúde", "REMEDIO": "saúde",
    "MÉDICO": "saúde", "MEDICO": "saúde", "EXAME": "saúde",
    "PLANO DE SAÚDE": "saúde", "DENTISTA": "saúde",

    # LAZER
    "LAZER": "lazer", "CINEMA": "lazer", "FILME": "lazer",
    "STREAMING": "lazer", "NETFLIX": "lazer", "SPOTIFY": "lazer",
    "SHOW": "lazer", "FESTA": "lazer", "BAR": "lazer",
    "VIAGEM CURTA": "lazer",

    # CONTAS
    "CONTAS": "contas", "BOLETO": "contas", "FATURA": "contas",
    "CARTÃO": "contas", "CARTAO": "contas", "DÍVIDA": "contas",
    "DIVIDA": "contas", "PAGAMENTO": "contas",

    # INVESTIMENTO
    "INVESTIMENTO": "investimento", "AÇÃO": "investimento",
    "ACAO": "investimento", "AÇÕES": "investimento", "ACOES": "investimento",
    "CRIPTO": "investimento", "BITCOIN": "investimento",
    "RENDA FIXA": "investimento", "TESOURO": "investimento",
    "CDB": "investimento", "POUPANÇA": "investimento",

    # PRESENTE
    "PRESENTE": "presente", "PRESENTES": "presente",
    "ANIVERSÁRIO": "presente", "ANIVERSARIO": "presente",
    "NATAL": "presente", "SURPRESA": "presente",

    # OUTROS
    "OUTROS": "outros", "DIVERSOS": "outros", "VARIADO": "outros",
    "ALEATÓRIO": "outros", "ALEATORIO": "outros"
}

def _resolve_type_id(cur, type_id: Optional[int], type_name: Optional[str]) -> Optional[int]:
    if type_name:
        t = type_name.strip().upper()
        if t in TYPE_ALIASES:
            t = TYPE_ALIASES[t]
        cur.execute(
            "SELECT id FROM transaction_types WHERE UPPER(type)=%s LIMIT 1;",
            (t,)
        )
        row = cur.fetchone()
        return row[0] if row else None
    if type_id:
        return int(type_id)
    return 2  # Default EXPENSES

def _resolve_category_id(
    cur,
    category_id: Optional[int],
    category_name: Optional[str],
    source_text: Optional[str]
) -> Optional[int]:

    if category_name:
        nome = category_name.strip().upper()

        if nome in TYPE_CATEGORIES:
            nome = TYPE_CATEGORIES[nome]

        cur.execute(
            "SELECT id FROM categories WHERE UPPER(name)=%s LIMIT 1;",
            (nome.upper(),)
        )
        row = cur.fetchone()
        if row:
            return row[0]

    if source_text:
        texto = source_text.upper()

        for palavra, categoria in TYPE_CATEGORIES.items():
            if palavra in texto:
                cur.execute(
                    "SELECT id FROM categories WHERE UPPER(name)=%s LIMIT 1;",
                    (categoria.upper(),)
                )
                row = cur.fetchone()
                if row:
                    return row[0]

    if category_id:
        return int(category_id)

    cur.execute(
        "SELECT id FROM categories WHERE UPPER(name)=%s LIMIT 1;",
        ("OUTROS",),
    )
    row = cur.fetchone()
    return row[0] if row else None

# Tool: add_transaction -> Insere uma nova transação no banco
@tool("add_transaction", args_schema=AddTransactionArgs)
def add_transaction(
    amount: float,
    source_text: str,
    occurred_at: Optional[str] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    config: RunnableConfig = None,
) -> dict:
    """Insere uma transação financeira no banco de dados Postgres."""
    if not math.isfinite(amount) or amount < 0:
        return {"status": "error", "message": "O valor da transação não pode ser negativo."}
    turno = obter_turno_escrita(config)

    try:
        conn = get_conn()
        cur = conn.cursor()
    except Exception as exc:
        return {"status": "error", "message": f"PostgreSQL indisponível: {exc}"}

    try:
        resolved_type_id = _resolve_type_id(cur, type_id, type_name)
        if not resolved_type_id:
            return {"status": "error", "message": "Tipo inválido."}

        resolved_category_id = _resolve_category_id(cur, category_id, category_name, source_text)
        cur.execute("SELECT type FROM transaction_types WHERE id = %s;", (resolved_type_id,))
        tipo = cur.fetchone()
        if not tipo:
            return {"status": "error", "message": "Tipo inválido."}
        categoria = None
        if resolved_category_id is not None:
            cur.execute("SELECT name FROM categories WHERE id = %s;", (resolved_category_id,))
            categoria = cur.fetchone()
            if not categoria:
                return {"status": "error", "message": "Categoria inválida."}
        # A sequence reserva uma identidade real sem inserir a linha; recusas podem deixar lacunas.
        cur.execute(
            "SELECT nextval(pg_get_serial_sequence('transactions', 'id')), "
            "COALESCE(%s::timestamptz, NOW()), %s::numeric(14, 2);",
            (occurred_at, amount),
        )
        preview_id, occurred, amount_norm = cur.fetchone()
        occurred_str = str(occurred)
    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

    def _efetivar_insert() -> None:
        conn_w = get_conn()
        cur_w = conn_w.cursor()
        try:
            cur_w.execute(
                """
                INSERT INTO transactions
                    (id, amount, type, category_id, description, payment_method, occurred_at, source_text)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s::timestamptz, %s);
                """,
                (
                    preview_id,
                    amount_norm,
                    resolved_type_id,
                    resolved_category_id,
                    description,
                    payment_method,
                    occurred_str,
                    source_text,
                ),
            )
            conn_w.commit()
        except Exception:
            conn_w.rollback()
            raise
        finally:
            try:
                cur_w.close()
                conn_w.close()
            except Exception:
                pass

    try:
        agendar_escrita(_efetivar_insert, config)
        if turno is not None:
            with turno.lock:
                turno.transacoes[preview_id] = {
                    "id": preview_id, "occurred_at": occurred_str, "amount": float(amount_norm),
                    "type": tipo[0], "category": categoria[0] if categoria else None,
                    "description": description, "payment_method": payment_method, "source_text": source_text,
                }
    except Exception as e:
        return {"status": "error", "message": str(e)}

    return {
        "status": "ok",
        "id": preview_id,
        "occurred_at": occurred_str,
    }
        

class QueryTransactionsArgs(BaseModel):
    limit: int = Field(default=10, description="Número máximo de transações a retornar.")
    date: Optional[str] = Field(
        default=None,
        description="Filtrar por dia (YYYY-MM-DD) ou por mês (YYYY-MM).",
    )
    date_from: Optional[str] = Field(
        default=None,
        description="Data inicial inclusiva (YYYY-MM-DD) para um intervalo.",
    )
    date_to: Optional[str] = Field(
        default=None,
        description="Data final inclusiva (YYYY-MM-DD) para um intervalo.",
    )
    type_filter: Optional[str] = Field(default=None, description="Filtrar por tipo: INCOME | EXPENSES | TRANSFER.")
 
# Tool: query_transactions -> Busca as últimas transações
@tool(args_schema=QueryTransactionsArgs)
def query_transactions(
    limit: int = 10,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    type_filter: Optional[str] = None,
) -> dict:
    """Lista as transações mais recentes do banco de dados, com filtros opcionais por data e tipo."""
    filtro_data = "TRUE"
    parametros_data: list[str] = []
    if date:
        date = date.strip()
        if re.fullmatch(r"\d{4}-\d{2}", date):
            filtro_data = "DATE_TRUNC('month', t.occurred_at AT TIME ZONE 'America/Sao_Paulo') = %s::date"
            parametros_data.append(f"{date}-01")
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            filtro_data = "(t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s::date"
            parametros_data.append(date)
        else:
            return {
                "status": "error",
                "message": "Data inválida. Use YYYY-MM ou YYYY-MM-DD.",
            }

    if date_from and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_from):
        return {"status": "error", "message": "date_from inválida. Use YYYY-MM-DD."}
    if date_to and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_to):
        return {"status": "error", "message": "date_to inválida. Use YYYY-MM-DD."}
    if date_from:
        filtro_data = f"{filtro_data} AND (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date >= %s::date"
        parametros_data.append(date_from)
    if date_to:
        filtro_data = f"{filtro_data} AND (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date <= %s::date"
        parametros_data.append(date_to)

    conn = get_conn()
    cur = conn.cursor()
 
    try:
        if type_filter:
            type_filter = TYPE_ALIASES.get(type_filter.strip().upper(), type_filter.strip().upper())
 
        cur.execute(f"""
            SELECT t.amount, tt.type, c.name, t.description, t.occurred_at
            FROM transactions t
            LEFT JOIN transaction_types tt ON tt.id = t.type
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE {filtro_data}
              AND (%s IS NULL OR UPPER(tt.type) = %s)
            ORDER BY t.occurred_at DESC
            LIMIT %s;
        """, (*parametros_data, type_filter, type_filter, limit))
 
        rows = cur.fetchall()
 
        return {
            "status": "ok",
            "data": [
                {
                    "amount": r[0],
                    "type": r[1],
                    "category": r[2],
                    "description": r[3],
                    "occurred_at": str(r[4]),
                }
                for r in rows
            ]
        }
 
    except Exception as exc:
        return {"status": "error", "message": f"Não foi possível consultar transações: {exc}"}
    finally:
        cur.close()
        conn.close()
 

# Tool: total_balance -> Calcula saldo total
@tool
def total_balance():
    """Calcula o saldo total (entradas - despesas)."""
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN type = 1 THEN amount END), 0) -
                COALESCE(SUM(CASE WHEN type = 2 THEN amount END), 0)
            FROM transactions;
        """)

        total = cur.fetchone()[0]

        return {"status": "ok", "total_balance": float(total)}

    finally:
        cur.close()
        conn.close()


class DailyBalanceArgs(BaseModel):
    date: str = Field(..., description="Filtrar por data no formato YYYY-MM-DD.")
    
# Tool: daily_balance -> Calcula saldo de um dia específico
@tool(args_schema=DailyBalanceArgs)
def daily_balance(date: str) -> dict:
    """Calcula o saldo de um dia específico (entradas - despesas)."""
    conn = get_conn()
    cur = conn.cursor()
 
    try:
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN type = 1 THEN amount END), 0) -
                COALESCE(SUM(CASE WHEN type = 2 THEN amount END), 0)
            FROM transactions
            WHERE DATE(occurred_at) = %s;
        """, (date,))
        total = cur.fetchone()[0]
        return {"status": "ok", "date": date, "balance": float(total)}
 
    finally:
        cur.close()
        conn.close()
        
        
def _local_date_filter_sql(field: str = "occurred_at") -> str:
    """
    Retorna um trecho SQL para filtragem por dia local em America/Sao_Paulo.
    Ex.: (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s::date
    """
    return f"(({field} AT TIME ZONE 'America/Sao_Paulo')::date = %s::date)"
        

class UpdateTransactionArgs(BaseModel):
    id: Optional[int] = Field(
        default=None,
        description="ID da transação a atualizar. Se ausente, será feita uma busca por (match_text + date_local)."
    )
    match_text: Optional[str] = Field(
        default=None,
        description="Texto para localizar transação quando id não for informado (busca em source_text/description)."
    )
    date_local: Optional[str] = Field(
        default=None,
        description="Data local (YYYY-MM-DD) em America/Sao_Paulo; usado em conjunto com match_text quando id ausente."
    )
    amount: Optional[float] = Field(default=None, description="Novo valor.")
    type_id: Optional[int] = Field(default=None, description="Novo type_id (1/2/3).")
    type_name: Optional[str] = Field(default=None, description="Novo type_name: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="Nova categoria (id).")
    category_name: Optional[str] = Field(default=None, description="Nova categoria (nome).")
    description: Optional[str] = Field(default=None, description="Nova descrição.")
    payment_method: Optional[str] = Field(default=None, description="Novo meio de pagamento.")
    occurred_at: Optional[str] = Field(default=None, description="Novo timestamp ISO 8601.")

@tool("update_transaction", args_schema=UpdateTransactionArgs)
def update_transaction(
    id: Optional[int] = None,
    match_text: Optional[str] = None,
    date_local: Optional[str] = None,
    amount: Optional[float] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    occurred_at: Optional[str] = None,
    config: RunnableConfig = None,
) -> dict:
    """
    Atualiza uma transação existente.
    Estratégias:
      - Se 'id' for informado: atualiza diretamente por ID.
      - Caso contrário: localiza a transação mais recente que combine (match_text em source_text/description)
        E (date_local em America/Sao_Paulo), então atualiza.
    Retorna: status, rows_affected, id, e o registro atualizado.
    """
    if all(v is None for v in [amount, type_id, type_name, category_id, category_name, description, payment_method, occurred_at]):
        return {"status": "error", "message": "Nada para atualizar: forneça pelo menos um campo (amount, type, category, description, payment_method, occurred_at)."}
    if amount is not None and (not math.isfinite(amount) or amount < 0):
        return {"status": "error", "message": "O valor da transação não pode ser negativo."}
    turno = obter_turno_escrita(config)

    conn = get_conn()
    cur = conn.cursor()
    try:
        # Resolve target_id
        target_id = id
        if target_id is None:
            if not match_text or not date_local:
                return {"status": "error", "message": "Sem 'id': informe match_text E date_local para localizar o registro."}

            # Buscar o mais recente no dia local informado que combine o texto
            cur.execute(
                f"""
                SELECT t.id
                FROM transactions t
                WHERE (t.source_text ILIKE %s OR t.description ILIKE %s)
                  AND {_local_date_filter_sql("t.occurred_at")}
                ORDER BY t.occurred_at DESC
                LIMIT 1;
                """,
                (f"%{match_text}%", f"%{match_text}%", date_local)
            )
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "Nenhuma transação encontrada para os filtros fornecidos."}
            target_id = row[0]

        # Buscar o registro original antes de agendar a atualização
        cur.execute(
            """
            SELECT
              t.id, t.occurred_at, t.amount, tt.type AS type_name,
              c.name AS category_name, t.description, t.payment_method, t.source_text
            FROM transactions t
            JOIN transaction_types tt ON tt.id = t.type
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = %s;
            """,
            (target_id,)
        )
        r = cur.fetchone()
        if turno is not None:
            with turno.lock:
                pendente = turno.transacoes.get(target_id)
                if pendente:
                    r = tuple(pendente[campo] for campo in (
                        "id", "occurred_at", "amount", "type", "category", "description", "payment_method", "source_text",
                    ))
        if not r:
            return {"status": "error", "message": "Nenhuma transação encontrada para os filtros fornecidos."}

        # Resolver type_id / category_id a partir de nomes, se fornecidos
        resolved_type_id = _resolve_type_id(cur, type_id, type_name) if (type_id or type_name) else None
        new_type_name = None
        if resolved_type_id is not None:
            cur.execute("SELECT type FROM transaction_types WHERE id = %s;", (resolved_type_id,))
            tr = cur.fetchone()
            new_type_name = tr[0] if tr else None
            if not tr:
                return {"status": "error", "message": "Tipo inválido."}
        elif type_id is not None or type_name is not None:
            return {"status": "error", "message": "Tipo inválido."}

        resolved_category_id = category_id
        if category_name and not category_id:
            resolved_category_id = _resolve_category_id(
                cur, category_id=None, category_name=category_name, source_text=None
            )
        new_category_name = None
        if resolved_category_id is not None:
            cur.execute("SELECT name FROM categories WHERE id = %s;", (resolved_category_id,))
            cr = cur.fetchone()
            new_category_name = cr[0] if cr else None
            if not cr:
                return {"status": "error", "message": "Categoria inválida."}

        amount_norm = None
        if amount is not None:
            cur.execute("SELECT %s::numeric(14, 2);", (amount,))
            amount_norm = cur.fetchone()[0]

        occurred_norm = None
        if occurred_at is not None:
            cur.execute("SELECT %s::timestamptz;", (occurred_at,))
            occurred_norm = str(cur.fetchone()[0])

        # Montar SET dinâmico
        sets = []
        params: List[object] = []
        if amount is not None:
            sets.append("amount = %s")
            params.append(amount_norm)
        if resolved_type_id is not None:
            sets.append("type = %s")
            params.append(resolved_type_id)
        if resolved_category_id is not None:
            sets.append("category_id = %s")
            params.append(resolved_category_id)
        if description is not None:
            sets.append("description = %s")
            params.append(description)
        if payment_method is not None:
            sets.append("payment_method = %s")
            params.append(payment_method)
        if occurred_at is not None:
            sets.append("occurred_at = %s::timestamptz")
            params.append(occurred_at)

        if not sets:
            return {"status": "error", "message": "Nenhum campo válido para atualizar."}

        params.append(target_id)

        updated = {
            "id": r[0],
            "occurred_at": occurred_norm if occurred_norm is not None else str(r[1]),
            "amount": float(amount_norm) if amount is not None else float(r[2]),
            "type": new_type_name if new_type_name is not None else r[3],
            "category": new_category_name if new_category_name is not None else r[4],
            "description": description if description is not None else r[5],
            "payment_method": payment_method if payment_method is not None else r[6],
            "source_text": r[7],
        }
    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

    sql_update = f"UPDATE transactions SET {', '.join(sets)} WHERE id = %s;"
    params_update = tuple(params)

    def _efetivar_update() -> None:
        conn_w = get_conn()
        cur_w = conn_w.cursor()
        try:
            cur_w.execute(sql_update, params_update)
            if cur_w.rowcount != 1:
                raise RuntimeError("A transação não existe mais; nenhuma atualização foi confirmada.")
            conn_w.commit()
        except Exception:
            conn_w.rollback()
            raise
        finally:
            try:
                cur_w.close()
                conn_w.close()
            except Exception:
                pass

    try:
        agendar_escrita(_efetivar_update, config)
        if turno is not None:
            with turno.lock:
                turno.transacoes[target_id] = updated
    except Exception as e:
        return {"status": "error", "message": str(e)}

    return {
        "status": "ok",
        "rows_affected": 1,
        "id": target_id,
        "updated": updated,
    }


# Exporta a lista de tools
TOOLS = [
    consultar_perfil_financeiro,
    add_transaction,
    query_transactions,
    total_balance,
    daily_balance,
    update_transaction,
]
