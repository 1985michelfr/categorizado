from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
from datetime import datetime, timedelta
import os
from sqlalchemy import func
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sdfghjkolksaçoldf'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///despesas.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Adicionado para evitar warnings

# Se usar PostgreSQL, substitua 'postgres://' por 'postgresql://' na URL
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['UPLOAD_FOLDER'] = 'uploads'

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)

# Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Após criar a instância do SQLAlchemy
migrate = Migrate(app, db)

class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(100), nullable=False)
    categorias = db.relationship('Categoria', backref='usuario', lazy=True)
    estabelecimentos = db.relationship('Estabelecimento', backref='usuario', lazy=True)
    transacoes = db.relationship('Transacao', backref='usuario', lazy=True)

class Categoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    estabelecimentos = db.relationship('Estabelecimento', backref='categoria', lazy=True)
    palavras_chave = db.relationship('PalavraChaveCategoria', backref='categoria', lazy=True)
    
    __table_args__ = (
        db.UniqueConstraint('nome', 'usuario_id', name='unique_nome_usuario'),
    )

class Estabelecimento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categoria.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    
    __table_args__ = (
        db.UniqueConstraint('nome', 'usuario_id', name='unique_nome_usuario'),
    )

class Transacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    estabelecimento = db.Column(db.String(200), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categoria.id'))
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)

class PalavraChaveCategoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    palavra_chave = db.Column(db.String(100), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categoria.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    
    __table_args__ = (
        db.UniqueConstraint('palavra_chave', 'usuario_id', name='unique_palavra_usuario'),
    )

with app.app_context():
    db.create_all()

@app.route('/')
@login_required
def index():
    # Dados básicos
    categorias = Categoria.query.filter_by(usuario_id=current_user.id).all()
    estabelecimentos = Estabelecimento.query.filter_by(usuario_id=current_user.id).all()
    transacoes = Transacao.query.filter_by(usuario_id=current_user.id).order_by(Transacao.data.desc()).limit(10).all()
    
    # Calcula total dos últimos 12 meses
    hoje = datetime.now()
    data_inicio = hoje - timedelta(days=365)  # 12 meses atrás
    
    total_12_meses = db.session.query(func.sum(Transacao.valor)).filter(
        Transacao.usuario_id == current_user.id,
        Transacao.data >= data_inicio,
        Transacao.data <= hoje
    ).scalar() or 0
    
    # Dados para o gráfico de gastos por mês
    gastos_por_mes = db.session.query(
        func.extract('month', Transacao.data).label('mes'),
        func.extract('year', Transacao.data).label('ano'),
        func.sum(Transacao.valor).label('total')
    ).filter(
        Transacao.usuario_id == current_user.id
    ).group_by(
        func.extract('year', Transacao.data),
        func.extract('month', Transacao.data)
    ).order_by(
        func.extract('year', Transacao.data).desc(),
        func.extract('month', Transacao.data).desc()
    ).limit(12).all()
    
    # Inverte a ordem para mostrar do mais antigo para o mais recente
    gastos_por_mes = gastos_por_mes[::-1]
    
    # Formata os dados para o gráfico
    labels_meses = []
    valores_meses = []
    for mes in gastos_por_mes:
        nome_mes = datetime(int(mes.ano), int(mes.mes), 1).strftime('%b/%Y')
        labels_meses.append(nome_mes)
        valores_meses.append(float(mes.total))
    
    # Dados para o gráfico de distribuição por categoria
    gastos_por_categoria = db.session.query(
        Categoria.nome,
        func.sum(Transacao.valor).label('total')
    ).join(
        Transacao, Transacao.categoria_id == Categoria.id
    ).filter(
        Transacao.usuario_id == current_user.id,
        Transacao.data >= data_inicio,  # Últimos 12 meses
        Transacao.data <= hoje
    ).group_by(
        Categoria.nome
    ).order_by(
        func.sum(Transacao.valor).desc()  # Ordena do maior para o menor valor
    ).all()
    
    labels_categorias = []
    valores_categorias = []
    for cat in gastos_por_categoria:
        labels_categorias.append(cat.nome)
        valores_categorias.append(float(cat.total))
    
    tem_pendentes = Transacao.query.filter(
        Transacao.categoria_id == None,
        Transacao.usuario_id == current_user.id,
        ~Transacao.estabelecimento.contains("Pagamento recebido"),
        ~Transacao.estabelecimento.contains("Desconto Antecipação"),
        ~Transacao.estabelecimento.contains("Saldo restante da fatura anterior"),
        ~Transacao.estabelecimento.contains("Estorno de")
    ).first() is not None
    
    return render_template('index.html',
                         categorias=categorias,
                         estabelecimentos=estabelecimentos,
                         transacoes=transacoes,
                         tem_pendentes=tem_pendentes,
                         total_12_meses=total_12_meses,
                         labels_meses=labels_meses,
                         valores_meses=valores_meses,
                         labels_categorias=labels_categorias,
                         valores_categorias=valores_categorias)

def encontrar_categoria_por_palavra_chave(estabelecimento, usuario_id):
    """Busca uma categoria baseada nas palavras-chave cadastradas"""
    palavras_chave = PalavraChaveCategoria.query.filter_by(
        usuario_id=usuario_id
    ).all()
    
    for palavra in palavras_chave:
        if palavra.palavra_chave.lower() in estabelecimento.lower():
            return palavra.categoria_id
    return None

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        flash('Nenhum arquivo selecionado')
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado')
        return redirect(url_for('index'))
    
    if file:
        # Salva o arquivo temporariamente
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            # Tenta ler o arquivo baseado na extensão
            if filename.endswith('.csv'):
                # Tenta diferentes encodings
                try:
                    df = pd.read_csv(filepath, encoding='utf-8')
                except:
                    try:
                        df = pd.read_csv(filepath, encoding='latin1')
                    except:
                        df = pd.read_csv(filepath, encoding='iso-8859-1')
            else:
                # Tenta diferentes engines do Excel
                try:
                    df = pd.read_excel(filepath, engine='openpyxl')
                except:
                    try:
                        df = pd.read_excel(filepath, engine='xlrd')
                    except:
                        raise Exception('Formato de arquivo não suportado. Use .xlsx ou .csv')
            
            # Verifica e mapeia as colunas necessárias
            colunas_necessarias = {
                'data': ['Data', 'DATA', 'data', 'date', 'DATE', 'Date'],
                'descricao': ['Descrição', 'DESCRIÇÃO', 'Descricao', 'DESCRICAO', 'descricao', 
                             'Estabelecimento', 'ESTABELECIMENTO', 'title', 'TITLE', 'Title'],
                'valor': ['Valor', 'VALOR', 'valor', 'amount', 'AMOUNT', 'Amount']
            }
            
            colunas_encontradas = {}
            for tipo, possiveis_nomes in colunas_necessarias.items():
                coluna_encontrada = None
                for nome in possiveis_nomes:
                    if nome in df.columns:
                        coluna_encontrada = nome
                        break
                if coluna_encontrada is None:
                    raise Exception(f'Coluna de {tipo} não encontrada. Nomes possíveis: {", ".join(possiveis_nomes)}')
                colunas_encontradas[tipo] = coluna_encontrada
            
            # Remove linhas que contêm "Saldo restante da fatura anterior" ou "Pagamento recebido"
            df = df[~df[colunas_encontradas['descricao']].str.contains('Saldo restante da fatura anterior|Pagamento recebido|Desconto Antecipação|Estorno de', 
                                                                      case=False, 
                                                                      na=False,
                                                                      regex=True)]
            
            # Processa cada linha do arquivo
            for _, row in df.iterrows():
                try:
                    # Tenta diferentes formatos de data
                    data_str = str(row[colunas_encontradas['data']])
                    try:
                        data = pd.to_datetime(data_str).date()
                    except:
                        # Tenta diferentes formatos de data
                        for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y']:
                            try:
                                data = datetime.strptime(data_str, fmt).date()
                                break
                            except:
                                continue
                        else:
                            raise Exception(f'Formato de data não reconhecido: {data_str}')
                    
                    # Limpa o nome do estabelecimento removendo informações de parcelamento
                    estabelecimento = limpar_nome_estabelecimento(str(row[colunas_encontradas['descricao']]).strip())
                    valor_str = str(row[colunas_encontradas['valor']])
                    
                    # Limpa e converte o valor
                    valor_str = valor_str.replace('R$', '').replace(' ', '')
                    if ',' in valor_str and '.' in valor_str:
                        valor_str = valor_str.replace('.', '')
                    valor = abs(float(valor_str.replace(',', '.').strip()))
                    
                    # Verifica se já existe uma transação idêntica
                    transacao_existente = Transacao.query.filter_by(
                        data=data,
                        estabelecimento=estabelecimento,
                        valor=valor,
                        usuario_id=current_user.id
                    ).first()
                    
                    if not transacao_existente:
                        # Primeiro tenta encontrar um estabelecimento já cadastrado
                        estabelecimento_obj = Estabelecimento.query.filter_by(
                            nome=estabelecimento,
                            usuario_id=current_user.id
                        ).first()
                        
                        if estabelecimento_obj:
                            categoria_id = estabelecimento_obj.categoria_id
                        else:
                            # Se não encontrou estabelecimento, tenta encontrar por palavra-chave
                            categoria_id = encontrar_categoria_por_palavra_chave(estabelecimento, current_user.id)
                        
                        nova_transacao = Transacao(
                            data=data,
                            estabelecimento=estabelecimento,
                            valor=valor,
                            categoria_id=categoria_id,
                            usuario_id=current_user.id
                        )
                        db.session.add(nova_transacao)
                
                except Exception as e:
                    flash(f'Erro ao processar linha: {str(e)}')
                    continue
            
            db.session.commit()
            flash('Arquivo processado com sucesso!')
            
        except Exception as e:
            flash(f'Erro ao processar arquivo: {str(e)}')
            
        finally:
            # Remove o arquivo temporário
            if os.path.exists(filepath):
                os.remove(filepath)
    
    return redirect(url_for('index'))

@app.route('/categoria', methods=['POST'])
@login_required
def adicionar_categoria():
    nome = request.form.get('nome')
    if nome:
        categoria_existente = Categoria.query.filter(
            Categoria.usuario_id == current_user.id,
            func.lower(Categoria.nome) == func.lower(nome)
        ).first()
        
        if categoria_existente:
            flash('Já existe uma categoria com este nome!')
            return redirect(url_for('listar_categorias'))
        
        categoria = Categoria(nome=nome, usuario_id=current_user.id)
        db.session.add(categoria)
        db.session.commit()
        flash('Categoria adicionada com sucesso!')
    return redirect(url_for('listar_categorias'))

@app.route('/estabelecimento', methods=['POST'])
@login_required
def adicionar_estabelecimento():
    nome = request.form.get('nome')
    categoria_id = request.form.get('categoria_id')
    
    if nome and categoria_id:
        estabelecimento = Estabelecimento(
            nome=nome, 
            categoria_id=categoria_id,
            usuario_id=current_user.id
        )
        db.session.add(estabelecimento)
        db.session.commit()
        flash('Estabelecimento categorizado com sucesso!')
    return redirect(url_for('index'))

@app.route('/relatorio')
def relatorio():
    mes = request.args.get('mes')
    ano = request.args.get('ano')
    
    # Busca todas as competências disponíveis
    competencias = db.session.query(
        func.extract('month', Transacao.data).label('mes'),
        func.extract('year', Transacao.data).label('ano')
    ).group_by(
        func.extract('month', Transacao.data),
        func.extract('year', Transacao.data)
    ).order_by(
        func.extract('year', Transacao.data).desc(),
        func.extract('month', Transacao.data).desc()
    ).all()
    
    # Busca gastos totais por competência
    gastos_por_competencia = db.session.query(
        func.extract('month', Transacao.data).label('mes'),
        func.extract('year', Transacao.data).label('ano'),
        func.sum(Transacao.valor).label('total')
    ).group_by(
        func.extract('month', Transacao.data),
        func.extract('year', Transacao.data)
    ).order_by(
        func.extract('year', Transacao.data),
        func.extract('month', Transacao.data)
    ).all()
    
    if mes and ano:
        gastos = calcular_gastos_por_categoria(int(mes), int(ano))
        # Buscar todas as transações do período
        transacoes = Transacao.query.filter(
            func.extract('month', Transacao.data) == int(mes),
            func.extract('year', Transacao.data) == int(ano)
        ).order_by(Transacao.data).all()
        
        # Organizar transações por categoria
        transacoes_por_categoria = {}
        for t in transacoes:
            if t.categoria_id:
                if t.categoria_id not in transacoes_por_categoria:
                    transacoes_por_categoria[t.categoria_id] = []
                transacoes_por_categoria[t.categoria_id].append(t)
        
        # Prepara dados para o gráfico de pizza
        dados_grafico_pizza = {
            'labels': [g.nome for g in gastos],
            'valores': [float(g.total) for g in gastos]
        }
        
        # Busca todas as categorias para o modal de edição
        categorias = Categoria.query.order_by(Categoria.nome).all()
        
        return render_template('relatorio.html', 
                             gastos=gastos, 
                             transacoes_por_categoria=transacoes_por_categoria,
                             mes=mes, 
                             ano=ano,
                             competencias=competencias,
                             dados_grafico_pizza=dados_grafico_pizza,
                             gastos_por_competencia=gastos_por_competencia,
                             categorias=categorias)
    
    return render_template('relatorio.html', 
                         competencias=competencias,
                         mes=None,
                         ano=None,
                         gastos=None,
                         transacoes_por_categoria={},
                         gastos_por_competencia=gastos_por_competencia)

@app.route('/relatorio/categoria/<int:categoria_id>')
def detalhes_categoria(categoria_id):
    mes = request.args.get('mes')
    ano = request.args.get('ano')
    
    if not (mes and ano):
        flash('Mês e ano são obrigatórios')
        return redirect(url_for('relatorio'))
    
    categoria = Categoria.query.get_or_404(categoria_id)
    
    # Busca todas as transações da categoria no mês/ano especificado
    transacoes = Transacao.query.filter(
        Transacao.categoria_id == categoria_id,
        func.extract('month', Transacao.data) == int(mes),
        func.extract('year', Transacao.data) == int(ano)
    ).order_by(Transacao.data).all()
    
    total = sum(t.valor for t in transacoes)
    
    return render_template(
        'detalhes_categoria.html',
        categoria=categoria,
        transacoes=transacoes,
        total=total,
        mes=mes,
        ano=ano
    )

@app.route('/transacoes')
def listar_transacoes():
    transacoes = Transacao.query.order_by(Transacao.data.desc()).all()
    return render_template('transacoes.html', transacoes=transacoes)

@app.route('/categorizacao-pendente')
@login_required
def categorizacao_pendente():
    # Busca transações sem categoria, excluindo registros específicos
    transacoes_sem_categoria = Transacao.query.filter(
        Transacao.categoria_id == None,
        Transacao.usuario_id == current_user.id,
        ~Transacao.estabelecimento.contains("Pagamento recebido"),
        ~Transacao.estabelecimento.contains("Desconto Antecipação"),
        ~Transacao.estabelecimento.contains("Estorno de")
    ).all()
    
    # Agrupa por estabelecimento para não mostrar duplicados
    estabelecimentos_sem_categoria = set(t.estabelecimento for t in transacoes_sem_categoria)
    
    # Busca categorias ordenadas por nome
    categorias = Categoria.query.filter_by(
        usuario_id=current_user.id
    ).order_by(Categoria.nome).all()
    
    return render_template('categorizacao_pendente.html', 
                         estabelecimentos=estabelecimentos_sem_categoria,
                         categorias=categorias)

@app.route('/categorizar-estabelecimento', methods=['POST'])
@login_required
def categorizar_estabelecimento():
    estabelecimento_nome = request.form.get('estabelecimento')
    categoria_id = request.form.get('categoria_id')
    
    if estabelecimento_nome and categoria_id:
        # Cria novo estabelecimento com o usuario_id
        estabelecimento = Estabelecimento(
            nome=estabelecimento_nome,
            categoria_id=categoria_id,
            usuario_id=current_user.id
        )
        db.session.add(estabelecimento)
        
        # Atualiza todas as transações deste estabelecimento
        Transacao.query.filter_by(
            estabelecimento=estabelecimento_nome,
            usuario_id=current_user.id
        ).update({
            Transacao.categoria_id: categoria_id
        })
        
        db.session.commit()
        flash(f'Estabelecimento {estabelecimento_nome} categorizado com sucesso!')
    
    # Verifica se ainda existem estabelecimentos para categorizar
    if Transacao.query.filter_by(
        categoria_id=None,
        usuario_id=current_user.id
    ).first():
        return redirect(url_for('categorizacao_pendente'))
    return redirect(url_for('index'))

def limpar_nome_estabelecimento(nome):
    """Remove informações de parcelamento do nome do estabelecimento"""
    # Remove " - Parcela X/Y" do final do nome
    if " - Parcela " in nome:
        nome = nome.split(" - Parcela ")[0]
    return nome.strip()

@app.route('/corrigir-nomes-estabelecimentos')
def corrigir_nomes_estabelecimentos():
    # Busca todas as transações
    transacoes = Transacao.query.all()
    estabelecimentos_atualizados = set()
    
    for transacao in transacoes:
        nome_original = transacao.estabelecimento
        nome_limpo = limpar_nome_estabelecimento(nome_original)
        
        if nome_original != nome_limpo:
            # Atualiza o nome da transação
            transacao.estabelecimento = nome_limpo
            
            # Verifica se existe um estabelecimento cadastrado com o nome original
            estab_original = Estabelecimento.query.filter_by(nome=nome_original).first()
            if estab_original:
                # Verifica se já existe um estabelecimento com o nome limpo
                estab_limpo = Estabelecimento.query.filter_by(nome=nome_limpo).first()
                if estab_limpo:
                    # Se existe, usa a categoria dele
                    transacao.categoria_id = estab_limpo.categoria_id
                    # Remove o estabelecimento com nome original
                    db.session.delete(estab_original)
                else:
                    # Se não existe, atualiza o nome do estabelecimento original
                    estab_original.nome = nome_limpo
                estabelecimentos_atualizados.add(nome_limpo)
    
    db.session.commit()
    flash('Nomes dos estabelecimentos foram corrigidos com sucesso!')
    return redirect(url_for('index'))

def processar_arquivo(filepath):
    df = pd.read_csv(filepath)
    estabelecimentos_novos = False
    
    # Verifica se arquivo já foi processado
    primeira_transacao = df.iloc[0]
    data = datetime.strptime(primeira_transacao['date'], '%Y-%m-%d').date()
    estabelecimento = limpar_nome_estabelecimento(primeira_transacao['title'])  # Aplica limpeza
    valor = float(primeira_transacao['amount'])
    
    # Verifica se já existe uma transação com mesmos dados
    transacao_existente = Transacao.query.filter_by(
        data=data,
        estabelecimento=estabelecimento,
        valor=valor
    ).first()
    
    if transacao_existente:
        flash('Este arquivo já foi processado anteriormente!')
        return redirect(url_for('index'))
    
    # Se não existir, processa o arquivo
    for _, row in df.iterrows():
        estabelecimento = limpar_nome_estabelecimento(row['title'])
        
        if ("Pagamento recebido" in estabelecimento or 
            "Desconto Antecipação" in estabelecimento or
            "Estorno de" in estabelecimento):
            continue
            
        data = datetime.strptime(row['date'], '%Y-%m-%d').date()
        valor = float(row['amount'])
        
        # Procura categoria do estabelecimento
        estab = Estabelecimento.query.filter_by(
            nome=estabelecimento,
            usuario_id=current_user.id
        ).first()
        categoria_id = estab.categoria_id if estab else None
        
        if not categoria_id:
            estabelecimentos_novos = True
        
        transacao = Transacao(
            data=data,
            estabelecimento=estabelecimento,
            valor=valor,
            categoria_id=categoria_id,
            usuario_id=current_user.id
        )
        db.session.add(transacao)
    
    db.session.commit()
    
    if estabelecimentos_novos:
        return redirect(url_for('categorizacao_pendente'))
    return redirect(url_for('index'))

def calcular_gastos_por_categoria(mes, ano):
    gastos = db.session.query(
        Categoria.nome,
        Categoria.id,
        func.sum(Transacao.valor).label('total')
    ).join(
        Categoria,
        Transacao.categoria_id == Categoria.id
    ).filter(
        func.extract('month', Transacao.data) == mes,
        func.extract('year', Transacao.data) == ano
    ).group_by(
        Categoria.nome,
        Categoria.id
    ).all()
    
    return gastos

@app.route('/limpar-banco')
def limpar_banco():
    # Remove todas as transações
    Transacao.query.delete()
    
    # Remove todos os estabelecimentos
    Estabelecimento.query.delete()
    
    # Remove todas as categorias
    Categoria.query.delete()
    
    db.session.commit()
    flash('Banco de dados limpo com sucesso!')
    return redirect(url_for('index'))

@app.route('/categorias')
@login_required
def listar_categorias():
    # Busca todas as categorias do usuário com contagem de estabelecimentos e transações
    categorias_info = []
    categorias = Categoria.query.filter_by(usuario_id=current_user.id).order_by(Categoria.nome).all()
    
    for categoria in categorias:
        # Conta estabelecimentos
        total_estabelecimentos = Estabelecimento.query.filter_by(
            categoria_id=categoria.id,
            usuario_id=current_user.id
        ).count()
        
        # Conta transações e soma valores
        transacoes_query = Transacao.query.filter_by(
            categoria_id=categoria.id,
            usuario_id=current_user.id
        )
        total_transacoes = transacoes_query.count()
        total_valor = db.session.query(func.sum(Transacao.valor)).filter(
            Transacao.categoria_id == categoria.id,
            Transacao.usuario_id == current_user.id
        ).scalar() or 0
        
        categorias_info.append({
            'categoria': categoria,
            'num_estabelecimentos': total_estabelecimentos,
            'num_transacoes': total_transacoes,
            'total_valor': total_valor
        })
    
    return render_template('categorias.html', categorias=categorias_info)

@app.route('/editar-categoria', methods=['POST'])
@login_required
def editar_categoria():
    categoria_id = request.form.get('categoria_id')
    novo_nome = request.form.get('nome')
    
    if categoria_id and novo_nome:
        categoria = Categoria.query.filter_by(
            id=categoria_id, 
            usuario_id=current_user.id
        ).first()
        
        if categoria:
            # Verifica se já existe outra categoria com o mesmo nome
            categoria_existente = Categoria.query.filter(
                Categoria.usuario_id == current_user.id,
                Categoria.id != categoria_id,
                func.lower(Categoria.nome) == func.lower(novo_nome)
            ).first()
            
            if categoria_existente:
                flash('Já existe uma categoria com este nome!')
            else:
                categoria.nome = novo_nome
                db.session.commit()
                flash('Categoria atualizada com sucesso!')
        else:
            flash('Categoria não encontrada!')
    else:
        flash('Dados inválidos!')
        
    return redirect(url_for('listar_categorias'))

@app.route('/excluir-categoria/<int:categoria_id>', methods=['POST'])
@login_required
def excluir_categoria(categoria_id):
    categoria = Categoria.query.filter_by(
        id=categoria_id, 
        usuario_id=current_user.id
    ).first()
    
    if categoria:
        # Verifica se existem transações ou estabelecimentos vinculados
        tem_vinculos = db.session.query(
            Transacao.query.filter_by(categoria_id=categoria_id).exists() |
            Estabelecimento.query.filter_by(categoria_id=categoria_id).exists()
        ).scalar()
        
        if tem_vinculos:
            flash('Não é possível excluir uma categoria que possui transações ou estabelecimentos vinculados!')
        else:
            db.session.delete(categoria)
            db.session.commit()
            flash('Categoria excluída com sucesso!')
    else:
        flash('Categoria não encontrada!')
        
    return redirect(url_for('listar_categorias'))

@app.route('/atualizar-categoria-transacao', methods=['POST'])
def atualizar_categoria_transacao():
    transacao_id = request.form.get('transacao_id')
    categoria_id = request.form.get('categoria_id')
    mes = request.form.get('mes')
    ano = request.form.get('ano')
    
    if transacao_id and categoria_id:
        # Busca a transação original
        transacao = Transacao.query.get(transacao_id)
        if transacao:
            estabelecimento_nome = transacao.estabelecimento
            
            # Atualiza todas as transações do mesmo estabelecimento
            Transacao.query.filter_by(estabelecimento=estabelecimento_nome).update(
                {Transacao.categoria_id: categoria_id}
            )
            
            # Atualiza ou cria o estabelecimento com a nova categoria
            estabelecimento = Estabelecimento.query.filter_by(nome=estabelecimento_nome).first()
            if estabelecimento:
                estabelecimento.categoria_id = categoria_id
            else:
                novo_estabelecimento = Estabelecimento(
                    nome=estabelecimento_nome,
                    categoria_id=categoria_id
                )
                db.session.add(novo_estabelecimento)
            
            db.session.commit()
            flash(f'Categoria atualizada com sucesso para todas as transações de {estabelecimento_nome}!')
    
    return redirect(url_for('relatorio', mes=mes, ano=ano))

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')
        
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and check_password_hash(usuario.senha, senha):
            login_user(usuario)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        
        flash('Email ou senha inválidos')
    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')
        
        if Usuario.query.filter_by(email=email).first():
            flash('Email já cadastrado')
            return redirect(url_for('registro'))
        
        novo_usuario = Usuario(
            email=email,
            senha=generate_password_hash(senha)
        )
        db.session.add(novo_usuario)
        db.session.commit()
        
        login_user(novo_usuario)
        return redirect(url_for('index'))
    
    return render_template('registro.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/adicionar-palavra-chave', methods=['POST'])
@login_required
def adicionar_palavra_chave():
    categoria_id = request.form.get('categoria_id')
    palavra_chave = request.form.get('palavra_chave')
    
    if categoria_id and palavra_chave:
        # Verifica se a categoria pertence ao usuário
        categoria = Categoria.query.filter_by(
            id=categoria_id, 
            usuario_id=current_user.id
        ).first()
        
        if categoria:
            # Verifica se já existe esta palavra-chave
            palavra_existente = PalavraChaveCategoria.query.filter(
                PalavraChaveCategoria.usuario_id == current_user.id,
                func.lower(PalavraChaveCategoria.palavra_chave) == func.lower(palavra_chave)
            ).first()
            
            if palavra_existente:
                flash('Esta palavra-chave já está cadastrada!')
            else:
                nova_palavra = PalavraChaveCategoria(
                    palavra_chave=palavra_chave,
                    categoria_id=categoria_id,
                    usuario_id=current_user.id
                )
                db.session.add(nova_palavra)
                
                # Atualiza transações existentes que contêm esta palavra-chave
                transacoes = Transacao.query.filter(
                    Transacao.usuario_id == current_user.id,
                    Transacao.categoria_id == None,
                    Transacao.estabelecimento.ilike(f'%{palavra_chave}%')
                ).all()
                
                for transacao in transacoes:
                    transacao.categoria_id = categoria_id
                
                db.session.commit()
                flash('Palavra-chave adicionada com sucesso!')
        else:
            flash('Categoria não encontrada!')
    else:
        flash('Dados inválidos!')
        
    return redirect(url_for('listar_categorias'))

@app.route('/remover-palavra-chave/<int:palavra_id>', methods=['POST'])
@login_required
def remover_palavra_chave(palavra_id):
    palavra = PalavraChaveCategoria.query.filter_by(
        id=palavra_id,
        usuario_id=current_user.id
    ).first()
    
    if palavra:
        db.session.delete(palavra)
        db.session.commit()
        flash('Palavra-chave removida com sucesso!')
    else:
        flash('Palavra-chave não encontrada!')
    
    return redirect(url_for('listar_categorias'))

@app.template_filter('format_currency')
def format_currency(value):
    """Formata um valor numérico para moeda (R$)"""
    try:
        return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "0,00"

if __name__ == '__main__':
    app.run(debug=True) 