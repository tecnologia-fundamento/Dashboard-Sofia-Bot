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

# === Cards (atendimento = cliente único POR DIA: se o mesmo cliente volta em outro dia, conta de novo) ===
cards_data = run_query(
    f"""
    SELECT
        COUNT(DISTINCT (telefone, (created_at AT TIME ZONE 'America/Sao_Paulo')::date)) AS atendimentos,
        COUNT(DISTINCT (telefone, (created_at AT TIME ZONE 'America/Sao_Paulo')::date)) FILTER (WHERE escalado_humano) AS transferidos,
        COUNT(*) FILTER (WHERE resposta_sofia LIKE '%/products/%') AS links_produto
    FROM conversas_sofia
    WHERE (created_at AT TIME ZONE 'America/Sao_Paulo')::date
          BETWEEN '{data_inicio.isoformat()}' AND '{data_fim.isoformat()}'
    """
)
total_atendimentos = int(cards_data["atendimentos"].iloc[0])
total_transferidos = int(cards_data["transferidos"].iloc[0])
total_sozinha = total_atendimentos - total_transferidos
total_links = int(cards_data["links_produto"].iloc[0])
pct_sozinha = (total_sozinha / total_atendimentos * 100) if total_atendimentos else 0
pct_transf = (total_transferidos / total_atendimentos * 100) if total_atendimentos else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Atendimentos", f"{total_atendimentos:,}".replace(",", "."))
col2.metric(
    "Atendidos sozinha",
    f"{total_sozinha:,}".replace(",", "."),
    f"{pct_sozinha:.1f}% do total",
    delta_color="off",
)
col3.metric(
    "Transferidos",
    f"{total_transferidos:,}".replace(",", "."),
    f"{pct_transf:.1f}% do total",
    delta_color="off",
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

# === Volume por hora do dia e por dia da semana ===
col_h, col_d = st.columns(2)

por_hora = run_query(
    f"""
    SELECT EXTRACT(HOUR FROM created_at AT TIME ZONE 'America/Sao_Paulo')::int AS hora,
           COUNT(DISTINCT telefone) AS conversas
    FROM conversas_sofia
    WHERE (created_at AT TIME ZONE 'America/Sao_Paulo')::date
          BETWEEN '{data_inicio.isoformat()}' AND '{data_fim.isoformat()}'
    GROUP BY hora
    ORDER BY hora
    """
)
horas_completas = pd.DataFrame({"hora": list(range(24))})
por_hora = horas_completas.merge(por_hora, on="hora", how="left").fillna(0)
por_hora["conversas"] = por_hora["conversas"].astype(int)
por_hora["hora_label"] = por_hora["hora"].apply(lambda h: f"{int(h):02d}h")

with col_h:
    st.subheader("⏰ Conversas por hora do dia")
    fig_hora = px.bar(por_hora, x="hora_label", y="conversas", text="conversas")
    fig_hora.update_traces(marker_color="#1abc9c", textposition="outside")
    fig_hora.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="",
        yaxis_title="Conversas",
    )
    st.plotly_chart(fig_hora, use_container_width=True)

por_dow = run_query(
    f"""
    SELECT EXTRACT(DOW FROM created_at AT TIME ZONE 'America/Sao_Paulo')::int AS dow,
           COUNT(DISTINCT telefone) AS conversas
    FROM conversas_sofia
    WHERE (created_at AT TIME ZONE 'America/Sao_Paulo')::date
          BETWEEN '{data_inicio.isoformat()}' AND '{data_fim.isoformat()}'
    GROUP BY dow
    ORDER BY dow
    """
)
nomes_dow = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]
dow_completos = pd.DataFrame({"dow": list(range(7))})
por_dow = dow_completos.merge(por_dow, on="dow", how="left").fillna(0)
por_dow["conversas"] = por_dow["conversas"].astype(int)
por_dow["dia"] = por_dow["dow"].apply(lambda d: nomes_dow[int(d)])

with col_d:
    st.subheader("📅 Conversas por dia da semana")
    fig_dow = px.bar(por_dow, x="dia", y="conversas", text="conversas")
    fig_dow.update_traces(marker_color="#e67e22", textposition="outside")
    fig_dow.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="",
        yaxis_title="Conversas",
    )
    st.plotly_chart(fig_dow, use_container_width=True)

# === Top 5 produtos mais mostrados ===
st.subheader("🏆 Top 5 produtos mais mostrados pela Sofia")
top_produtos = run_query(
    f"""
    SELECT handle, COUNT(*) AS mencoes
    FROM sofia_produtos_mostrados
    WHERE dia BETWEEN '{data_inicio.isoformat()}' AND '{data_fim.isoformat()}'
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
