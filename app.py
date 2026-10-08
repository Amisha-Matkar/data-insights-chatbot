import html
from google.genai import errors
import pandas as pd
import streamlit as st
from engine import answer_question, data

st.set_page_config(page_title="Data Insights Chatbot", page_icon="🤖", layout="centered")

# ---------- Style for the user's message bubble ----------
st.markdown(
    """
    <style>
    .user-bubble {
        margin-left: auto;
        width: fit-content;
        max-width: 80%;
        background: #EEF0FF;
        color: #1F2937;
        padding: 0.6rem 1rem;
        border-radius: 18px 18px 4px 18px;
        margin-bottom: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

EXAMPLES = [
    "Total revenue by region",
    "Revenue by month",
    "Top 5 products by units sold",
    "Which customer segment has the highest average order value?",
]
BOT_AVATAR = "🤖"


def show_user(text):
    """Draw the user's message as a bubble on the right."""
    safe_text = html.escape(text)
    st.markdown(f'<div class="user-bubble">{safe_text}</div>', unsafe_allow_html=True)


def show_chart(result):
    """Draw a chart if the result is one label column + one number column."""
    if result is None or len(result) < 2 or len(result.columns) != 2:
        return

    label_col, value_col = result.columns

    if not pd.api.types.is_numeric_dtype(result[value_col]):
        return

    is_time = (
        pd.api.types.is_datetime64_any_dtype(result[label_col])
        or "month" in label_col.lower()
        or "date" in label_col.lower()
    )

    if is_time:
        st.line_chart(result, x=label_col, y=value_col)
    else:
        st.bar_chart(result, x=label_col, y=value_col)


def show_answer(msg):
    """Draw one bot answer on the left: explanation and chart first, data and SQL folded away."""
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        st.write(msg["text"])
        result = msg.get("result")
        if result is not None:
            show_chart(result)
            with st.expander("Show data", icon=":material/table_chart:"):
                column_settings = {}
                for col in result.columns:
                    if pd.api.types.is_numeric_dtype(result[col]):
                        column_settings[col] = st.column_config.NumberColumn(
                            col, alignment="left", format="localized"
                        )
                st.dataframe(result, hide_index=True, width="stretch", column_config=column_settings)
        if msg.get("sql"):
            with st.expander("Show SQL", icon=":material/code:"):
                st.code(msg["sql"], language="sql")


# ---------- Memory ----------
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------- Sidebar ----------
clicked = None
with st.sidebar:
    st.header("📁 About the data")
    st.write(f"**{len(data):,}** sales orders")
    st.write(f"{data['order_date'].min():%b %Y} – {data['order_date'].max():%b %Y}")
    st.caption("Columns: " + ", ".join(data.columns))

    st.header("💡 Try asking")
    for example in EXAMPLES:
        if st.button(example, width="stretch"):
            clicked = example

    st.divider()
    if st.button("🗑️ Clear chat", width="stretch"):
        st.session_state.messages = []

# ---------- Main page ----------
st.title("🤖 Data Insights Chatbot")
st.caption("Ask about the sales data in plain English. I write the SQL, run it and explain the result.")

question = st.chat_input("Ask a question about your data...") or clicked

if not st.session_state.messages and not question:
    st.info("Pick an example question from the sidebar, or type your own below.")

# Redraw saved messages
for msg in st.session_state.messages:
    if msg["role"] == "user":
        show_user(msg["text"])
    else:
        show_answer(msg)

# Handle a new question
if question:
    history = ""
    for msg in st.session_state.messages[-6:]:
        if msg["role"] == "user":
            history += f"User asked: {msg['text']}\n"
        else:
            history += f"SQL used: {msg.get('sql')}\n"

    show_user(question)
    st.session_state.messages.append({"role": "user", "text": question})

    with st.spinner("Writing SQL and analysing..."):
        try:
            sql, result, explanation = answer_question(question, history)
        except errors.ServerError as e:
            print("Gemini server error:", e)
            sql, result = "", None
            explanation = "⚠️ The AI service is busy right now. Please try again in a minute."
        except errors.ClientError as e:
            print("Gemini client error:", e)
            sql, result = "", None
            if e.code == 429:
                explanation = "⚠️ The app has reached its usage limit for now. Please try again later."
            else:
                explanation = "⚠️ Something went wrong with the request. Please try again."
    answer = {"role": "assistant", "text": explanation, "sql": sql, "result": result}
    show_answer(answer)

    st.session_state.messages.append(answer)