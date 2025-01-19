from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
from datetime import datetime, timedelta
import os
from sqlalchemy import func
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate

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

with app.app_context():
    db.create_all()

@app.route('/')
@login_required
def index():
    # Dados básicos
    categorias = Categoria.query.filter_by(usuario_id=current_user.id).all()
    estabelecimentos = Estabelecimento.query.filter_by(usuario_id=current_user.id).all()
    # Adicione .all() para executar a query
    transacoes = Transacao.query.filter_by(usuario_id=current_user.id).order_by(Transacao.data.desc()).limit(10).all()
    
    # Calcula total do mês atual
    hoje = datetime.now()
    total_mes_atual = db.session.query(func.sum(Transacao.valor)).filter(
        Transacao.usuario_id == current_user.id,
        func.extract('month', Transacao.data) == hoje.month,
        func.extract('year', Transacao.data) == hoje.year
    ).scalar() or 0
    
    tem_pendentes = Transacao.query.filter(
        Transacao.categoria_id == None,
        Transacao.usuario_id == current_user.id,
        ~Transacao.estabelecimento.contains("Pagamento recebido"),
        ~Transacao.estabelecimento.contains("Desconto Antecipação"),
        ~Transacao.estabelecimento.contains("Estorno de")
    ).first() is not None
    
    return render_template('index.html',
                         categorias=categorias,
                         estabelecimentos=estabelecimentos,
                         transacoes=transacoes,
                         tem_pendentes=tem_pendentes,
                         total_mes_atual=total_mes_atual)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('Nenhum arquivo selecionado')
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado')
        return redirect(url_for('index'))

    if file and file.filename.endswith('.csv'):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)
        processar_arquivo(filepath)
        flash('Arquivo processado com sucesso!')
        return redirect(url_for('index'))

    flash('Arquivo inválido')
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
            return redirect(url_for('index'))
        
        categoria = Categoria(nome=nome, usuario_id=current_user.id)
        db.session.add(categoria)
        db.session.commit()
        flash('Categoria adicionada com sucesso!')
    return redirect(url_for('index'))

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
def listar_categorias():
    # Busca todas as categorias e seus estabelecimentos
    categorias = Categoria.query.order_by(Categoria.nome).all()
    
    # Para cada categoria, busca o total de estabelecimentos e transações
    categorias_info = []
    for categoria in categorias:
        num_estabelecimentos = Estabelecimento.query.filter_by(categoria_id=categoria.id).count()
        num_transacoes = Transacao.query.filter_by(categoria_id=categoria.id).count()
        
        categorias_info.append({
            'categoria': categoria,
            'num_estabelecimentos': num_estabelecimentos,
            'num_transacoes': num_transacoes
        })
    
    return render_template('categorias.html', categorias=categorias_info)

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

if __name__ == '__main__':
    app.run(debug=True) 