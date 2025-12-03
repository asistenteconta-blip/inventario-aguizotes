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

# =========================================================
# NORMALIZACIÓN
# =========================================================

def normalize(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode()
    return s.strip().upper()

# =========================================================
# NORMALIZAR COLUMNAS
# =========================================================

def normalizar_columnas(df):
    if df is None:
        return df
    df = df.copy()
    mapping = {}

    for col in df.columns:
        key = normalize(col)

        if key.startswith("PRODUCTO"):
            mapping[col] = "PRODUCTO"
        elif key == "UNIDAD RECETA":
            mapping[col] = "UNIDAD"
        elif key in ("CANTIDAD DE UNIDAD DE MEDIDA", "CANTIDAD DE UNIDAD"):
            mapping[col] = "MEDIDA"
        elif key in ("CERRADO", "CANTIDAD CERRADO"):
            mapping[col] = "CERRADO"
        elif "ABIERTO" in key:
            mapping[col] = "ABIERTO(PESO)"
        elif "BOTELLAS" in key:
            mapping[col] = "BOTELLAS_ABIERTAS"

    return df.rename(columns=mapping)

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

    if a == "COCINA":
        return hojas[normalize(INV_CO)]
    if a in ["SUMINISTROS", "CONSUMIBLE"]:
        return hojas[normalize(INV_SU)]
    if a == "BARRA":
        return hojas[normalize(INV_BA)]

    st.error("Área inválida")
    st.stop()

@st.cache_data(show_spinner=False)
def load_area_products(area):
    ws = get_sheet(area)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")

    headers = raw[HEADER_ROW - 1]
    data = raw[DATA_START - 1:]

    df = pd.DataFrame(data, columns=headers)
    df.columns = [normalize(c) for c in df.columns]

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

col_producto = None
for c in df_fil.columns:
    if normalize(c).startswith("PRODUCTO"):
        col_producto = c
        break

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
# TABLA EDITABLE (Entrada)
# =========================================================

# Datos invisibles para cálculos
precio_neto = pd.to_numeric(
    df_sel["PRECIO NETO"].astype(str).str.replace(",", ".", regex=False).str.strip(),
    errors="coerce"
).fillna(0)

costo_unidad = pd.to_numeric(
    df_sel["COSTO X UNIDAD"].astype(str).str.replace(",", ".", regex=False).str.strip(),
    errors="coerce"
).fillna(0)

# Construir tabla visible
tabla_visible = {
    "PRODUCTO": df_sel["PRODUCTO GENÉRICO"].tolist(),
    "UNIDAD": df_sel["UNIDAD RECETA"].tolist(),
    "MEDIDA": df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].tolist(),
    "CERRADO": [0.0] * len(df_sel),
    "ABIERTO(PESO)": [0.0] * len(df_sel),
}

# SOLO mostrar BOTELLAS ABIERAS en área BARRA
if area == "BARRA":
    tabla_visible["BOTELLAS_ABIERTAS"] = [0.0] * len(df_sel)

df_visible = pd.DataFrame(tabla_visible)

# Editor de entrada
df_edit = st.data_editor(
    df_visible,
    disabled=["PRODUCTO", "UNIDAD", "MEDIDA"],
    use_container_width=True,
    hide_index=True,
    column_config={
        "CERRADO": st.column_config.NumberColumn("CERRADO", format="%.4f"),
        "ABIERTO(PESO)": st.column_config.NumberColumn("ABIERTO (PESO)", format="%.4f"),
        "BOTELLAS_ABIERTAS": st.column_config.NumberColumn("BOTELLAS ABIERTAS", format="%.0f") if area == "BARRA" else None,
    }
)

# =========================================================
# AGREGAR CAMPOS INVISIBLES PARA CALCULOS
# =========================================================

df_edit["_PRECIO_NETO"] = precio_neto.values
df_edit["_COSTO_X_UNIDAD"] = costo_unidad.values

# =========================================================
# CALCULO VALOR DE INVENTARIO
# =========================================================

df_edit["VALOR INVENTARIO"] = (
    df_edit["CERRADO"].astype(float) * df_edit["_PRECIO_NETO"]
    + df_edit["ABIERTO(PESO)"].astype(float) * df_edit["_COSTO_X_UNIDAD"]
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

entrada = normalizar_columnas(df_edit[mask].copy())

if not entrada.empty:
    prev = normalizar_columnas(st.session_state["preview_por_area"][area])
    prev = prev[~prev["PRODUCTO"].isin(entrada["PRODUCTO"])]
    prev = pd.concat([prev, entrada], ignore_index=True)
    st.session_state["preview_por_area"][area] = prev

st.subheader("Vista previa")
prev = st.session_state["preview_por_area"][area].copy()

if not prev.empty:

    # ======= Agregar precios desde Google Sheets =======
    df_prec = df_area.copy()

    # Normalizar columnas
    df_prec.columns = [normalize(c) for c in df_prec.columns]

    col_prod_norm = normalize(col_producto)

    tiene_precio = "PRECIO NETO" in df_prec.columns
    tiene_costo = "COSTO X UNIDAD" in df_prec.columns
    tiene_producto = col_prod_norm in df_prec.columns

    if tiene_precio and tiene_costo and tiene_producto:

        df_prec_f = df_prec[
            [col_prod_norm, "PRECIO NETO", "COSTO X UNIDAD"]
        ].rename(columns={col_prod_norm: "PRODUCTO"})

        prev = prev.merge(df_prec_f, on="PRODUCTO", how="left")

        prev["VALOR INVENTARIO (PREVIO)"] = (
            prev["PRECIO NETO"].fillna(0) * prev["CERRADO"].fillna(0)
            + prev["COSTO X UNIDAD"].fillna(0) * prev["ABIERTO(PESO)"].fillna(0)
        ).round(2)

        # 🔥 Ocultar columnas sensibles y columnas que no deben verse
        prev = prev.drop(
            columns=["PRECIO NETO", "COSTO X UNIDAD", "UNIDAD", "MEDIDA"],
            errors="ignore"
        )

    else:
        st.warning("⚠ No se encontraron columnas de precio para esta área.")

    # Mostrar vista previa
    st.dataframe(prev, use_container_width=True)

    st.session_state["preview_por_area"][area] = prev

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

    col_prod = None
    for k in headers.keys():
        if normalize(k).startswith("PRODUCTO"):
            col_prod = headers[k]
            break

    rows = get_rows(ws, col_prod)
    updates = []

    for _, r in prev.iterrows():
        prod = normalize(r["PRODUCTO"])
        row = rows.get(prod)
        if not row:
            continue

        campos = {
            "CERRADO": "CANTIDAD CERRADO",
            "ABIERTO(PESO)": "CANTIDAD ABIERTO (PESO)",
            "BOTELLAS_ABIERTAS": "CANTIDAD BOTELLAS ABIERTAS",
        }

        for campo, nombre_real in campos.items():
            if campo == "BOTELLAS_ABIERTAS" and area != "BARRA":
                continue

            col = None
            for h, idx in headers.items():
                if normalize(h) == normalize(nombre_real):
                    col = idx
                    break

            if col:
                updates.append({
                    "range": f"{colletter(col)}{row}",
                    "values": [[safe_value(r.get(campo, 0))]],
                })

        for h, ci in headers.items():
            if normalize(h) == "FECHA":
                updates.append({
                    "range": f"{colletter(ci)}{row}",
                    "values": [[fecha_str]],
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
        if normalize(k).startswith("PRODUCTO"):
            col_prod = v
            break

    rows = get_rows(ws, col_prod)
    updates = []

    # Reset valores de inventario
    for row in rows.values():
        for campo in ["CANTIDAD CERRADO", "CANTIDAD ABIERTO (PESO)", "CANTIDAD BOTELLAS ABIERTAS"]:
            target = normalize(campo)
            for h, ci in headers.items():
                if normalize(h) == target:
                    updates.append({"range": f"{colletter(ci)}{row}", "values": [[0]]})

        # Reset FECHA
        for h, ci in headers.items():
            if normalize(h) == "FECHA":
                updates.append({"range": f"{colletter(ci)}{row}", "values": [[""]]})

    # Reset comentario (celda C3)
    updates.append({"range": "C3", "values": [[""]]})

    ws.batch_update(updates)

    # Reset vista previa
    st.session_state["preview_por_area"][area] = pd.DataFrame(
        columns=["PRODUCTO", "CERRADO", "ABIERTO(PESO)", "BOTELLAS_ABIERTAS"]
    )

    # 🔥 RESET del comentario en sesión también
    st.session_state["comentarios_por_area"][area] = ""

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
# COMENTARIO POR ÁREA
# =========================================================

if "comentarios_por_area" not in st.session_state:
    st.session_state["comentarios_por_area"] = {
        "COCINA": "",
        "SUMINISTROS": "",
        "BARRA": "",
    }

st.subheader(f"Comentario — {area}")

comentario_actual = st.text_area(
    "Comentario general",
    value=st.session_state["comentarios_por_area"][area],
    key=f"comentario_{area}"
)

if st.button("💬 Guardar comentario"):
    st.session_state["comentarios_por_area"][area] = comentario_actual
    ws = get_sheet(area)
    ws.update("C3", [[comentario_actual]])
    st.success(f"Comentario de {area} guardado ✔")








