#!/usr/bin/env python3
"""Recoge el resultado del análisis de SonarQube y lo deja en disco.

Consulta la instancia que levanta el flujo de trabajo, espera a que termine de
procesar el informe que subió el escáner y escribe dos archivos: uno con los
datos en bruto para quien quiera procesarlos, y un resumen legible.

Uso:
    python3 ci/recoger-resultados.py <url> <token> <projectKey> <directorio>
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

METRICAS = [
    "alert_status", "bugs", "vulnerabilities", "code_smells", "security_hotspots",
    "coverage", "duplicated_lines_density", "ncloc", "tests", "test_failures",
    "reliability_rating", "security_rating", "sqale_rating", "sqale_index",
]

NOMBRES = {
    "alert_status": "Puerta de calidad",
    "bugs": "Errores",
    "vulnerabilities": "Vulnerabilidades",
    "code_smells": "Olores de código",
    "security_hotspots": "Puntos de seguridad por revisar",
    "coverage": "Cobertura (%)",
    "duplicated_lines_density": "Duplicación (%)",
    "ncloc": "Líneas de código",
    "tests": "Pruebas ejecutadas",
    "test_failures": "Pruebas fallidas",
    "reliability_rating": "Confiabilidad",
    "security_rating": "Seguridad",
    "sqale_rating": "Mantenibilidad",
    "sqale_index": "Deuda técnica (minutos)",
}

LETRA = {"1.0": "A", "2.0": "B", "3.0": "C", "4.0": "D", "5.0": "E"}


def pedir(url: str, token: str, ruta: str) -> dict:
    cred = base64.b64encode(f"{token}:".encode()).decode()
    req = urllib.request.Request(f"{url}{ruta}", headers={"Authorization": f"Basic {cred}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def esperar_procesamiento(url: str, token: str, tarea: str | None) -> str:
    """El escáner sube el informe y el servidor lo procesa aparte; hay que esperarlo."""
    if not tarea:
        time.sleep(20)
        return "sin identificador de tarea"
    for _ in range(60):
        d = pedir(url, token, f"/api/ce/task?id={tarea}")
        estado = d.get("task", {}).get("status", "")
        if estado in ("SUCCESS", "FAILED", "CANCELED"):
            return estado
        time.sleep(5)
    return "TIMEOUT"


def id_de_tarea() -> str | None:
    ruta = ".scannerwork/report-task.txt"
    if not os.path.exists(ruta):
        return None
    for linea in open(ruta, encoding="utf-8"):
        if linea.startswith("ceTaskId="):
            return linea.strip().split("=", 1)[1]
    return None


def main() -> int:
    url, token, clave, destino = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    os.makedirs(destino, exist_ok=True)

    estado = esperar_procesamiento(url, token, id_de_tarea())
    print(f"procesamiento del informe: {estado}")

    datos: dict = {"projectKey": clave, "procesamiento": estado}
    try:
        m = pedir(url, token, f"/api/measures/component?component={clave}&metricKeys={','.join(METRICAS)}")
        datos["medidas"] = {x["metric"]: x.get("value") for x in m["component"]["measures"]}
    except urllib.error.HTTPError as e:
        datos["medidas"] = {}
        print(f"no se pudieron leer las medidas: HTTP {e.code}")

    try:
        datos["puerta"] = pedir(url, token, f"/api/qualitygates/project_status?projectKey={clave}")["projectStatus"]
    except urllib.error.HTTPError:
        datos["puerta"] = {}

    try:
        iss = pedir(url, token, f"/api/issues/search?componentKeys={clave}&ps=200&resolved=false")
        datos["incidencias"] = [
            {"severidad": i.get("severity"), "tipo": i.get("type"),
             "archivo": i.get("component", "").split(":")[-1], "linea": i.get("line"),
             "mensaje": i.get("message")}
            for i in iss.get("issues", [])
        ]
    except urllib.error.HTTPError:
        datos["incidencias"] = []

    with open(os.path.join(destino, "sonarqube.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)

    med = datos.get("medidas", {})
    filas = []
    for k in METRICAS:
        if k not in med:
            continue
        v = med[k]
        if k.endswith("_rating"):
            v = LETRA.get(v, v)
        filas.append(f"| {NOMBRES.get(k, k)} | {v} |")

    puerta = datos.get("puerta", {}).get("status", "desconocida")
    fallidas = [c for c in datos.get("puerta", {}).get("conditions", []) if c.get("status") == "ERROR"]

    lineas = [
        "# Análisis de calidad del código", "",
        f"Proyecto: `{clave}`  ·  Puerta de calidad: **{puerta}**", "",
        "| Medida | Valor |", "|---|---|", *filas, "",
    ]
    if fallidas:
        lineas += ["## Condiciones que no pasaron", ""]
        lineas += [f"- `{c['metricKey']}`: {c.get('actualValue')} frente al umbral "
                   f"{c.get('comparator','')} {c.get('errorThreshold')}" for c in fallidas]
        lineas.append("")

    inc = datos.get("incidencias", [])
    lineas += [f"## Incidencias abiertas: {len(inc)}", ""]
    for i in inc[:25]:
        lineas.append(f"- {i['severidad']} · {i['tipo']} · `{i['archivo']}`"
                      f"{':' + str(i['linea']) if i['linea'] else ''} — {i['mensaje']}")
    if len(inc) > 25:
        lineas.append(f"- y {len(inc) - 25} más, en `sonarqube.json`")

    resumen = "\n".join(lineas) + "\n"
    with open(os.path.join(destino, "resumen.md"), "w", encoding="utf-8") as f:
        f.write(resumen)

    print(resumen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
