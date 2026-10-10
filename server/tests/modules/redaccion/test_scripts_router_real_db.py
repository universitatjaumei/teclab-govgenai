"""scripts_router.py contra una sesión real (no mockeada).

Hallazgo de la verificación manual del Camino 4 de MAN.2 (2026-08-14): `POST
/redaccion/scripts/{id}/test` daba 500 siempre. Causa idéntica a la de
`create_template` (hallazgo 7 del mismo día): cada endpoint que hace `commit()` y
luego construye la respuesta leyendo `proposal.id` / `template.id` / `new_version.id`
del objeto ORM dispara una recarga perezosa síncrona sobre atributos que
`expire_on_commit=True` acaba de expirar — revienta con `MissingGreenlet` en una
`AsyncSession` de asyncpg. Los tests existentes de este router (p. ej.
`test_script_proposal_workflow.py`) mockean la sesión con `AsyncMock`, que no
reproduce `expire_on_commit`, así que el patrón se repitió en prácticamente todos
los endpoints (`test`, `validate-test-result`, `save-to-private-template`,
`submit-for-review`, `admin-retest`, `approve`, `reject`, `propose`) sin que nada
lo cazara. Arreglado capturando cada valor **antes** del commit — o, cuando el
propio parámetro de ruta ya es el id, usando ese parámetro en vez de releer el
atributo.

Este test cubre el camino que usa el panel: proposed → tested → validado por el
proposer → pending_review → admin-retest → approved.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.modules.redaccion.database.models import (
    HubReportTemplate,
    HubReportTemplateVersion,
    HubScriptProposal,
)
from server.app.modules.redaccion.pipelines.contracts import StorageRef
from server.app.routers.redaccion._actor import user_to_uuid
from server.app.routers.redaccion.scripts_router import (
    ApproveRequest as _ApproveRequest,
    RejectRequest as _RejectRequest,
    TestProposalRequest as _TestProposalRequest,
    admin_retest as _admin_retest,
    approve_script_proposal as _approve_script_proposal,
    reject_script_proposal as _reject_script_proposal,
    submit_for_review as _submit_for_review,
    test_proposal as _test_proposal,
    validate_test_result as _validate_test_result,
)
from server.app.core.sandbox_client import LocalSandboxClient

_CODE_VALIDO = (
    'result = {"tables": [], '
    '"metrics": [{"name": "total", "value": 1, "unit": "EUR"}], '
    '"free_text": "ok"}'
)


async def _plantilla_global(session) -> uuid.UUID:
    template = HubReportTemplate(
        name="Plantilla destino global",
        report_profile="GENERIC_REPORT",
        owner_kind="platform",
    )
    session.add(template)
    await session.flush()
    template_id = template.id

    version = HubReportTemplateVersion(
        template_id=template_id, version=1, spec_json={}, created_by=uuid.uuid4()
    )
    session.add(version)
    await session.flush()
    template.current_version_id = version.id
    return template_id


async def _propuesta_platform(session, proposer_user_id: str) -> uuid.UUID:
    proposal = HubScriptProposal(
        proposer_user_id=user_to_uuid(proposer_user_id),
        target_owner_kind="platform",
        prompt_nl="Extrae el total de una factura",
        code=_CODE_VALIDO,
        audit_result_json={
            "approved": True,
            "risk_level": "SAFE",
            "puede_revisarse": True,
            "findings": [],
            "confidence": 1.0,
        },
        status="proposed",
    )
    session.add(proposal)
    await session.flush()
    return proposal.id


class _AlmacenDePrueba:
    """El fichero de prueba, en memoria.

    PRO.2 — desde que el contenido del fichero viaja al sandbox (y no su ruta, que dentro
    del contenedor no existía), la tubería lo lee por `StorageService`. Antes este test
    pasaba `key="fake.pdf"` y colaba porque nadie miraba el fichero.
    """

    async def get(self, key: str) -> bytes:
        return b"contenido de prueba"

    async def delete_prefix(self, prefix: str) -> None:
        """#251 — cerrar la propuesta borra lo subido; aquí no hay nada subido que borrar."""


async def test_ciclo_completo_propuesta_hasta_aprobada_en_bd_real(db_url):
    """SuperAdmin de desarrollo (user_id no-UUID) propone, prueba y un admin aprueba."""
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            proposer = UserInfo(user_id="1", email="admin@example.local", role="superadmin")
            admin = UserInfo(user_id="1", email="admin@example.local", role="superadmin")
            sandbox = LocalSandboxClient()
            almacen = _AlmacenDePrueba()

            proposal_id = await _propuesta_platform(session, proposer.user_id)
            await session.commit()

            test_out = await _test_proposal(
                proposal_id=proposal_id,
                body=_TestProposalRequest(
                    test_data_ref=StorageRef(bucket="test-data", key="fake.pdf"),
                    use_real_data=False,
                ),
                user=proposer,
                session=session,
                sandbox=sandbox,
                storage=almacen,
            )
            assert test_out.proposal_id == proposal_id
            assert test_out.status == "tested"

            validate_out = await _validate_test_result(
                proposal_id=proposal_id, user=proposer, session=session
            )
            assert validate_out.proposal_id == proposal_id

            # target_data_is_anonymized se marca directo: la anonimización no es
            # el objeto de este test, que cubre el ciclo sandbox->aprobación.
            proposal = await session.get(HubScriptProposal, proposal_id)
            proposal.test_data_is_anonymized = True
            await session.commit()

            submit_out = await _submit_for_review(
                proposal_id=proposal_id, user=proposer, session=session
            )
            assert submit_out.status == "pending_review"

            retest_out = await _admin_retest(
                proposal_id=proposal_id,
                user=admin,
                session=session,
                sandbox=sandbox,
                storage=almacen,
            )
            assert retest_out.hash_matches is True

            template_id = await _plantilla_global(session)
            await session.commit()

            approve_out = await _approve_script_proposal(
                proposal_id=proposal_id,
                body=_ApproveRequest(target_global_template_id=template_id),
                user=admin,
                session=session,
                storage=almacen,
            )
            assert approve_out.proposal_id == proposal_id
            assert approve_out.template_id == template_id
            assert approve_out.new_version_id is not None
    finally:
        await engine.dispose()


async def test_reject_devuelve_el_proposal_id_correcto_en_bd_real(db_url):
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            proposer = UserInfo(user_id="1", email="admin@example.local", role="superadmin")
            admin = UserInfo(user_id="1", email="admin@example.local", role="superadmin")

            proposal_id = await _propuesta_platform(session, proposer.user_id)
            proposal = await session.get(HubScriptProposal, proposal_id)
            proposal.status = "pending_review"
            await session.commit()

            reject_out = await _reject_script_proposal(
                proposal_id=proposal_id,
                body=_RejectRequest(review_note="No cumple el formato esperado"),
                user=admin,
                session=session,
                storage=_AlmacenDePrueba(),
            )

            assert reject_out.proposal_id == proposal_id
            assert reject_out.status == "rejected"
    finally:
        await engine.dispose()
