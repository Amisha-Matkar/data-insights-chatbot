import duckdb
import pandas as pd
import re
from google import genai

client = genai.Client()
MODEL = "gemini-3.5-flash-lite"


def clean_column_name(name):
    name = name.strip()
    name = re.sub(r"\W+","_",name)
    name = name.strip("_")
    name = name.lower()
    
    if name == "":
        return "column"
    else:
        return name
    
def load_data(file):
    new_columns = []
    
    data = pd.read_csv(file)
    for col in data.columns:
        cleaned_name = clean_column_name(col)
        while cleaned_name in new_columns:
            cleaned_name = cleaned_name + "_2" 
        new_columns.append(cleaned_name)
    data.columns = new_columns
    
    for col in data.columns:
        if pd.api.types.is_string_dtype(data[col]):
            as_numbers = pd.to_numeric(data[col].str.replace(",",""), errors="coerce")
            if as_numbers.notna().mean() > 0.9:
                lost = data[col].notna() & as_numbers.isna()
                if lost.any():
                    data[col + "_text"] = data[col].where(lost)
                data[col] = as_numbers    
    
    for col in data.columns:
        if pd.api.types.is_string_dtype(data[col]):
            converted = pd.to_datetime(data[col], errors="coerce", format="mixed")
            if converted.notna().mean() > 0.9:
                data[col] = converted
    return data
        
            
    
    
    
def make_schema(df):
    schema = ""
    for col in df.columns:
        unique_values = df[col].dropna().unique()

        # Decide: all the values, or just 3?
        if len(unique_values) <= 10:
            values = unique_values
            label = "all values"
        else:
            values = unique_values[:3]
            label = "e.g."

        # Same steps either way
        examples = []
        for v in values:
            examples.append(str(v)[:30])
        examples_text = ", ".join(examples)
        schema += f"- {col} ({df[col].dtype}), {label}: {examples_text}\n"

    return schema
    
def ask_ai(prompt):
    """Send the prompt to AI and get response"""
    response = client.models.generate_content(model= MODEL, contents = prompt)
    return response.text
    
def write_sql(question,schema,error_note="",history = ""):
    prompt = f"""You are a data analyst. Write the DuckDB SQL query for the question asked.
    The table is called data and has these columns:
    {schema}
    Rules:
    1. Return just the SQL query, nothing else.
    2. Only write SELECT queries.
    3. Return CANNOT_ANSWER only if the question needs information that is not in these columns.
    4. If the question is broad or vague, answer it with a sensible summary query instead of refusing. Examples:
       - "What does the data look like?" -> SELECT * FROM data LIMIT 10
       - "Give me an overview" → the number of rows plus totals or averages of the main number columns.
    5. If the message is a greeting, small talk, or not a question about this data, return only the word NOT_A_QUESTION.
    6. When a column lists "all values", use those exact values in WHERE filters.
    7. Do not substitute a similar-sounding column. For example, a question about individual people or items
       cannot be answered with a column that only groups them into categories or segments. 
       In that case, return CANNOT_ANSWER.
    8. When ranking, filtering or comparing, include the column you used in the SELECT, so the result shows the evidence.

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


def explain(question, sql, result):
    
    """Ask AI to explain the result"""
    
    prompt = f"""The user asked: {question}
    
    This SQL query was used to answer it : {sql}
    This is the result of database query that answers it
    {result.to_string(index=False)}
    
    Answers the user's question in 2-3 sentences in plain English.
    Use only the numbers shown above. Don't make up any numbers or reasons.
    In one short sentence, say what measure was used to decide the answer (for example, 'fastest = lowest 0–60 time').
    Do not show the SQL itself.
    """
        
    return ask_ai(prompt)

#------------------- Main Program -----------------

def answer_question(question,df,history=""):
    """This is the full pipeline. Returns sql query, result and explaination. Result will be None
    when there is no table to show"""
    
    schema = make_schema(df)
    
    sql = write_sql(question,schema,history=history)
    
    con = duckdb.connect(config={"enable_external_access": False})
    con.register("data",df)
    
    if "NOT_A_QUESTION" in sql:
            return "", None, "Hi! I answer questions about the data. Try asking anything about the columns."
    if "CANNOT_ANSWER" in sql:
        return sql, None, "This question cannot be answered using the data"
    if not is_safe(sql):
        return sql, None, f"""Blocked: the generated query was not read-only, so it was not run."""   
    try:
        result = con.sql(sql).df()
    except Exception as e1:
        print(f"Error is: \n",e1,"\n")
        error_input = f"""Your previous sql query {sql} could not be run with error message {e1}. Write the corrected query."""
        sql = write_sql(question,schema,error_input,history=history)
        if "CANNOT_ANSWER" in sql:
            return sql, None, "This question can't be answered from this data."
        if not is_safe(sql):
            return sql, None, "Blocked: the generated query was not read-only, so it was not run."   
        try:
            result = con.sql(sql).df()
        except Exception as e2:
            return sql, None, f"Sorry query failed for the second time with error : {e2}"
    return sql, result, explain(question, sql, result)    
        
        
