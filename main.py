from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import unicodedata
import os
import re
import bcrypt
import psycopg2
from jose import jwt, JWTError
from database import get_db_connection

app = FastAPI(title="BENITHE - Se cuide para cuidar melhor")

BASE_DIR = Path(__file__).resolve().parent

# Carregar configurações locais
env_file = BASE_DIR / ".env"
if env_file.exists():
    for linha in env_file.read_text().splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip())

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET não encontrado no arquivo .env")

ALGORITHM = "HS256"
COOKIE_NAME = "benithe_token"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Conexão segura com o PostgreSQL
@contextmanager
def banco():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Dados recebidos
class CadastroPayload(BaseModel):
    nome: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., min_length=5, max_length=255)
    senha: str = Field(..., min_length=8, max_length=72)


class LoginPayload(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    senha: str = Field(..., min_length=1, max_length=72)


class EmocaoPayload(BaseModel):
    emocao: str = Field(..., min_length=1, max_length=60)
    notas: str = Field(default="", max_length=2000)


# Biblioteca original de emoções e intervenções
INTERVENCOES = {
    "ansiedade": {
        "mensagem_acolhimento": "A ansiedade pode fazer o peito apertar e a respiração parecer mais difícil. Aqui, no Se Cuide para Cuidar, você encontra um espaço de acolhimento, sem julgamentos. Vamos passar por esse momento um passo de cada vez.",
        "intervencao_pratica": "Respiração consciente: inspire suavemente pelo nariz por 4 segundos e solte o ar lentamente por 6 segundos. Repita por 1 minuto, sem forçar a respiração."
    },
    "tensao": {
        "mensagem_acolhimento": "O corpo também sente o peso das pressões do plantão e da rotina. Você merece um momento para relaxar e cuidar de si.",
        "intervencao_pratica": "Relaxamento muscular: gire os ombros suavemente para trás 5 vezes. Relaxe a mandíbula, solte os braços e faça movimentos leves com o pescoço, respeitando seus limites."
    },
    "cansaco": {
        "mensagem_acolhimento": "Seu esforço é importante, mas seus limites também precisam ser respeitados. Você não precisa estar disponível e produtivo o tempo todo.",
        "intervencao_pratica": "Pausa de recuperação: se possível, sente-se em um ambiente tranquilo por alguns minutos, hidrate-se e permita que seu corpo descanse."
    },
    "sobrecarga": {
        "mensagem_acolhimento": "Tudo parece urgente ao mesmo tempo, mas você não precisa resolver tudo de uma vez. Um passo de cada vez também é progresso.",
        "intervencao_pratica": "Organização mental: identifique duas prioridades reais para este momento. Divida as demais tarefas em pequenas etapas e, quando possível, peça apoio."
    },
    "alegria": {
        "mensagem_acolhimento": "Que bom que você está se sentindo bem! Permita-se reconhecer e aproveitar os momentos positivos. Você também merece sentir leveza.",
        "intervencao_pratica": "Registro positivo: pense em três coisas que contribuíram para esse sentimento e registre uma delas no seu diário emocional."
    },
    "tristeza": {
        "mensagem_acolhimento": "Está tudo bem não estar bem o tempo todo. Você não precisa esconder o que sente nem se cobrar para melhorar imediatamente.",
        "intervencao_pratica": "Acolhimento emocional: permita-se reconhecer o que está sentindo. Se puder, converse com alguém de confiança e faça algo gentil por você."
    },
    "animacao": {
        "mensagem_acolhimento": "É muito bom sentir entusiasmo e disposição! Valorize essa energia e lembre-se de equilibrar suas conquistas com momentos de descanso.",
        "intervencao_pratica": "Intenção positiva: escolha algo que gostaria de realizar hoje e defina um pequeno passo para começar."
    },
    "irritacao": {
        "mensagem_acolhimento": "Às vezes, a irritação aparece quando nossas necessidades e limites não estão sendo respeitados. Seus sentimentos merecem atenção.",
        "intervencao_pratica": "Pausa consciente: afaste-se brevemente da situação, se possível. Relaxe os ombros e identifique o que está incomodando você."
    },
    "frustracao": {
        "mensagem_acolhimento": "Nem tudo acontece como esperamos. Sentir frustração não significa fracasso. Você pode recomeçar no seu próprio ritmo.",
        "intervencao_pratica": "Reorganização: identifique o que está ao seu alcance mudar e escolha uma pequena atitude possível neste momento."
    },
    "solidao": {
        "mensagem_acolhimento": "Mesmo quando parece que ninguém percebe o que você está sentindo, seus sentimentos importam. Você não precisa enfrentar tudo sozinho.",
        "intervencao_pratica": "Conexão: envie uma mensagem para alguém de confiança. Não precisa explicar tudo. Permita-se receber companhia e acolhimento."
    },
    "desmotivacao": {
        "mensagem_acolhimento": "Você não precisa estar motivado todos os dias. Seu valor não depende da sua produtividade ou do quanto consegue realizar.",
        "intervencao_pratica": "Pequenos passos: escolha uma atividade simples e possível para hoje. Reconheça seu esforço, mesmo que pareça pequeno."
    },
    "medo": {
        "mensagem_acolhimento": "Sentir medo não significa fraqueza. Você merece acolhimento e pode respeitar seu próprio tempo para lidar com aquilo que preocupa você.",
        "intervencao_pratica": "Reconhecimento: identifique o que está causando esse medo. Pense em uma atitude pequena e segura que possa ajudar neste momento."
    },
    "esgotamento": {
        "mensagem_acolhimento": "Você não precisa chegar ao seu limite para merecer descanso. Cuidar de si também faz parte do cuidado com o outro.",
        "intervencao_pratica": "Recuperação: se possível, interrompa suas atividades por alguns minutos, procure apoio e avalie a necessidade de descanso e acompanhamento profissional."
    },
    "sofrimento_intenso": {
        "mensagem_acolhimento": "Você não precisa enfrentar esse momento sozinho. O que está sentindo merece atenção e cuidado. Sua vida importa e existe ajuda disponível.",
        "intervencao_pratica": "Procure apoio agora. O CVV atende gratuitamente pelo telefone 188, 24 horas. Se houver risco imediato de se machucar ou tirar a própria vida, procure um pronto-socorro ou ligue 192 (SAMU). Se possível, fique acompanhado de alguém de confiança."
    }
}


def normalizar_texto(texto):
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        c for c in texto if not unicodedata.combining(c)
    )
    return texto.lower().strip().replace(" ", "_")


def classificar_atencao(chave):
    if chave == "sofrimento_intenso":
        return "alto"
    if chave in [
        "ansiedade", "sobrecarga", "tristeza",
        "irritacao", "frustracao", "medo",
        "esgotamento", "solidao", "desmotivacao"
    ]:
        return "moderado"
    return "baixo"


def criar_token(usuario_id):
    expiracao = datetime.now(timezone.utc) + timedelta(hours=8)
    dados = {"sub": str(usuario_id), "exp": expiracao}
    return jwt.encode(dados, JWT_SECRET, algorithm=ALGORITHM)


def obter_usuario_atual(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")

    try:
        dados = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        usuario_id = int(dados["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Sessão inválida. Faça login novamente.")

    with banco() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, nome, email FROM usuarios WHERE id = %s AND ativo = TRUE",
                (usuario_id,)
            )
            usuario = cur.fetchone()

    if not usuario:
        raise HTTPException(status_code=401, detail="Usuário não encontrado.")

    return {"id": usuario[0], "nome": usuario[1], "email": usuario[2]}


# Página inicial original
@app.get("/")
def pagina_inicial():
    return FileResponse(BASE_DIR / "index.html")


# Cadastro
@app.post("/api/cadastro")
def cadastrar(payload: CadastroPayload):
    nome = payload.nome.strip()
    email = payload.email.strip().lower()

    if not nome or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Informe nome e e-mail válidos.")

    if len(payload.senha.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="A senha excede o limite permitido.")

    senha_hash = bcrypt.hashpw(
        payload.senha.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    try:
        with banco() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usuarios (nome, email, senha_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id, nome, email
                    """,
                    (nome, email, senha_hash)
                )
                usuario = cur.fetchone()
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="Este e-mail já está cadastrado.")

    return {
        "mensagem": "Cadastro realizado com sucesso.",
        "usuario": {"id": usuario[0], "nome": usuario[1], "email": usuario[2]}
    }


# Login
@app.post("/api/login")
def login(payload: LoginPayload, response: Response):
    email = payload.email.strip().lower()

    if len(payload.senha.encode("utf-8")) > 72:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")

    with banco() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, nome, email, senha_hash
                FROM usuarios
                WHERE email = %s AND ativo = TRUE
                """,
                (email,)
            )
            usuario = cur.fetchone()

    if not usuario or not bcrypt.checkpw(
        payload.senha.encode("utf-8"), usuario[3].encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")

    token = criar_token(usuario[0])

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=28800,
        path="/"
    )

    return {
        "mensagem": "Login realizado com sucesso.",
        "usuario": {"id": usuario[0], "nome": usuario[1], "email": usuario[2]}
    }


# Consultar usuário autenticado
@app.get("/api/me")
def meu_usuario(usuario=Depends(obter_usuario_atual)):
    return {"usuario": usuario}


# Sair da conta
@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax"
    )
    return {"mensagem": "Sessão encerrada."}


# Registrar emoção no PostgreSQL
@app.post("/api/emocao")
def processar_emocao(
    payload: EmocaoPayload,
    usuario=Depends(obter_usuario_atual)
):
    chave = normalizar_texto(payload.emocao)
    resposta = INTERVENCOES.get(chave)

    if resposta is None:
        raise HTTPException(
            status_code=400,
            detail="Emoção não encontrada. Selecione uma opção da lista."
        )

    nivel = classificar_atencao(chave)

    with banco() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO registros_emocionais
                (usuario_id, emocoes, notas, mensagem_acolhimento,
                 intervencao_pratica, nivel_atencao)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING criado_em
                """,
                (
                    usuario["id"],
                    [chave],
                    payload.notas,
                    resposta["mensagem_acolhimento"],
                    resposta["intervencao_pratica"],
                    nivel
                )
            )
            data_hora = cur.fetchone()[0]

    return {
        "emocao": payload.emocao,
        "mensagem_acolhimento": resposta["mensagem_acolhimento"],
        "intervencao_pratica": resposta["intervencao_pratica"],
        "nivel_atencao": nivel,
        "notas": payload.notas,
        "data_hora": data_hora.strftime("%d/%m/%Y %H:%M")
    }


# Histórico privado do usuário autenticado
@app.get("/entries")
def buscar_registros(usuario=Depends(obter_usuario_atual)):
    with banco() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT emocoes, notas, mensagem_acolhimento,
                       intervencao_pratica, nivel_atencao, criado_em
                FROM registros_emocionais
                WHERE usuario_id = %s
                ORDER BY criado_em DESC
                """,
                (usuario["id"],)
            )
            registros = cur.fetchall()

    return [
        {
            "emocao": registro[0][0] if registro[0] else "",
            "notas": registro[1] or "",
            "mensagem_acolhimento": registro[2] or "",
            "intervencao_pratica": registro[3] or "",
            "nivel_atencao": registro[4] or "",
            "data_hora": registro[5].strftime("%d/%m/%Y %H:%M")
        }
        for registro in registros
    ]


# Verificar funcionamento
@app.get("/api/status")
def verificar_status():
    try:
        with banco() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM registros_emocionais")
                total_registros = cur.fetchone()[0]

        return {
            "aplicativo": "BENITHE",
            "slogan": "Se cuide para cuidar melhor",
            "status": "funcionando",
            "total_emocoes": len(INTERVENCOES),
            "banco": "PostgreSQL conectado",
            "total_registros": total_registros
        }
    except Exception:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível.")
