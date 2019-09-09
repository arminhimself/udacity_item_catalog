import json, httplib2, requests

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g, make_response
from flask_httpauth import HTTPBasicAuth
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, Category, CategoryItem, User

app = Flask(__name__)
auth = HTTPBasicAuth()

engine = create_engine('postgresql://catalog:catalog@localhost:5432/catalog')
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)
session = DBSession()

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']

@auth.verify_password
def verify_password(username_or_token, password):
    user_id = User.verify_auth_token(username_or_token)
    if user_id:
        user = session.query(User).filter_by(id=user_id).one()
    else:
        user = session.query(User).filter_by(
            username=username_or_token).first()
        if not user or not user.verify_password(password):
            return False
    g.user = user
    return True

@app.route('/oauth/<provider>', methods=['POST'])
def oauth(provider):

    auth_code = request.get_json(force=True)
    if provider == 'google':

        try:
            oauth_flow = flow_from_clientsecrets(
                'client_secrets.json', scope='')
            oauth_flow.redirect_uri = 'postmessage'
            credentials = oauth_flow.step2_exchange(auth_code)
        except FlowExchangeError:
            response = make_response(json.dumps(
                'Failed to upgrade the authorization code.'), 401)
            response.headers['Content-Type'] = 'application/json'
            return response

        access_token = credentials.access_token
        url = (
            'https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s' % access_token)
        h = httplib2.Http()
        result = json.loads(h.request(url, 'GET')[1])

        if result.get('error') is not None:
            response = make_response(json.dumps(result.get('error')), 500)
            response.headers['Content-Type'] = 'application/json'

        h = httplib2.Http()
        userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
        params = {'access_token': credentials.access_token, 'alt': 'json'}

        answer = requests.get(userinfo_url, params=params)
        data = answer.json()

        print(data)

        name = data['name']
        picture = data['picture']
        email = data['email']

        user = session.query(User).filter_by(email=email).first()
        if not user:
            user = User(username=name, picture=picture, email=email)
            session.add(user)
            session.commit()

        token = user.generate_auth_token(600)

        return jsonify({'token': token.decode('ascii')})
    else:
        return 'Unrecoginized Provider'


@app.route('/token')
@auth.login_required
def get_auth_token():
    token = g.user.generate_auth_token()
    return jsonify({'token': token.decode('ascii')})


@app.route('/users', methods=['POST'])
def new_user():
    username = request.json.get('username')
    password = request.json.get('password')
    if username is None or password is None:
        abort(400) 

    if session.query(User).filter_by(username=username).first() is not None:
        None 
        user = session.query(User).filter_by(username=username).first()
        return jsonify({'message': 'user already exists'}), 200

    user = User(username=username)
    user.hash_password(password)
    session.add(user)
    session.commit()
    return jsonify({'username': user.username}), 201


@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/signup')
def signup():
    return render_template('signup.tml')

@app.route('/profile')
def profile():
    return render_template('profile.html')

@app.route('/')
def index():
    categories = session.query(Category)
    return render_template('index.html', categories=categories)

@app.route('/catalog/new', methods=['GET', 'POST'])
@auth.login_required
def newCategory():
    if request.method == 'POST':
        newCategory = Category(name=request.form['name'])
        session.add(newCategory)
        session.commit()
        return redirect(url_for('showCategories'))
    else:
        return render_template('newCategory.html')


@app.route('/catalog/<int:category_id>/edit', methods=['GET', 'POST'])
@auth.login_required
def editCategory(category_id):
    editedCategory = session.query(Category).filter_by(id=category_id).one()
    if request.method == 'POST':
        if request.form['name']:
            editedCategory.name = request.form['name']
            return redirect(url_for('showCategories'))
    else:
        return render_template('editCategory.html', category=editedCategory)


@app.route('/catalog/<int:category_id>/delete', methods=['GET', 'POST'])
@auth.login_required
def deleteCategory(category_id):
    categoryToDelete = session.query(Category).filter_by(id=category_id).one()
    if request.method == 'POST':
        session.delete(categoryToDelete)
        session.commit()
        return redirect(url_for('showCategories', category_id=category_id))
    else:
        return render_template('deleteCategory.html', category=categoryToDelete)


@app.route('/catalog/<int:category_id>/items')
def showCategoryItems(category_id):
    categories = session.query(Category)
    category = session.query(Category).filter_by(id=category_id).one()
    categoryItems = session.query(CategoryItem).filter_by(
        category_id=category_id).all()
    return render_template('categoryItems.html', category=category, categoryItems=categoryItems, category_id=category_id, categories=categories)


@app.route('/catalog/<int:category_id>/items/new', methods=['GET', 'POST'])
@auth.login_required
def newCategoryItem(category_id):
    if request.method == 'POST':
        newCategoryItem = CategoryItem(name=request.form['name'], description=request.form['description'],
                                       price=request.form['price'], size=request.form['size'], color=request.form['color'], category_id=category_id)
        session.add(newItem)
        session.commit()
        return redirect(url_for('showCategoryItems', category_id=category_id))
    else:
        return render_template('newCategoryItem.html', category_id=category_id)


@app.route('/catalog/<int:category_id>/items/<int:item_id>/edit', methods=['GET', 'POST'])
@auth.login_required
def editCategoryItem(category_id, item_id):
    editedCategoryItem = session.query(
        CategoryItem).filter_by(id=item_id).one()
    if request.method == 'POST':
        if request.form['name']:
            editedCategoryItem.name = request.form['name']
        session.add(editedCategoryItem)
        session.commit()
        return redirect(url_for('showCategoryItems', category_id=category_id, item_id=item_id))
    else:
        return render_template('editCategoryItem.html', category_id=category_id, item_id=item_id, item=editedCategoryItem)


@app.route('/catalog/<int:category_id>/items/<int:item_id>/delete', methods=['GET', 'POST'])
@auth.login_required
def deleteCategoryItem(category_id, item_id):
    categoryItemToDelete = session.query(
        CategoryItem).filter_by(id=item_id).one()
    if request.method == 'POST':
        session.delete(categoryItemToDelete)
        session.commit()
        return redirect(url_for('showCategoryItems', category_id=category_id, item_id=item_id))
    else:
        return render_template('deleteCategoryItem.html', category_id=category_id, item_id=item_id, item=categoryItemToDelete)
    
    
@app.route('/catalog/JSON')
#@auth.login_required
def showCategoriesJSON():
    categories = session.query(Category).all()
    return jsonify(categoryItems=[i.serialize for i in categories])
    
    
@app.route('/catalog/<int:category_id>/items/JSON')
#@auth.login_required
def showCategoryItemsJSON(category_id):
    category = session.query(Category).filter_by(id=category_id).one()
    categoryItems = session.query(CategoryItem).filter_by(
        category_id=category_id).all()
    return jsonify(categoryItems=[i.serialize for i in categoryItems])


@app.route('/catalog/<int:category_id>/items/<int:item_id>/JSON')
#@auth.login_required
def showItemJSON(category_id, item_id):
    categoryItem = session.query(CategoryItem).filter_by(id=item_id).one()
    return jsonify(categoryItem=categoryItem.serialize)


@app.route('/api/users/<int:id>')
def get_user(id):
    user = session.query(User).filter_by(id=id).one()
    if not user:
        abort(400)
    return jsonify({'username': user.username})

        
if __name__ == '__main__':
    # app.debug = True
    # app.run(host='0.0.0.0', port=8000)
    app.run()