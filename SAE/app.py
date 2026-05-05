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

app = Flask(__name__)

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

# ─── CÁLCULO VPN ─────────────────────────────────────────────────────────────

def calcular_vpn(datos):
    """
    Calcula el Valor Presente Neto.
    Modo uniforme: ingresos y egresos anuales constantes.
    Modo manual: flujos netos ingresados por período.
    """
    i = datos['tasa'] / 100
    N = int(datos['vida'])
    P0 = datos['inversion']
    modo = datos['modo']

    flujos_detalle = []

    if modo == 'uniforme':
        R = datos.get('ingresos', 0)
        E = datos.get('egresos', 0)
        S = datos.get('salvamento', 0)
        FC_neto = R - E

        vpn = -P0
        for t in range(1, N + 1):
            vp_t = FC_neto * factor_PF(i, t)
            vpn += vp_t
            flujos_detalle.append({
                'periodo': t,
                'flujo': FC_neto if t < N else FC_neto + S,
                'factor_pf': round(factor_PF(i, t), 6),
                'vp': round(vp_t if t < N else (FC_neto + S) * factor_PF(i, t), 2)
            })
        # Ajustar el último período con salvamento
        vp_s = S * factor_PF(i, N)
        vpn += vp_s
        flujos_detalle[-1]['flujo'] = FC_neto + S
        flujos_detalle[-1]['vp'] = round((FC_neto + S) * factor_PF(i, N), 2)

    else:  # modo manual
        flujos = datos['flujos']  # lista de flujos netos por período
        vpn = -P0
        for t, fc in enumerate(flujos, 1):
            vp_t = fc * factor_PF(i, t)
            vpn += vp_t
            flujos_detalle.append({
                'periodo': t,
                'flujo': fc,
                'factor_pf': round(factor_PF(i, t), 6),
                'vp': round(vp_t, 2)
            })

    return {
        'vpn': round(vpn, 2),
        'flujos': flujos_detalle,
        'decision': 'ACEPTAR ✓' if vpn >= 0 else 'RECHAZAR ✗',
        'color_decision': 'verde' if vpn >= 0 else 'rojo'
    }

# ─── CÁLCULO CAE ─────────────────────────────────────────────────────────────

def calcular_cae(datos):
    """
    Calcula el Costo Anual Equivalente (Valor Anual).
    VA(i%) = R - E - RC(i%)
    RC(i%) = I(A/P,i%,N) - S(A/F,i%,N)
    """
    i = datos['tasa'] / 100
    N = int(datos['vida'])
    I = datos['inversion']
    S = datos.get('salvamento', 0)
    modo = datos['modo']

    ap = factor_AP(i, N)
    af = factor_AF(i, N)

    RC = I * ap - S * af

    if modo == 'uniforme':
        R = datos.get('ingresos', 0)
        E = datos.get('egresos', 0)
        VA = R - E - RC
    else:
        # Con flujos manuales: convertir VP a VA
        flujos = datos['flujos']
        vp_total = -I
        for t, fc in enumerate(flujos, 1):
            vp_total += fc * factor_PF(i, t)
        VA = vp_total * factor_AP(i, N)

    return {
        'cae': round(VA, 2),
        'rc': round(RC, 2),
        'ap': round(ap, 6),
        'af': round(af, 6),
        'decision': 'ACEPTAR ✓' if VA >= 0 else 'RECHAZAR ✗',
        'color_decision': 'verde' if VA >= 0 else 'rojo'
    }

# ─── CÁLCULO TIR ─────────────────────────────────────────────────────────────

def calcular_vpn_para_tir(flujos_completos, tasa):
    """Calcula VPN para una tasa dada (usado en bisección)"""
    vpn = 0
    for t, fc in enumerate(flujos_completos):
        vpn += fc / (1 + tasa) ** t
    return vpn

def calcular_tir(datos):
    """
    Calcula la Tasa Interna de Retorno usando método de bisección.
    """
    N = int(datos['vida'])
    P0 = datos['inversion']
    modo = datos['modo']
    trema = datos['trema'] / 100

    # Construir flujos completos [período 0, 1, 2, ..., N]
    if modo == 'uniforme':
        R = datos.get('ingresos', 0)
        E = datos.get('egresos', 0)
        S = datos.get('salvamento', 0)
        FC_neto = R - E
        flujos_completos = [-P0] + [FC_neto] * (N - 1) + [FC_neto + S]
    else:
        flujos = datos['flujos']
        flujos_completos = [-P0] + flujos

    # Bisección para encontrar TIR
    tir = None
    try:
        low, high = 0.0001, 9.999  # 0.01% a 999.9%
        vpn_low = calcular_vpn_para_tir(flujos_completos, low)
        vpn_high = calcular_vpn_para_tir(flujos_completos, high)

        if vpn_low * vpn_high > 0:
            # No hay raíz en este rango
            tir = None
        else:
            for _ in range(200):
                mid = (low + high) / 2
                vpn_mid = calcular_vpn_para_tir(flujos_completos, mid)
                if abs(vpn_mid) < 0.01:
                    tir = mid
                    break
                if vpn_low * vpn_mid < 0:
                    high = mid
                else:
                    low = mid
                    vpn_low = vpn_mid
            if tir is None:
                tir = (low + high) / 2
    except:
        tir = None

    # Tabla de flujos con VP a la TIR encontrada
    flujos_detalle = []
    for t, fc in enumerate(flujos_completos):
        flujos_detalle.append({
            'periodo': t,
            'flujo': fc,
            'factor_pf': round(factor_PF(tir, t), 6) if tir else 0,
            'vp': round(fc * factor_PF(tir, t), 2) if tir else 0
        })

    tir_pct = round(tir * 100, 2) if tir is not None else None
    acepta = tir_pct is not None and tir_pct >= datos['trema']

    return {
        'tir': tir_pct,
        'trema': datos['trema'],
        'flujos': flujos_detalle,
        'decision': 'ACEPTAR ✓' if acepta else 'RECHAZAR ✗',
        'color_decision': 'verde' if acepta else 'rojo',
        'sin_tir': tir is None
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
        if ta and tb:
            ganador = alt_a['nombre'] if ta >= tb else alt_b['nombre']
        elif ta:
            ganador = alt_a['nombre']
        elif tb:
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

# ─── RUTAS FLASK ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/calcular', methods=['POST'])
def calcular():
    datos = request.get_json()
    metodo = datos['metodo']
    alt_a = datos['alternativa_a']
    alt_b = datos['alternativa_b']

    if metodo == 'VPN':
        res_a = calcular_vpn(alt_a)
        res_b = calcular_vpn(alt_b)
    elif metodo == 'CAE':
        res_a = calcular_cae(alt_a)
        res_b = calcular_cae(alt_b)
    else:
        res_a = calcular_tir(alt_a)
        res_b = calcular_tir(alt_b)

    # Determinar ganador
    if metodo == 'VPN':
        ganador = alt_a.get('nombre', 'A') if res_a['vpn'] >= res_b['vpn'] else alt_b.get('nombre', 'B')
        val_a, val_b = res_a['vpn'], res_b['vpn']
    elif metodo == 'CAE':
        ganador = alt_a.get('nombre', 'A') if res_a['cae'] >= res_b['cae'] else alt_b.get('nombre', 'B')
        val_a, val_b = res_a['cae'], res_b['cae']
    else:
        ta, tb = res_a.get('tir') or -999, res_b.get('tir') or -999
        ganador = alt_a.get('nombre', 'A') if ta >= tb else alt_b.get('nombre', 'B')
        val_a, val_b = ta, tb

    return jsonify({
        'resultado_a': res_a,
        'resultado_b': res_b,
        'ganador': ganador,
        'val_a': val_a,
        'val_b': val_b
    })

@app.route('/reporte', methods=['POST'])
def reporte():
    datos = request.get_json()
    buffer = generar_pdf(datos)
    return send_file(buffer, as_attachment=True,
                     download_name='SAE_Reporte.pdf',
                     mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
