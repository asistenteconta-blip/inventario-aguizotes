import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials

# =========================================================
#  CONFIGURACIÓN GOOGLE SHEETS — CORREGIDO
# =========================================================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DOC_NAME = "Copia de INV AGUI ESCALANTE  31-10-25 CIERRE"

service_info = st.secrets["google_service_account"]

credentials = Credentials.from_service_account_info(
    service_info,
    scopes=scope
)

client = gspread.authorize(credentials)

@st.cache_resource(show_spinner=False)
def get_doc():
    return client.open(DOC_NAME)

doc = get_doc()

BD_TAB = "BD_productos"
INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

# =========================================================
#  CARGAR BD
# =========================================================

@st.cache_data(show_spinner=False)
def get_bd_df_cached():
    ws = doc.worksheet("BD_productos")
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")

    if not raw or len(raw) < 2:
        st.error("❌ La hoja BD_productos está vacía.")
        st.stop()

    headers = [h.strip() for h in raw[0]]
    df = pd.DataFrame(raw[1:], columns=headers)

    df.columns = df.columns.str.strip().str.upper()

    numeric_cols = [
        "PRECIO NETO",
        "CANTIDAD DE UNIDAD DE MEDIDA",
        "COSTO X UNIDAD",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                .str.replace(" ", "")
                .str.replace(",", "")
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df

df = get_bd_df_cached()

def get_dest_sheet(area: str):
    hojas = {ws.title.upper(): ws for ws in doc.worksheets()}

    if area == "COCINA":
        target = INV_CO.upper()
    elif area == "CONSUMIBLE":
        target = INV_SU.upper()
    elif area == "BARRA":
        target = INV_BA.upper()
    else:
        return None

    if target in hojas:
        return hojas[target]

    st.error(f"❌ No se encontró la hoja '{target}'.")
    st.write(list(hojas.keys()))
    st.stop()

import unicodedata

def normalizar(texto):
    if not texto:
        return ""
    texto = texto.strip().upper()
    texto = unicodedata.normalize("NFKD", texto).encode("ASCII","ignore").decode()
    texto = texto.replace("  ", " ")
    return texto

def get_header_map(ws):
    header_row = ws.row_values(3)
    header_map = {}

    for idx, name in enumerate(header_row, start=1):
        norm = normalizar(name)
        if norm:
            header_map[norm] = idx

    return header_map


def get_product_row_map(ws, col_idx_producto: int):
    productos_col = ws.col_values(col_idx_producto)
    mapping = {}
    for row_idx in range(4, len(productos_col) + 1):
        nombre = str(productos_col[row_idx - 1]).strip().upper()
        if nombre:
            mapping[nombre] = row_idx
    return mapping

# =========================================================
#  UI
# =========================================================

st.title("📦 Sistema de Inventario Diario – Restaurante")

st.warning("""
⚠️ **Atención**
- Revise unidades antes de guardar
- RESET borra TODO el área seleccionada
""")

fecha_inv = st.date_input("Fecha de inventario:", value=date.today())
fecha_str = fecha_inv.strftime("%d-%m-%Y")

areas = sorted([a for a in df["ÁREA"].unique() if a.upper() != "GASTO"])
area = st.selectbox("Área:", areas)

df_area = df[df["ÁREA"] == area]

categorias = sorted(df_area["CATEGORIA"].unique())
categoria = st.selectbox("Categoría:", categorias)

df_cat = df_area[df_area["CATEGORIA"] == categoria]

subfams = sorted(df_cat["SUB FAMILIA"].unique())
subfam_options = ["TODOS"] + subfams
subfam = st.selectbox("Sub Familia:", subfam_options)

df_sf = df_cat[df_cat["SUB FAMILIA"] == subfam] if subfam != "TODOS" else df_cat

productos_lista = sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_options = ["TODOS"] + productos_lista
prod_filtro = st.selectbox("Producto:", prod_options)

df_sel = df_sf[df_sf["PRODUCTO GENÉRICO"] == prod_filtro] if prod_filtro != "TODOS" else df_sf

productos = df_sel["PRODUCTO GENÉRICO"].tolist()
n = len(productos)

tabla_base = pd.DataFrame({
    "PRODUCTO": productos,
    "UNIDAD RECETA": df_sel["UNIDAD RECETA"].values,
    "CANTIDAD DE UNIDAD DE MEDIDA": df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].values,
    "CANTIDAD CERRADO": [0.0] * n,
    "CANTIDAD ABIERTO (PESO)": [0.0] * n,
})

editable_cols = ["CANTIDAD CERRADO", "CANTIDAD ABIERTO (PESO)"]

tabla_editada = st.data_editor(
    tabla_base,
    use_container_width=True,
    num_rows="fixed",
    disabled=[c for c in tabla_base.columns if c not in editable_cols],
)

# =========================================================
#  DETECCIÓN AUTOMÁTICA DE COLUMNAS
# =========================================================

ws_dest = get_dest_sheet(area)
header_map = get_header_map(ws_dest)

# PRODUCTO
posibles_productos = [
    "PRODUCTO GENÉRICO",
    "PRODUCTO",
    "PRODUCTO ",
    "NOMBRE PRODUCTO",
]

prod_col_name = next((p for p in posibles_productos if p in header_map), None)

if not prod_col_name:
    st.error("❌ No se encontró columna de PRODUCTO")
    st.stop()

col_prod = header_map[prod_col_name]

# CERRADO
pos_cerrado = [
    "CANTIDAD CERRADO",
    "CERRADO",
    "CANTIDAD CERRADO A",
]

# ABIERTO
pos_abierto = [
    "CANTIDAD ABIERTO (PESO)",
    "CANTIDAD ABIERTO",
    "ABIERTO",
    "CANTIDAD ABIERTO A",
]

def buscar_col(nombre):
    for k,v in header_map.items():
        if nombre in k.replace("Á","A").upper():
            return v
    return None

col_cerrado = buscar_col(pos_cerrado)
col_abierto = buscar_col(pos_abierto)
col_valor = header_map.get("VALOR INVENTARIO")
col_fecha = header_map.get("FECHA")

prod_row_map = get_product_row_map(ws_dest, col_prod)

# =========================================================
#  GUARDAR
# =========================================================

def colnum_to_colletter(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(r + ord("A")) + s
    return s

def guardar_inventario():
    updates = []
    filas_actualizadas = 0

    for _, row in tabla_editada.iterrows():
        prod = str(row["PRODUCTO"]).strip().upper()
        cerrado = row["CANTIDAD CERRADO"]
        abierto = row["CANTIDAD ABIERTO (PESO)"]

        if prod not in prod_row_map:
            continue

        r = prod_row_map[prod]

        if col_cerrado:
            updates.append({
                "range": f"{ws_dest.title}!{colnum_to_colletter(col_cerrado)}{r}",
                "values": [[cerrado]]
            })

        if col_abierto:
            updates.append({
                "range": f"{ws_dest.title}!{colnum_to_colletter(col_abierto)}{r}",
                "values": [[abierto]]
            })

        updates.append({
            "range": f"{ws_dest.title}!{colnum_to_colletter(col_fecha)}{r}",
            "values": [[fecha_str]]
        })

        filas_actualizadas += 1

    if updates:
        doc.batch_update({
            "value_input_option": "USER_ENTERED",
            "data": updates
        })

    return filas_actualizadas


# =========================================================
#  RESET
# =========================================================

def reset_inventario():
    updates = []
    total_rows = len(ws_dest.col_values(col_prod))

    for r in range(4, total_rows + 1):
        if col_cerrado:
            updates.append({"range": f"{colnum_to_colletter(col_cerrado)}{r}", "values": [[0]]})
        if col_abierto:
            updates.append({"range": f"{colnum_to_colletter(col_abierto)}{r}", "values": [[0]]})
        if col_valor:
            updates.append({"range": f"{colnum_to_colletter(col_valor)}{r}", "values": [[0]]})

        updates.append({"range": f"{colnum_to_colletter(col_fecha)}{r}", "values": [[""]]})

    if updates:
    ws_dest.batch_update({
        "value_input_option": "USER_ENTERED",
        "data": updates
    })


    return total_rows - 3

# =========================================================
#  BOTONES
# =========================================================

col1, col2 = st.columns(2)

with col1:
    if st.button("💾 Guardar inventario"):
        n = guardar_inventario()
        st.success(f"✅ Guardado: {n} filas actualizadas")

with col2:
    if st.button("🧹 Resetear inventario"):
        n = reset_inventario()
        st.success(f"✅ Reset: {n} filas limpiadas")




