from flask import Flask, render_template, request, jsonify, send_file
import math
import io
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import json
from datetime import datetime

app = Flask(
    __name__,
    static_folder='static',
    static_url_path='/static'
)

# ─── FACTORES DE INTERÉS COMPUESTO ───────────────────────────────────────────

def factor_FP(i, n):
    """Factor F/P: Dado P encontrar F"""
    return (1 + i) ** n

def factor_PF(i, n):
    """Factor P/F: Dado F encontrar P"""
    return 1 / (1 + i) ** n

def factor_FA(i, n):
    """Factor F/A: Dado A encontrar F"""
    if i == 0:
        return n
    return ((1 + i) ** n - 1) / i

def factor_AF(i, n):
    """Factor A/F: Dado F encontrar A"""
    if i == 0:
        return 1 / n
    return i / ((1 + i) ** n - 1)

def factor_PA(i, n):
    """Factor P/A: Dado A encontrar P"""
    if i == 0:
        return n
    return ((1 + i) ** n - 1) / (i * (1 + i) ** n)

def factor_AP(i, n):
    """Factor A/P: Recuperación de capital"""
    if i == 0:
        return 1 / n
    return (i * (1 + i) ** n) / ((1 + i) ** n - 1)

def detectar_tipo_analisis(datos):
    """
    Detecta si la alternativa es:
    - beneficio: tiene ingresos/ahorros.
    - costos: solo tiene egresos/costos.
    """
    modo = datos.get('modo', 'uniforme')

    if modo == 'uniforme':
        ingresos = float(datos.get('ingresos', 0) or 0)
        egresos = float(datos.get('egresos', 0) or 0)

        if ingresos <= 0 and egresos > 0:
            return 'costos'
        return 'beneficio'

    flujos = [float(x or 0) for x in datos.get('flujos', [])]

    if flujos and all(fc <= 0 for fc in flujos):
        return 'costos'

    return 'beneficio'


def construir_flujos_ciclo(datos):
    """
    Construye los flujos completos de una alternativa:
    [año 0, año 1, año 2, ..., año N]

    En modo manual, el salvamento se suma automáticamente al último año.
    """
    N = int(datos['vida'])
    inversion = float(datos.get('inversion', 0) or 0)
    salvamento = float(datos.get('salvamento', 0) or 0)
    modo = datos.get('modo', 'uniforme')

    if modo == 'uniforme':
        ingresos = float(datos.get('ingresos', 0) or 0)
        egresos = float(datos.get('egresos', 0) or 0)
        flujo_neto = ingresos - egresos
        flujos = [-inversion] + [flujo_neto] * N
    else:
        flujos_usuario = [float(x or 0) for x in datos.get('flujos', [])]
        flujos = [-inversion] + flujos_usuario[:N]

    if N > 0 and salvamento != 0:
        flujos[N] += salvamento

    return flujos


def extender_flujos_a_periodo(datos, periodo_total):
    """
    Repite el ciclo de vida de una alternativa hasta un periodo común.
    Sirve para comparar VPN cuando las alternativas tienen vidas diferentes.
    """
    N = int(datos['vida'])
    ciclo = construir_flujos_ciclo(datos)
    periodo_total = int(periodo_total)

    if periodo_total <= N:
        return ciclo

    flujos = [0.0] * (periodo_total + 1)

    for inicio in range(0, periodo_total, N):
        flujos[inicio] += ciclo[0]

        for t in range(1, N + 1):
            if inicio + t <= periodo_total:
                flujos[inicio + t] += ciclo[t]

    return flujos


def crear_detalle_vp(flujos, tasa):
    detalle = []

    for t, fc in enumerate(flujos):
        if t == 0:
            continue

        factor = factor_PF(tasa, t)

        detalle.append({
            'periodo': t,
            'flujo': round(fc, 2),
            'factor_pf': round(factor, 6),
            'vp': round(fc * factor, 2)
        })

    return detalle

# ─── CÁLCULO VPN ─────────────────────────────────────────────────────────────

def calcular_vpn(datos, periodo_comparacion=None):
    """
    Calcula el Valor Presente Neto.

    - Para proyectos con ingresos: acepta si VPN >= 0.
    - Para alternativas solo de costos: recomienda el menor costo presente.
    - Si se recibe periodo_comparacion, repite ciclos hasta ese periodo.
    """
    i = datos['tasa'] / 100
    N = int(datos['vida'])
    tipo = detectar_tipo_analisis(datos)

    periodo = int(periodo_comparacion) if periodo_comparacion else N

    if periodo_comparacion:
        flujos = extender_flujos_a_periodo(datos, periodo)
    else:
        flujos = construir_flujos_ciclo(datos)

    vpn = sum(fc * factor_PF(i, t) for t, fc in enumerate(flujos))
    flujos_detalle = crear_detalle_vp(flujos, i)

    if tipo == 'costos':
        decision = 'EVALUADA ✓'
        color = 'verde'
        criterio = 'Alternativa de solo costos: se recomienda el menor costo equivalente.'
    else:
        decision = 'ACEPTAR ✓' if vpn >= 0 else 'RECHAZAR ✗'
        color = 'verde' if vpn >= 0 else 'rojo'
        criterio = 'Proyecto con beneficios: se acepta si VPN ≥ 0.'

    return {
        'vpn': round(vpn, 2),
        'costo_presente': round(-vpn, 2),
        'flujos': flujos_detalle,
        'decision': decision,
        'color_decision': color,
        'tipo_analisis': tipo,
        'periodo_comparacion': periodo,
        'criterio': criterio
    }

# ─── CÁLCULO CAE ─────────────────────────────────────────────────────────────

def calcular_cae(datos):
    """
    Calcula el Valor Anual / Costo Anual Equivalente.

    Con ingresos:
        VA = R - E - RC

    Con solo costos:
        se recomienda el menor CAUE.
    """
    i = datos['tasa'] / 100
    N = int(datos['vida'])
    I = float(datos['inversion'])
    S = float(datos.get('salvamento', 0) or 0)
    modo = datos['modo']
    tipo = detectar_tipo_analisis(datos)

    ap = factor_AP(i, N)
    af = factor_AF(i, N)

    RC = I * ap - S * af

    if modo == 'uniforme':
        R = float(datos.get('ingresos', 0) or 0)
        E = float(datos.get('egresos', 0) or 0)
        VA = R - E - RC
    else:
        flujos = construir_flujos_ciclo(datos)
        vp_total = sum(fc * factor_PF(i, t) for t, fc in enumerate(flujos))
        VA = vp_total * ap

    if tipo == 'costos':
        decision = 'EVALUADA ✓'
        color = 'verde'
        criterio = 'Alternativa de solo costos: se recomienda el menor CAUE.'
    else:
        decision = 'ACEPTAR ✓' if VA >= 0 else 'RECHAZAR ✗'
        color = 'verde' if VA >= 0 else 'rojo'
        criterio = 'Proyecto con beneficios: se acepta si VA ≥ 0.'

    return {
        'cae': round(VA, 2),
        'caue_costo': round(-VA, 2),
        'rc': round(RC, 2),
        'ap': round(ap, 6),
        'af': round(af, 6),
        'decision': decision,
        'color_decision': color,
        'tipo_analisis': tipo,
        'criterio': criterio
    }
# ─── CÁLCULO TIR ─────────────────────────────────────────────────────────────

# ─── CÁLCULO TIR ─────────────────────────────────────────────────────────────

def calcular_vpn_para_tir(flujos_completos, tasa):
    """Calcula el VPN de una serie de flujos para una tasa dada."""
    return sum(fc / (1 + tasa) ** t for t, fc in enumerate(flujos_completos))


def contar_cambios_signo(flujos):
    """Cuenta cambios de signo ignorando ceros para advertir posibles TIR múltiples."""
    signos = []

    for fc in flujos:
        if abs(fc) < 1e-12:
            continue

        signos.append(1 if fc > 0 else -1)

    return sum(1 for a, b in zip(signos, signos[1:]) if a != b)


def buscar_raices_tir(flujos_completos):
    """
    Busca raíces de VPN = 0 en el rango -99.99% a 1000%.
    Esto permite detectar TIR negativas, positivas y posibles TIR múltiples.
    """
    tasas = [-0.9999]

    # Rango negativo: -99% a 0%
    tasas += [(-0.99 + k * (0.99 / 1200)) for k in range(1, 1201)]

    # Rango positivo: 0% a 1000%
    tasas += [(k * (10.0 / 4000)) for k in range(1, 4001)]

    raices = []

    prev_t = tasas[0]

    try:
        prev_v = calcular_vpn_para_tir(flujos_completos, prev_t)
    except Exception:
        prev_v = None

    for t in tasas[1:]:
        try:
            v = calcular_vpn_para_tir(flujos_completos, t)
        except Exception:
            prev_t, prev_v = t, None
            continue

        if prev_v is not None:
            if abs(v) < 1e-7:
                raiz = t

                if not any(abs(raiz - r) < 1e-5 for r in raices):
                    raices.append(raiz)

            elif prev_v * v < 0:
                low, high = prev_t, t
                f_low = prev_v

                for _ in range(120):
                    mid = (low + high) / 2
                    f_mid = calcular_vpn_para_tir(flujos_completos, mid)

                    if abs(f_mid) < 1e-10 or abs(high - low) < 1e-12:
                        break

                    if f_low * f_mid <= 0:
                        high = mid
                    else:
                        low = mid
                        f_low = f_mid

                raiz = (low + high) / 2

                if not any(abs(raiz - r) < 1e-5 for r in raices):
                    raices.append(raiz)

        prev_t, prev_v = t, v

    return sorted(raices)


def calcular_tir(datos):
    """
    Calcula la TIR usando los mismos flujos que VPN y CAE.
    Esto corrige el problema del modo manual, porque ahora sí suma el salvamento al último año.
    """
    trema = float(datos.get('trema', datos.get('tasa', 0)) or 0)

    # Usa construir_flujos_ciclo(), así el salvamento se suma correctamente en modo manual.
    flujos_completos = construir_flujos_ciclo(datos)

    cambios_signo = contar_cambios_signo(flujos_completos)
    raices = buscar_raices_tir(flujos_completos)

    tir = raices[0] if raices else None

    tir_pct_preciso = tir * 100 if tir is not None else None
    tir_pct = round(tir_pct_preciso, 2) if tir_pct_preciso is not None else None

    # Evita que un caso de 9.999999% se muestre/rechace como 9.99% cuando la TREMA es 10%.
    if tir_pct_preciso is not None and abs(tir_pct_preciso - trema) <= 0.01:
        tir_pct = round(trema, 2)

    # Tolerancia de 0.01 puntos porcentuales para no rechazar por redondeo.
    tolerancia_pct = 0.01
    acepta = tir_pct_preciso is not None and tir_pct_preciso >= trema - tolerancia_pct

    flujos_detalle = []

    for t, fc in enumerate(flujos_completos):
        flujos_detalle.append({
            'periodo': t,
            'flujo': round(fc, 2),
            'factor_pf': round(factor_PF(tir, t), 6) if tir is not None else 0,
            'vp': round(fc * factor_PF(tir, t), 2) if tir is not None else 0
        })

    mensajes = []

    if tir is None:
        mensajes.append(
            'No se pudo determinar una TIR en el rango evaluado (-99.99% a 1000%). '
            'Revise que los flujos tengan al menos un cambio de signo.'
        )

    if cambios_signo > 1:
        mensajes.append(
            'Advertencia: los flujos tienen más de un cambio de signo; pueden existir TIR múltiples. '
            'Se muestra la primera raíz encontrada. Para estos casos conviene verificar con VPN o TER.'
        )

    if len(raices) > 1:
        mensajes.append(
            'TIR múltiples detectadas: ' +
            ', '.join(f'{round(r * 100, 2)}%' for r in raices) +
            '.'
        )

    return {
        'tir': tir_pct,
        'tir_precisa': tir_pct_preciso,
        'trema': trema,
        'flujos': flujos_detalle,
        'decision': 'ACEPTAR ✓' if acepta else 'RECHAZAR ✗',
        'color_decision': 'verde' if acepta else 'rojo',
        'sin_tir': tir is None,
        'mensaje': ' '.join(mensajes) if mensajes else None,
        'cambios_signo': cambios_signo,
        'tirs_detectadas': [round(r * 100, 6) for r in raices]
    }

# ─── GENERACIÓN DE PDF ───────────────────────────────────────────────────────

UES_ROJO = colors.HexColor('#8B1A1A')
UES_GRIS = colors.HexColor('#2C2C2C')
UES_CLARO = colors.HexColor('#F5F0F0')
VERDE = colors.HexColor('#1A6B1A')
ROJO_DEC = colors.HexColor('#8B1A1A')

def generar_pdf(datos_reporte):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            topMargin=0.75*inch, bottomMargin=0.75*inch,
                            leftMargin=0.75*inch, rightMargin=0.75*inch)

    styles = getSampleStyleSheet()
    estilos = {
        'titulo': ParagraphStyle('titulo', fontSize=18, textColor=UES_ROJO,
                                  spaceAfter=4, fontName='Helvetica-Bold', alignment=TA_CENTER),
        'subtitulo': ParagraphStyle('subtitulo', fontSize=11, textColor=UES_GRIS,
                                     spaceAfter=8, fontName='Helvetica', alignment=TA_CENTER),
        'seccion': ParagraphStyle('seccion', fontSize=13, textColor=UES_ROJO,
                                   spaceBefore=12, spaceAfter=6, fontName='Helvetica-Bold'),
        'normal': ParagraphStyle('normal', fontSize=10, textColor=UES_GRIS,
                                  spaceAfter=4, fontName='Helvetica'),
        'formula': ParagraphStyle('formula', fontSize=10, textColor=UES_GRIS,
                                   spaceAfter=4, fontName='Helvetica-Oblique',
                                   leftIndent=20),
        'decision_verde': ParagraphStyle('dec_v', fontSize=14, textColor=VERDE,
                                          fontName='Helvetica-Bold', alignment=TA_CENTER,
                                          spaceBefore=8, spaceAfter=8),
        'decision_rojo': ParagraphStyle('dec_r', fontSize=14, textColor=ROJO_DEC,
                                         fontName='Helvetica-Bold', alignment=TA_CENTER,
                                         spaceBefore=8, spaceAfter=8),
    }

    story = []
    metodo = datos_reporte['metodo']
    alt_a = datos_reporte['alternativa_a']
    alt_b = datos_reporte['alternativa_b']

    # ── Encabezado ──
    story.append(Paragraph("Universidad de El Salvador", estilos['titulo']))
    story.append(Paragraph("Facultad Multidisciplinaria de Occidente", estilos['subtitulo']))
    story.append(Paragraph("Ingeniería en Desarrollo de Software", estilos['subtitulo']))
    story.append(HRFlowable(width="100%", thickness=2, color=UES_ROJO))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Sistema de Análisis Económico — SAE", estilos['seccion']))
    story.append(Paragraph(f"Método: {metodo}", estilos['normal']))
    story.append(Paragraph(f"Asignatura: Ingeniería de Negocios — INE135", estilos['normal']))
    story.append(Paragraph(f"Fecha de generación: {datetime.now().strftime('%d/%m/%Y %H:%M')}", estilos['normal']))
    story.append(HRFlowable(width="100%", thickness=1, color=UES_GRIS))
    story.append(Spacer(1, 10))

    # ── Resumen comparativo ──
    story.append(Paragraph("Resumen Comparativo de Alternativas", estilos['seccion']))

    if metodo == 'VPN':
        val_a = f"${alt_a['resultado']['vpn']:,.2f}"
        val_b = f"${alt_b['resultado']['vpn']:,.2f}"
        label = "VPN"
        # Ganador: mayor VPN
        if alt_a['resultado']['vpn'] >= alt_b['resultado']['vpn']:
            ganador = alt_a['nombre']
        else:
            ganador = alt_b['nombre']
    elif metodo == 'CAE':
        val_a = f"${alt_a['resultado']['cae']:,.2f}"
        val_b = f"${alt_b['resultado']['cae']:,.2f}"
        label = "CAE (VA)"
        if alt_a['resultado']['cae'] >= alt_b['resultado']['cae']:
            ganador = alt_a['nombre']
        else:
            ganador = alt_b['nombre']
    else:  # TIR
        ta = alt_a['resultado']['tir']
        tb = alt_b['resultado']['tir']
        val_a = f"{ta}%" if ta else "No determinada"
        val_b = f"{tb}%" if tb else "No determinada"
        label = "TIR"
        if ta is not None and tb is not None:
            ganador = alt_a['nombre'] if ta >= tb else alt_b['nombre']
        elif ta is not None:
            ganador = alt_a['nombre']
        elif tb is not None:
            ganador = alt_b['nombre']
        else:
            ganador = "Ninguna"

    tabla_res = Table([
        ['Alternativa', label, 'Decisión'],
        [alt_a['nombre'], val_a, alt_a['resultado']['decision']],
        [alt_b['nombre'], val_b, alt_b['resultado']['decision']],
    ], colWidths=[2.5*inch, 2*inch, 2.5*inch])

    tabla_res.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), UES_ROJO),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [UES_CLARO, colors.white]),
        ('GRID', (0,0), (-1,-1), 0.5, UES_GRIS),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(tabla_res)
    story.append(Spacer(1, 6))
    if ganador == "Ninguna" or ganador == "Ninguna alternativa recomendable":
        story.append(Paragraph("Conclusión: Ninguna alternativa es recomendable según el método seleccionado.", estilos['decision_rojo']))
    else:
        story.append(Paragraph(f"✔ Alternativa Recomendada: {ganador}", estilos['decision_verde']))
    story.append(HRFlowable(width="100%", thickness=1, color=UES_GRIS))

    # ── Detalle por alternativa ──
    for alt in [alt_a, alt_b]:
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"Detalle: {alt['nombre']}", estilos['seccion']))

        params = alt['parametros']
        story.append(Paragraph(f"• Inversión inicial: ${params.get('inversion', 0):,.2f}", estilos['normal']))
        story.append(Paragraph(f"• Tasa de descuento (TREMA): {params.get('tasa', 0)}%", estilos['normal']))
        story.append(Paragraph(f"• Vida del proyecto: {params.get('vida', 0)} años", estilos['normal']))

        if params.get('salvamento'):
            story.append(Paragraph(f"• Valor de salvamento: ${params.get('salvamento', 0):,.2f}", estilos['normal']))
        if params.get('ingresos'):
            story.append(Paragraph(f"• Ingresos anuales: ${params.get('ingresos', 0):,.2f}", estilos['normal']))
        if params.get('egresos'):
            story.append(Paragraph(f"• Egresos anuales: ${params.get('egresos', 0):,.2f}", estilos['normal']))

        res = alt['resultado']

        if metodo == 'VPN':
            story.append(Spacer(1, 4))
            story.append(Paragraph("Fórmula aplicada:", estilos['normal']))
            story.append(Paragraph("VPN = -P₀ + Σ FC_t × (P/F, i%, t)", estilos['formula']))
            story.append(Paragraph(f"VPN = ${res['vpn']:,.2f}", estilos['normal']))

            # Tabla de flujos
            if res.get('flujos'):
                encabezado = ['Período', 'Flujo Neto ($)', 'Factor P/F', 'VP ($)']
                filas = [[f['periodo'], f"${f['flujo']:,.2f}", f['factor_pf'], f"${f['vp']:,.2f}"]
                         for f in res['flujos']]
                tabla_f = Table([encabezado] + filas,
                                colWidths=[1*inch, 2*inch, 1.5*inch, 1.5*inch])
                tabla_f.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), UES_GRIS),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0,0), (-1,-1), 9),
                    ('ALIGN', (1,0), (-1,-1), 'CENTER'),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [UES_CLARO, colors.white]),
                    ('GRID', (0,0), (-1,-1), 0.4, colors.grey),
                    ('PADDING', (0,0), (-1,-1), 5),
                ]))
                story.append(tabla_f)

        elif metodo == 'CAE':
            story.append(Paragraph("Fórmulas aplicadas:", estilos['normal']))
            story.append(Paragraph("RC(i%) = I×(A/P,i%,N) - S×(A/F,i%,N)", estilos['formula']))
            story.append(Paragraph("VA(i%) = R - E - RC(i%)", estilos['formula']))
            story.append(Paragraph(f"Factor A/P = {res['ap']}", estilos['normal']))
            story.append(Paragraph(f"Factor A/F = {res['af']}", estilos['normal']))
            story.append(Paragraph(f"Recuperación de Capital (RC) = ${res['rc']:,.2f}", estilos['normal']))
            story.append(Paragraph(f"CAE (VA) = ${res['cae']:,.2f}", estilos['normal']))

        else:  # TIR
            story.append(Paragraph("Fórmula aplicada:", estilos['normal']))
            story.append(Paragraph("VPN = 0 = -P₀ + Σ FC_t/(1+TIR)^t", estilos['formula']))
            story.append(Paragraph(f"TREMA de referencia: {res['trema']}%", estilos['normal']))
            if res.get('tir'):
                story.append(Paragraph(f"TIR calculada = {res['tir']}%", estilos['normal']))
            else:
                story.append(Paragraph("TIR: No determinada para estos flujos", estilos['normal']))

        # Decisión
        estilo_dec = estilos['decision_verde'] if 'ACEPTAR' in res['decision'] else estilos['decision_rojo']
        story.append(Paragraph(f"Decisión: {res['decision']}", estilo_dec))
        story.append(HRFlowable(width="100%", thickness=0.5, color=UES_GRIS))

    # ── Pie de página ──
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1, color=UES_ROJO))
    story.append(Paragraph("SAE — Sistema de Análisis Económico | INE135 Ingeniería de Negocios | UES",
                            ParagraphStyle('pie', fontSize=8, textColor=UES_GRIS,
                                           alignment=TA_CENTER, fontName='Helvetica')))

    doc.build(story)
    buffer.seek(0)
    return buffer

def validar_alternativa(alt, nombre_alt):
    """
    Valida los datos mínimos de una alternativa antes de calcular.
    """
    errores = []

    if not alt:
        return [f"No se recibieron datos para {nombre_alt}."]

    inversion = alt.get('inversion')
    tasa = alt.get('tasa')
    vida = alt.get('vida')
    modo = alt.get('modo')

    if inversion is None or inversion < 0:
        errores.append(f"{nombre_alt}: la inversión inicial es obligatoria y no puede ser negativa.")

    if tasa is None or tasa < 0:
        errores.append(f"{nombre_alt}: la tasa/TREMA es obligatoria y no puede ser negativa.")

    if vida is None or int(vida) <= 0:
        errores.append(f"{nombre_alt}: la vida del proyecto debe ser mayor que cero.")

    if modo not in ['uniforme', 'manual']:
        errores.append(f"{nombre_alt}: el modo de flujos no es válido.")

    if modo == 'manual':
        flujos = alt.get('flujos', [])

        if not isinstance(flujos, list) or len(flujos) == 0:
            errores.append(f"{nombre_alt}: debe ingresar los flujos manuales.")
        elif vida and len(flujos) != int(vida):
            errores.append(
                f"{nombre_alt}: la cantidad de flujos manuales debe coincidir con la vida del proyecto."
            )

    return errores


def obtener_ganador(metodo, alt_a, alt_b, res_a, res_b):
    """
    Determina la alternativa recomendada sin elegir proyectos rechazados.
    """
    nombre_a = alt_a.get('nombre', 'Alternativa A')
    nombre_b = alt_b.get('nombre', 'Alternativa B')

    if metodo == 'VPN':
        val_a = res_a['vpn']
        val_b = res_b['vpn']
        aceptada_a = val_a >= 0
        aceptada_b = val_b >= 0

    elif metodo == 'CAE':
        val_a = res_a['cae']
        val_b = res_b['cae']
        aceptada_a = val_a >= 0
        aceptada_b = val_b >= 0

    else:
        val_a = res_a.get('tir')
        val_b = res_b.get('tir')
        trema_a = alt_a.get('trema', alt_a.get('tasa', 0))
        trema_b = alt_b.get('trema', alt_b.get('tasa', 0))

        aceptada_a = val_a is not None and val_a >= trema_a
        aceptada_b = val_b is not None and val_b >= trema_b

    if not aceptada_a and not aceptada_b:
        return {
            'ganador': 'Ninguna alternativa recomendable',
            'mensaje': 'Ambas alternativas fueron rechazadas según el criterio del método seleccionado.',
            'val_a': val_a,
            'val_b': val_b
        }

    if aceptada_a and not aceptada_b:
        return {
            'ganador': nombre_a,
            'mensaje': f'Solo {nombre_a} cumple con el criterio de aceptación.',
            'val_a': val_a,
            'val_b': val_b
        }

    if aceptada_b and not aceptada_a:
        return {
            'ganador': nombre_b,
            'mensaje': f'Solo {nombre_b} cumple con el criterio de aceptación.',
            'val_a': val_a,
            'val_b': val_b
        }

    if val_a >= val_b:
        ganador = nombre_a
    else:
        ganador = nombre_b

    return {
        'ganador': ganador,
        'mensaje': 'Ambas alternativas son aceptables; se recomienda la de mejor resultado económico.',
        'val_a': val_a,
        'val_b': val_b
    }

# ─── RUTAS FLASK ─────────────────────────────────────────────────────────────
def validar_alternativa(alt, nombre_alt):
    errores = []

    if not alt:
        return [f"No se recibieron datos para {nombre_alt}."]

    inversion = alt.get('inversion')
    tasa = alt.get('tasa')
    vida = alt.get('vida')
    modo = alt.get('modo')

    if inversion is None or inversion < 0:
        errores.append(f"{nombre_alt}: la inversión inicial es obligatoria y no puede ser negativa.")

    if tasa is None or tasa < 0:
        errores.append(f"{nombre_alt}: la tasa/TREMA es obligatoria y no puede ser negativa.")

    if vida is None or int(vida) <= 0:
        errores.append(f"{nombre_alt}: la vida del proyecto debe ser mayor que cero.")

    if modo not in ['uniforme', 'manual']:
        errores.append(f"{nombre_alt}: el modo de flujos no es válido.")

    if modo == 'manual':
        flujos = alt.get('flujos', [])

        if not isinstance(flujos, list) or len(flujos) == 0:
            errores.append(f"{nombre_alt}: debe ingresar los flujos manuales.")
        elif vida and len(flujos) != int(vida):
            errores.append(
                f"{nombre_alt}: la cantidad de flujos manuales debe coincidir con la vida del proyecto."
            )

    return errores


def obtener_ganador(metodo, alt_a, alt_b, res_a, res_b):
    """
    Determina la alternativa recomendada.

    Para ingresos/beneficios:
        VPN mayor, CAE/VA mayor o TIR mayor entre aceptadas.

    Para solo costos:
        VPN menos negativo o CAE menos negativo.
    """
    nombre_a = alt_a.get('nombre', 'Alternativa A')
    nombre_b = alt_b.get('nombre', 'Alternativa B')

    tipo_a = res_a.get('tipo_analisis', detectar_tipo_analisis(alt_a))
    tipo_b = res_b.get('tipo_analisis', detectar_tipo_analisis(alt_b))

    analisis_costos = tipo_a == 'costos' and tipo_b == 'costos'

    if metodo == 'VPN':
        val_a = res_a['vpn']
        val_b = res_b['vpn']

        if analisis_costos:
            ganador = nombre_a if val_a >= val_b else nombre_b

            return {
                'ganador': ganador,
                'mensaje': 'Ejercicio de solo costos: se recomienda la alternativa con menor costo en valor presente.',
                'val_a': val_a,
                'val_b': val_b
            }

        aceptada_a = val_a >= 0
        aceptada_b = val_b >= 0

    elif metodo == 'CAE':
        val_a = res_a['cae']
        val_b = res_b['cae']

        if analisis_costos:
            ganador = nombre_a if val_a >= val_b else nombre_b

            return {
                'ganador': ganador,
                'mensaje': 'Ejercicio de solo costos: se recomienda la alternativa con menor CAUE.',
                'val_a': val_a,
                'val_b': val_b
            }

        aceptada_a = val_a >= 0
        aceptada_b = val_b >= 0

    else:
        val_a = res_a.get('tir')
        val_b = res_b.get('tir')

        val_precisa_a = res_a.get('tir_precisa')
        val_precisa_b = res_b.get('tir_precisa')

        trema_a = float(alt_a.get('trema', alt_a.get('tasa', 0)) or 0)
        trema_b = float(alt_b.get('trema', alt_b.get('tasa', 0)) or 0)

        tolerancia_pct = 0.01

        aceptada_a = val_precisa_a is not None and val_precisa_a >= trema_a - tolerancia_pct
        aceptada_b = val_precisa_b is not None and val_precisa_b >= trema_b - tolerancia_pct

    if not aceptada_a and not aceptada_b:
        return {
            'ganador': 'Ninguna alternativa recomendable',
            'mensaje': 'Ambas alternativas fueron rechazadas según el criterio del método seleccionado.',
            'val_a': val_a,
            'val_b': val_b
        }

    if aceptada_a and not aceptada_b:
        return {
            'ganador': nombre_a,
            'mensaje': f'Solo {nombre_a} cumple con el criterio de aceptación.',
            'val_a': val_a,
            'val_b': val_b
        }

    if aceptada_b and not aceptada_a:
        return {
            'ganador': nombre_b,
            'mensaje': f'Solo {nombre_b} cumple con el criterio de aceptación.',
            'val_a': val_a,
            'val_b': val_b
        }

    ganador = nombre_a if val_a >= val_b else nombre_b

    return {
        'ganador': ganador,
        'mensaje': 'Ambas alternativas son aceptables; se recomienda la de mejor resultado económico.',
        'val_a': val_a,
        'val_b': val_b
    }


def periodo_comun_vpn(alt_a, alt_b):
    """
    Calcula el MCM de las vidas útiles para comparar VPN
    cuando las alternativas tienen vidas diferentes.
    """
    vida_a = int(alt_a.get('vida', 0))
    vida_b = int(alt_b.get('vida', 0))

    if vida_a > 0 and vida_b > 0 and vida_a != vida_b:
        return abs(vida_a * vida_b) // math.gcd(vida_a, vida_b)

    return None

def calcular_resultados(metodo, alt_a, alt_b):
    """
    Calcula los resultados de ambas alternativas.
    Se usa en /calcular y en /reporte.
    """
    if metodo == 'VPN':
        periodo_vpn = periodo_comun_vpn(alt_a, alt_b)
        res_a = calcular_vpn(alt_a, periodo_vpn)
        res_b = calcular_vpn(alt_b, periodo_vpn)

    elif metodo == 'CAE':
        res_a = calcular_cae(alt_a)
        res_b = calcular_cae(alt_b)

    elif metodo == 'TIR':
        res_a = calcular_tir(alt_a)
        res_b = calcular_tir(alt_b)

    else:
        raise ValueError('El método seleccionado no es válido.')

    comparacion = obtener_ganador(metodo, alt_a, alt_b, res_a, res_b)

    return res_a, res_b, comparacion


def preparar_datos_reporte(metodo, alt_a, alt_b, res_a, res_b, comparacion):
    """
    Prepara los datos con la estructura que necesita generar_pdf().
    """
    return {
        'metodo': metodo,
        'ganador': comparacion.get('ganador'),
        'alternativa_a': {
            'nombre': alt_a.get('nombre', 'Alternativa A'),
            'parametros': alt_a,
            'resultado': res_a
        },
        'alternativa_b': {
            'nombre': alt_b.get('nombre', 'Alternativa B'),
            'parametros': alt_b,
            'resultado': res_b
        }
    }


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/calcular', methods=['POST'])
def calcular():
    try:
        datos = request.get_json()

        if not datos:
            return jsonify({'error': 'No se recibieron datos para calcular.'}), 400

        metodo = datos.get('metodo')
        alt_a = datos.get('alternativa_a')
        alt_b = datos.get('alternativa_b')

        if metodo not in ['VPN', 'CAE', 'TIR']:
            return jsonify({'error': 'El método seleccionado no es válido.'}), 400

        errores = []
        errores.extend(validar_alternativa(alt_a, 'Alternativa A'))
        errores.extend(validar_alternativa(alt_b, 'Alternativa B'))

        if errores:
            return jsonify({
                'error': 'Datos inválidos.',
                'detalles': errores
            }), 400

        res_a, res_b, comparacion = calcular_resultados(metodo, alt_a, alt_b)

        return jsonify({
            'resultado_a': res_a,
            'resultado_b': res_b,
            'ganador': comparacion['ganador'],
            'mensaje': comparacion['mensaje'],
            'val_a': comparacion['val_a'],
            'val_b': comparacion['val_b']
        })

    except Exception as e:
        return jsonify({
            'error': 'Ocurrió un error interno al calcular.',
            'detalles': str(e)
        }), 500

@app.route('/reporte', methods=['POST'])
def reporte():
    """
    Genera y descarga el reporte PDF.
    """
    try:
        datos = request.get_json()

        if not datos:
            return jsonify({'error': 'No se recibieron datos para generar el reporte.'}), 400

        metodo = datos.get('metodo')
        alt_a = datos.get('alternativa_a')
        alt_b = datos.get('alternativa_b')

        if metodo not in ['VPN', 'CAE', 'TIR']:
            return jsonify({'error': 'El método seleccionado no es válido.'}), 400

        errores = []
        errores.extend(validar_alternativa(alt_a, 'Alternativa A'))
        errores.extend(validar_alternativa(alt_b, 'Alternativa B'))

        if errores:
            return jsonify({
                'error': 'Datos inválidos.',
                'detalles': errores
            }), 400

        res_a, res_b, comparacion = calcular_resultados(metodo, alt_a, alt_b)

        datos_reporte = preparar_datos_reporte(
            metodo,
            alt_a,
            alt_b,
            res_a,
            res_b,
            comparacion
        )

        pdf = generar_pdf(datos_reporte)

        nombre_archivo = f"SAE_Reporte_{metodo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        return send_file(
            pdf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=nombre_archivo
        )

    except Exception as e:
        return jsonify({
            'error': 'Ocurrió un error interno al generar el reporte.',
            'detalles': str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=False, port=5000)
