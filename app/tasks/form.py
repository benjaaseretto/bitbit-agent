"""FormTask: captura de campos (email, DNI, etc.) según schema del spec."""
from __future__ import annotations

import re
from typing import Any, Callable, Optional, Sequence

from pipecat.frames.frames import FunctionCallResultProperties

from app.tasks.base import BaseTask, TaskContext
from app.tasks.registry import register_task
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@register_task
class FormTask(BaseTask):
    task_type = "FormTask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.form") -> None:
        super().__init__(ctx, node_id=node_id)

    def _schema(self) -> list[dict[str, Any]]:
        return list(self.node_params().get("schema") or [])

    def system_prompt(self) -> str:
        params = self.node_params()
        fields = ", ".join(
            f"{f.get('name')} ({f.get('label') or f.get('type')})" for f in self._schema()
        )
        custom = params.get("instructions") or params.get("custom_instructions") or ""
        title = params.get("title") or "formulario"
        return (
            f"Sos {self.session.nombre_agente} de {self.session.nombre_empresa}. "
            f"FASE: FORMULARIO ({title}). Identidad ya confirmada.\n"
            f"Campos: {fields or 'los que pida el usuario'}.\n"
            "Pedí un campo a la vez. No inventes valores.\n"
            "- registrar_campo / registrar_email cuando el usuario dicta el dato.\n"
            "- confirmar_campo cuando dice que sí, el valor es correcto.\n"
            "- omitir_campo solo si el campo no es required y se niega a darlo.\n"
            "- cancelar_formulario si pide cortar.\n"
            f"{custom}\n"
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [
            self.registrar_campo,
            self.registrar_email,
            self.confirmar_campo,
            self.omitir_campo,
            self.cancelar_formulario,
        ]

    def _field(self, nombre: str) -> Optional[dict[str, Any]]:
        for item in self._schema():
            if str(item.get("name")) == nombre:
                return item
        return self._schema()[0] if self._schema() else None

    async def _maybe_complete(self, params) -> bool:
        pending = []
        for field in self._schema():
            name = str(field.get("name"))
            required = bool(field.get("required"))
            if required and not self.session.variables.get(name):
                pending.append(name)
        if pending:
            return False
        await self.advance("Completado")
        await params.result_callback(
            {"ok": True, "outcome": "Completado", "fields": dict(self.session.variables)},
            properties=_WAIT,
        )
        return True

    @register_tool(type="normal")
    async def registrar_campo(self, params, nombre: str, valor: str) -> None:
        """Registra un campo del formulario (DNI, código, texto)."""
        field = self._field(nombre)
        name = str((field or {}).get("name") or nombre)
        raw = (valor or "").strip()
        if (field or {}).get("type") == "email":
            await self.registrar_email(params, nombre=name, email=raw)
            return
        if (field or {}).get("normalize") == "digits" or (
            (field or {}).get("match") or {}
        ).get("normalize") == "digits":
            raw = re.sub(r"\D+", "", raw)
        self.session.variables[name] = raw
        if (field or {}).get("require_confirmation"):
            await self.speak(
                str((field or {}).get("confirm_question") or f"¿Confirma {name} {raw}?")
                .replace("[[valor]]", raw)
            )
            await params.result_callback(
                {"ok": True, "needs_confirm": True, "field": name, "value": raw},
                properties=_WAIT,
            )
            return
        if await self._maybe_complete(params):
            return
        await params.result_callback(
            {"ok": True, "field": name, "value": raw}, properties=_CONTINUE
        )

    @register_tool(type="normal")
    async def registrar_email(self, params, nombre: str, email: str) -> None:
        """Registra un correo. email debe tener @ y dominio."""
        value = (email or "").strip().lower()
        if not _EMAIL.match(value):
            await params.result_callback(
                {
                    "ok": False,
                    "error": "Email inválido. Pedí que lo dicte como usuario arroba dominio punto com.",
                },
                properties=_CONTINUE,
            )
            return
        name = nombre or "email_cliente"
        self.session.variables[name] = value
        field = self._field(name) or {}
        if field.get("require_confirmation", True):
            q = str(
                field.get("confirm_question")
                or f"Para confirmar, el correo es {value}. ¿Es correcto?"
            ).replace("[[valor]]", value)
            await self.speak(q)
            await params.result_callback(
                {"ok": True, "needs_confirm": True, "field": name, "value": value},
                properties=_WAIT,
            )
            return
        if await self._maybe_complete(params):
            return
        await params.result_callback({"ok": True, "field": name, "value": value}, properties=_CONTINUE)

    @register_tool(type="normal")
    async def confirmar_campo(self, params, nombre: str) -> None:
        """El usuario confirma que el valor registrado es correcto."""
        name = nombre or (self._schema()[0]["name"] if self._schema() else "")
        if name and not self.session.variables.get(name):
            await params.result_callback(
                {"ok": False, "error": "No hay valor para confirmar. Pedí que lo dicte."},
                properties=_CONTINUE,
            )
            return
        if await self._maybe_complete(params):
            return
        await params.result_callback({"ok": True, "confirmed": name}, properties=_CONTINUE)

    @register_tool(type="normal")
    async def omitir_campo(self, params, nombre: str) -> None:
        """Omite un campo no obligatorio."""
        field = self._field(nombre)
        if field and field.get("required"):
            await params.result_callback(
                {"ok": False, "error": "Ese campo es obligatorio. Volvé a pedirlo."},
                properties=_CONTINUE,
            )
            return
        if await self._maybe_complete(params):
            return
        await params.result_callback({"ok": True, "skipped": nombre}, properties=_CONTINUE)

    @register_tool(type="normal")
    async def cancelar_formulario(self, params, razon: Optional[str] = None) -> None:
        """El usuario no quiere completar el formulario."""
        self.session.final_status = "Cancelado"
        await self.advance("Cancelado")
        await params.result_callback(
            {"ok": True, "outcome": "Cancelado", "reason": razon}, properties=_WAIT
        )
