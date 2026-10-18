# ============================================================
# SERVIDOR LOCAL — INPE + PURPLEAIR
# Monitoramento de focos de calor e qualidade do ar
#
# Requisitos: Python 3.9+
# Bibliotecas externas: nenhuma
#
# Endereço: http://127.0.0.1:8000
# ============================================================

import csv
import io
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo


HOST = "127.0.0.1"
PORT = 8000
FUSO = ZoneInfo("America/Sao_Paulo")

INPE_BASE = (
    "https://dataserver-coids.inpe.br/queimadas/"
    "queimadas/focos/csv/diario/Brasil/"
)

PURPLEAIR_BASE = "https://api.purpleair.com/v1/sensors"

# A chave é lida do ambiente, nunca do HTML.
PURPLEAIR_API_KEY = os.environ.get("PURPLEAIR_API_KEY", "").strip()

# Marcador fictício: substitua no terminal pela sua chave READ válida.
CHAVE_FICTICIA = "SUA_CHAVE_PURPLEAIR_AQUI"


def sem_acentos(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in texto if not unicodedata.combining(c))


def normalizar_nome(valor):
    valor = sem_acentos(valor).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", valor).strip("_")


def numero(valor):
    try:
        return float(str(valor).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


def data_local():
    return datetime.now(FUSO).date()


def data_iso_para_nome(data):
    return data.strftime("%Y%m%d")


def buscar_url(url, headers=None, timeout=60):
    requisicao = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MonitoramentoAmbientalBrasil/1.0",
            **(headers or {}),
        },
    )

    with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
        return resposta.read()


def interpretar_csv(conteudo):
    texto = conteudo.decode("utf-8-sig", errors="replace")

    if not texto.strip():
        return []

    amostra = texto[:12000]

    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=",;\t")
    except csv.Error:
        dialeto = csv.excel

    leitor = csv.DictReader(io.StringIO(texto), dialect=dialeto)
    registros = []

    for linha in leitor:
        registro = {
            normalizar_nome(chave): (valor or "").strip()
            for chave, valor in (linha or {}).items()
            if chave is not None
        }
        registros.append(registro)

    return registros


def obter_campo(registro, *nomes):
    for nome in nomes:
        chave = normalizar_nome(nome)
        valor = registro.get(chave)
        if valor not in (None, ""):
            return valor
    return ""


def datahora_inpe(valor):
    if not valor:
        return None

    texto = str(valor).strip().replace("/", "-")

    formatos = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    )

    try:
        instante = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=ZoneInfo("UTC"))
        return instante
    except ValueError:
        pass

    for formato in formatos:
        try:
            return datetime.strptime(texto, formato).replace(
                tzinfo=ZoneInfo("UTC")
            )
        except ValueError:
            continue

    return None


def normalizar_foco(registro):
    lat = numero(obter_campo(registro, "latitude", "lat"))
    lon = numero(obter_campo(registro, "longitude", "lon", "long"))

    if lat is None or lon is None:
        return None

    # Limites aproximados do Brasil continental.
    if not (-34.0 <= lat <= 5.5 and -74.0 <= lon <= -34.0):
        return None

    satelite = obter_campo(registro, "satelite", "satélite")
    sat_normalizado = normalizar_nome(satelite)

    # O arquivo diário pode conter diferentes satélites.
    # Este painel mantém o satélite de referência AQUA_M-T.
    if "aqua" not in sat_normalizado:
        return None

    horario = datahora_inpe(
        obter_campo(registro, "datahora", "data_hora", "data hora")
    )

    # Se a data/hora não estiver disponível, não descartamos o foco:
    # a localização e o arquivo diário continuam sendo informativos.
    timestamp = horario.timestamp() if horario else None

    return {
        "lat": lat,
        "lon": lon,
        "timestamp": timestamp,
        "satelite": satelite or "AQUA_M-T",
        "municipio": obter_campo(registro, "municipio"),
        "estado": obter_campo(registro, "estado", "uf"),
        "bioma": obter_campo(registro, "bioma"),
        "frp": obter_campo(registro, "frp"),
    }


def consultar_inpe(tipo_dia):
    hoje = data_local()

    if tipo_dia == "yesterday":
        dia = hoje - timedelta(days=1)
    elif tipo_dia == "today":
        dia = hoje
    else:
        raise ValueError("Parâmetro day inválido. Use today ou yesterday.")

    nome = f"focos_diario_br_{data_iso_para_nome(dia)}.csv"
    url = urllib.parse.urljoin(INPE_BASE, nome)

    conteudo = buscar_url(url, timeout=90)
    registros = interpretar_csv(conteudo)

    focos = []
    for registro in registros:
        foco = normalizar_foco(registro)
        if foco is not None:
            focos.append(foco)

    return {
        "date": dia.isoformat(),
        "date_label": dia.strftime("%d/%m/%Y"),
        "file": nome,
        "url": url,
        "rows_read": len(registros),
        "count": len(focos),
        "focos": focos,
    }


def consultar_purpleair():
    if not PURPLEAIR_API_KEY or PURPLEAIR_API_KEY == CHAVE_FICTICIA:
        raise RuntimeError(
            "A chave PurpleAir não foi configurada. "
            "Defina PURPLEAIR_API_KEY no terminal antes de iniciar o servidor."
        )

    campos = ",".join([
        "name",
        "latitude",
        "longitude",
        "pm2.5_24hour",
        "pm2.5_atm",
        "last_seen",
        "location_type",
    ])

    parametros = {
        "fields": campos,
        "location_type": "0",
        "max_age": "86400",
        "nwlat": "5.5",
        "nwlng": "-74",
        "selat": "-34",
        "selng": "-34",
    }

    url = PURPLEAIR_BASE + "?" + urllib.parse.urlencode(parametros)

    conteudo = buscar_url(
        url,
        headers={"X-API-Key": PURPLEAIR_API_KEY},
        timeout=60,
    )

    dados = json.loads(conteudo.decode("utf-8"))

    if "fields" not in dados or "data" not in dados:
        raise RuntimeError(
            dados.get("description", "Resposta inesperada da API PurpleAir.")
        )

    indices = {nome: i for i, nome in enumerate(dados["fields"])}

    def valor(linha, campo):
        indice = indices.get(campo)
        return linha[indice] if indice is not None else None

    sensores = []

    for linha in dados["data"]:
        lat = numero(valor(linha, "latitude"))
        lon = numero(valor(linha, "longitude"))
        ultima = numero(valor(linha, "last_seen"))

        if lat is None or lon is None or ultima is None:
            continue

        if not (-34.0 <= lat <= 5.5 and -74.0 <= lon <= -34.0):
            continue

        sensores.append({
            "name": valor(linha, "name") or "Sensor PurpleAir",
            "latitude": lat,
            "longitude": lon,
            "pm24": numero(valor(linha, "pm2.5_24hour")),
            "pmAtual": numero(valor(linha, "pm2.5_atm")),
            "last_seen": ultima,
            "location_type": valor(linha, "location_type"),
        })

    return {
        "count": len(sensores),
        "sensors": sensores,
        "retrieved_at": datetime.now(FUSO).isoformat(),
    }


class Servidor(BaseHTTPRequestHandler):
    def responder_json(self, codigo, objeto):
        corpo = json.dumps(objeto, ensure_ascii=False).encode("utf-8")

        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        caminho = urllib.parse.urlparse(self.path)
        rota = caminho.path
        parametros = urllib.parse.parse_qs(caminho.query)

        if rota in ("/", "/index.html"):
            try:
                with open("index.html", "rb") as arquivo:
                    corpo = arquivo.read()

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            except OSError:
                self.responder_json(500, {
                    "error": "Não encontrei index.html na pasta atual."
                })
            return

        if rota == "/api/inpe":
            dia = (parametros.get("day") or [""])[0].lower()

            try:
                resultado = consultar_inpe(dia)
                self.responder_json(200, resultado)
            except urllib.error.HTTPError as erro:
                self.responder_json(502, {
                    "error": f"INPE retornou HTTP {erro.code}.",
                    "detail": str(erro),
                })
            except Exception as erro:
                self.responder_json(502, {
                    "error": "Falha ao consultar ou interpretar o CSV do INPE.",
                    "detail": str(erro),
                })
            return

        if rota == "/api/purpleair":
            try:
                resultado = consultar_purpleair()
                self.responder_json(200, resultado)
            except urllib.error.HTTPError as erro:
                detalhe = erro.read().decode("utf-8", errors="replace")
                self.responder_json(502, {
                    "error": f"PurpleAir retornou HTTP {erro.code}.",
                    "detail": detalhe[:1200],
                })
            except Exception as erro:
                self.responder_json(502, {
                    "error": "Falha ao consultar PurpleAir.",
                    "detail": str(erro),
                })
            return

        self.responder_json(404, {"error": "Rota não encontrada."})

    def log_message(self, formato, *args):
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            + (formato % args)
        )


if __name__ == "__main__":
    print("=" * 64)
    print("MONITORAMENTO AMBIENTAL — INPE + PURPLEAIR")
    print("=" * 64)
    print(f"Endereço: http://{HOST}:{PORT}")
    print(f"Chave PurpleAir configurada: {'SIM' if PURPLEAIR_API_KEY else 'NÃO'}")
    print("Para encerrar, pressione Ctrl+C.")
    print("=" * 64)

    servidor = ThreadingHTTPServer((HOST, PORT), Servidor)

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        servidor.server_close()
