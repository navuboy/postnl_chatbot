import os
import streamlit as st
from dotenv import load_dotenv
import duckdb
import pandas as pd
import random
import time

from etl import extract, transform, persist_parcels_table
from agent import init_agent
from utils import (
    INDIVIDUAL_SUGGESTIONS_TEMPLATE,
    KPI_SUGGESTIONS_TEMPLATE,
    MULTI_INDIVIDUAL_QUESTIONS,
    MULTI_KPI_QUESTIONS,
    generate_metrics,
    generate_summary,
    generate_yoy_growth
)

st.set_page_config(page_title="🤖Posty", layout="wide")
load_dotenv()

partner_aliases = {
    "PaccoPronto (Italy)": "PaccoPronto",
    "BlitzPaket (Germany)": "BlitzPaket",
    "LivraPlus (France)": "LivraPlus",
    "Parcelly (United Kingdom)": "Parcelly"
}

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "selected_partners" not in st.session_state:
    st.session_state.selected_partners = []
if "last_query" not in st.session_state:
    st.session_state.last_query = None
if "last_df" not in st.session_state:
    st.session_state.last_df = None
if "last_label" not in st.session_state:
    st.session_state.last_label = None
if "suggested_quick_questions" not in st.session_state:
    st.session_state.suggested_quick_questions = []
if "suggested_kpi_questions" not in st.session_state:
    st.session_state.suggested_kpi_questions = []
if "last_question_refresh" not in st.session_state:
    st.session_state.last_question_refresh = 0

refresh_clicked = st.sidebar.button("🔄 Refresh Questions")

# Normalize partner names in user prompt
if 'pending_question' in st.session_state and st.session_state['pending_question']:
    for alias, real in partner_aliases.items():
        if alias in st.session_state['pending_question']:
            st.session_state['pending_question'] = st.session_state['pending_question'].replace(alias, real)

# Refresh questions every 2 minutes
if (
    refresh_clicked
    or time.time() - st.session_state.last_question_refresh > 300
    or not st.session_state.suggested_quick_questions
    or not st.session_state.suggested_kpi_questions
):
    selected_partners_for_prompt = st.session_state.selected_partners or ["partner"]
    first_partner = selected_partners_for_prompt[0] if selected_partners_for_prompt else "partner"

    quick_template = (
        MULTI_INDIVIDUAL_QUESTIONS
        if len(selected_partners_for_prompt) > 1
        else [q.format(partner=first_partner) for q in INDIVIDUAL_SUGGESTIONS_TEMPLATE]
    )
    kpi_template = (
        MULTI_KPI_QUESTIONS
        if len(selected_partners_for_prompt) > 1
        else [q.format(partner=first_partner) for q in KPI_SUGGESTIONS_TEMPLATE]
    )

    st.session_state.suggested_quick_questions = random.sample(quick_template, min(3, len(quick_template)))
    st.session_state.suggested_kpi_questions = random.sample(kpi_template, min(3, len(kpi_template)))
    st.session_state.last_question_refresh = time.time()


duckdb_path = os.getenv('DUCKDB_PATH', './data/parcels.duckdb')
csv_path = os.getenv('CSV_PATH', './data/parcel_per_network_partner.csv')
con = duckdb.connect(database=duckdb_path)

def ensure_parcels_table(con, csv_path):
    result = con.execute("SELECT * FROM duckdb_tables() WHERE table_name = 'parcels'").fetchall()
    if not result:
        raw = extract(csv_path)
        cleaned = transform(raw, raw['final_network_partner'].unique().tolist())
        persist_parcels_table(cleaned, duckdb_path, table_name='parcels')

ensure_parcels_table(con, csv_path)

partners = con.execute("SELECT DISTINCT final_network_partner FROM parcels").df()['final_network_partner'].tolist()

st.sidebar.title("Partner & Actions")

def on_partner_change():
    st.session_state.messages = []
    st.session_state.agent_partner = None
    st.session_state.agent = None
    st.session_state.suggested_quick_questions = []
    st.session_state.suggested_kpi_questions = []
    st.session_state.last_question_refresh = 0

selected = st.sidebar.multiselect(
    "Select Partner(s)",
    partners,
    default=partners[:1] if not st.session_state.selected_partners else st.session_state.selected_partners,
    key="selected_partners",
    on_change=on_partner_change
)

if len(st.session_state.selected_partners) == 0:
    st.header("Hi there!! I am Posty📦, your AI chatbot assistant🤖.")
    st.warning("Please select at least one partner to continue.")
    st.stop()

selected_partners = st.session_state.selected_partners
is_multi_mode = len(selected_partners) > 1

with st.sidebar.expander("Quick Questions", expanded=False):
    for i, q in enumerate(st.session_state.suggested_quick_questions):
        st.button(q, key=f"quick_{i}", on_click=lambda qi=q: st.session_state.__setitem__('pending_question', qi))

with st.sidebar.expander("KPI-focused Questions", expanded=False):
    for i, q in enumerate(st.session_state.suggested_kpi_questions):
        st.button(q, key=f"kpi_{i}", on_click=lambda qi=q: st.session_state.__setitem__('pending_question', qi))

st.sidebar.button("Clear Chat", key="clear_chat", on_click=lambda: st.session_state.update(messages=[]))

if not st.session_state.messages:
    st.session_state.messages.append({
        "role": "assistant",
        "content": (
            "Hi, I’m 📫**Posty**, your AI Chat representative from PostNL🤗 "
            "Ask me anything about parcel trends, Key Performance Indicators (KPIs), or summaries related to our delivery partners and I’ll try to repond to you.😊"
        )
    })

def handle_user_input(user_input, current_df, current_label):
    if st.session_state.last_df is not None and user_input.lower().strip() in ["generate summary", "create summary"]:
        user_input = st.session_state.last_query or user_input
        current_df = st.session_state.last_df
        current_label = st.session_state.last_label
    else:
        st.session_state.last_query = user_input
        st.session_state.last_df = current_df
        st.session_state.last_label = current_label

    start = current_df['date'].min()
    end = current_df['date'].max()

    if "summary" in user_input.lower():
        try:
            if is_multi_mode and 'partner' in current_df.columns:
                partner_metrics = {
                    partner: generate_metrics(current_df[current_df['partner'] == partner], start, end)
                    for partner in current_df['partner'].unique()
                }
            else:
                partner_metrics = {current_label: generate_metrics(current_df, start, end)}

            summary = generate_summary(partner_metrics)
            return "### 🧾 Summary\n" + "\n".join(summary)
        except Exception as e:
            return f"❌ Failed to generate summary: {e}"

    if "yoy" in user_input.lower() or "year over year" in user_input.lower():
        try:
            if is_multi_mode and 'partner' in current_df.columns:
                partner_yoys = []
                for partner in current_df['partner'].unique():
                    df_sub = current_df[current_df['partner'] == partner]
                    yoy_text = generate_yoy_growth(df_sub, str(start.date()), str(end.date()))
                    partner_yoys.append(f"**{partner}**\n{yoy_text}")
                return "### 📊 Year-over-Year Growth Per Partner\n" + "\n\n".join(partner_yoys)
            else:
                yoy_text = generate_yoy_growth(current_df, str(start.date()), str(end.date()))
                return f"### 📊 Year-over-Year Growth\n{yoy_text}"
        except Exception as e:
            return f"❌ Failed to calculate YoY growth: {e}"

    return st.session_state.agent.run(user_input)

if is_multi_mode:
    st.title("🤖 Multi-Partner Comparison & Chat Assitant ")
    st.text("For queries related to multiple partners")

    partner_dfs = {}
    combined_df = pd.DataFrame()
    for partner in selected_partners:
        df = con.execute("SELECT date, item, weight, final_network_partner AS partner FROM parcels WHERE final_network_partner = ?", [partner]).df()
        df['date'] = pd.to_datetime(df['date'])
        combined_df = pd.concat([combined_df, df], axis=0)
        partner_dfs[partner] = df

    if 'agent_partner' not in st.session_state or st.session_state.agent_partner != "MULTI":
        st.session_state.agent = init_agent(combined_df, selected_partners, multi_mode=True)
        st.session_state.agent.handle_parsing_errors = True
        st.session_state.agent_partner = "MULTI"

    st.subheader("Partner Dashboard View")
    selected_partner_ui = st.selectbox("Choose a partner to view details:", selected_partners)
    df = partner_dfs[selected_partner_ui]

    total = int(df['item'].sum())
    avg_day = round(df.groupby('date')['item'].sum().mean(), 1)
    active_days = df['date'].nunique()
    start_period = df['date'].min().date()
    end_period = df['date'].max().date()

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Parcels", total)
    c2.metric("Avg Parcels/Day", avg_day)
    c3.metric(f"Active Days ({start_period}--{end_period})", active_days)

    with st.expander("Daily Trends: Items & Weight", expanded=False):
        daily = df.groupby('date').agg(total_items=('item', 'sum'), total_weight=('weight', 'sum'))
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📦 Daily Parcel Count")
            st.line_chart(daily[['total_items']], use_container_width=True)
        with col2:
            st.subheader("⚖️ Daily Parcel Weight")
            st.line_chart(daily[['total_weight']], use_container_width=True)

    with st.expander("Monthly Active Days", expanded=False):
        ma = df.groupby(pd.Grouper(key='date', freq='M')).date.nunique().rename('active_days')
        st.bar_chart(ma, use_container_width=True)

    with st.expander("Partner Data Table", expanded=False):
        st.dataframe(df.sort_values('date'), height=300)

    for msg in st.session_state.messages:
        st.chat_message(msg['role']).markdown(msg['content'])

    chat_typed = st.chat_input("Ask a question comparing partners or request a report...")
    user_input = st.session_state.get('pending_question') or chat_typed
    st.session_state['pending_question'] = None

    if user_input:
        st.session_state.messages.append({'role': 'user', 'content': user_input})
        st.chat_message('user').markdown(user_input)

        with st.chat_message('assistant'):
            status = st.empty()
            status.write("Thinking…")
            answer = handle_user_input(user_input, combined_df, "MULTI")
            status.empty()
            st.markdown(answer, unsafe_allow_html=True)

            # Feedback block
            with st.container():
                cols = st.columns([1, 1, 2])
                if cols[0].button("👍 Good Response", key=f"good_{len(st.session_state.messages)}"):
                    st.success("Thanks for the feedback! ✅")

                if cols[1].button("👎 Bad Response", key=f"bad_{len(st.session_state.messages)}"):
                    st.session_state[f"show_feedback_{len(st.session_state.messages)}"] = True

                if st.button("📋 Copy Response", key=f"copy_{len(st.session_state.messages)}"):
                    st.code(answer, language='markdown')

        st.session_state.messages.append({'role': 'assistant', 'content': answer})

    st.stop()

sel = selected_partners[0]
df = con.execute("SELECT date, item, weight FROM parcels WHERE final_network_partner = ?", [sel]).df()
df['date'] = pd.to_datetime(df['date'])

if 'agent_partner' not in st.session_state or st.session_state.agent_partner != sel:
    st.session_state.agent = init_agent(df, [sel])
    st.session_state.agent.handle_parsing_errors = True
    st.session_state.agent_partner = sel

st.title(f"🤖Partner Dashboard for: {sel}")
st.text(f"For queries related to {sel}")
total = int(df['item'].sum())
avg_day = round(df.groupby('date')['item'].sum().mean(), 1)
active_days = df['date'].nunique()
start_period = df['date'].min().date()
end_period = df['date'].max().date()

c1, c2, c3 = st.columns(3)
c1.metric("Total Parcels", total)
c2.metric("Avg Parcels/Day", avg_day)
c3.metric(f"Active Days ({start_period}–{end_period})", active_days)

if not df.empty:
    with st.expander("Daily Trends: Items & Weight", expanded=False):
        daily = df.groupby('date').agg(total_items=('item', 'sum'), total_weight=('weight', 'sum'))
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📦 Daily Parcel Count")
            st.line_chart(daily[['total_items']], use_container_width=True)
        with col2:
            st.subheader("⚖️ Daily Parcel Weight")
            st.line_chart(daily[['total_weight']], use_container_width=True)

    with st.expander("Monthly Active Days", expanded=False):
        ma = df.groupby(pd.Grouper(key='date', freq='M')).date.nunique().rename('active_days')
        st.bar_chart(ma, use_container_width=True)

    with st.expander("Partner Data", expanded=False):
        st.dataframe(df.sort_values('date'), height=300)

for msg in st.session_state.messages:
    st.chat_message(msg['role']).markdown(msg['content'])

chat_typed = st.chat_input("Type your question or request a summary...")
user_input = st.session_state.get('pending_question') or chat_typed
st.session_state['pending_question'] = None

if user_input:
    st.session_state.messages.append({'role': 'user', 'content': user_input})
    st.chat_message('user').markdown(user_input)

    with st.chat_message('assistant'):
        status = st.empty()
        status.write("Thinking…")
        answer = handle_user_input(user_input, df, sel)
        status.empty()
        st.markdown(answer, unsafe_allow_html=True)

        # Feedback block
        with st.container():
            cols = st.columns([1, 1, 2])
            if cols[0].button("👍 Good Response", key=f"good_{len(st.session_state.messages)}"):
                st.success("Thanks for the feedback! ✅")

            if cols[1].button("👎 Bad Response", key=f"bad_{len(st.session_state.messages)}"):
                st.session_state[f"show_feedback_{len(st.session_state.messages)}"] = True

            if st.button("📋 Copy Response", key=f"copy_{len(st.session_state.messages)}"):
                st.code(answer, language='markdown')

    st.session_state.messages.append({'role': 'assistant', 'content': answer})
