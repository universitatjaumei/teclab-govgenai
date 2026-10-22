"""#270 — la contraseña del superadministrador no se pasa como argumento a `bootstrap`.

Un argumento se ve en `ps` mientras corre el proceso y se queda en el historial del shell.
`restablecer_superadmin.py` ya escribía esa regla y `setup.sh` ya la pasaba por entorno, pero la
opción seguía existiendo. Ahora sólo llega por `SUPERADMIN_PASSWORD` o por la entrada estándar.
"""
from __future__ import annotations

import io

import pytest

from server.app.scripts import bootstrap


def test_la_opcion_de_la_contrasena_ya_no_existe() -> None:
    with pytest.raises(SystemExit):
        bootstrap._parse_args(["--superadmin-email", "a@b.c", "--superadmin-password", "x"])


def test_se_lee_del_entorno(monkeypatch) -> None:
    monkeypatch.setenv("SUPERADMIN_PASSWORD", "del-entorno")

    assert bootstrap._contrasena_del_superadmin() == "del-entorno"


def test_sin_entorno_se_lee_de_la_entrada_estandar(monkeypatch) -> None:
    monkeypatch.delenv("SUPERADMIN_PASSWORD", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("de-la-entrada\n"))

    assert bootstrap._contrasena_del_superadmin() == "de-la-entrada"


def test_sin_entorno_ni_entrada_falta_y_no_se_inventa(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SUPERADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("SUPERADMIN_EMAIL", "a@b.c")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    assert bootstrap.main([]) == 2
    assert "SUPERADMIN_PASSWORD" in capsys.readouterr().err
