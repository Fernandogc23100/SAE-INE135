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
import tempfile
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from reportlab.platypus import Image

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

AZUL_OSCURO = colors.HexColor('#071F4D')
AZUL_MEDIO = colors.HexColor('#123C7C')
AZUL_CLARO = colors.HexColor('#EAF1FB')
AZUL_TABLA = colors.HexColor('#D7E4F5')
GRIS_TEXTO = colors.HexColor('#263238')
GRIS_LINEA = colors.HexColor('#B0BEC5')
VERDE = colors.HexColor('#0B7A3B')
ROJO_DEC = colors.HexColor('#B3261E')
BLANCO = colors.white

def crear_formula_imagen(formula_latex, ancho=6.2, alto=0.55, fontsize=16):
    """
    Crea una imagen PNG temporal a partir de una fórmula LaTeX.
    Sirve para insertar fórmulas matemáticas bien formateadas en el PDF.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
    tmp.close()

    fig = plt.figure(figsize=(ancho, alto))
    fig.patch.set_facecolor('white')

    plt.text(
        0.5,
        0.5,
        formula_latex,
        fontsize=fontsize,
        ha='center',
        va='center'
    )

    plt.axis('off')
    plt.savefig(
        tmp.name,
        dpi=220,
        bbox_inches='tight',
        pad_inches=0.12,
        transparent=False
    )
    plt.close(fig)

    return tmp.name

def agregar_formula_pdf(story, titulo, formulas_latex, estilos):
    """
    Agrega una caja azul con una o varias fórmulas renderizadas como imagen.
    """
    story.append(Paragraph(titulo, estilos['formula_titulo']))

    elementos_formula = []

    archivos_temporales = []

    for formula in formulas_latex:
        ruta_img = crear_formula_imagen(formula)
        archivos_temporales.append(ruta_img)

        img = Image(ruta_img)
        img.hAlign = 'CENTER'
        img.drawHeight = 0.45 * inch
        img.drawWidth = 5.8 * inch

        elementos_formula.append([img])

    tabla = Table(
        elementos_formula,
        colWidths=[6.5 * inch]
    )

    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F3F7FD')),
        ('BOX', (0, 0), (-1, -1), 0.7, AZUL_MEDIO),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))

    story.append(tabla)
    story.append(Spacer(1, 8))

    return archivos_temporales

def generar_pdf(datos_reporte):
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        leftMargin=0.70 * inch,
        rightMargin=0.70 * inch
    )

    styles = getSampleStyleSheet()

    estilos = {
        'titulo': ParagraphStyle(
            'titulo',
            fontSize=18,
            leading=22,
            textColor=AZUL_OSCURO,
            spaceAfter=3,
            fontName='Helvetica-Bold',
            alignment=TA_CENTER
        ),
        'subtitulo': ParagraphStyle(
            'subtitulo',
            fontSize=10,
            leading=13,
            textColor=GRIS_TEXTO,
            spaceAfter=5,
            fontName='Helvetica',
            alignment=TA_CENTER
        ),
        'titulo_reporte': ParagraphStyle(
            'titulo_reporte',
            fontSize=15,
            leading=18,
            textColor=AZUL_OSCURO,
            spaceBefore=12,
            spaceAfter=8,
            fontName='Helvetica-Bold'
        ),
        'seccion': ParagraphStyle(
            'seccion',
            fontSize=12.5,
            leading=16,
            textColor=AZUL_OSCURO,
            spaceBefore=13,
            spaceAfter=7,
            fontName='Helvetica-Bold'
        ),
        'normal': ParagraphStyle(
            'normal',
            fontSize=9.5,
            leading=13,
            textColor=GRIS_TEXTO,
            spaceAfter=4,
            fontName='Helvetica'
        ),
        'normal_bold': ParagraphStyle(
            'normal_bold',
            fontSize=9.5,
            leading=13,
            textColor=GRIS_TEXTO,
            spaceAfter=4,
            fontName='Helvetica-Bold'
        ),
        'formula_titulo': ParagraphStyle(
            'formula_titulo',
            fontSize=9.5,
            leading=12,
            textColor=AZUL_OSCURO,
            spaceAfter=4,
            fontName='Helvetica-Bold'
        ),
        'formula': ParagraphStyle(
            'formula',
            fontSize=10.5,
            leading=15,
            textColor=AZUL_OSCURO,
            fontName='Helvetica',
            alignment=TA_CENTER
        ),
        'decision_verde': ParagraphStyle(
            'decision_verde',
            fontSize=13,
            leading=16,
            textColor=VERDE,
            fontName='Helvetica-Bold',
            alignment=TA_CENTER,
            spaceBefore=8,
            spaceAfter=8
        ),
        'decision_rojo': ParagraphStyle(
            'decision_rojo',
            fontSize=13,
            leading=16,
            textColor=ROJO_DEC,
            fontName='Helvetica-Bold',
            alignment=TA_CENTER,
            spaceBefore=8,
            spaceAfter=8
        ),
        'pie': ParagraphStyle(
            'pie',
            fontSize=8,
            textColor=GRIS_TEXTO,
            alignment=TA_CENTER,
            fontName='Helvetica'
        )
    }

    story = []

    metodo = datos_reporte['metodo']
    alt_a = datos_reporte['alternativa_a']
    alt_b = datos_reporte['alternativa_b']
    ganador_reporte = datos_reporte.get('ganador')

    def dinero(valor):
        try:
            return f"${float(valor):,.2f}"
        except Exception:
            return "$0.00"

    def porcentaje(valor):
        try:
            return f"{float(valor):,.2f}%"
        except Exception:
            return "0.00%"

    def texto_tir(valor):
        if valor is None:
            return "No determinada"
        return porcentaje(valor)

    def estilo_tabla(header_color=AZUL_OSCURO):
        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), header_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), BLANCO),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8.5),
            ('TEXTCOLOR', (0, 1), (-1, -1), GRIS_TEXTO),
            ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),

            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, AZUL_CLARO]),
            ('GRID', (0, 0), (-1, -1), 0.35, GRIS_LINEA),

            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ])

    def caja_formula(titulo, formulas):
        agregar_formula_pdf(story, titulo, formulas, estilos)

    def valor_resultado(alt):
        res = alt['resultado']

        if metodo == 'VPN':
            return dinero(res.get('vpn', 0))

        if metodo == 'CAE':
            return dinero(res.get('cae', 0))

        tir = res.get('tir')
        return texto_tir(tir)

    def obtener_ganador_pdf():
        if ganador_reporte:
            return ganador_reporte

        if metodo == 'VPN':
            return alt_a['nombre'] if alt_a['resultado']['vpn'] >= alt_b['resultado']['vpn'] else alt_b['nombre']

        if metodo == 'CAE':
            return alt_a['nombre'] if alt_a['resultado']['cae'] >= alt_b['resultado']['cae'] else alt_b['nombre']

        ta = alt_a['resultado'].get('tir')
        tb = alt_b['resultado'].get('tir')

        if ta is not None and tb is not None:
            return alt_a['nombre'] if ta >= tb else alt_b['nombre']
        if ta is not None:
            return alt_a['nombre']
        if tb is not None:
            return alt_b['nombre']

        return "Ninguna alternativa recomendable"

    def agregar_tabla_flujos(res):
        if not res.get('flujos'):
            return

        encabezado = ['Período', 'Flujo Neto ($)', 'Factor P/F', 'VP ($)']
        filas = []

        for f in res['flujos']:
            filas.append([
                str(f.get('periodo', '')),
                dinero(f.get('flujo', 0)),
                f"{float(f.get('factor_pf', 0)):,.6f}",
                dinero(f.get('vp', 0))
            ])

        tabla_f = Table(
            [encabezado] + filas,
            colWidths=[0.95 * inch, 1.95 * inch, 1.45 * inch, 1.65 * inch]
        )
        tabla_f.setStyle(estilo_tabla(AZUL_MEDIO))
        story.append(tabla_f)
        story.append(Spacer(1, 8))

    def agregar_parametros(alt):
        params = alt['parametros']

        filas = [
            ['Parámetro', 'Valor'],
            ['Inversión inicial', dinero(params.get('inversion', 0))],
            ['Tasa de descuento / TREMA', porcentaje(params.get('tasa', 0))],
            ['Vida del proyecto', f"{params.get('vida', 0)} años"],
            ['Valor de salvamento', dinero(params.get('salvamento', 0))]
        ]

        if params.get('modo') == 'manual':
            filas.append(['Modo de flujos', 'Ingreso manual'])
        else:
            filas.append(['Modo de flujos', 'El sistema calcula'])
            filas.append(['Ingresos anuales', dinero(params.get('ingresos', 0))])
            filas.append(['Egresos anuales', dinero(params.get('egresos', 0))])

        tabla = Table(filas, colWidths=[2.5 * inch, 3.5 * inch])
        tabla.setStyle(estilo_tabla(AZUL_MEDIO))
        story.append(tabla)
        story.append(Spacer(1, 8))

    def formulas_por_metodo():
        if metodo == 'VPN':
            return [
                r"$VPN = -P_0 + \sum_{t=1}^{n} FC_t(P/F,i,t)$",
                r"$(P/F,i,t)=\frac{1}{(1+i)^t}$",
                r"$VPN = -P_0 + \sum_{t=1}^{n}\frac{FC_t}{(1+i)^t}$"
            ]

        if metodo == 'CAE':
            return [
                r"$RC(i)=I(A/P,i,N)-S(A/F,i,N)$",
                r"$VA(i)=R-E-RC(i)$",
                r"$VA=VP(A/P,i,N)$"
            ]

        return [
            r"$VP=\sum_{k=0}^{N}R_k(P/F,i',k)-\sum_{k=0}^{N}E_k(P/F,i',k)=0$",
            r"$TIR=i'\quad cuando\quad VP=0$",
            r"$Si\ TIR\geq TREMA,\ se\ acepta;\quad si\ TIR<TREMA,\ se\ rechaza$"
        ]

    def formula_resultado_alt(alt):
        res = alt['resultado']

        if metodo == 'VPN':
            vpn = res.get('vpn', 0)
            return [
                rf"$VPN = {vpn:,.2f}$"
            ]

        if metodo == 'CAE':
            rc = res.get('rc', res.get('recuperacion_capital', 0))
            cae = res.get('cae', 0)

            return [
                rf"$RC = {rc:,.2f}$",
                rf"$CAE = {cae:,.2f}$"
            ]

        tir = res.get('tir')
        trema = res.get('trema', 0)

        if tir is None:
            return [
                rf"$TREMA = {trema:,.2f}\%$",
                r"$TIR\ no\ determinada$"
            ]

        return [
            rf"$TREMA = {trema:,.2f}\%$",
            rf"$TIR = {tir:,.2f}\%$"
        ]

    ganador = obtener_ganador_pdf()

    # ── Encabezado ──
    story.append(Paragraph("Universidad de El Salvador", estilos['titulo']))
    story.append(Paragraph("Facultad Multidisciplinaria de Occidente", estilos['subtitulo']))
    story.append(Paragraph("Ingeniería en Desarrollo de Software", estilos['subtitulo']))

    story.append(HRFlowable(width="100%", thickness=2.2, color=AZUL_OSCURO))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Sistema de Análisis Económico — SAE", estilos['titulo_reporte']))
    story.append(Paragraph(f"<b>Método:</b> {metodo}", estilos['normal']))
    story.append(Paragraph("<b>Asignatura:</b> Ingeniería de Negocios — INE135", estilos['normal']))
    story.append(Paragraph(f"<b>Fecha de generación:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", estilos['normal']))
    story.append(HRFlowable(width="100%", thickness=0.8, color=GRIS_LINEA))
    story.append(Spacer(1, 12))

    # ── Resumen ──
    story.append(Paragraph("Resumen comparativo de alternativas", estilos['seccion']))

    if metodo == 'VPN':
        etiqueta = "VPN"
    elif metodo == 'CAE':
        etiqueta = "CAE / VA"
    else:
        etiqueta = "TIR"

    tabla_res = Table([
        ['Alternativa', etiqueta, 'Decisión'],
        [alt_a['nombre'], valor_resultado(alt_a), alt_a['resultado'].get('decision', 'N/D')],
        [alt_b['nombre'], valor_resultado(alt_b), alt_b['resultado'].get('decision', 'N/D')],
    ], colWidths=[2.45 * inch, 2.05 * inch, 2.35 * inch])

    tabla_res.setStyle(estilo_tabla(AZUL_OSCURO))
    story.append(tabla_res)
    story.append(Spacer(1, 8))

    if ganador == "Ninguna" or ganador == "Ninguna alternativa recomendable":
        story.append(Paragraph("Conclusión: Ninguna alternativa es recomendable según el método seleccionado.", estilos['decision_rojo']))
    else:
        story.append(Paragraph(f"✓ Alternativa recomendada: {ganador}", estilos['decision_verde']))

    story.append(HRFlowable(width="100%", thickness=0.8, color=GRIS_LINEA))
    story.append(Spacer(1, 8))

    # ── Fórmulas generales ──
    story.append(Paragraph("Fórmulas y criterio utilizado", estilos['seccion']))
    caja_formula(f"Fórmulas principales del método {metodo}", formulas_por_metodo())

    # ── Detalle por alternativa ──
    for alt in [alt_a, alt_b]:
        params = alt['parametros']
        res = alt['resultado']

        story.append(Paragraph(f"Detalle de alternativa: {alt['nombre']}", estilos['seccion']))

        story.append(Paragraph("Datos ingresados", estilos['normal_bold']))
        agregar_parametros(alt)

        story.append(Paragraph("Cálculo aplicado", estilos['normal_bold']))
        caja_formula("Resultado calculado", formula_resultado_alt(alt))

        if metodo == 'VPN':
            story.append(Paragraph("Flujos descontados a valor presente", estilos['normal_bold']))
            agregar_tabla_flujos(res)

        elif metodo == 'TIR':
            story.append(Paragraph("Flujos usados para encontrar la tasa interna", estilos['normal_bold']))
            agregar_tabla_flujos(res)

        estilo_dec = estilos['decision_verde'] if 'ACEPTAR' in res.get('decision', '') else estilos['decision_rojo']
        story.append(Paragraph(f"Decisión: {res.get('decision', 'N/D')}", estilo_dec))
        story.append(HRFlowable(width="100%", thickness=0.6, color=GRIS_LINEA))
        story.append(Spacer(1, 8))

    # ── Cierre ──
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL_OSCURO))
    story.append(Paragraph(
        "SAE — Sistema de Análisis Económico | INE135 Ingeniería de Negocios | Universidad de El Salvador",
        estilos['pie']
    ))

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
