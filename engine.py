import duckdb
import pandas as pd
import re
from google import genai

client = genai.Client()
MODEL = "gemini-3.5-flash-lite"

data = pd.read_csv("sample_sales.csv")
con = duckdb.connect(config={"enable_external_access": False})
con.register("data",data)

schema = ""
for col in data.columns:
    schema += f"- {col} ({data[col].dtype})\n"
    
def ask_ai(prompt):
    """Send the prompt to AI and get response"""
    response = client.models.generate_content(model= MODEL, contents = prompt)
    return response.text
    
def write_sql(question,error_note="",history = ""):
    prompt = f"""You are a data analyst. Write the DuckDB SQL query for the question asked.
    The table is called data and has these columns:
    {schema}
    Rules:
    1. Return just the SQL query, nothing else.
    2. Only write SELECT queries.
    3. Return CANNOT_ANSWER only if the question needs information that is not in these columns, such as customer names or profit.
    4. If the question is broad or vague, answer it with a sensible summary query instead of refusing. Examples:
       - "What does the data look like?" -> SELECT * FROM data LIMIT 10
       - "How is the North region performing?" -> total revenue, total units and number of orders for North
    5. If the message is a greeting, small talk, or not a question about this data, return only the word NOT_A_QUESTION.

    Earlier in this conversation:
    {history}
    Use the earlier conversations only to understand follow up questions, like what about the lowest?
    
    Question : {question}
    {error_note}"""
    
    sql = ask_ai(prompt)
    return sql.replace("```sql","").replace("```","").strip()


def is_safe(sql):
    """Guardrail : Only allow read-only queries"""
    sql_upper = sql.upper().strip().rstrip(";")
    
    if not sql_upper:
        return False
    if sql_upper.split()[0].upper() not in ('WITH','SELECT'):
        return False
    if ";" in sql_upper:
        return False
    for word in ('DELETE','ALTER','CREATE','DROP','INSERT','UPDATE'):
        if re.search(rf"\b{word}\b",sql_upper):
            return False
    return True


def explain(question,result):
    
    """Ask AI to explain the result"""
    
    prompt = f"""The user asked: {question}
    This is the result of database query that answers it
    {result.to_string(index=False)}
    
    Answers the user's question in 2-3 sentences in plain Enlgish.
    Use only the numbers shown above. Don't make up any numbers or reasons.
    """
        
    return ask_ai(prompt)

#------------------- Main Program -----------------

def answer_question(question,history=""):
    """This is the full pipeline. Returns sql query, result and explaination. Result will be None
    when there is no table to show"""
    
    sql = write_sql(question,history=history)
    if "NOT_A_QUESTION" in sql:
            return "", None, "Hi! I answer questions about the sales data. Try asking 'Total revenue by region' or 'Revenue by month'."
    if "CANNOT_ANSWER" in sql:
        return sql, None, "This question cannot be answered using the data"
    if not is_safe(sql):
        return sql, None, f"""Blocked: the generated query was not read-only, so it was not run."""   
    try:
        result = con.sql(sql).df()
    except Exception as e1:
        print(f"Error is: \n",e1,"\n")
        error_input = f"""Your previous sql query {sql} cpuld not be run with error message {e1}. Write the corrected query."""
        sql = write_sql(question,error_input,history=history)
        if "CANNOT_ANSWER" in sql:
            return sql, None, "This question can't be answered from this data."
        if not is_safe(sql):
            return sql, None, "Blocked: the generated query was not read-only, so it was not run."   
        try:
            result = con.sql(sql).df()
        except Exception as e2:
            return sql, None, f"Sorry query failed for the second time with error : {e2}"
    return sql, result, explain(question, result)    
        
        
