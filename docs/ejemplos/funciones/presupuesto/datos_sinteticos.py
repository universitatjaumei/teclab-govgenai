"""Datos sintéticos del presupuesto propio, para probar las dos funciones (AUT.10, issue #120).

**Nunca el CSV real**: lleva nombres y NIF de terceros. Esto genera un presupuesto con la misma
forma —las columnas del ERP, dos ejercicios, gastos e ingresos, afectados y no— y con los casos que
la anonimización tiene que resolver puestos a propósito:

* un nombre detrás de un código de convocatoria (`PID2023-…`, `CIDEGENT/…`);
* un nombre del PDI suelto en una descripción, sin código delante;
* **dos** personas en la misma descripción;
* un proyecto que lleva código y **no** nombre, y que tiene que quedar intacto;
* un tercero persona en los gastos y una entidad en los ingresos, cada uno con su NIF.

Lo usan los tests del servidor (modo local, pandas 2) y los del sandbox (pandas 3), y por eso está
aquí y sin dependencias: los dos proyectos lo cargan por ruta.

Todos los nombres y NIF son inventados.
"""
from __future__ import annotations

COLUMNAS = [
    "Presupuesto", "Pcr Apl Tipo", "Af", "Centre", "Descr Centre", "Sbc", "Descr Sbc",
    "Pcr Prg Id", "Cap", "Art", "Conc", "Pcr Importe SUM", "Proj", "Descr Proj", "Sbp",
    "Nombre Subproyecto", "Tercero Nombre", "Tercero Nif", "Tercero Per Id", "Observacion",
    "Comentario Centro", "Expediente Pluri Nombre",
]

#: Las personas que aparecen en el presupuesto. **Ninguna puede sobrevivir a la anonimización.**
PERSONAS = [
    "Marta Ferrer Soler",
    "Joan Puig Vidal",
    "Laura Gómez Ruiz",
    "Pere Martí Roca",
    "Nuria Castells Pla",
]

#: Lo que **no** es una persona y tiene que quedar como estaba.
NO_PERSONAS = [
    "SISTEMA DE GESTIÓN ENERGÉTICA INTELIGENTE",
    "Suministros Levante SL",
    "MINISTERIO DE CIENCIA E INNOVACIÓN",
]

NIF_PERSONA = "12345678Z"
NIF_EMPRESA = "B12345678"
NIF_ENTIDAD = "S2800000A"


def _fila(**campos) -> list[str]:
    return [str(campos.get(c, "")) for c in COLUMNAS]


def _filas() -> list[list[str]]:
    filas = []
    for ejercicio, factor in (("2025", 1.0), ("2026", 1.1)):
        def imp(x):
            return f"{x * factor:.2f}".replace(".", ",")

        filas += [
            # Gastos de personal con nombre tras un código de convocatoria.
            _fila(Presupuesto=ejercicio, **{"Pcr Apl Tipo": "P", "Af": "S", "Centre": "10",
                  "Descr Centre": "Vicerectorat d'Investigació", "Sbc": "101",
                  "Descr Sbc": "Projectes", "Pcr Prg Id": "541-A", "Cap": "1", "Art": "13",
                  "Conc": "131", "Pcr Importe SUM": imp(420000), "Proj": "P1",
                  "Descr Proj": "PID2023-145678OB-I00 Marta Ferrer Soler",
                  "Sbp": "S1", "Nombre Subproyecto": "CIDEGENT/2024/017 Joan Puig Vidal",
                  "Tercero Nombre": "Pere Martí Roca", "Tercero Nif": NIF_PERSONA,
                  "Tercero Per Id": "900", "Observacion": "Revisat amb Nuria Castells Pla"}),
            # Un nombre del PDI suelto, y dos personas en la misma descripción.
            _fila(Presupuesto=ejercicio, **{"Pcr Apl Tipo": "P", "Af": "N", "Centre": "10",
                  "Descr Centre": "Vicerectorat d'Investigació", "Sbc": "102",
                  "Descr Sbc": "Ajudes", "Pcr Prg Id": "541-A", "Cap": "2", "Art": "22",
                  "Conc": "226", "Pcr Importe SUM": imp(180000), "Proj": "P2",
                  "Descr Proj": "Ajudes de viatge Laura Gómez Ruiz",
                  "Sbp": "S2",
                  "Nombre Subproyecto": "PID2022-1234 Marta Ferrer Soler i Laura Gómez Ruiz",
                  "Tercero Nombre": "Suministros Levante SL", "Tercero Nif": NIF_EMPRESA,
                  "Tercero Per Id": "901"}),
            # Un proyecto con código y sin nombre: no se toca.
            _fila(Presupuesto=ejercicio, **{"Pcr Apl Tipo": "P", "Af": "N", "Centre": "20",
                  "Descr Centre": "Gerència", "Sbc": "201", "Descr Sbc": "Manteniment",
                  "Pcr Prg Id": "422-A", "Cap": "2", "Art": "21", "Conc": "212",
                  "Pcr Importe SUM": imp(650000), "Proj": "P3",
                  "Descr Proj": "PID2023-1 SISTEMA DE GESTIÓN ENERGÉTICA INTELIGENTE",
                  "Sbp": "S3", "Nombre Subproyecto": "Manteniment general",
                  "Tercero Nombre": "Suministros Levante SL", "Tercero Nif": NIF_EMPRESA,
                  "Tercero Per Id": "901"}),
            # Ingresos: el tercero es la entidad que financia y conserva su NIF.
            _fila(Presupuesto=ejercicio, **{"Pcr Apl Tipo": "C", "Af": "S", "Centre": "10",
                  "Descr Centre": "Vicerectorat d'Investigació", "Sbc": "101",
                  "Descr Sbc": "Projectes", "Pcr Prg Id": "541-A", "Cap": "7", "Art": "70",
                  "Conc": "700", "Pcr Importe SUM": imp(900000), "Proj": "P1",
                  "Descr Proj": "Finançament de projectes", "Sbp": "S1",
                  "Nombre Subproyecto": "Convocatòria estatal",
                  "Tercero Nombre": "MINISTERIO DE CIENCIA E INNOVACIÓN",
                  "Tercero Nif": NIF_ENTIDAD, "Tercero Per Id": "800"}),
            _fila(Presupuesto=ejercicio, **{"Pcr Apl Tipo": "C", "Af": "N", "Centre": "20",
                  "Descr Centre": "Gerència", "Sbc": "201", "Descr Sbc": "Manteniment",
                  "Pcr Prg Id": "422-A", "Cap": "4", "Art": "45", "Conc": "450",
                  "Pcr Importe SUM": imp(1500000), "Proj": "P4",
                  "Descr Proj": "Transferència nominativa", "Sbp": "S4",
                  "Nombre Subproyecto": "Contracte programa",
                  "Tercero Nombre": "GENERALITAT VALENCIANA", "Tercero Nif": "S4611001A",
                  "Tercero Per Id": "801"}),
        ]
    return filas


def _csv(cabecera: list[str], filas: list[list[str]]) -> bytes:
    def campo(v: str) -> str:
        if any(c in v for c in ',"\n'):
            return '"' + v.replace('"', '""') + '"'
        return v

    lineas = [",".join(campo(c) for c in cabecera)]
    lineas += [",".join(campo(c) for c in fila) for fila in filas]
    return ("\n".join(lineas) + "\n").encode("utf-8")


def presupuesto() -> bytes:
    return _csv(COLUMNAS, _filas())


def pdi() -> bytes:
    # El gazetteer: los nombres del personal investigador, uno por línea.
    return ("\n".join(PERSONAS) + "\n").encode("utf-8")


def clasificacion() -> bytes:
    cab = ["tipo", "nivel", "codigo", "descripcion"]
    filas = [
        ["D", "cap", "1", "Despeses de personal"], ["D", "art", "13", "Personal laboral"],
        ["D", "conc", "131", "Laboral eventual"],
        ["D", "cap", "2", "Despeses corrents en béns i serveis"],
        ["D", "art", "21", "Reparacions i manteniment"], ["D", "conc", "212", "Edificis"],
        ["D", "art", "22", "Material, subministraments i altres"], ["D", "conc", "226", "Despeses diverses"],
        ["I", "cap", "4", "Transferències corrents"], ["I", "art", "45", "De la Generalitat"],
        ["I", "conc", "450", "Contracte programa"],
        ["I", "cap", "7", "Transferències de capital"], ["I", "art", "70", "De l'Estat"],
        ["I", "conc", "700", "Projectes d'investigació"],
    ]
    return _csv(cab, filas)


def prosa() -> bytes:
    texto = """# Pressupost UJI — proposta

## Resum executiu

El pressupost de despeses puja a {{VAL:total_despeses}} euros, amb una variació de {{VAL:var_despeses_pct}}.

{{TAULA:00_Resum:INICI}}
{{TAULA:00_Resum:FI}}

## A.1 — Despeses per concepte

Les despeses sense afectació sumen {{VAL:despeses_sense_afectacio}} euros.

{{TAULA:A1_3_total:INICI}}
{{TAULA:A1_3_total:FI}}
"""
    return texto.encode("utf-8")


def total_gastos_del_ultimo_ejercicio() -> float:
    """Lo que el documento tiene que dar como total de gastos de 2026."""
    return round((420000 + 180000 + 650000) * 1.1, 2)
