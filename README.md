# TR Nóminas 1.2.1 — corrección de porcentajes y validación de pagos

Aplicación local Python + SQLite. Requiere Python 3.10+. Ejecute `run.bat` en Windows y abra `http://127.0.0.1:8765`.

## Cambios
- Los conceptos porcentuales se calculan en el servidor como porcentaje del salario base del trabajador y el detalle de la nómina muestra la base, tasa y resultado del cálculo.
- Los conceptos deben estar activos y la incidencia debe estar **aprobada** y corresponder al período de la nómina para incorporarse al cálculo. Una nómina ya generada es una instantánea: si se aprueba/añade una incidencia después, hay que eliminar/recrear el borrador mediante el flujo disponible o preparar un nuevo período; no se altera una nómina cerrada.
- Pago individual: el importe se compara con el saldo pendiente de ese trabajador, no con la masa salarial global.
- Pago general: el importe se compara con la suma de saldos pendientes de toda la nómina y se distribuye sin exceder el neto individual.
- Los rechazos de exceso devuelven un mensaje claro y no guardan el pago.
- El detalle identifica el concepto vinculado y muestra la explicación del cálculo.

## Importante
Haz una copia de seguridad de `data/tr_nominas.db` antes de actualizar. Esta versión corrige la lógica genérica de porcentajes y las validaciones de pagos, pero no certifica todos los supuestos de la legislación salarial cubana. Verifica tasas, bases, reglas especiales y retenciones con RR. HH./Contabilidad antes de usarla para liquidaciones reales.


## Gestión segura de nóminas y pagos (1.2.2)
- Los borradores permiten editar sus observaciones y eliminarse antes del cierre. Al eliminar un borrador, las incidencias asociadas se liberan para poder volver a preparar el período.
- Una nómina cerrada no se edita ni se elimina directamente; debe conservarse y corregirse mediante un procedimiento de ajuste trazable.
- Los pagos no se borran físicamente: se pueden anular con un motivo obligatorio. La anulación se registra en auditoría y el importe deja de contar como pagado, restituyendo el saldo pendiente.
- Un pago anulado permanece visible en el historial como evidencia y no se puede volver a anular.
