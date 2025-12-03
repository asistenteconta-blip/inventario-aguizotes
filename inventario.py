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

DOC_NAME = "INVENTARIO AGUIZOTES CIERRE FORM"

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

# comentarios por area
if "comentarios_por_area" not in st.session_state:
    st.session_state["comentarios_por_area"] = {
        "COCINA": "",
        "SUMINISTROS": "",
        "BARRA": ""
    }

# =========================================================
# NORMALIZACIÓN
# =========================================================

def normalize(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode()
    return s.strip().upper()

# =========================================================
# NORMALIZAR COLUMNAS -> nombres canónicos internos
# =========================================================

def normalizar_columnas(df):
    """
    Convierte columnas comunes a nombres canónicos usados por la app:
    PRODUCTO, UNIDAD, MEDIDA, CERRADO, ABIERTO(PESO), BOTELLAS_ABIERTAS,
    PRECIO_NETO, COSTO_X_UNIDAD, VALOR_INVENTARIO (este último puede llenarse después).
    """
    if df is None:
        return df
    df = df.copy()
    mapping = {}
    for col in df.columns:
        key = normalize(col)
        # producto
        if key.startswith("PRODUCTO"):
            mapping[col] = "PRODUCTO"
        elif key == "UNIDAD RECETA":
            mapping[col] = "UNIDAD"
        elif key in ("CANTIDAD DE UNIDAD DE MEDIDA", "CANTIDAD DE UNIDAD"):
            mapping[col] = "MEDIDA"
        elif key in ("CANTIDAD CERRADO", "CERRADO"):
            mapping[col] = "CERRADO"
        elif "ABIERTO" in key:
            mapping[col] = "ABIERTO(PESO)"
        elif "BOTELLAS" in key:
            mapping[col] = "BOTELLAS_ABIERTAS"
        elif "PRECIO NETO" in key or key == "PRECIO":
            mapping[col] = "PRECIO_NETO"
        elif "COSTO X UNIDAD" in key or "COSTO POR UNIDAD" in key or "COSTO X" in key:
            mapping[col] = "COSTO_X_UNIDAD"
        elif "VALOR INVENTARIO" in key or "VALOR" == key:
            mapping[col] = "VALOR_INVENTARIO"
    if mapping:
        df = df.rename(columns=mapping)
    return df

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
    # protect in case sheet empty-ish
    if len(raw) < HEADER_ROW:
        st.error("Hoja incompleta o encabezados fuera de rango")
        st.stop()

    headers = raw[HEADER_ROW - 1]
    data = raw[DATA_START - 1:] if len(raw) >= DATA_START else []

    df = pd.DataFrame(data, columns=headers)
    # normalize column names (ASCII uppercase)
    df.columns = [normalize(c) for c in df.columns]

    # find producto column (PRODUCTO GENERICO or PRODUCTO GENÉRICO or PRODUCTO)
    col_producto = None
    for c in df.columns:
        if normalize(c).startswith("PRODUCTO"):
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
    return {normalize(h): i for i, h in enumerate(header_row, start=1) if h}

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

# FILTROS
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

# detect product column in df_fil (columns are normalized after load)
col_producto = next((c for c in df_fil.columns if normalize(c).startswith("PRODUCTO")), None)
if col_producto is None:
    st.error("No se encontró columna de producto.")
    st.stop()

prods = ["TODOS"] + sorted(df_fil[col_producto].dropna().unique())
prod_sel = st.selectbox("Producto:", prods)

df_sel = df_fil if prod_sel == "TODOS" else df_fil[df_fil[col_producto] == prod_sel]

if df_sel.empty:
    st.info("No hay productos con los filtros.")
    st.stop()

# =========================================================
# Construir df_tabla con columnas canónicas internas
# =========================================================

# normalizar columnas de df_sel para nombres canónicos
df_sel_canon = normalizar_columnas(df_sel)

n = len(df_sel_canon)
tabla = {
    "PRODUCTO": df_sel_canon.get("PRODUCTO", df_sel_canon[col_producto]).tolist() if "PRODUCTO" in df_sel_canon.columns else df_sel[col_producto].tolist(),
    "UNIDAD": df_sel_canon.get("UNIDAD", [""] * n).tolist(),
    "MEDIDA": df_sel_canon.get("MEDIDA", [""] * n).tolist(),
    "CERRADO": [0] * n,
    "ABIERTO(PESO)": [0] * n,
    "BOTELLAS_ABIERTAS": [0] * n if area == "BARRA" else [""] * n,
    "PRECIO_NETO": df_sel_canon.get("PRECIO_NETO", [0] * n).tolist(),
    "COSTO_X_UNIDAD": df_sel_canon.get("COSTO_X_UNIDAD", [0] * n).tolist(),
    "VALOR_INVENTARIO": [0] * n
}

df_tabla = pd.DataFrame(tabla)

# -------------------------
# LIMPIEZA Y NORMALIZACIÓN NUMÉRICA
# -------------------------
num_cols = ["CERRADO", "ABIERTO(PESO)", "BOTELLAS_ABIERTAS", "PRECIO_NETO", "COSTO_X_UNIDAD"]
for c in num_cols:
    if c in df_tabla.columns:
        df_tabla[c] = (
            df_tabla[c]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.strip()
        )
        df_tabla[c] = pd.to_numeric(df_tabla[c], errors="coerce").fillna(0)

# Forzar floats (keeps 0 instead of '0.0' when displayed as int-like depends on Streamlit)
for c in num_cols:
    if c in df_tabla.columns:
        df_tabla[c] = df_tabla[c].astype(float)

# =========================================================
# DATA EDITOR (permitir decimales, formatos)
# =========================================================
df_edit = st.data_editor(
    df_tabla,
    disabled=["PRODUCTO", "UNIDAD", "MEDIDA", "PRECIO_NETO", "COSTO_X_UNIDAD", "VALOR_INVENTARIO"],
    use_container_width=True,
    column_config={
        "CERRADO": st.column_config.NumberColumn("CERRADO", format="%.10g"),
        "ABIERTO(PESO)": st.column_config.NumberColumn("ABIERTO (PESO)", format="%.10g"),
        "BOTELLAS_ABIERTAS": st.column_config.NumberColumn("BOTELLAS ABIERTAS", format="%.0f"),
    }
)

# =========================================================
# CALCULAR VALOR INVENTARIO EN df_edit
# =========================================================
# asegurar columnas existen
for col in ["PRECIO_NETO", "COSTO_X_UNIDAD", "CERRADO", "ABIERTO(PESO)"]:
    if col not in df_edit.columns:
        df_edit[col] = 0

df_edit["VALOR_INVENTARIO"] = (
    df_edit["PRECIO_NETO"].astype(float) * df_edit["CERRADO"].astype(float)
) + (
    df_edit["COSTO_X_UNIDAD"].astype(float) * df_edit["ABIERTO(PESO)"].astype(float)
)

# =========================================================
# PREVIEW POR ÁREA
# =========================================================

if "preview_por_area" not in st.session_state:
    st.session_state["preview_por_area"] = {
        "COCINA": pd.DataFrame(),
        "SUMINISTROS": pd.DataFrame(),
        "BARRA": pd.DataFrame(),
    }

mask = (df_edit["CERRADO"] != 0) | (df_edit["ABIERTO(PESO)"] != 0) | (df_edit["VALOR_INVENTARIO"] != 0)
if area == "BARRA":
    mask |= (df_edit["BOTELLAS_ABIERTAS"] != 0)

entrada = df_edit[mask].copy()

if not entrada.empty:
    prev = st.session_state["preview_por_area"][area]
    # normalizar prev columns to canonical if exists
    if prev is None or prev.empty:
        prev = pd.DataFrame(columns=entrada.columns)
    else:
        prev = normalizar_columnas(prev)

    entrada = normalizar_columnas(entrada)

    # asegurar exista PRODUCTO en ambos
    if "PRODUCTO" in prev.columns and "PRODUCTO" in entrada.columns:
        prev = prev[~prev["PRODUCTO"].isin(entrada["PRODUCTO"])]
    # concatenar
    prev = pd.concat([prev, entrada], ignore_index=True, sort=False)

    # recalcular VALOR_INVENTARIO por si alguno cambió
    if "PRECIO_NETO" in prev.columns and "COSTO_X_UNIDAD" in prev.columns:
        prev["PRECIO_NETO"] = pd.to_numeric(prev["PRECIO_NETO"], errors="coerce").fillna(0).astype(float)
        prev["COSTO_X_UNIDAD"] = pd.to_numeric(prev["COSTO_X_UNIDAD"], errors="coerce").fillna(0).astype(float)
    prev["CERRADO"] = pd.to_numeric(prev.get("CERRADO", 0), errors="coerce").fillna(0).astype(float)
    prev["ABIERTO(PESO)"] = pd.to_numeric(prev.get("ABIERTO(PESO)", 0), errors="coerce").fillna(0).astype(float)
    prev["VALOR_INVENTARIO"] = (
        prev.get("PRECIO_NETO", 0).astype(float) * prev["CERRADO"].astype(float)
    ) + (
        prev.get("COSTO_X_UNIDAD", 0).astype(float) * prev["ABIERTO(PESO)"].astype(float)
    )

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
    if prev is None or prev.empty:
        st.warning("No hay datos para guardar.")
        return

    ws = get_sheet(area)
    headers = get_headers(ws)

    # detectar columna producto original (índice)
    col_prod_idx = None
    for h, idx in headers.items():
        if normalize(h).startswith("PRODUCTO"):
            col_prod_idx = idx
            break

    if col_prod_idx is None:
        st.error("No se encontró columna PRODUCTO en la hoja para escribir.")
        return

    rows = get_rows(ws, col_prod_idx)
    updates = []

    for _, r in prev.iterrows():
        prod_val = r.get("PRODUCTO", None)
        if prod_val is None:
            continue
        prod = normalize(str(prod_val))
        row = rows.get(prod)
        if not row:
            continue

        # Mapeo de campos a columna escrita
        mapping = {
            "CERRADO": "CANTIDAD CERRADO",
            "ABIERTO(PESO)": "CANTIDAD ABIERTO (PESO)",
            "BOTELLAS_ABIERTAS": "CANTIDAD BOTELLAS ABIERTAS",
        }

        for campo, colname in mapping.items():
            if campo == "BOTELLAS_ABIERTAS" and area != "BARRA":
                continue
            # buscar índice real en headers (comparando normalize)
            target_idx = None
            for h, idx in headers.items():
                if normalize(h) == normalize(colname):
                    target_idx = idx
                    break
            if target_idx:
                updates.append({
                    "range": f"{colletter(target_idx)}{row}",
                    "values": [[safe_value(r.get(campo, 0))]]
                })

        # Fecha
        for h, idx in headers.items():
            if normalize(h) == "FECHA":
                updates.append({
                    "range": f"{colletter(idx)}{row}",
                    "values": [[fecha_str]]
                })

    if updates:
        ws.batch_update(updates)
    st.success("Inventario guardado ✔")

# =========================================================
# RESET
# =========================================================

def resetear():
    ws = get_sheet(area)
    headers = get_headers(ws)

    # detectar columna producto original
    col_prod_idx = None
    for h, idx in headers.items():
        if normalize(h).startswith("PRODUCTO"):
            col_prod_idx = idx
            break

    rows = get_rows(ws, col_prod_idx)
    updates = []

    for row in rows.values():
        for colname in ["CANTIDAD CERRADO", "CANTIDAD ABIERTO (PESO)", "CANTIDAD BOTELLAS ABIERTAS"]:
            for h, idx in headers.items():
                if normalize(h) == normalize(colname):
                    updates.append({"range": f"{colletter(idx)}{row}", "values": [[0]]})
        for h, idx in headers.items():
            if normalize(h) == "FECHA":
                updates.append({"range": f"{colletter(idx)}{row}", "values": [[""]]})

    updates.append({"range": "C3", "values": [[""]]})
    if updates:
        ws.batch_update(updates)

    st.session_state["preview_por_area"][area] = pd.DataFrame()
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
# COMENTARIOS POR ÁREA
# =========================================================

st.subheader(f"Comentario — {area}")

comentario_actual = st.text_area(
    "Comentario general",
    value=st.session_state["comentarios_por_area"][area],
    key=f"comentario_{area}"
)

if st.button("💬 Guardar comentario"):
    st.session_state["comentarios_por_area"][area] = comentario_actual
    ws = get_sheet(area)
    # escribe en C3 de la hoja correspondiente
    ws.update("C3", [[comentario_actual]])
    st.success(f"Comentario de {area} guardado ✔")
