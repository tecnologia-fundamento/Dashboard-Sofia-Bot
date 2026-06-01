import streamlit as st
import pandas as pd
import psycopg2
import plotly.express as px
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo("America/Sao_Paulo")

st.set_page_config(page_title="Dashboard Sofia", page_icon="🤖", layout="wide")


@st.cache_resource
def get_connection():
    conn = psycopg2.connect(
        host=st.secrets["db"]["host"],
        port=int(st.secrets["db"]["port"]),
        dbname=st.secrets["db"]["database"],
        user=st.secrets["db"]["user"],
        password=st.secrets["db"]["password"],
        sslmode="require",
    )
    conn.autocommit = True
    return conn


@st.cache_data(ttl=300)
def run_query(query: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql(query, conn)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


st.title("🤖 Dashboard Sofia — Editora Fundamento")
st.caption(f"Atualizado em {datetime.now(BR_TZ).strftime('%d/%m/%Y %H:%M')}")

opcao = st.radio(
    "Período",
    ["Hoje", "Ontem", "Últimos 7 dias", "Últimos 14 dias", "Últimos 30 dias", "Personalizado"],
    horizontal=True,
    index=2,
)

hoje = datetime.now(BR_TZ).date()
if opcao == "Hoje":
    data_inicio = data_fim = hoje
elif opcao == "Ontem":
    data_inicio = data_fim = hoje - timedelta(days=1)
elif opcao == "Últimos 7 dias":
    data_fim = hoje
    data_inicio = hoje - timedelta(days=6)
elif opcao == "Últimos 14 dias":
    data_fim = hoje
    data_inicio = hoje - timedelta(days=13)
elif opcao == "Últimos 30 dias":
    data_fim = hoje
    data_inicio = hoje - timedelta(days=29)
else:  # Personalizado
    intervalo = st.date_input(
        "Selecione o período",
        value=(hoje - timedelta(days=6), hoje),
        max_value=hoje,
        format="DD/MM/YYYY",
    )
    if isinstance(intervalo, tuple) and len(intervalo) == 2:
        data_inicio, data_fim = intervalo
    elif isinstance(intervalo, date):
        data_inicio = data_fim = intervalo
    else:
        data_inicio = data_fim = hoje

st.caption(
    f"Mostrando dados de **{data_inicio.strftime('%d/%m/%Y')}** até **{data_fim.strftime('%d/%m/%Y')}**."
)

diario = run_query(
    f"""
    SELECT * FROM sofia_dashboard_diario
    WHERE dia BETWEEN '{data_inicio.isoformat()}' AND '{data_fim.isoformat()}'
    ORDER BY dia
    """
)

# Periodo anterior (mesma duracao, deslocado pra tras) — pra comparacao
periodo_dias = (data_fim - data_inicio).days + 1
anterior_fim = data_inicio - timedelta(days=1)
anterior_inicio = anterior_fim - timedelta(days=periodo_dias - 1)
anterior = run_query(
    f"""
    SELECT * FROM sofia_dashboard_diario
    WHERE dia BETWEEN '{anterior_inicio.isoformat()}' AND '{anterior_fim.isoformat()}'
    """
)


def delta_pct(atual: int, ant: int):
    if not ant:
        return None
    return f"{((atual - ant) / ant * 100):+.1f}% vs anterior"


ant_clientes = int(anterior["clientes_unicos"].sum()) if not anterior.empty else 0
ant_sozinha = int(anterior["clientes_atendidos_sozinha"].sum()) if not anterior.empty else 0
ant_transferidos = int(anterior["clientes_transferidos"].sum()) if not anterior.empty else 0
ant_links = int(anterior["mensagens_com_link_produto"].sum()) if not anterior.empty else 0

# === Cards ===
total_clientes = int(diario["clientes_unicos"].sum())
total_sozinha = int(diario["clientes_atendidos_sozinha"].sum())
total_transferidos = int(diario["clientes_transferidos"].sum())
total_links = int(diario["mensagens_com_link_produto"].sum())

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "Clientes únicos",
    f"{total_clientes:,}".replace(",", "."),
    delta_pct(total_clientes, ant_clientes),
)
col2.metric(
    "Atendidos sozinha",
    f"{total_sozinha:,}".replace(",", "."),
    delta_pct(total_sozinha, ant_sozinha),
)
col3.metric(
    "Transferidos",
    f"{total_transferidos:,}".replace(",", "."),
    delta_pct(total_transferidos, ant_transferidos),
    delta_color="inverse",
)
col4.metric(
    "Links de produto",
    f"{total_links:,}".replace(",", "."),
    delta_pct(total_links, ant_links),
)

st.divider()

# === Linha: mensagens por dia ===
st.subheader("📊 Volume de mensagens por dia")
fig_msg = px.line(diario, x="dia", y="total_mensagens", markers=True)
fig_msg.update_traces(line_color="#3498db")
fig_msg.update_layout(
    height=300,
    margin=dict(l=0, r=0, t=10, b=0),
    xaxis_title="",
    yaxis_title="Mensagens",
)
st.plotly_chart(fig_msg, use_container_width=True)

# === Barras: sozinha vs transferidos ===
st.subheader("👥 Atendidos sozinha vs Transferidos")
df_long = diario.melt(
    id_vars="dia",
    value_vars=["clientes_atendidos_sozinha", "clientes_transferidos"],
    var_name="tipo",
    value_name="clientes",
)
df_long["tipo"] = df_long["tipo"].map(
    {
        "clientes_atendidos_sozinha": "Sofia sozinha",
        "clientes_transferidos": "Transferidos",
    }
)
fig_split = px.bar(
    df_long,
    x="dia",
    y="clientes",
    color="tipo",
    color_discrete_map={"Sofia sozinha": "#2ecc71", "Transferidos": "#e74c3c"},
    barmode="stack",
)
fig_split.update_layout(
    height=300,
    margin=dict(l=0, r=0, t=10, b=0),
    xaxis_title="",
    yaxis_title="Clientes",
    legend_title="",
)
st.plotly_chart(fig_split, use_container_width=True)

# === Top 5 produtos mais mostrados ===
st.subheader("🏆 Top 5 produtos mais mostrados pela Sofia")
top_produtos = run_query(
    f"""
    WITH produtos AS (
        SELECT (regexp_matches(resposta_sofia, 'editorafundamento[.]com[.]br/products/([a-z0-9-]+)', 'g'))[1] AS handle
        FROM conversas_sofia
        WHERE (created_at AT TIME ZONE 'America/Sao_Paulo')::date
              BETWEEN '{data_inicio.isoformat()}' AND '{data_fim.isoformat()}'
    )
    SELECT handle, COUNT(*) AS mencoes
    FROM produtos
    GROUP BY handle
    ORDER BY mencoes DESC
    LIMIT 5
    """
)
if top_produtos.empty:
    st.info("Nenhum produto mostrado pela Sofia no período.")
else:
    top_produtos["produto"] = top_produtos["handle"].apply(
        lambda h: " ".join(w.capitalize() for w in h.replace("-", " ").split())
    )
    fig_top = px.bar(
        top_produtos.sort_values("mencoes"),
        x="mencoes",
        y="produto",
        orientation="h",
        text="mencoes",
    )
    fig_top.update_traces(marker_color="#9b59b6", textposition="outside")
    fig_top.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="Vezes mostrado",
        yaxis_title="",
    )
    st.plotly_chart(fig_top, use_container_width=True)

st.caption("Dados cacheados por 5 minutos. Recarregue a página para forçar atualização.")
