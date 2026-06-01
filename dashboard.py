import streamlit as st
import pandas as pd
import psycopg2
import plotly.express as px
from datetime import datetime, date, timedelta

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
st.caption(f"Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")

opcao = st.radio(
    "Período",
    ["Hoje", "Ontem", "Últimos 7 dias", "Últimos 14 dias", "Últimos 30 dias", "Personalizado"],
    horizontal=True,
    index=2,
)

hoje = date.today()
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

por_agente = run_query(
    f"""
    SELECT agente_usado,
           SUM(total_mensagens) AS msgs,
           SUM(transferencias_efetivadas) AS transferencias_ok,
           SUM(transferencias_perdidas) AS transferencias_perdidas
    FROM sofia_metricas_diarias
    WHERE dia BETWEEN '{data_inicio.isoformat()}' AND '{data_fim.isoformat()}'
    GROUP BY agente_usado
    ORDER BY msgs DESC
    """
)

top_problemas = run_query(
    """
    SELECT telefone, dia, total_mensagens,
           perguntas_repetidas_dados, transferencias_perdidas,
           mensagens_irritacao, score_problema
    FROM sofia_top_problemas_semana
    ORDER BY score_problema DESC
    LIMIT 15
    """
)

# === Cards ===
total_clientes = int(diario["clientes_unicos"].sum())
total_sozinha = int(diario["clientes_atendidos_sozinha"].sum())
total_transferidos = int(diario["clientes_transferidos"].sum())
total_links = int(diario["mensagens_com_link_produto"].sum())
pct_transf = (total_transferidos / total_clientes * 100) if total_clientes else 0
pct_sozinha = (total_sozinha / total_clientes * 100) if total_clientes else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Clientes únicos", f"{total_clientes:,}".replace(",", "."))
col2.metric(
    "Atendidos sozinha",
    f"{total_sozinha:,}".replace(",", "."),
    f"{pct_sozinha:.1f}% do total",
)
col3.metric(
    "Transferidos",
    f"{total_transferidos:,}".replace(",", "."),
    f"{pct_transf:.1f}% do total",
    delta_color="inverse",
)
col4.metric("Links de produto", f"{total_links:,}".replace(",", "."))

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

# === Pizza por agente + tabela top problemas ===
col_a, col_b = st.columns([1, 1.2])

with col_a:
    st.subheader("🤖 Distribuição por agente")
    fig_agente = px.pie(por_agente, names="agente_usado", values="msgs", hole=0.4)
    fig_agente.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig_agente, use_container_width=True)

with col_b:
    st.subheader("📋 Top 15 conversas problemáticas")
    if top_problemas.empty:
        st.info("Nenhum problema registrado no período.")
    else:
        max_val = top_problemas["score_problema"].max()
        max_score = (
            int(max_val) if pd.notna(max_val) and max_val and max_val > 0 else 1
        )
        st.dataframe(
            top_problemas,
            use_container_width=True,
            hide_index=True,
            height=350,
            column_config={
                "score_problema": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=max_score, format="%d"
                )
            },
        )

st.caption("Dados cacheados por 5 minutos. Recarregue a página para forçar atualização.")
