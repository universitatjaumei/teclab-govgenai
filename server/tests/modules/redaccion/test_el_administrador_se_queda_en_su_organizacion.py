"""Un administrador de organización actúa sobre lo de su organización, y sólo sobre eso.

Dos puertas por las que no era así, las dos en Informes:

* **Plantillas.** `TemplateCreateIn.owner_kind` valía `"platform"` por omisión y crear sólo
  pedía rol de administrador, así que un administrador de organización creaba plantillas de
  plataforma —las que ven todas las organizaciones—, y además sin pedirlo, porque el panel no
  envía el nivel. Es el mismo criterio que #90 fijó al aprobar un borrador como plantilla: el
  nivel de plataforma es de quien administra la plataforma.
* **Revisión de scripts.** La propuesta no sabía de qué organización era, y la cola, el
  re-test, la aprobación, el rechazo y la descarga de los datos de prueba sólo miraban el rol.
  Ahora la propuesta lleva su organización; un administrador ve y revisa las de la suya, y una
  sin organización —las anteriores a este cambio, o las de un superadministrador— sólo la
  revisa un superadministrador. Y aprobar exige poder sobre la plantilla de destino, con la
  misma regla que editarla.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.modules.redaccion.database.models import (
    HubReportTemplate,
    HubReportTemplateVersion,
    HubScriptProposal,
)
from server.app.modules.redaccion.services.script_auditor import AuditResult
from server.app.modules.redaccion.services.script_proposal_service import ProposalResult
from server.app.routers.redaccion._actor import user_to_uuid

ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")


def _admin(org: uuid.UUID, user_id: str = "admin-a") -> UserInfo:
    return UserInfo(user_id=user_id, email=f"{user_id}@uji.es", role="admin", organizacion_ids=(str(org),))


def _superadmin() -> UserInfo:
    return UserInfo(user_id="root", email="root@uji.es", role="superadmin")


_AUDITORIA = {
    "approved": True,
    "risk_level": "SAFE",
    "puede_revisarse": True,
    "findings": [],
    "confidence": 1.0,
}


async def _propuesta(session, *, organizacion_id, status="pending_review") -> uuid.UUID:
    proposal = HubScriptProposal(
        proposer_user_id=user_to_uuid("quien-propone"),
        target_owner_kind="platform",
        prompt_nl="Extrae el total",
        code='result = {"tables": []}',
        audit_result_json=_AUDITORIA,
        status=status,
        organizacion_id=organizacion_id,
        test_data_is_anonymized=True,
        test_data_ref={"bucket": "", "key": "test-data/x.csv"},
    )
    session.add(proposal)
    await session.flush()
    return proposal.id


async def _plantilla(session, *, owner_kind: str, organizacion_id=None) -> uuid.UUID:
    template = HubReportTemplate(
        name="Destino",
        report_profile="GENERIC_REPORT",
        owner_kind=owner_kind,
        organizacion_id=organizacion_id,
    )
    session.add(template)
    await session.flush()
    version = HubReportTemplateVersion(
        template_id=template.id, version=1, spec_json={}, created_by=uuid.uuid4()
    )
    session.add(version)
    await session.flush()
    template.current_version_id = version.id
    return template.id


@pytest.fixture
async def sesion(db_url):
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


# ───────────────────────── Plantillas ─────────────────────────


class TestElNivelDePlataformaEsDelSuperadministrador:

    async def test_should_refuse_a_platform_template_to_an_organization_admin(self, sesion):
        from server.app.routers.redaccion.hub_redaccion_router import TemplateCreateIn, create_template

        with pytest.raises(HTTPException) as fallo:
            await create_template(TemplateCreateIn(name="X", owner_kind="platform"), _admin(ORG_A), sesion)

        assert fallo.value.status_code == 403

    async def test_should_make_it_an_organization_template_when_an_admin_says_nothing(self, sesion):
        """El panel no envía el nivel: lo que se crea sin decirlo es de la organización."""
        from server.app.routers.redaccion.hub_redaccion_router import TemplateCreateIn, create_template

        creada = await create_template(TemplateCreateIn(name="X"), _admin(ORG_A), sesion)

        assert creada.owner_kind == "organizacion"
        plantilla = await sesion.get(HubReportTemplate, creada.id)
        assert plantilla.organizacion_id == ORG_A

    async def test_should_still_let_a_superadmin_create_one_for_the_platform(self, sesion):
        from server.app.routers.redaccion.hub_redaccion_router import TemplateCreateIn, create_template

        creada = await create_template(TemplateCreateIn(name="X"), _superadmin(), sesion)

        assert creada.owner_kind == "platform"


# ───────────────────────── Revisión de scripts ─────────────────────────


class _ServicioQuePropone:
    async def propose(self, **_):
        return ProposalResult(
            code='result = {"tables": []}',
            audit_result=AuditResult.model_validate(_AUDITORIA),
            model_used="doble",
        )


class TestLaPropuestaSabeDeQueOrganizacionEs:

    async def test_should_record_the_proposers_organization(self, sesion):
        from server.app.routers.redaccion.scripts_router import ProposeRequest, propose_script

        respuesta = await propose_script(
            ProposeRequest(prompt_nl="Extrae el total"), _admin(ORG_A), _ServicioQuePropone(), sesion
        )

        propuesta = await sesion.get(HubScriptProposal, respuesta.proposal_id)
        assert propuesta.organizacion_id == ORG_A


class TestLaColaSeAcotaALaOrganizacion:

    async def test_should_list_only_the_admins_own_organization(self, sesion):
        from server.app.routers.redaccion.scripts_router import list_pending_scripts

        propia = await _propuesta(sesion, organizacion_id=ORG_A)
        await _propuesta(sesion, organizacion_id=ORG_B)
        await _propuesta(sesion, organizacion_id=None)
        await sesion.commit()

        vistas = await list_pending_scripts(_admin(ORG_A), sesion)

        assert [p.proposal_id for p in vistas] == [propia]

    async def test_should_show_everything_to_a_superadmin(self, sesion):
        from server.app.routers.redaccion.scripts_router import list_pending_scripts

        for org in (ORG_A, ORG_B, None):
            await _propuesta(sesion, organizacion_id=org)
        await sesion.commit()

        assert len(await list_pending_scripts(_superadmin(), sesion)) == 3


class TestUnaPropuestaAjenaNoExiste:
    """404 y no 403: no se cuenta que existe, como en el resto de Informes."""

    @pytest.mark.parametrize("org", [ORG_B, None], ids=["otra-organizacion", "sin-organizacion"])
    async def test_should_hide_it_from_the_retest(self, sesion, org):
        from server.app.routers.redaccion.scripts_router import admin_retest

        propuesta = await _propuesta(sesion, organizacion_id=org)
        await sesion.commit()

        with pytest.raises(HTTPException) as fallo:
            await admin_retest(propuesta, _admin(ORG_A), sesion, sandbox=None, storage=None)

        assert fallo.value.status_code == 404

    @pytest.mark.parametrize("org", [ORG_B, None], ids=["otra-organizacion", "sin-organizacion"])
    async def test_should_hide_it_from_the_approval(self, sesion, org):
        from server.app.routers.redaccion.scripts_router import ApproveRequest, approve_script_proposal

        propuesta = await _propuesta(sesion, organizacion_id=org)
        destino = await _plantilla(sesion, owner_kind="organizacion", organizacion_id=ORG_A)
        await sesion.commit()

        with pytest.raises(HTTPException) as fallo:
            await approve_script_proposal(
                propuesta, ApproveRequest(target_global_template_id=destino), _admin(ORG_A), sesion, storage=None
            )

        assert fallo.value.status_code == 404

    async def test_should_hide_it_from_the_rejection(self, sesion):
        from server.app.routers.redaccion.scripts_router import RejectRequest, reject_script_proposal

        propuesta = await _propuesta(sesion, organizacion_id=ORG_B)
        await sesion.commit()

        with pytest.raises(HTTPException) as fallo:
            await reject_script_proposal(propuesta, RejectRequest(review_note="no"), _admin(ORG_A), sesion)

        assert fallo.value.status_code == 404

    async def test_should_hide_its_test_data(self, sesion):
        from server.app.routers.redaccion.scripts_router import download_test_data

        propuesta = await _propuesta(sesion, organizacion_id=ORG_B)
        await sesion.commit()

        with pytest.raises(HTTPException) as fallo:
            await download_test_data(propuesta, _admin(ORG_A), sesion, storage=None)

        assert fallo.value.status_code == 404


class TestAprobarExigePoderSobreElDestino:

    async def test_should_refuse_to_embed_into_a_platform_template(self, sesion):
        """Aunque la propuesta sea de su organización: el destino es de todas."""
        from server.app.routers.redaccion.scripts_router import ApproveRequest, approve_script_proposal

        propuesta = await _propuesta(sesion, organizacion_id=ORG_A)
        destino = await _plantilla(sesion, owner_kind="platform")
        await sesion.commit()

        with pytest.raises(HTTPException) as fallo:
            await approve_script_proposal(
                propuesta, ApproveRequest(target_global_template_id=destino), _admin(ORG_A), sesion, storage=None
            )

        assert fallo.value.status_code == 403

    async def test_should_refuse_to_embed_into_another_organizations_template(self, sesion):
        from server.app.routers.redaccion.scripts_router import ApproveRequest, approve_script_proposal

        propuesta = await _propuesta(sesion, organizacion_id=ORG_A)
        destino = await _plantilla(sesion, owner_kind="organizacion", organizacion_id=ORG_B)
        await sesion.commit()

        with pytest.raises(HTTPException) as fallo:
            await approve_script_proposal(
                propuesta, ApproveRequest(target_global_template_id=destino), _admin(ORG_A), sesion, storage=None
            )

        assert fallo.value.status_code == 403
