import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials
import unicodedata

# ================================
# CONFIG
# ================================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = "1RD7Y0kvyeyQzmNY0HELzp7MuWkJFjFsZOw66TQkJL3w"

service_info = st.secrets["google_service_account"]

credentials = Credentials.from_service_account_info(
    service_info,
    scopes=scope
)

client = gspread.authorize(credentials)

@st.cache_resource(show_spinner=False)
def get_doc():
    return client.open_by_key(SPREADSHEET_ID)

doc = get_doc()

INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

# ================================
# HELPERS
# ================================

def normalizar(texto):
    if not texto:
        return ""
    texto = texto.strip().upper()
    texto = unicodedata.normalize("NFKD", texto).encode("ASCII","ignore").decode()
    texto = " ".join(texto.split())
    return texto

def get_header_map(ws):
    header_row = ws.row_values(3)
    return {normalizar(name): idx for idx, name in enumerate(header_row, start=1)}

def get_dest_sheet(area):
    hojas = {ws.title.upper(): ws for ws in doc.worksheets()}
    mapa = {
        "COCINA": INV_CO.upper(),
        "CONSUMIBLE": INV_SU.upper(),
        "BARRA": INV_BA.upper()
    }
    target = mapa.get(area.upper())
    if target in hojas:
        return hojas[target]
    st.error("❌ No se encontró hoja del área")
    st.stop()

def col_letter(n):
    s = ""
    while n > 0:
        n, r = divmod(n-1, 26)
        s = chr(r+65) + s
    return s

# ================================
# UI
# ================================

st.title("📦 Sistema de Inventario Diario – Restaurante")

fecha_inv = st.date_input("Fecha inventario:", value=date.today())
fecha_str = fecha_inv.strftime("%d-%m-%Y")

area = st.selectbox("Área:", ["COCINA","BARRA","CONSUMIBLE"])

# obtener hoja y columnas
ws_dest = get_dest_sheet(area)
header_map = get_header_map(ws_dest)

# detectar columnas
col_prod    = next((v for k,v in header_map.items() if "PRODUCTO" in k),None)
col_cerrado = next((v for k,v in header_map.items() if "CERRADO" in k),None)
col_abierto = next((v for k,v in header_map.items() if "ABIERTO" in k),None)
col_fecha   = next((v for k,v in header_map.items() if "FECHA" in k),None)

if not col_prod:
    st.error("❌ No se encontró columna PRODUCTO")
    st.stop()

productos_col = ws_dest.col_values(col_prod)[3:]
productos = [p for p in productos_col if p.strip()!=""]

prod = st.selectbox("Producto:", ["TODOS"] + productos)

if prod == "TODOS":
    productos_sel = productos
else:
    productos_sel = [prod]

tabla = pd.DataFrame({
    "PRODUCTO": productos_sel,
    "CANTIDAD CERRADO": [0.0]*len(productos_sel),
    "CANTIDAD ABIERTO": [0.0]*len(productos_sel)
})

tabla_editada = st.data_editor(
    tabla,
    num_rows="fixed",
    use_container_width=True
)

# ================================
# GUARDAR
# ================================

def guardar():
    updates = []
    for _, row in tabla_editada.iterrows():
        nombre = row["PRODUCTO"].strip().upper()

        # buscar fila
        productos_sheet = ws_dest.col_values(col_prod)
        for idx in range(3,len(productos_sheet)):
            if str(productos_sheet[idx]).strip().upper()==nombre:
                fila = idx+1
                break
        else:
            continue

        if col_cerrado:
            updates.append({
                "range": f"{ws_dest.title}!{col_letter(col_cerrado)}{fila}",
                "values": [[row["CANTIDAD CERRADO"]]]
            })
        if col_abierto:
            updates.append({
                "range": f"{ws_dest.title}!{col_letter(col_abierto)}{fila}",
                "values": [[row["CANTIDAD ABIERTO"]]]
            })
        if col_fecha:
            updates.append({
                "range": f"{ws_dest.title}!{col_letter(col_fecha)}{fila}",
                "values": [[fecha_str]]
            })

    if updates:
        doc.batch_update({
            "value_input_option": "USER_ENTERED",
            "data": updates
        })
        return len(updates)
    return 0

# ================================
# RESET
# ================================

def reset():
    updates=[]
    productos_sheet = ws_dest.col_values(col_prod)
    for idx in range(3,len(productos_sheet)):
        fila = idx+1
        if col_cerrado:
            updates.append({"range":f"{ws_dest.title}!{col_letter(col_cerrado)}{fila}","values":[[0]]})
        if col_abierto:
            updates.append({"range":f"{ws_dest.title}!{col_letter(col_abierto)}{fila}","values":[[0]]})
        if col_fecha:
            updates.append({"range":f"{ws_dest.title}!{col_letter(col_fecha)}{fila}","values":[[""]]})

    if updates:
        doc.batch_update({
            "value_input_option":"USER_ENTERED",
            "data":updates
        })

# ================================
# BOTONES
# ================================

col1,col2 = st.columns(2)

with col1:
    if st.button("💾 Guardar inventario"):
        guardar()
        st.success("✅ Guardado")

with col2:
    if st.button("🧹 Reset inventario"):
        reset()
        st.success("✅ Reset realizado")
