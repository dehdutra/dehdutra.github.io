import geopandas as gpd
import os

# ============================================================
# CAMINHO DO SHAPEFILE
# ============================================================

shp = r"D:/dados_gerais_geo/BR_UF_2022/BR_UF_2022.shp"

# ============================================================
# LER SHAPEFILE
# ============================================================

gdf = gpd.read_file(shp)

print("Número de estados:", len(gdf))
print("CRS original:", gdf.crs)

# ============================================================
# CONVERTER PARA WGS84
# ============================================================

gdf = gdf.to_crs("EPSG:4326")

# ============================================================
# MANTER APENAS AS INFORMAÇÕES NECESSÁRIAS
# ============================================================

gdf = gdf[
    [
        "SIGLA_UF",
        "NM_UF",
        "geometry"
    ]
].copy()

# Renomear para facilitar o uso no JavaScript
gdf = gdf.rename(columns={
    "SIGLA_UF": "sigla",
    "NM_UF": "nome"
})

# ============================================================
# SIMPLIFICAR GEOMETRIA
# ============================================================

print("Simplificando geometrias...")

gdf["geometry"] = gdf.geometry.simplify(
    tolerance=0.01,
    preserve_topology=True
)

# ============================================================
# CAMINHO DE SAÍDA
# ============================================================

saida = r"D:/dados_gerais_geo/BR_UF_2022/estados_simplificado.geojson"

# ============================================================
# SALVAR GEOJSON
# ============================================================

gdf.to_file(
    saida,
    driver="GeoJSON"
)

# ============================================================
# VERIFICAR TAMANHO
# ============================================================

tamanho_mb = os.path.getsize(saida) / (1024 ** 2)

print()
print("==========================================")
print("GEOJSON CRIADO")
print("==========================================")
print(f"Arquivo: {saida}")
print(f"Estados: {len(gdf)}")
print(f"Tamanho: {tamanho_mb:.2f} MB")
print("==========================================")

# ============================================================
# VERIFICAR ATRIBUTOS
# ============================================================

print("\nAtributos:")
print(gdf[["sigla", "nome"]])
