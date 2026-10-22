# Base normativa y criterios de cálculo — Cuba (revisión 22-10-2026)

## Normativa de referencia a validar con la entidad
- **Ley 189/2026, Código de Trabajo**, publicada en Gaceta Oficial No. 78 Ordinaria el 18-09-2026; vigencia desde 25-09-2026. En particular, revisar el título de remuneración por el trabajo: salario y otros ingresos (arts. 245-251), pago e información al trabajador (art. 261), retenciones autorizadas y límites (art. 265), forma de pago a tiempo y tarifa horaria (arts. 267-270). El art. 270.2 dispone descontar, en el sistema a sueldo, las horas dejadas de laborar según la tarifa horaria del salario básico y el régimen de trabajo/descanso aprobado.
- **Resolución 14/2026 del MTSS**, salario mínimo actualizado a 3 210 CUP mensual y 16,84 CUP/hora desde 01-07-2026 (confirmar aplicabilidad al caso y consultar Gaceta oficial).
- **Decreto 164/2026**, organización del sistema salarial en el sector empresarial estatal: aplicar solo cuando el empleador esté dentro de su ámbito.
- **Ley 181/2025**, Presupuesto del Estado para 2026, art. 19: verificar tasa, base y sujetos obligados para la contribución patronal a la Seguridad Social.

## Reglas implementadas en este prototipo
- El salario base se toma del expediente del trabajador; el cálculo de jornada parcial, licencias, vacaciones, subsidios, trabajo extraordinario y rendimiento requiere parametrización y validación específica.
- Una incidencia aprobada puede vincularse a un concepto salarial activo. El concepto puede ser manual, fijo o porcentaje del salario base. El porcentaje se expresa como número porcentual: por ejemplo, 10 significa 10 %.
- Los conceptos `DEVENGO` aumentan el bruto; los `DEDUCCION` se restan del bruto; `APORTE_PATRONAL` e `INFORMATIVO` no se descuentan del neto del trabajador.
- Ausencias injustificadas y llegadas tarde: si se registra un importe aprobado, se aplica ese importe. Si no hay importe, se calcula solo cuando el fondo mensual de horas se haya configurado y la unidad/cantidad sea compatible; la tarifa horaria es salario base dividido por fondo mensual configurado. Configure en Ajustes el fondo de horas y horas por jornada de acuerdo con el régimen aprobado de la entidad. El programa no presume un fondo universal.
- Retenciones tributarias, pensiones alimenticias, embargos, aportes patronales, subsidios, vacaciones, garantías salariales, horas extra y límites legales especiales **no se calculan universalmente**. Deben configurarse conforme a normativa específica, tipo de entidad, situación del trabajador y validación de Contabilidad/RR. HH.
- Las fórmulas libres no se ejecutan; si se selecciona `formula`, el cálculo se detiene para evitar importes silenciosamente incorrectos.

## Fuentes para revisión
- Ley 189/2026: https://www.cibercuba.com/s/gacetaoficial/ley-189-de-2026-de-asamblea-nacional-del-poder-popular
- Aviso del MTSS sobre publicación y vigencia: https://t.me/s/mtss_cuba?before=15455
- Resolución 14/2026: https://www.cibercuba.com/s/gacetaoficial/resolucion-14-de-2026-de-ministerio-de-trabajo-y-seguridad-social
- Consultar siempre el PDF oficial de la Gaceta Oficial: https://www.gacetaoficial.gob.cu/

**Advertencia:** herramienta de gestión, no dictamen jurídico ni garantía de cumplimiento. Antes de liquidaciones reales, validar normativa y convenio colectivo/sistema salarial aplicable al empleador.
