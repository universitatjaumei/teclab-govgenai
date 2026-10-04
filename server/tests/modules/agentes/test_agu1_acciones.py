"""#172 — quién puede qué con un agente de unidad, y cuándo.

La gobernanza es la del catálogo de funciones (FUN), trasladada tal cual porque el problema es
el mismo: una unidad comparte algo que ha hecho, sin que la publicación pase por el equipo de la
plataforma.

* **Registrar es publicar.** No hay aprobación previa: un agente recién registrado se ofrece ya.
* **Suspender es de quien revisa; retirar es de quien publica.** Quien lo publicó no puede
  revisarlo, ni suspenderlo, ni reactivarlo: si pudiera, suspender sería una sugerencia.
* **La fecha de revisión prevista avisa, no oculta** (decisión del usuario, 2026-10-02): un agente
  que se apagara solo al vencer dejaría a alguien sin él sin que nadie lo hubiera decidido.
* **El colectivo no es un nivel de acceso**: dice **quién** lo usa, no cuánto se protege.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from server.app.core.auth.models import UserInfo

ORG = str(uuid.uuid4())
OTRA = str(uuid.uuid4())
AUTORA = str(uuid.uuid4())


def _agente(*, organizacion=ORG, creado_por=AUTORA):
    from server.app.core.identidad import user_to_uuid

    return SimpleNamespace(organizacion_id=uuid.UUID(organizacion), creado_por=user_to_uuid(creado_por))


def _version(estado="registrada", **extra):
    base = dict(
        estado=estado,
        colectivo="organizacion",
        grupos=[],
        revision_prevista_en=date.today() + timedelta(days=90),
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _persona(user_id=None, role="user", orgs=(ORG,), grupos=()):
    return UserInfo(
        user_id=user_id or str(uuid.uuid4()),
        email="p@uji.es",
        role=role,
        organizacion_ids=tuple(orgs),
        saml_groups=tuple(grupos),
    )


def _acciones(version, principal, agente=None):
    from server.app.modules.agentes.acciones import acciones_permitidas

    return acciones_permitidas(agente or _agente(), version, principal=principal)


class TestAcciones:

    def test_la_autora_versiona_y_retira_pero_no_revisa_ni_suspende(self):
        assert _acciones(_version(), _persona(AUTORA)) == ["versionar", "cargar_indice", "cambiar_registro", "ver_calidad", "retirar"]

    def test_el_admin_de_la_organizacion_revisa_suspende_y_retira(self):
        assert _acciones(_version(), _persona(role="admin")) == [
            "versionar",
            "cargar_indice",
            "cambiar_registro",
            "ver_calidad",
            "revisar",
            "suspender",
            "retirar",
        ]

    def test_el_admin_que_lo_publico_no_se_revisa_a_si_mismo(self):
        assert "suspender" not in _acciones(_version(), _persona(AUTORA, role="admin"))
        assert "revisar" not in _acciones(_version(), _persona(AUTORA, role="admin"))

    def test_el_admin_de_otra_organizacion_no_puede_nada(self):
        assert _acciones(_version(), _persona(role="admin", orgs=(OTRA,))) == []

    def test_una_persona_cualquiera_de_la_casa_no_puede_nada(self):
        assert _acciones(_version(), _persona()) == []

    def test_el_superadmin_revisa_suspende_y_retira(self):
        acciones = _acciones(_version(), _persona(role="superadmin", orgs=()))
        assert {"revisar", "suspender", "retirar"} <= set(acciones)

    def test_suspendido_lo_reactiva_quien_revisa_y_no_la_autora(self):
        assert "reactivar" in _acciones(_version("suspendida"), _persona(role="admin"))
        assert "reactivar" not in _acciones(_version("suspendida"), _persona(AUTORA))

    def test_retirado_no_admite_nada(self):
        assert _acciones(_version("retirada"), _persona(role="admin")) == []
        assert _acciones(_version("retirada"), _persona(AUTORA)) == []


class TestTransiciones:

    def test_suspender_exige_motivo(self):
        from server.app.modules.agentes.acciones import AgenteIncoherente, suspender

        with pytest.raises(AgenteIncoherente):
            suspender(_version(), motivo="  ", suspendida_por=uuid.uuid4())

    def test_suspender_y_reactivar_conservan_el_motivo(self):
        from server.app.modules.agentes.acciones import reactivar, suspender

        version = _version(motivo_suspension=None, suspendida_por=None, suspendida_en=None)
        suspender(version, motivo="cita un criterio superado", suspendida_por=uuid.uuid4())
        assert version.estado == "suspendida"
        reactivar(version)
        assert version.estado == "registrada"
        assert version.motivo_suspension == "cita un criterio superado"

    def test_revisar_no_cambia_el_estado(self):
        """Revisar no bloquea usar: es lo que separa la revisión posterior de una aprobación."""
        from server.app.modules.agentes.acciones import aplicar_revision

        version = _version(revisada_por=None, revisada_en=None, revision_resultado=None, revision_nota=None)
        aplicar_revision(version, resultado="correcciones", nota="falta el anexo", revisada_por=uuid.uuid4())
        assert version.estado == "registrada"
        assert version.revision_resultado == "correcciones"

    def test_aprobar_no_es_un_resultado_de_la_revision(self):
        from server.app.modules.agentes.acciones import RevisionInvalida, aplicar_revision

        with pytest.raises(RevisionInvalida):
            aplicar_revision(_version(), resultado="aprobada", nota=None, revisada_por=uuid.uuid4())


class TestRevisionPrevista:

    def test_vencida_avisa(self):
        from server.app.modules.agentes.acciones import revision_vencida

        assert revision_vencida(_version(revision_prevista_en=date.today() - timedelta(days=1)))

    def test_el_mismo_dia_no_esta_vencida(self):
        from server.app.modules.agentes.acciones import revision_vencida

        assert not revision_vencida(_version(revision_prevista_en=date.today()))

    def test_vencida_no_quita_ninguna_accion_ni_lo_oculta(self):
        from server.app.modules.agentes.acciones import lo_puede_usar

        version = _version(revision_prevista_en=date.today() - timedelta(days=400))
        assert lo_puede_usar(_agente(), version, principal=_persona())


class TestColectivo:

    def test_toda_la_organizacion_lo_ve_quien_es_de_ella(self):
        from server.app.modules.agentes.acciones import lo_puede_usar

        assert lo_puede_usar(_agente(), _version(), principal=_persona())
        assert not lo_puede_usar(_agente(), _version(), principal=_persona(orgs=(OTRA,)))

    def test_por_grupos_compara_sin_mayusculas(self):
        """Los acrónimos institucionales se teclean como salen: el mismo criterio que los módulos."""
        from server.app.modules.agentes.acciones import lo_puede_usar

        version = _version(colectivo="grupos", grupos=["PDI"])
        assert lo_puede_usar(_agente(), version, principal=_persona(grupos=("pdi",)))
        assert not lo_puede_usar(_agente(), version, principal=_persona(grupos=("PTGAS",)))

    def test_por_grupos_sin_grupos_no_lo_ve_nadie_de_la_casa(self):
        """Con el login de Google no llegan grupos: un agente por grupos no se ofrece."""
        from server.app.modules.agentes.acciones import lo_puede_usar

        version = _version(colectivo="grupos", grupos=["PDI"])
        assert not lo_puede_usar(_agente(), version, principal=_persona())

    def test_el_grupo_no_salta_la_organizacion(self):
        from server.app.modules.agentes.acciones import lo_puede_usar

        version = _version(colectivo="grupos", grupos=["PDI"])
        assert not lo_puede_usar(_agente(), version, principal=_persona(orgs=(OTRA,), grupos=("PDI",)))

    @pytest.mark.parametrize("estado", ["suspendida", "retirada"])
    def test_suspendido_o_retirado_no_se_ofrece(self, estado):
        from server.app.modules.agentes.acciones import lo_puede_usar

        assert not lo_puede_usar(_agente(), _version(estado), principal=_persona())
