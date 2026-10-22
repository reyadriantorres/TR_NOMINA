from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import sqlite3, json, os, io, csv
from contextlib import contextmanager

BASE=Path(__file__).resolve().parent
DB=Path(os.environ.get("TRN_DB_PATH", BASE/"data"/"tr_nominas.db"))
STATIC=BASE/"static"

SCHEMA="""
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, identity_no TEXT DEFAULT '', department TEXT DEFAULT '', position TEXT DEFAULT '', contract_type TEXT DEFAULT 'Indeterminado', hire_date TEXT DEFAULT '', salary_base NUMERIC NOT NULL DEFAULT 0, payment_system TEXT DEFAULT 'Tiempo', cost_center TEXT DEFAULT 'GENERAL', bank_account TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), incident_type TEXT NOT NULL, date_from TEXT NOT NULL, date_to TEXT DEFAULT '', quantity NUMERIC DEFAULT 1, unit TEXT DEFAULT 'días', amount NUMERIC DEFAULT 0, reason TEXT DEFAULT '', document_ref TEXT DEFAULT '', concept_id INTEGER REFERENCES concepts(id), status TEXT DEFAULT 'Pendiente', reviewed_by TEXT DEFAULT '', reviewed_at TEXT DEFAULT '', payroll_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payrolls(id INTEGER PRIMARY KEY, period TEXT NOT NULL UNIQUE, status TEXT DEFAULT 'Borrador', created_at TEXT DEFAULT CURRENT_TIMESTAMP, closed_at TEXT DEFAULT '', note TEXT DEFAULT '', total_gross NUMERIC DEFAULT 0, total_deductions NUMERIC DEFAULT 0, total_net NUMERIC DEFAULT 0);
CREATE TABLE IF NOT EXISTS payroll_lines(id INTEGER PRIMARY KEY, payroll_id INTEGER NOT NULL REFERENCES payrolls(id), employee_id INTEGER NOT NULL REFERENCES employees(id), base_salary NUMERIC DEFAULT 0, additions NUMERIC DEFAULT 0, deductions NUMERIC DEFAULT 0, gross NUMERIC DEFAULT 0, net NUMERIC DEFAULT 0, breakdown_json TEXT DEFAULT '{}', UNIQUE(payroll_id,employee_id));
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, payroll_id INTEGER REFERENCES payrolls(id), employee_id INTEGER REFERENCES employees(id), payment_date TEXT NOT NULL, amount NUMERIC NOT NULL, method TEXT DEFAULT 'Transferencia', reference TEXT DEFAULT '', status TEXT DEFAULT 'Registrado', note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS payment_allocations(id INTEGER PRIMARY KEY, payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE, payroll_line_id INTEGER NOT NULL REFERENCES payroll_lines(id), amount NUMERIC NOT NULL CHECK(amount > 0), UNIQUE(payment_id,payroll_line_id));
CREATE TABLE IF NOT EXISTS concepts(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, account_debit TEXT DEFAULT '', account_credit TEXT DEFAULT '', enabled INTEGER DEFAULT 1, calculation_mode TEXT DEFAULT 'manual', default_rate NUMERIC DEFAULT 0, valid_from TEXT DEFAULT '', valid_to TEXT DEFAULT '', legal_reference TEXT DEFAULT '', note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, event_at TEXT DEFAULT CURRENT_TIMESTAMP, user_name TEXT DEFAULT 'admin', action TEXT NOT NULL, entity TEXT NOT NULL, entity_id TEXT DEFAULT '', detail TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS accounting_exports(id INTEGER PRIMARY KEY, payroll_id INTEGER NOT NULL REFERENCES payrolls(id), exported_at TEXT DEFAULT CURRENT_TIMESTAMP, format TEXT NOT NULL, total_debit NUMERIC NOT NULL, total_credit NUMERIC NOT NULL, status TEXT DEFAULT 'Generado');
"""
CONCEPTS=[
("SAL_BASE","Salario básico","DEVENGO","6100","4100","Decreto 164/2026 según ámbito aplicable"),
("HORAS_EXTRA","Horas extras / trabajo adicional","DEVENGO","6100","4100","Requiere regla aprobada según régimen aplicable"),
("BONIF","Bonificación / incentivo","DEVENGO","6100","4100","Reglamento salarial de la entidad"),
("AUSENCIA","Ajuste por ausencia","DEDUCCION","4100","4190","Aplicar solo con regla validada"),
("ANTICIPO","Descuento de anticipo","DEDUCCION","4100","1360","Según autorización y norma aplicable"),
("RETENCION","Retenciones al trabajador","DEDUCCION","4100","2190","Tasa/base por validar con Contabilidad"),
("APORTE_SS_EMP","Contribución patronal a Seguridad Social","APORTE_PATRONAL","6200","2195","Validar base y aplicabilidad legal")]
DEFAULTS={"company_name":"Mi Empresa","currency":"CUP","jurisdiction":"Cuba","legal_review_status":"Pendiente de validación profesional","account_salary_expense":"6100","account_payroll_payable":"4100","account_employee_deductions":"2190","account_employer_contribution":"2195","employer_social_security_rate":"0.14","employer_social_security_reference":"Ley 181/2025, Presupuesto 2026, art. 19; verificar base y aplicabilidad","monthly_work_hours":"0","workday_hours":"8"}
@contextmanager
def db():
    """Conexión por petición: commit/rollback explícito y cierre garantizado."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=20000")
        c.execute("PRAGMA journal_mode=WAL")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
def init():
    with db() as c:
        c.executescript(SCHEMA)
        # Migración no destructiva para bases de datos creadas con versiones anteriores.
        cols={r[1] for r in c.execute("PRAGMA table_info(incidents)").fetchall()}
        if "concept_id" not in cols: c.execute("ALTER TABLE incidents ADD COLUMN concept_id INTEGER REFERENCES concepts(id)")
        for x in CONCEPTS: c.execute("INSERT OR IGNORE INTO concepts(code,name,kind,account_debit,account_credit,legal_reference) VALUES(?,?,?,?,?,?)",x)
        for k,v in DEFAULTS.items(): c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
def audit(c,action,entity,eid="",detail=""): c.execute("INSERT INTO audit_log(action,entity,entity_id,detail) VALUES(?,?,?,?)",(action,entity,str(eid),str(detail)[:1000]))
def rnd(n): return float(Decimal(str(n or 0)).quantize(Decimal(".01"),rounding=ROUND_HALF_UP))
def rows(rs): return [dict(r) for r in rs]
class App(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(STATIC),**kw)
    def log_message(self,fmt,*args): print("[TRN]",fmt%args)
    def sendj(self,obj,status=200):
        b=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(b)
    def body(self):
        n=int(self.headers.get("Content-Length","0") or 0); return json.loads(self.rfile.read(n).decode()) if n else {}
    def do_GET(self):
        p=urlparse(self.path); path=p.path
        if path == "/favicon.ico":
            self.send_response(204); self.end_headers(); return
        try:
            with db() as c:
                if path=="/api/health": return self.sendj({"ok":True,"version":"1.2.2","database":str(DB),"sqlite":sqlite3.sqlite_version})
                if path=="/api/employees": return self.sendj(rows(c.execute("SELECT * FROM employees ORDER BY active DESC,name")))
                if path=="/api/incidents": return self.sendj(rows(c.execute("SELECT i.*,e.name employee_name,e.code employee_code FROM incidents i JOIN employees e ON e.id=i.employee_id ORDER BY i.id DESC")))
                if path=="/api/payrolls":
                    return self.sendj(rows(c.execute("""SELECT pr.*,
                        COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id WHERE p.payroll_id=pr.id AND p.status<>'Anulado'),0) AS total_paid,
                        COALESCE((SELECT SUM(pl.net) FROM payroll_lines pl WHERE pl.payroll_id=pr.id),0)-
                        COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id WHERE p.payroll_id=pr.id AND p.status<>'Anulado'),0) AS total_outstanding
                        FROM payrolls pr ORDER BY pr.id DESC""")))
                if path=="/api/payments": return self.sendj(rows(c.execute("SELECT p.*,e.name employee_name,pr.period FROM payments p LEFT JOIN employees e ON e.id=p.employee_id LEFT JOIN payrolls pr ON pr.id=p.payroll_id ORDER BY p.id DESC")))
                if path=="/api/concepts": return self.sendj(rows(c.execute("SELECT * FROM concepts ORDER BY id")))
                if path=="/api/settings": return self.sendj(dict(c.execute("SELECT key,value FROM settings").fetchall()))
                if path=="/api/audit": return self.sendj(rows(c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 300")))
                if path=="/api/payroll-detail":
                    pid=int(parse_qs(p.query).get("id",["0"])[0]); pay=c.execute("SELECT * FROM payrolls WHERE id=?",(pid,)).fetchone()
                    lines=rows(c.execute("SELECT pl.*,e.name,e.code,e.department,e.position FROM payroll_lines pl JOIN employees e ON e.id=pl.employee_id WHERE payroll_id=? ORDER BY e.name",(pid,)))
                    for l in lines: l["breakdown"]=json.loads(l.pop("breakdown_json") or "{}")
                    return self.sendj({"payroll":dict(pay) if pay else None,"lines":lines})
                if path=="/api/accounting/export":
                    pid=int(parse_qs(p.query).get("id",["0"])[0]); pay=c.execute("SELECT * FROM payrolls WHERE id=?",(pid,)).fetchone()
                    if not pay: return self.sendj({"error":"Nómina no encontrada"},404)
                    if pay["status"]!="Cerrada": return self.sendj({"error":"Cierre la nómina antes de exportar"},409)
                    ls=rows(c.execute("SELECT pl.*,e.code,e.name,e.cost_center FROM payroll_lines pl JOIN employees e ON e.id=pl.employee_id WHERE payroll_id=?",(pid,)))
                    st=dict(c.execute("SELECT key,value FROM settings").fetchall()); out=[]
                    # Asiento agregado: gasto bruto al debe, neto y deducciones al haber.
                    for l in ls:
                        gross=rnd(l["gross"]); net=rnd(l["net"]); ded=rnd(l["deductions"])
                        if gross: out.append([pay["period"]+"-01",pay["period"],"NOM-"+pay["period"],st.get("account_salary_expense","6100"),gross,0,l["cost_center"] or "GENERAL",l["code"]+" "+l["name"],"Devengo salarial",l["code"]])
                        if net: out.append([pay["period"]+"-01",pay["period"],"NOM-"+pay["period"],st.get("account_payroll_payable","4100"),0,net,l["cost_center"] or "GENERAL",l["code"]+" "+l["name"],"Neto a pagar",l["code"]])
                        if ded: out.append([pay["period"]+"-01",pay["period"],"NOM-"+pay["period"],st.get("account_employee_deductions","2190"),0,ded,l["cost_center"] or "GENERAL",l["code"]+" "+l["name"],"Deducciones registradas",l["code"]])
                    debit=rnd(sum(float(x[4]) for x in out)); credit=rnd(sum(float(x[5]) for x in out))
                    if debit!=credit: return self.sendj({"error":"Asiento descuadrado. Revise mapeo de cuentas/deducciones antes de exportar.","debe":debit,"haber":credit,"diferencia":rnd(debit-credit)},409)
                    c.execute("INSERT INTO accounting_exports(payroll_id,format,total_debit,total_credit) VALUES(?,?,?,?)",(pid,"CSV genérico",debit,credit)); audit(c,"EXPORTAR_CONTABILIDAD","nomina",pid,f"{debit}={credit}")
                    sio=io.StringIO(newline=""); w=csv.writer(sio,delimiter=";"); w.writerow(["fecha","periodo","asiento","cuenta","debe","haber","centro_costo","tercero","concepto","referencia"]); w.writerows(out); data=("\\ufeff"+sio.getvalue()).encode()
                    self.send_response(200); self.send_header("Content-Type","text/csv; charset=utf-8"); self.send_header("Content-Disposition",f'attachment; filename="asiento_nomina_{pay["period"]}.csv"'); self.send_header("Content-Length",str(len(data))); self.end_headers(); return self.wfile.write(data)
            return super().do_GET()
        except Exception as e: return self.sendj({"error":str(e)},500)
    def do_POST(self):
        path=urlparse(self.path).path
        try:
            d=self.body()
            with db() as c:
                if path=="/api/employees":
                    fs=["code","name","identity_no","department","position","contract_type","hire_date","salary_base","payment_system","cost_center","bank_account","active"]
                    code=str(d.get("code", "")).strip()
                    name=str(d.get("name", "")).strip()
                    position=str(d.get("position", "")).strip()
                    if not code or not name or not position:
                        return self.sendj({"error":"Complete Código, Nombre y Cargo."},400)
                    try:
                        salary=float(d.get("salary_base", 0) or 0)
                        if salary < 0: raise ValueError()
                    except (TypeError, ValueError):
                        return self.sendj({"error":"El salario base debe ser un número igual o mayor que cero."},400)
                    vals=[code,name,str(d.get("identity_no", "")).strip(),str(d.get("department", "")).strip(),position,str(d.get("contract_type", "Indeterminado")),str(d.get("hire_date", "")),salary,str(d.get("payment_system", "Tiempo")),str(d.get("cost_center", "GENERAL")).strip() or "GENERAL",str(d.get("bank_account", "")).strip(),1 if str(d.get("active",1)).lower() not in ("0","false","inactivo") else 0]
                    try:
                        cur=c.execute("INSERT INTO employees("+",".join(fs)+") VALUES("+",".join("?" for _ in fs)+")",vals)
                    except sqlite3.IntegrityError as ex:
                        if "employees.code" in str(ex) or "UNIQUE constraint failed: employees.code" in str(ex):
                            return self.sendj({"error":f"El código {code} ya existe. Escriba otro código."},409)
                        raise
                    audit(c,"CREAR","trabajador",cur.lastrowid,name)
                    c.commit()
                    return self.sendj({"ok":True,"id":cur.lastrowid},201)
                if path.startswith("/api/employees/") and path.endswith("/update"):
                    eid=int(path.split("/")[3]); fs=["code","name","identity_no","department","position","contract_type","hire_date","salary_base","payment_system","cost_center","bank_account","active"]
                    if not c.execute("SELECT id FROM employees WHERE id=?",(eid,)).fetchone():
                        return self.sendj({"error":"El trabajador que intenta editar ya no existe."},404)
                    code=str(d.get("code", "")).strip(); name=str(d.get("name", "")).strip(); position=str(d.get("position", "")).strip()
                    if not code or not name or not position:
                        return self.sendj({"error":"Complete Código, Nombre y Cargo."},400)
                    try:
                        salary=float(d.get("salary_base", 0) or 0)
                        if salary < 0: raise ValueError()
                    except (TypeError, ValueError):
                        return self.sendj({"error":"El salario base debe ser un número igual o mayor que cero."},400)
                    vals=[code,name,str(d.get("identity_no", "")).strip(),str(d.get("department", "")).strip(),position,str(d.get("contract_type", "Indeterminado")),str(d.get("hire_date", "")),salary,str(d.get("payment_system", "Tiempo")),str(d.get("cost_center", "GENERAL")).strip() or "GENERAL",str(d.get("bank_account", "")).strip(),1 if str(d.get("active",1)).lower() not in ("0","false","inactivo") else 0]
                    try:
                        c.execute("UPDATE employees SET "+",".join(k+"=?" for k in fs)+",updated_at=CURRENT_TIMESTAMP WHERE id=?",[*vals,eid])
                    except sqlite3.IntegrityError as ex:
                        if "employees.code" in str(ex) or "UNIQUE constraint failed: employees.code" in str(ex):
                            return self.sendj({"error":f"El código {code} ya existe. Escriba otro código."},409)
                        raise
                    audit(c,"ACTUALIZAR","trabajador",eid,name)
                    c.commit()
                    return self.sendj({"ok":True,"id":eid})
                if path=="/api/incidents":
                    fs=["employee_id","incident_type","date_from","date_to","quantity","unit","amount","reason","document_ref","concept_id"]; vals=[(d.get(k) or None) if k=="concept_id" else d.get(k,0 if k in ("quantity","amount") else "") for k in fs]
                    cur=c.execute("INSERT INTO incidents("+",".join(fs)+") VALUES("+",".join("?" for _ in fs)+")",vals); audit(c,"CREAR","incidencia",cur.lastrowid,d.get("incident_type")); c.commit(); return self.sendj({"ok":True,"id":cur.lastrowid},201)
                if path.startswith("/api/incidents/") and path.endswith("/review"):
                    iid=int(path.split("/")[3]); state=d.get("status")
                    if state not in ("Aprobada","Rechazada"): return self.sendj({"error":"Estado inválido"},400)
                    c.execute("UPDATE incidents SET status=?,reviewed_by='admin',reviewed_at=CURRENT_TIMESTAMP WHERE id=? AND status='Pendiente'",(state,iid)); audit(c,"REVISAR","incidencia",iid,state); c.commit(); return self.sendj({"ok":True})
                if path=="/api/payrolls":
                    period=d.get("period","").strip()
                    if not period: return self.sendj({"error":"Período requerido YYYY-MM"},400)
                    if c.execute("SELECT id FROM payrolls WHERE period=?",(period,)).fetchone(): return self.sendj({"error":"Ya existe una nómina para ese período"},409)
                    active=rows(c.execute("SELECT * FROM employees WHERE active=1 ORDER BY name"))
                    if not active: return self.sendj({"error":"No hay trabajadores activos"},400)
                    pending=c.execute("SELECT COUNT(*) FROM incidents WHERE status='Pendiente' AND substr(date_from,1,7)=?",(period,)).fetchone()[0]
                    cur=c.execute("INSERT INTO payrolls(period,note) VALUES(?,?)",(period,d.get("note",""))); pid=cur.lastrowid; gross_total=ded_total=0
                    settings_map=dict(c.execute("SELECT key,value FROM settings").fetchall())
                    monthly_hours=float(settings_map.get("monthly_work_hours",0) or 0)
                    day_hours=float(settings_map.get("workday_hours",8) or 8)
                    for e in active:
                        inc=rows(c.execute("SELECT * FROM incidents WHERE employee_id=? AND status='Aprobada' AND substr(date_from,1,7)=? AND payroll_id IS NULL",(e["id"],period)))
                        base=float(e["salary_base"] or 0); adds=0.0; ded=0.0; incident_calc=[]
                        for i in inc:
                            amount=float(i.get("amount") or 0); concept=None
                            if i.get("concept_id"):
                                concept=c.execute("SELECT * FROM concepts WHERE id=? AND enabled=1",(i["concept_id"],)).fetchone()
                            if concept:
                                mode=concept["calculation_mode"] or "manual"; rate=float(concept["default_rate"] or 0)
                                if mode=="fijo": amount=rate
                                elif mode=="porcentaje":
                                    # Por defecto, el porcentaje se calcula sobre el salario base del trabajador.
                                    # La incidencia debe estar aprobada y pertenecer al período de la nómina.
                                    amount=rnd(base*rate/100.0)
                                    i["calculation_note"]=f"{rate:g}% del salario base ({base:.2f} CUP) = {amount:.2f} CUP"
                                elif mode=="formula":
                                    return self.sendj({"error":f"El concepto {concept['code']} usa fórmula no soportada. Use manual, fijo o porcentaje hasta configurar una fórmula validada."},400)
                                kind=concept["kind"]
                                if kind=="DEVENGO": adds+=amount
                                elif kind=="DEDUCCION": ded+=amount
                                # Los aportes patronales e informativos nunca reducen el neto del trabajador.
                                i["concept_name"]=concept["name"]; i["concept_kind"]=kind; i["calculated_amount"]=rnd(amount)
                            else:
                                typ=i["incident_type"]
                                if typ in ("Bonificación","Comisión","Horas extras","Otro devengo"): adds+=amount
                                elif typ in ("Anticipo salarial","Descuento autorizado","Ajuste por ausencia","Otra deducción","Retención"): ded+=amount
                                elif typ in ("Ausencia injustificada","Llegada tarde"):
                                    qty=float(i.get("quantity") or 0); unit=(i.get("unit") or "días").lower()
                                    if amount>0: ded+=amount; i["calculated_amount"]=rnd(amount); i["calculation_note"]="Importe manual aprobado"
                                    elif monthly_hours>0 and base>0:
                                        hours=qty*day_hours if unit.startswith("d") else qty if unit.startswith("hora") else 0
                                        calc=rnd(base/monthly_hours*hours) if hours>0 else 0
                                        ded+=calc; i["calculated_amount"]=calc; i["calculation_note"]="Tarifa horaria = salario base / fondo mensual configurado"
                                    else:
                                        i["calculated_amount"]=0; i["calculation_note"]="Sin descuento calculado: configure el fondo mensual de horas o introduzca un importe aprobado"
                                i.setdefault("calculated_amount",rnd(amount))
                            incident_calc.append(i)
                        adds=rnd(adds); ded=rnd(ded); gross=rnd(base+adds); net=rnd(gross-ded)
                        if net<0: return self.sendj({"error":f"La nómina de {e['name']} produciría un neto negativo. Revise descuentos y límites legales."},400)
                        breakdown={"salario_base":base,"incidencias_aprobadas":incident_calc,"devengos_manuales":adds,"deducciones_manuales":ded,"retenciones_legales_calculadas":False,"fondo_mensual_horas_configurado":monthly_hours,"aviso":"Validar retenciones, límites y reglas especiales aplicables antes de cerrar."}
                        c.execute("INSERT INTO payroll_lines(payroll_id,employee_id,base_salary,additions,deductions,gross,net,breakdown_json) VALUES(?,?,?,?,?,?,?,?)",(pid,e["id"],base,adds,ded,gross,net,json.dumps(breakdown,ensure_ascii=False)))
                        gross_total+=gross; ded_total+=ded
                    c.execute("UPDATE payrolls SET total_gross=?,total_deductions=?,total_net=? WHERE id=?",(rnd(gross_total),rnd(ded_total),rnd(gross_total-ded_total),pid))
                    c.execute("UPDATE incidents SET payroll_id=? WHERE status='Aprobada' AND substr(date_from,1,7)=? AND payroll_id IS NULL",(pid,period))
                    audit(c,"GENERAR_BORRADOR","nomina",pid,f"{period}; pendientes={pending}")
                    c.commit()
                    return self.sendj({"ok":True,"id":pid,"pending_incidents":pending,"message":"Borrador creado. Retenciones legales no calculadas automáticamente."},201)
                if path.startswith("/api/payrolls/") and path.endswith("/update-note"):
                    pid=int(path.split("/")[3]); pay=c.execute("SELECT * FROM payrolls WHERE id=?",(pid,)).fetchone()
                    if not pay: return self.sendj({"error":"Nómina no encontrada."},404)
                    if pay["status"]!="Borrador": return self.sendj({"error":"Solo se pueden editar observaciones de una nómina en borrador. Una nómina cerrada debe corregirse mediante un ajuste trazable."},409)
                    note=str(d.get("note", ""))[:1000]
                    c.execute("UPDATE payrolls SET note=? WHERE id=?",(note,pid)); audit(c,"EDITAR_OBSERVACIONES","nomina",pid,note); c.commit()
                    return self.sendj({"ok":True})
                if path.startswith("/api/payrolls/") and path.endswith("/delete"):
                    pid=int(path.split("/")[3]); pay=c.execute("SELECT * FROM payrolls WHERE id=?",(pid,)).fetchone()
                    if not pay: return self.sendj({"error":"Nómina no encontrada."},404)
                    if pay["status"]!="Borrador": return self.sendj({"error":"No se puede eliminar una nómina cerrada. Debe conservarse y corregirse con un ajuste trazable."},409)
                    if c.execute("SELECT 1 FROM payments WHERE payroll_id=? AND status<>'Anulado' LIMIT 1",(pid,)).fetchone(): return self.sendj({"error":"El borrador tiene pagos asociados; no se puede eliminar hasta resolverlos."},409)
                    c.execute("UPDATE incidents SET payroll_id=NULL WHERE payroll_id=?",(pid,))
                    c.execute("DELETE FROM payroll_lines WHERE payroll_id=?",(pid,))
                    c.execute("DELETE FROM payrolls WHERE id=?",(pid,)); audit(c,"ELIMINAR_BORRADOR","nomina",pid,pay["period"]); c.commit()
                    return self.sendj({"ok":True})
                if path.startswith("/api/payments/") and path.endswith("/annul"):
                    payment_id=int(path.split("/")[3]); payment=c.execute("SELECT * FROM payments WHERE id=?",(payment_id,)).fetchone()
                    if not payment: return self.sendj({"error":"Pago no encontrado."},404)
                    if payment["status"]=="Anulado": return self.sendj({"error":"Este pago ya está anulado."},409)
                    reason=str(d.get("reason", "")).strip()
                    if not reason: return self.sendj({"error":"Indique el motivo de anulación para mantener la trazabilidad."},400)
                    c.execute("UPDATE payments SET status='Anulado',note=CASE WHEN COALESCE(note,'')='' THEN ? ELSE note || ' | ANULADO: ' || ? END WHERE id=?",(reason,reason,payment_id))
                    audit(c,"ANULAR","pago",payment_id,reason); c.commit()
                    return self.sendj({"ok":True,"message":"Pago anulado; el saldo vuelve a quedar pendiente."})
                if path.startswith("/api/payrolls/") and path.endswith("/close"):
                    pid=int(path.split("/")[3]); pay=c.execute("SELECT * FROM payrolls WHERE id=?",(pid,)).fetchone()
                    if not pay: return self.sendj({"error":"No encontrada"},404)
                    if pay["status"]!="Borrador": return self.sendj({"error":"Solo se cierra un borrador"},409)
                    pending=c.execute("SELECT COUNT(*) FROM incidents WHERE status='Pendiente' AND substr(date_from,1,7)=?",(pay["period"],)).fetchone()[0]
                    if pending and not d.get("force"): return self.sendj({"error":f"Hay {pending} incidencias pendientes","requires_confirmation":True},409)
                    c.execute("UPDATE payrolls SET status='Cerrada',closed_at=CURRENT_TIMESTAMP WHERE id=?",(pid,)); audit(c,"CERRAR","nomina",pid,pay["period"]); c.commit(); return self.sendj({"ok":True})
                if path=="/api/payments":
                    try:
                        payroll_id=int(d.get("payroll_id") or 0); employee_id=int(d.get("employee_id") or 0) or None
                        amount=rnd(float(d.get("amount") or 0))
                    except (TypeError,ValueError): return self.sendj({"error":"Seleccione una nómina e introduzca un importe válido."},400)
                    if amount<=0: return self.sendj({"error":"El importe del pago debe ser mayor que cero."},400)
                    pay=c.execute("SELECT * FROM payrolls WHERE id=?",(payroll_id,)).fetchone()
                    if not pay: return self.sendj({"error":"Seleccione una nómina válida."},400)
                    if pay["status"]!="Cerrada": return self.sendj({"error":"Solo puede registrar pagos contra una nómina cerrada."},409)
                    # El destino se determina y valida en el servidor, nunca solo en la interfaz.
                    lines=rows(c.execute("SELECT pl.*, e.name FROM payroll_lines pl JOIN employees e ON e.id=pl.employee_id WHERE pl.payroll_id=? AND (? IS NULL OR pl.employee_id=?) ORDER BY pl.employee_id",(payroll_id,employee_id,employee_id)))
                    if not lines: return self.sendj({"error":"No hay líneas de nómina para el trabajador seleccionado."},400)
                    outstanding=[]
                    for line in lines:
                        paid=float(c.execute("SELECT COALESCE(SUM(pa.amount),0) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id WHERE p.payroll_id=? AND pa.payroll_line_id=? AND p.status<>'Anulado'",(payroll_id,line["id"])).fetchone()[0] or 0)
                        due=max(0,rnd(float(line["net"] or 0)-paid))
                        if due>0: outstanding.append((line,due))
                    total_due=rnd(sum(x[1] for x in outstanding))
                    if not outstanding or total_due<=0:
                        return self.sendj({"error":"No existe saldo pendiente para este destino.","outstanding":0},409)
                    if amount>total_due+0.009:
                        target=(f"el trabajador seleccionado ({lines[0]['name'] if 'name' in lines[0] else 'destino individual'})" if employee_id else "la nómina completa")
                        return self.sendj({"error":f"Pago rechazado: el importe ({amount:.2f} CUP) supera el saldo pendiente de {target} ({total_due:.2f} CUP). No se registró ningún pago.","outstanding":total_due,"requested":amount},409)
                    if employee_id and len(outstanding)!=1:
                        return self.sendj({"error":"No se pudo identificar una única línea salarial para el trabajador. No se registró el pago."},409)
                    fs=["payroll_id","employee_id","payment_date","amount","method","reference","note"]
                    vals=[payroll_id,employee_id,d.get("payment_date"),amount,d.get("method","Transferencia"),d.get("reference",""),d.get("note","")]
                    cur=c.execute("INSERT INTO payments("+",".join(fs)+") VALUES("+",".join("?" for _ in fs)+")",vals); payment_id=cur.lastrowid
                    if employee_id:
                        c.execute("INSERT INTO payment_allocations(payment_id,payroll_line_id,amount) VALUES(?,?,?)",(payment_id,outstanding[0][0]["id"],amount))
                    else:
                        # Pago por lote: distribuir proporcionalmente al saldo pendiente, sin superar ningún neto individual.
                        remaining=amount; total=rnd(total_due); allocated=[]
                        for idx,(line,due) in enumerate(outstanding):
                            part=remaining if idx==len(outstanding)-1 else min(due,rnd(amount*due/total))
                            part=min(part,due); allocated.append((line["id"],part)); remaining=rnd(remaining-part)
                        # Absorber redondeos en líneas que aún tengan saldo disponible.
                        if remaining>0.009:
                            for line,due in outstanding:
                                existing=next((a[1] for a in allocated if a[0]==line["id"]),0)
                                room=rnd(due-existing); extra=min(room,remaining)
                                if extra>0:
                                    allocated=[(lid,rnd(v+extra) if lid==line["id"] else v) for lid,v in allocated]; remaining=rnd(remaining-extra)
                                if remaining<=0.009: break
                        for line_id,part in allocated:
                            if part>0: c.execute("INSERT INTO payment_allocations(payment_id,payroll_line_id,amount) VALUES(?,?,?)",(payment_id,line_id,part))
                    audit(c,"REGISTRAR","pago",payment_id,f"nomina={payroll_id}; trabajador={employee_id or 'lote'}; importe={amount}"); c.commit()
                    return self.sendj({"ok":True,"id":payment_id,"allocated":amount,"outstanding_after":rnd(total_due-amount)},201)
                if path=="/api/settings":
                    for k,v in d.items(): c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,str(v)))
                    audit(c,"ACTUALIZAR","configuracion","",",".join(d.keys())); c.commit(); return self.sendj({"ok":True})
                if path=="/api/concepts":
                    fs=["code","name","kind","account_debit","account_credit","enabled","calculation_mode","default_rate","valid_from","valid_to","legal_reference","note"]
                    code=str(d.get("code","")).strip(); name=str(d.get("name","")).strip()
                    if not code or not name: return self.sendj({"error":"Complete el código y el nombre del concepto."},400)
                    enabled=1 if str(d.get("enabled",1)).lower() not in ("0","false","inactivo") else 0
                    vals=[code,name,str(d.get("kind","DEVENGO")),str(d.get("account_debit","")).strip(),str(d.get("account_credit","")).strip(),enabled,str(d.get("calculation_mode","manual")),float(d.get("default_rate",0) or 0),str(d.get("valid_from", "")),str(d.get("valid_to", "")),str(d.get("legal_reference", "")).strip(),str(d.get("note", "")).strip()]
                    cur=c.execute("INSERT INTO concepts("+",".join(fs)+") VALUES("+",".join("?" for _ in fs)+")",vals); audit(c,"CREAR","concepto",cur.lastrowid,code+"; activo="+str(enabled)); c.commit(); return self.sendj({"ok":True,"id":cur.lastrowid,"enabled":enabled},201)
                if path.startswith("/api/concepts/") and path.endswith("/toggle"):
                    cid=int(path.split("/")[3]); row=c.execute("SELECT id,code,enabled FROM concepts WHERE id=?",(cid,)).fetchone()
                    if not row: return self.sendj({"error":"No se encontró el concepto."},404)
                    enabled=0 if int(row["enabled"] or 0) else 1
                    c.execute("UPDATE concepts SET enabled=? WHERE id=?",(enabled,cid)); audit(c,"ACTIVAR" if enabled else "DESACTIVAR","concepto",cid,row["code"]); c.commit(); return self.sendj({"ok":True,"enabled":enabled})
            return self.sendj({"error":"Endpoint no encontrado"},404)
        except sqlite3.IntegrityError as e:
            return self.sendj({"error":"No se pudo guardar por una restricción de datos: "+str(e)},409)
        except Exception as e:
            print("[TRN ERROR]", repr(e))
            return self.sendj({"error":"Error interno: "+str(e)},500)
def main():
    init(); server=ThreadingHTTPServer(("127.0.0.1",8765),App)
    print("\\nTR NÓMINAS 1.2.2 | SQLite"); print("Base de datos:",DB); print("Abrir: http://127.0.0.1:8765"); print("Ctrl+C para cerrar\\n")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
if __name__=="__main__": main()
