import streamlit as st
from engine import answer_question
import pandas as pd 

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

st.title("📊 Data Insights Chatbot")
st.caption("Ask a question about the sales data in plain English.")

# 1. Create the memory, only on the very first run
if "messages" not in st.session_state:
    st.session_state.messages = []

# 2. On every rerun, redraw all saved messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["text"])
        if msg.get("result") is not None:
            st.dataframe(msg["result"])
            show_chart(msg.get("result"))
        if msg.get("sql"):
            st.code(msg["sql"], language="sql")

# 3. Handle a new question
question = st.chat_input("Ask a question about your data...")

if question:
    history = ""
    for msg in st.session_state.messages[-6:]:
        if msg["role"] == "user":
            history += f"User asked: {msg['text']}\n"
        else:
            history += f"SQL used: {msg.get('sql')}\n"
    st.chat_message("user").write(question)
    st.session_state.messages.append({"role": "user", "text": question})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            sql, result, explanation = answer_question(question,history)
        st.write(explanation)
        if result is not None:
            st.dataframe(result)
            show_chart(result)
        if sql:
            st.code(sql, language="sql")

    st.session_state.messages.append(
        {"role": "assistant", "text": explanation, "sql": sql, "result": result}
    )