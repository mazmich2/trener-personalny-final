from flask import Flask, request, render_template, url_for, make_response, jsonify
import google.generativeai as genai
import os
import requests
import re
from datetime import datetime
from io import BytesIO
from xhtml2pdf import pisa
import logging

app = Flask(__name__)

# Konfiguracja logowania
logging.basicConfig(level=logging.DEBUG)
app.logger.setLevel(logging.DEBUG)

# Konfiguracja API
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY') or 'AIzaSyBMEnnqCZzHPx8qlVVbbB6eT_PKPoWHetk'
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('models/gemini-1.5-pro-latest')

def generuj_plan_treningowy(dane_uzytkownika_dict):
    dane_tekstowe = "\n".join([f"{k}: {v}" for k, v in dane_uzytkownika_dict.items() if v])
    dni_treningowe = dane_uzytkownika_dict.get('dni', '3')

    prompt = f"""Stwórz szczegółowy, spersonalizowany plan treningowy w formie tabeli HTML na podstawie danych:
    {dane_tekstowe}

    Wymagania:
    1. Plan ma obejmować dokładnie 7 dni tygodnia (od poniedziałku do niedzieli).
    2. Użytkownik chce trenować przez {dni_treningowe} dni w tygodniu. Resztę dni zaplanuj jako \"Rest Day\" (dzień odpoczynku) z informacjami o regeneracji.
    3. Dla każdego dnia podaj:
        - Partie mięśniowe
        - Ćwiczenia (nazwa, serie, powtórzenia)
        - Uwagi
    4. Format tabeli HTML:
        <table class=\"training-table\">
            <thead>
                <tr>
                    <th>Dzie\u0144</th>
                    <th>Partie mi\u0119\u015Bniowe</th>
                    <th>\u0106wiczenia</th>
                    <th>Uwagi</th>
                </tr>
            </thead>
            <tbody>
                <!-- 7 dni -->
            </tbody>
        </table>
    5. Nie dodawaj \u017Cadnych znacznik\u00f3w HTML poza tabel\u0105 (&lt;html&gt;, &lt;body&gt; itd.).
    6. U\u017Cyj tylko poprawnego HTML dla tabeli, bez dodatkowych komentarzy czy kodu.
    """

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=4000,
                temperature=0.7,
            )
        )

        result = response.text.strip()
        result = result.replace('&lt;html&gt;&lt;body&gt;', '').replace('&lt;/body&gt;&lt;/html&gt;', '')
        result = result.replace('<html><body>', '').replace('</body></html>', '')

        return result
    except Exception as e:
        app.logger.error(f"Błąd generowania planu: {str(e)}")
        return f'<div class="error">Błąd generowania planu: {str(e)}</div>'

def render_to_pdf(html):
    try:
        html = html.replace('&lt;html&gt;&lt;body&gt;', '').replace('&lt;/body&gt;&lt;/html&gt;', '')
        html = html.replace('<html><body>', '').replace('</body></html>', '')

        polish_char_map = {
            'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
            'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
            'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
            'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z'
        }

        for pol_char, ascii_char in polish_char_map.items():
            html = html.replace(pol_char, ascii_char)

        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
            <title>Plan Treningowy</title>
            <style>
                @page {{ size: A4; margin: 1.5cm; }}
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; color: #333; line-height: 1.6; }}
                h1 {{ color: #2c3e50; text-align: center; margin-bottom: 20px; font-size: 24px; }}
                table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; page-break-inside: avoid; }}
                th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; vertical-align: top; }}
                th {{ background-color: #3498db; color: white; font-weight: bold; }}
                tr:nth-child(even) {{ background-color: #f8f9fa; }}
                ul {{ margin: 0; padding-left: 20px; }}
                li {{ margin-bottom: 8px; }}
                .generation-time {{ text-align: right; color: #7f8c8d; margin-bottom: 20px; font-size: 14px; }}
                .page-break {{ page-break-after: always; }}
            </style>
        </head>
        <body>
            <h1>Plan Treningowy</h1>
            <p class="generation-time">Wygenerowano: {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
            {html}
        </body>
        </html>
        """

        pdf_file = BytesIO()
        pisa_status = pisa.CreatePDF(
            full_html,
            dest=pdf_file,
            encoding='UTF-8'
        )

        if pisa_status.err:
            app.logger.error(f"Błąd PISA: {pisa_status.err}")
            return None

        pdf_file.seek(0)
        return pdf_file

    except Exception as e:
        app.logger.error(f"Błąd podczas renderowania PDF: {str(e)}")
        return None

@app.route('/download_pdf', methods=['POST'])
def download_pdf():
    plan_html = request.form.get('plan_html')
    if not plan_html:
        return "Nie znaleziono planu treningowego.", 400

    pdf = render_to_pdf(plan_html)
    if not pdf:
        return "Błąd podczas generowania PDF.", 500

    response = make_response(pdf.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename="plan_treningowy.pdf"'
    return response

@app.route('/chat', methods=['POST'])
def chat_with_trainer():
    try:
        # Read the trainer's personality
        with open('trener_charakter.txt', 'r', encoding='utf-8') as f:
            personality = f.read().strip()
        
        user_message = request.json.get('message', '')
        
        if not user_message:
            return jsonify({'error': 'Empty message'}), 400
        
        # Prepare the prompt for Gemini
        prompt = f"""
        {personality}
        
        Poniżej znajduje się wiadomość od użytkownika. Odpowiedz jako wirtualny trener Max:
        
        Użytkownik: {user_message}
        
        Max: """
        
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=1000,
                temperature=0.8,
            )
        )
        
        return jsonify({'response': response.text.strip()})
    
    except Exception as e:
        app.logger.error(f"Błąd czatu: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/', methods=['GET', 'POST'])
def index():
    plan_treningowy_html = None
    dane_uzytkownika = {}

    if request.method == 'POST':
        regen = request.form.get('regen', '') == 'true'
        download = request.form.get('download', '') == 'true'

        dane_uzytkownika = {
            'imie': request.form.get('imie', ''),
            'wiek': request.form.get('wiek', ''),
            'plec': request.form.get('plec', ''),
            'waga': request.form.get('waga', ''),
            'wzrost': request.form.get('wzrost', ''),
            'poziom': request.form.get('poziom', ''),
            'cele': request.form.get('cele', ''),
            'dni': request.form.get('dni', '3'),
            'czas': request.form.get('czas', '60'),
            'sprzet': request.form.get('sprzet', 'Własna waga ciała, hantle, mata do ćwiczeń'),
            'kontuzje': request.form.get('kontuzje', 'brak'),
            'preferencje': request.form.get('preferencje', 'brak')
        }

        plan_treningowy_html = generuj_plan_treningowy(dane_uzytkownika)

        if download and plan_treningowy_html:
            pdf = render_to_pdf(plan_treningowy_html)
            if pdf:
                response = make_response(pdf.read())
                response.headers['Content-Type'] = 'application/pdf'
                response.headers['Content-Disposition'] = 'attachment; filename="plan_treningowy.pdf"'
                return response
            else:
                plan_treningowy_html = f'<div class="error">Błąd podczas generowania PDF.</div>{plan_treningowy_html}'

    return render_template(
        'gym.html',
        plan_treningowy=plan_treningowy_html,
        now=datetime.now().strftime('%d.%m.%Y %H:%M'),
        **dane_uzytkownika
    )

if __name__ == '__main__':
    app.run(debug=True)