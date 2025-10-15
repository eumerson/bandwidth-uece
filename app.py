from flask import Flask, jsonify, request, render_template
import sqlite3
import os
import re
from datetime import datetime, timeddate
from contextlib import contextmanager

app = Flask(__name__)

# Configuração do banco
DATABASE = 'bandwidth.db'

@contextmanager
def get_db():
    """Gerenciador de contexto para conexão com o banco"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Inicializa o banco de dados"""
    with get_db() as conn:
        # Tabela de interfaces
        conn.execute('''
            CREATE TABLE IF NOT EXISTS interfaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT UNIQUE NOT NULL,
                descricao TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabela de consumo
        conn.execute('''
            CREATE TABLE IF NOT EXISTS consumo_banda (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interface_id INTEGER,
                data_referencia DATE NOT NULL,
                periodo TEXT CHECK (periodo IN ('diario', 'mensal')),
                entrada_bytes INTEGER,
                saida_bytes INTEGER,
                total_bytes INTEGER,
                taxa_media_bps INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (interface_id) REFERENCES interfaces (id),
                UNIQUE(interface_id, data_referencia, periodo)
            )
        ''')
        
        # Insere interfaces padrão
        interfaces = ['WAN', 'CAMPUS', 'DI', 'ETICE_NUVENS', 'ETICE_GOV']
        for interface in interfaces:
            conn.execute(
                'INSERT OR IGNORE INTO interfaces (nome) VALUES (?)',
                (interface,)
            )
        
        conn.commit()
    print("✅ Banco de dados inicializado!")

def convert_to_bytes(value: str) -> int:
    """Converte valores como '2.58 TiB', '877.23 GiB' para bytes"""
    if not value or value == 'None':
        return 0
        
    units = {
        'kib': 1024,
        'mib': 1024**2,
        'gib': 1024**3,
        'tib': 1024**4,
        'kb': 1000,
        'mb': 1000**2,
        'gb': 1000**3,
        'tb': 1000**4
    }
    
    value = value.lower().replace(' ', '')
    match = re.match(r'([\d.]+)([a-z]+)', value)
    if match:
        number, unit = match.groups()
        return int(float(number) * units.get(unit, 1))
    return int(float(value))

def convert_speed_to_bps(speed: str) -> int:
    """Converte velocidades como '349.48 Mbit/s' para bps"""
    if not speed or speed == 'None':
        return 0
        
    units = {
        'kbit/s': 1000,
        'mbit/s': 1000**2,
        'gbit/s': 1000**3,
        'tbit/s': 1000**4
    }
    
    speed = speed.lower().replace(' ', '')
    match = re.match(r'([\d.]+)([a-z]+/s)', speed)
    if match:
        number, unit = match.groups()
        return int(float(number) * units.get(unit, 1))
    return int(float(speed))

def parse_bandwidth_data(text: str):
    """Extrai dados do texto fornecido"""
    lines = text.split('\n')
    data = []
    current_date = None
    current_period = None
    
    for line in lines:
        line = line.strip()
        
        # Detecta data e período
        if line.startswith('- Ontem ('):
            date_match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', line)
            if date_match:
                current_date = date_match.group(1)
                current_period = 'diario'
        elif line.startswith('- No mês ('):
            date_match = re.search(r'\((\d{4}-\d{2})\)', line)
            if date_match:
                current_date = date_match.group(1) + '-01'
                current_period = 'mensal'
        
        # Detecta interface
        elif line.startswith('--- Interface '):
            interface = line.replace('--- Interface ', '').strip()
            
            if current_date and current_period:
                entry = {
                    'interface': interface,
                    'data_referencia': current_date,
                    'periodo': current_period,
                    'entrada': None,
                    'saida': None,
                    'total': None,
                    'taxa_media': None
                }
                data.append(entry)
        
        # Extrai valores
        elif line.startswith('Entrada:') and data:
            data[-1]['entrada'] = line.replace('Entrada:', '').strip()
        elif line.startswith('Saida:') and data:
            data[-1]['saida'] = line.replace('Saida:', '').strip()
        elif line.startswith('Total:') and data:
            data[-1]['total'] = line.replace('Total:', '').strip()
        elif line.startswith('Taxa de transferência média:') and data:
            data[-1]['taxa_media'] = line.replace('Taxa de transferência média:', '').strip()
    
    return data

@app.route('/')
def index():
    """Página inicial"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>📊 Monitoramento de Banda - UECE</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .card { background: #f5f5f5; padding: 20px; margin: 10px 0; border-radius: 8px; }
            button { background: #007cba; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; }
            textarea { width: 100%; height: 200px; margin: 10px 0; }
        </style>
    </head>
    <body>
        <h1>📊 Sistema de Monitoramento de Banda - UECE</h1>
        
        <div class="card">
            <h2>📤 Upload de Dados</h2>
            <form id="uploadForm">
                <textarea id="dados" placeholder="Cole aqui os dados de consumo de banda..."></textarea>
                <br>
                <button type="submit">Enviar Dados</button>
            </form>
            <div id="result"></div>
        </div>

        <div class="card">
            <h2>📈 Consultas Rápidas</h2>
            <p><a href="/api/interfaces" target="_blank">Listar Interfaces</a></p>
            <p><a href="/api/consumo/WAN" target="_blank">Consumo WAN</a></p>
            <p><a href="/api/consumo/DI" target="_blank">Consumo DI</a></p>
            <p><a href="/api/relatorio/mensal" target="_blank">Relatório Mensal</a></p>
        </div>

        <script>
            document.getElementById('uploadForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                const dados = document.getElementById('dados').value;
                
                const response = await fetch('/api/upload', {
                    method: 'POST',
                    headers: { 'Content-Type': 'text/plain' },
                    body: dados
                });
                
                const result = await response.json();
                document.getElementById('result').innerHTML = 
                    result.success ? 
                    '<p style="color: green;">✅ ' + result.message + '</p>' :
                    '<p style="color: red;">❌ ' + result.message + '</p>';
            });
        </script>
    </body>
    </html>
    '''

@app.route('/api/upload', methods=['POST'])
def upload_data():
    """Endpoint para upload de dados"""
    try:
        text_data = request.get_data(as_text=True)
        
        if not text_data:
            return jsonify({'success': False, 'message': 'Nenhum dado fornecido'})
        
        # Parse dos dados
        parsed_data = parse_bandwidth_data(text_data)
        
        if not parsed_data:
            return jsonify({'success': False, 'message': 'Nenhum dado válido encontrado'})
        
        # Salva no banco
        records_saved = 0
        with get_db() as conn:
            for entry in parsed_data:
                # Obtém ID da interface
                cursor = conn.execute(
                    'SELECT id FROM interfaces WHERE nome = ?',
                    (entry['interface'],)
                )
                result = cursor.fetchone()
                
                if result:
                    interface_id = result['id']
                    
                    # Converte valores
                    entrada_bytes = convert_to_bytes(entry['entrada'])
                    saida_bytes = convert_to_bytes(entry['saida'])
                    total_bytes = convert_to_bytes(entry['total'])
                    taxa_bps = convert_speed_to_bps(entry['taxa_media'])
                    
                    # Insere ou atualiza
                    conn.execute('''
                        INSERT OR REPLACE INTO consumo_banda 
                        (interface_id, data_referencia, periodo, entrada_bytes, saida_bytes, total_bytes, taxa_media_bps)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        interface_id, entry['data_referencia'], entry['periodo'],
                        entrada_bytes, saida_bytes, total_bytes, taxa_bps
                    ))
                    
                    records_saved += 1
            
            conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Dados processados com sucesso! {records_saved} registros salvos.',
            'records': records_saved
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/interfaces')
def get_interfaces():
    """Lista todas as interfaces"""
    with get_db() as conn:
        interfaces = conn.execute(
            'SELECT id, nome, created_at FROM interfaces ORDER BY nome'
        ).fetchall()
    
    return jsonify([dict(interface) for interface in interfaces])

@app.route('/api/consumo/<interface>')
def get_consumo_interface(interface):
    """Consulta consumo por interface"""
    periodo = request.args.get('periodo', 'diario')
    limite = int(request.args.get('limite', 30))
    
    with get_db() as conn:
        # Verifica se a interface existe
        interface_obj = conn.execute(
            'SELECT id, nome FROM interfaces WHERE nome = ?',
            (interface,)
        ).fetchone()
        
        if not interface_obj:
            return jsonify({'error': 'Interface não encontrada'}), 404
        
        # Busca dados
        dados = conn.execute('''
            SELECT data_referencia, periodo, entrada_bytes, saida_bytes, total_bytes, taxa_media_bps
            FROM consumo_banda 
            WHERE interface_id = ? AND periodo = ?
            ORDER BY data_referencia DESC
            LIMIT ?
        ''', (interface_obj['id'], periodo, limite)).fetchall()
    
    resultado = {
        'interface': interface_obj['nome'],
        'periodo': periodo,
        'dados': []
    }
    
    for row in dados:
        resultado['dados'].append({
            'data': row['data_referencia'],
            'periodo': row['periodo'],
            'entrada_bytes': row['entrada_bytes'],
            'saida_bytes': row['saida_bytes'],
            'total_bytes': row['total_bytes'],
            'taxa_media_bps': row['taxa_media_bps'],
            'entrada_gib': row['entrada_bytes'] / (1024**3),
            'saida_gib': row['saida_bytes'] / (1024**3),
            'total_gib': row['total_bytes'] / (1024**3),
            'taxa_mbps': row['taxa_media_bps'] / (1000**2)
        })
    
    return jsonify(resultado)

@app.route('/api/relatorio/mensal')
def get_relatorio_mensal():
    """Relatório mensal consolidado"""
    mes = request.args.get('mes', datetime.now().strftime('%Y-%m'))
    
    with get_db() as conn:
        relatorio = conn.execute('''
            SELECT i.nome, 
                   SUM(entrada_bytes) as total_entrada,
                   SUM(saida_bytes) as total_saida,
                   AVG(taxa_media_bps) as media_taxa
            FROM consumo_banda cb
            JOIN interfaces i ON cb.interface_id = i.id
            WHERE cb.periodo = 'mensal' 
            AND strftime('%Y-%m', data_referencia) = ?
            GROUP BY i.nome
        ''', (mes,)).fetchall()
    
    resultado = {}
    for row in relatorio:
        resultado[row['nome']] = {
            'total_entrada_bytes': row['total_entrada'],
            'total_saida_bytes': row['total_saida'],
            'media_taxa_bps': int(row['media_taxa']) if row['media_taxa'] else 0,
            'total_entrada_tib': row['total_entrada'] / (1024**4),
            'total_saida_tib': row['total_saida'] / (1024**4)
        }
    
    return jsonify({
        'mes': mes,
        'relatorio': resultado
    })

@app.route('/api/status')
def status():
    """Status do sistema"""
    with get_db() as conn:
        total_interfaces = conn.execute('SELECT COUNT(*) FROM interfaces').fetchone()[0]
        total_registros = conn.execute('SELECT COUNT(*) FROM consumo_banda').fetchone()[0]
        ultima_atualizacao = conn.execute('SELECT MAX(created_at) FROM consumo_banda').fetchone()[0]
    
    return jsonify({
        'status': 'online',
        'total_interfaces': total_interfaces,
        'total_registros': total_registros,
        'ultima_atualizacao': ultima_atualizacao,
        'timestamp': datetime.now().isoformat()
    })

# Inicialização
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
