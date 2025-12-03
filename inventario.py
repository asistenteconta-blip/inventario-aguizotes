import streamlit as st
import pandas as pd
import gspread
import unicodedata
from datetime import date
from google.oauth2.service_account import Credentials

# =========================================================
# CONFIG GOOGLE SHEETS
# =========================================================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DOC_NAME = "AGUI ESCALANTE  DDMMAAAA - INVENTARIO MACHOTE 25"

service_info = st.secrets["google_service_account"]
credentials = Credentials.from_service_account_info(service_info, scopes=scope)
client = gspread.authorize(credentials)

@st.cache_resource(show_spinner=False)
def get_doc():
    return client.open(DOC_NAME)

doc = get_doc()

# =========================================================
# HOJAS
# =========================================================

INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

HEADER_ROW = 4
DATA_START = 5

if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"] = False

# =========================================================
# NORMALIZACIÓN (ignorar tildes, espacios, mayúsculas)
# =========================================================

def normalize(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode()
    return s.strip().upper()

# =========================================================
# FUNCIONES GLOBALES
# =========================================================

def colletter(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(r + 65) + s
    return s

def safe_value(v):
    try:
        if pd.isna(v) or v == "":
            return 0
        return float(v)
    except:
        return 0

def get_sheet(area):
    hojas = {normalize(ws.title): ws for ws in doc.worksheets()}
    a = normalize(area)

    if a == "COCINA": return hojas[normalize(INV_CO)]
    if a in ["SUMINISTROS", "CONSUMIBLE"]: return hojas[normalize(INV_SU)]
    if a == "BARRA": return hojas[normalize(INV_BA)]

    st.error("Área inválida")
    st.stop()

@st.cache_data(show_spinner=False)
def load_area_products(area):
    ws = get_sheet(area)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")

    headers = raw[HEADER_ROW - 1]
    data = raw[DATA_START - 1:]

    df = pd.DataFrame(data, columns=headers)

    # Normalizar columnas
    df.columns = [normalize(c) for c in df.columns]

    # Nombre real puede ser GENERICO (sin tilde) o GENÉRICO (con tilde)
    col_producto = None
    for c in df.columns:
        if normalize(c) in ["PRODUCTO GENERICO", "PRODUCTO GENERICO"]:
            col_producto = c
            break

    if not col_producto:
        st.error("No se encontró columna PRODUCTO GENERICO / GENÉRICO")
        st.stop()

    df = df[df[col_producto].notna()]
    df = df[df[col_producto].astype(str).str.strip() != ""]

    return df

def get_headers(ws):
    header_row = ws.row_values(HEADER_ROW)
    normalized = {normalize(h): i for i, h in enumerate(header_row, start=1) if h}
    return normalized

def get_rows(ws, col):
    vals = ws.col_values(col)
    return {
        normalize(v): i
        for i, v in enumerate(vals, start=1)
        if i >= DATA_START and str(v).strip() != ""
    }

# =========================================================
# UI
# =========================================================

st.title("📦 Inventario Diario — Aguizotes")

st.warning("""
- ⚠ Verifica antes de guardar.
- ⚠ Reset borra todos los datos del área actual.
- ⚠ Usa el botón de guardar comentario al terminar.
""")

fecha = st.date_input("Fecha:", date.today())
fecha_str = fecha.strftime("%d-%m-%Y")

areas = ["COCINA", "SUMINISTROS", "BARRA"]
area = st.selectbox("Área:", areas)

df_area = load_area_products(area)

# Filtros dinámicos
if "CATEGORIA" in df_area.columns:
    categorias = ["TODOS"] + sorted(df_area["CATEGORIA"].dropna().unique())
    categoria = st.selectbox("Categoría:", categorias)
    df_fil = df_area if categoria == "TODOS" else df_area[df_area["CATEGORIA"] == categoria]
else:
    df_fil = df_area

if "SUB FAMILIA" in df_fil.columns:
    subfams = ["TODOS"] + sorted(df_fil["SUB FAMILIA"].dropna().unique())
    subfam = st.selectbox("Subfamilia:", subfams)
    df_fil = df_fil if subfam == "TODOS" else df_fil[df_fil["SUB FAMILIA"] == subfam]

# Detectar columna PRODUCTO automáticamente
col_producto = None
for c in df_fil.columns:
    if normalize(c) in ["PRODUCTO GENERICO", "PRODUCTO GENERICO"]:
        col_producto = c

prods = ["TODOS"] + sorted(df_fil[col_producto].dropna().unique())
prod_sel = st.selectbox("Producto:", prods)

df_sel = df_fil if prod_sel == "TODOS" else df_fil[df_fil[col_producto] == prod_sel]

if df_sel.empty:
    st.info("No hay productos con los filtros.")
    st.stop()

# =========================================================
# TABLA
# =========================================================

tabla = {
    "PRODUCTO": df_sel[col_producto].tolist(),
    "UNIDAD": df_sel["UNIDAD RECETA"].tolist(),
    "MEDIDA": df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].tolist(),
    "CERRADO": [0] * len(df_sel),
    "ABIERTO(PESO)": [0] * len(df_sel),
}

tabla["BOTELLAS_ABIERTAS"] = [0] * len(df_sel) if area == "BARRA" else [""] * len(df_sel)

df_tabla = pd.DataFrame(tabla)

for c in ["CERRADO", "ABIERTO(PESO)", "BOTELLAS_ABIERTAS"]:
    if c in df_tabla.columns:
        df_tabla[c] = (
            df_tabla[c]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.strip()
        )
        df_tabla[c] = pd.to_numeric(df_tabla[c], errors="coerce").fillna(0)
        df_tabla[c] = df_tabla[c].astype(float)

df_edit = st.data_editor(
    df_tabla,
    disabled=["PRODUCTO", "UNIDAD", "MEDIDA"],
    use_container_width=True,
    column_config={
        "CERRADO": st.column_config.NumberColumn("CERRADO", format="%.10g"),
        "ABIERTO(PESO)": st.column_config.NumberColumn("ABIERTO (PESO)", format="%.10g"),
        "BOTELLAS_ABIERTAS": st.column_config.NumberColumn("BOTELLAS ABIERTAS", format="%.0f"),
    }
)

# =========================================================
# PREVIEW POR ÁREA
# =========================================================

if "preview_por_area" not in st.session_state:
    st.session_state["preview_por_area"] = {
        "COCINA": pd.DataFrame(columns=["PRODUCTO", "CERRADO", "ABIERTO(PESO)", "BOTELLAS_ABIERTAS"]),
        "SUMINISTROS": pd.DataFrame(columns=["PRODUCTO", "CERRADO", "ABIERTO(PESO)", "BOTELLAS_ABIERTAS"]),
        "BARRA": pd.DataFrame(columns=["PRODUCTO", "CERRADO", "ABIERTO(PESO)", "BOTELLAS_ABIERTAS"]),
    }

mask = (df_edit["CERRADO"] != 0) | (df_edit["ABIERTO(PESO)"] != 0)
if area == "BARRA":
    mask |= df_edit["BOTELLAS_ABIERTAS"] != 0

entrada = df_edit[mask].copy()

if not entrada.empty:
    prev = st.session_state["preview_por_area"][area]
    prev = prev[~prev["PRODUCTO"].isin(entrada["PRODUCTO"])]
    prev = pd.concat([prev, entrada], ignore_index=True)
    st.session_state["preview_por_area"][area] = prev

st.subheader("Vista previa")

prev = st.session_state["preview_por_area"][area]
if not prev.empty:
    st.dataframe(prev, use_container_width=True)
else:
    st.info("Sin registros aún.")

# =========================================================
# GUARDAR
# =========================================================

def guardar():
    prev = st.session_state["preview_por_area"][area]
    if prev.empty:
        st.warning("No hay datos para guardar.")
        return

    ws = get_sheet(area)
    headers = get_headers(ws)

    # detectar columna producto original
    col_prod = None
    for k in headers.keys():
        if normalize(k) in ["PRODUCTO GENERICO", "PRODUCTO GENERICO"]:
            col_prod = headers[k]
            break

    rows = get_rows(ws, col_prod)

    updates = []

    for _, r in prev.iterrows():
        prod = normalize(r["PRODUCTO"])
        row = rows.get(prod)
        if not row:
            continue

        m = {
            "CERRADO": "CANTIDAD CERRADO",
            "ABIERTO(PESO)": "CANTIDAD ABIERTO (PESO)",
            "BOTELLAS_ABIERTAS": "CANTIDAD BOTELLAS ABIERTAS",
        }

        for campo, nombre_real in m.items():
            normalized_target = normalize(nombre_real)
            col = None
            for h, idx in headers.items():
                if normalize(h) == normalized_target:
                    col = idx
                    break

            if col:
                updates.append({
                    "range": f"{colletter(col)}{row}",
                    "values": [[safe_value(r[campo])]]
                })

        # FECHA
        for h, ci in headers.items():
            if normalize(h) == "FECHA":
                updates.append({
                    "range": f"{colletter(ci)}{row}",
                    "values": [[fecha_str]]
                })

    ws.batch_update(updates)
    st.success("Inventario guardado ✔")

# =========================================================
# RESET
# =========================================================

def resetear():
    ws = get_sheet(area)
    headers = get_headers(ws)

    col_prod = None
    for k, v in headers.items():
        if normalize(k) in ["PRODUCTO GENERICO", "PRODUCTO GENERICO"]:
            col_prod = v
            break

    rows = get_rows(ws, col_prod)

    updates = []

    for row in rows.values():
        for campo in ["CANTIDAD CERRADO", "CANTIDAD ABIERTO (PESO)", "CANTIDAD BOTELLAS ABIERTAS"]:
            target = normalize(campo)
            for h, ci in headers.items():
                if normalize(h) == target:
                    updates.append({"range": f"{colletter(ci)}{row}", "values": [[0]]})

        for h, ci in headers.items():
            if normalize(h) == "FECHA":
                updates.append({"range": f"{colletter(ci)}{row}", "values": [[""]]})

    updates.append({"range": "C3", "values": [[""]]})
    ws.batch_update(updates)

    st.session_state["preview_por_area"][area] = pd.DataFrame(
        columns=["PRODUCTO", "CERRADO", "ABIERTO(PESO)", "BOTELLAS_ABIERTAS"]
    )

    st.success("Área reseteada ✔")

# =========================================================
# BOTONES
# =========================================================

c1, c2 = st.columns(2)

if c1.button("💾 Guardar"):
    guardar()

if c2.button("🧹 Resetear"):
    st.session_state["confirm_reset"] = True

if st.session_state.get("confirm_reset", False):
    st.error("⚠ Esto borrará TODO el inventario del área actual.")
    a, b = st.columns(2)

    if a.button("✔ Confirmar"):
        resetear()
        st.session_state["confirm_reset"] = False

    if b.button("✖ Cancelar"):
        st.session_state["confirm_reset"] = False

# =========================================================
# COMENTARIO
# =========================================================

st.subheader("Comentario")
coment = st.text_area("Comentario general", key="comentario")

if st.button("💬 Guardar comentario"):
    ws = get_sheet(area)
    ws.update("C3", [[st.session_state["comentario"]]])
    st.success("Comentario guardado ✔")
